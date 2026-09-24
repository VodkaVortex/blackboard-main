"""Terminal access to the blackboard's existing project API."""
from __future__ import annotations

import json
import time
from urllib.parse import quote

import click
import requests


class BoardClient:
    def __init__(self, server: str):
        self.server = server.rstrip("/")
        self.session = requests.Session()
        # The default board is local and should not go through an outbound proxy.
        if self.server.startswith(("http://127.0.0.1:", "http://localhost:")):
            self.session.trust_env = False

    def request(self, method: str, path: str, **kwargs):
        try:
            response = self.session.request(method, self.server + path, timeout=10, **kwargs)
        except requests.RequestException as exc:
            raise click.ClickException("无法连接黑板服务，请先启动 cairn serve，并检查 --server 地址。") from exc
        if not response.ok:
            try:
                detail = response.json().get("detail", response.reason)
            except (ValueError, AttributeError):
                detail = response.reason
            raise click.ClickException(f"黑板返回 HTTP {response.status_code}: {detail}")
        return response


def project_path(project_id: str) -> str:
    return "/projects/" + quote(project_id, safe="")


def print_json(value) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))


def print_project(data: dict) -> None:
    meta = data["project"]
    click.echo(f'{meta["id"]}  [{meta["status"]}]  {meta["title"]}')
    if meta.get("reason"):
        click.echo(f'正在分析：{meta["reason"]["worker"]}')
    for fact in data["facts"]:
        click.echo(f'\n事实 {fact["id"]}: {fact["description"]}')
    for intent in data["intents"]:
        status = "已完成" if intent.get("to") else ("执行中" if intent.get("worker") else "待执行")
        click.echo(f'\n意图 {intent["id"]} [{status}]: {intent["description"]}')
    for hint in data["hints"]:
        click.echo(f'\n提示 {hint["id"]}: {hint["content"]}')


@click.group()
@click.option("--server", default="http://127.0.0.1:8000", envvar="CAIRN_SERVER", show_default=True)
@click.pass_context
def project(ctx: click.Context, server: str):
    """在终端创建、查看和管理黑板项目。"""
    client = BoardClient(server)
    ctx.obj = client
    ctx.call_on_close(client.session.close)


@project.command("create")
@click.option("--title", required=True, help="项目标题")
@click.option("--origin", help="已有信息；可改用 --origin-file")
@click.option("--origin-file", type=click.File("r", encoding="utf-8"), help="从文本文件读取已有信息，- 表示标准输入")
@click.option("--goal", required=True, help="期望结果")
@click.option("--bootstrap/--no-bootstrap", default=True, show_default=True)
@click.option("--hint", multiple=True, help="初始提示，可重复指定")
@click.pass_obj
def create(client: BoardClient, title, origin, origin_file, goal, bootstrap, hint):
    """创建项目，只输出项目 ID，方便后续命令使用。"""
    if (origin is None) == (origin_file is None):
        raise click.UsageError("必须且只能指定 --origin 或 --origin-file 中的一项。")
    if origin_file is not None:
        origin = origin_file.read()
    if not origin.strip():
        raise click.UsageError("已有信息不能为空。")
    data = client.request("POST", "/projects", json={
        "title": title, "origin": origin, "goal": goal, "bootstrap_enabled": bootstrap,
        "hints": [{"content": text, "creator": "terminal"} for text in hint],
    }).json()
    click.echo(data["project"]["id"])


@project.command("list")
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
def list_projects(client: BoardClient, as_json: bool):
    """列出项目和运行状态。"""
    data = client.request("GET", "/projects").json()
    if as_json:
        print_json(data)
        return
    if not data:
        click.echo("暂无项目。")
    for item in data:
        click.echo(f'{item["id"]}  [{item["status"]}]  {item["title"]}  '
                   f'事实={item["fact_count"]} 执行中={item["working_intent_count"]} 待执行={item["unclaimed_intent_count"]}')


@project.command("show")
@click.argument("project_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
def show(client: BoardClient, project_id: str, as_json: bool):
    """查看目标、事实、意图、提示及最终结果。"""
    data = client.request("GET", project_path(project_id)).json()
    (print_json if as_json else print_project)(data)


@project.command("watch")
@click.argument("project_id")
@click.option("--interval", type=click.FloatRange(min=0.2), default=2.0, show_default=True)
@click.option("--timeout", type=click.FloatRange(min=0), default=0.0, help="最长等待秒数；0 表示不限时。超时不会停止项目。")
@click.pass_obj
def watch(client: BoardClient, project_id: str, interval: float, timeout: float):
    """有变化时打印黑板，项目完成或停止后退出。Ctrl+C 只退出观察。"""
    started = time.monotonic()
    previous = None
    while True:
        data = client.request("GET", project_path(project_id)).json()
        # Heartbeats change frequently without changing the visible board.
        visible = json.dumps({
            "project": {key: data["project"][key] for key in ("id", "status", "title")},
            "reason_worker": (data["project"].get("reason") or {}).get("worker"),
            "facts": data["facts"], "hints": data["hints"],
            "intents": [{key: value for key, value in item.items() if key != "last_heartbeat_at"}
                        for item in data["intents"]],
        }, sort_keys=True)
        if visible != previous:
            print_project(data)
            click.echo()
            previous = visible
        if data["project"]["status"] in ("completed", "stopped"):
            return
        if timeout and time.monotonic() - started >= timeout:
            raise click.ClickException("观察超时；项目仍保留当前状态，可使用 project stop 停止。")
        remaining = timeout - (time.monotonic() - started) if timeout else interval
        time.sleep(max(0, min(interval, remaining)))


@project.command("stop")
@click.argument("project_id")
@click.pass_obj
def stop(client: BoardClient, project_id: str):
    """停止项目，调度器将在下一次轮询时取消执行中的任务。"""
    data = client.request("PUT", project_path(project_id) + "/status", json={"status": "stopped"}).json()
    click.echo(f'{data["id"]} [{data["status"]}]')


@project.command("resume")
@click.argument("project_id")
@click.pass_obj
def resume(client: BoardClient, project_id: str):
    """恢复已停止的项目。"""
    data = client.request("PUT", project_path(project_id) + "/status", json={"status": "active"}).json()
    click.echo(f'{data["id"]} [{data["status"]}]')


@project.command("hint")
@click.argument("project_id")
@click.argument("content")
@click.pass_obj
def hint(client: BoardClient, project_id: str, content: str):
    """向黑板补充一条人工提示。"""
    data = client.request("POST", project_path(project_id) + "/hints",
                          json={"content": content, "creator": "terminal"}).json()
    click.echo(data["id"])


@project.command("export")
@click.argument("project_id")
@click.pass_obj
def export(client: BoardClient, project_id: str):
    """输出 YAML 黑板快照，可重定向到文件。"""
    response = client.request("GET", project_path(project_id) + "/export", params={"format": "yaml"})
    click.echo(response.text, nl=False)
