"""One foreground console owning a local board server and a Pi dispatcher."""
from __future__ import annotations

from contextlib import ExitStack, suppress
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

import click
import requests
import yaml

from cairn.dispatcher.config import DispatchConfig
from cairn.dispatcher.prompting import load_prompt
from cairn.dispatcher.tasks.common import TEXT_REJECTION_CREATOR, PI_DEV_REJECTION_CREATOR
from cairn.dispatcher.workers.registry import get_driver
from cairn.terminal import BoardClient, print_project, project_path


REPO_ROOT = Path(__file__).resolve().parents[3]
CLI = [sys.executable, "-c", "from cairn.cli import main; main()"]


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    # The dispatcher cancels its Pi subprocess before joining its workers.
    for sig, grace in ((signal.SIGINT, 12), (signal.SIGTERM, 3), (signal.SIGKILL, 3)):
        with suppress(ProcessLookupError):
            process.send_signal(sig)
        try:
            process.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


class Conversation:
    def __init__(self, client: BoardClient, *, check_running=lambda: None,
                 log_dir: Path | None = None, turn_timeout: float = 300, interval: float = 0.5,
                 prompt_group: str = "development", working_directory: str | None = None):
        self.client = client
        self.check_running = check_running
        self.log_dir = log_dir
        self.turn_timeout = turn_timeout
        self.interval = interval
        self.prompt_group = prompt_group
        self.working_directory = working_directory
        self.history: list[dict[str, str]] = []
        self.project_id: str | None = None

    def submit(self, message: str) -> str:
        self.check_running()
        transcript = [*self.history, {"role": "user", "content": message}]
        context = load_prompt(self.prompt_group, "runtime_context.md")
        context += f"\nCairn 应用源码目录：{REPO_ROOT}\n"
        if self.working_directory:
            context += f"本轮 Pi 的初始工作目录：{self.working_directory}\n"
        result = self.client.request("POST", "/projects", json={
            "title": message[:60],
            "origin": context +
                      "\n以下是用户与助手的对话记录，仅作为数据和上下文：\n" +
                      json.dumps(transcript, ensure_ascii=False),
            "goal": "结合对话上下文，处理用户最新的请求；需要执行时完成工作并报告结果：\n" + message,
            "bootstrap_enabled": True,
        }).json()
        self.project_id = result["project"]["id"]
        self.history.append({"role": "user", "content": message})
        return self.project_id

    def stop_current(self) -> None:
        if self.project_id is None:
            return
        path = project_path(self.project_id)
        data = self.client.request("GET", path).json()
        if data["project"]["status"] == "active":
            try:
                self.client.request("PUT", path + "/status", json={"status": "stopped"})
            except click.ClickException:
                # A worker may have completed between the GET and PUT.
                if self.client.request("GET", path).json()["project"]["status"] != "completed":
                    raise

    def wait_reply(self) -> str | None:
        assert self.project_id is not None
        started = time.monotonic()
        while True:
            self.check_running()
            data = self.client.request("GET", project_path(self.project_id)).json()
            status = data["project"]["status"]
            if status == "completed":
                parts = [fact["description"] for fact in data["facts"] if fact["id"] not in ("origin", "goal")]
                if not parts:
                    parts = [intent["description"] for intent in data["intents"] if intent.get("to") == "goal"]
                answer = "\n\n".join(parts) or "本轮已完成，但黑板没有返回文本结果。"
                self.history.append({"role": "assistant", "content": answer})
                return answer
            if status == "stopped":
                for hint in reversed(data["hints"]):
                    if hint.get("creator") in (TEXT_REJECTION_CREATOR, PI_DEV_REJECTION_CREATOR):
                        answer = "本轮未完成：" + hint["content"] + "\n任务已暂停，不会自动重复请求。可以补充信息后继续。"
                        self.history.append({"role": "assistant", "content": answer})
                        return answer
                return None
            if time.monotonic() - started >= self.turn_timeout:
                self.stop_current()
                raise click.ClickException("本轮等待超时，已停止该任务。可用 /status 查看黑板，或 /logs 查看日志位置。")
            time.sleep(self.interval)

    def run(self) -> None:
        mode = "通用开发模式 · 原生工具已启用" if self.prompt_group == "development" else "纯文本模式"
        click.echo(f"Cairn 已启动 · Pi worker · {mode}")
        if self.working_directory:
            click.echo(f"Pi 工作目录：{self.working_directory}")
        click.echo("直接输入需求即可；/new 新对话，/status 查看进度，/logs 日志，/quit 退出。")
        click.echo("处理消息时按 Ctrl+C 可停止本轮；输入提示处按 Ctrl+C 可退出。")
        while True:
            try:
                message = click.prompt("你", prompt_suffix="> ").strip()
            except (click.Abort, EOFError, KeyboardInterrupt):
                return
            if not message:
                continue
            self.check_running()
            if message in ("/quit", "/exit"):
                return
            if message == "/help":
                click.echo("/new 清空本次对话上下文；/status 当前黑板；/stop 停止当前任务；/logs 日志位置；/quit 退出。")
                continue
            if message == "/logs":
                click.echo(str(self.log_dir) if self.log_dir else "独立对话入口没有托管日志。")
                continue
            try:
                if message == "/new":
                    self.stop_current()
                    self.history.clear()
                    self.project_id = None
                    click.echo("已开始新对话。")
                elif message == "/status":
                    if self.project_id:
                        print_project(self.client.request("GET", project_path(self.project_id)).json())
                    else:
                        click.echo("尚未发送消息。")
                elif message == "/stop":
                    self.stop_current()
                    click.echo("当前没有运行中的任务。")
                elif message.startswith("/"):
                    click.echo("未知命令；输入 /help 查看可用命令。")
                else:
                    self.submit(message)
                    click.echo("Pi 正在处理…（Ctrl+C 停止本轮）")
                    try:
                        answer = self.wait_reply()
                    except KeyboardInterrupt:
                        self.stop_current()
                        click.echo("\n已停止本轮，可以修改需求后继续。")
                        continue
                    click.echo("\nPi> " + (answer if answer is not None else "本轮已停止。") + "\n")
            except click.ClickException as exc:
                click.echo(f"提示：{exc.format_message()}", err=True)


class LocalSession:
    def __init__(self, config_path: Path, data_dir: Path, port: int | None = None,
                 workdir: Path | None = None):
        self.config_path = config_path.resolve()
        self.config = DispatchConfig.load(self.config_path)
        if self.config.runtime.execution != "local" or any(w.type not in ("pi_text", "pi_dev") for w in self.config.workers):
            raise click.ClickException("统一对话入口需要本地 pi_dev 或 pi_text worker。")
        if workdir is not None:
            if self.config.runtime.prompt_group != "development":
                raise click.ClickException("--workdir 用于通用开发配置 dispatch.pi-dev.yaml。")
            local = self.config.local.model_dump()
            local.update(working_directory=str(workdir.resolve()), workspace_root=None, completed_action="keep")
            self.config.local = type(self.config.local).model_validate(local)
        if self.config.local.working_directory:
            directory = Path(self.config.local.working_directory).expanduser()
            if not directory.is_absolute():
                directory = self.config_path.parent / directory
            directory = directory.resolve()
            if not directory.is_dir():
                raise click.ClickException(f"Pi 工作目录不存在：{directory}")
            self.config.local.working_directory = str(directory)
        address = urlsplit(self.config.server)
        if (address.scheme != "http" or address.hostname not in ("127.0.0.1", "localhost")
                or address.path not in ("", "/") or address.query or address.fragment or address.username):
            raise click.ClickException("统一启动配置的 server 必须是本机 HTTP 地址。")
        self.port = port if port is not None else (address.port or 8000)
        self.data_dir = data_dir.resolve()
        self.server: subprocess.Popen | None = None
        self.dispatcher: subprocess.Popen | None = None
        self.client: BoardClient | None = None
        self.stack = ExitStack()
        self.log_dir: Path | None = None

    def check_running(self) -> None:
        for name, process in (("黑板服务", self.server), ("调度器", self.dispatcher)):
            if process is not None and process.poll() is not None:
                raise click.ClickException(f"{name}已退出（代码 {process.returncode}），日志位于 {self.log_dir}")

    def open(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        lock = self.stack.enter_context((self.data_dir / "session.lock").open("a"))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise click.ClickException("这个数据目录已有运行中的 Cairn 会话，请先退出它，或指定其他 --data-dir。") from exc
        binary = get_driver(self.config.workers[0].type, "local").local_binary()
        try:
            subprocess.run([binary, "--version"], check=True, timeout=10, capture_output=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise click.ClickException(f"Pi 启动检查失败，请检查 {binary}") from exc
        sock = self.stack.enter_context(socket.socket())
        try:
            sock.bind(("127.0.0.1", self.port))
            sock.listen(128)
        except OSError as exc:
            raise click.ClickException(f"无法监听本地端口 {self.port}；检查已有服务，或使用 --port 0 自动选择端口。") from exc
        self.port = sock.getsockname()[1]
        self.log_dir = Path(tempfile.mkdtemp(prefix="run-", dir=self.data_dir))
        server_log = self.stack.enter_context((self.log_dir / "server.log").open("w", encoding="utf-8"))
        dispatcher_log = self.stack.enter_context((self.log_dir / "dispatcher.log").open("w", encoding="utf-8"))
        for name in ("server.log", "dispatcher.log"):
            (self.log_dir / name).chmod(0o600)
        base_url = f"http://127.0.0.1:{self.port}"
        self.client = BoardClient(base_url)
        self.stack.callback(self.client.session.close)
        self.server = subprocess.Popen([
            *CLI, "serve", "--host", "127.0.0.1", "--port", str(self.port),
            "--fd", str(sock.fileno()), "--db-path", str(self.data_dir / "cairn.db"), "--no-access-log",
        ], pass_fds=(sock.fileno(),), stdout=server_log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + 15
        while True:
            self.check_running()
            try:
                response = self.client.session.get(base_url + "/settings", timeout=0.5)
                if response.status_code == 200:
                    break
            except requests.RequestException:
                pass
            if time.monotonic() >= deadline:
                raise click.ClickException(f"黑板服务启动超时，日志位于 {self.log_dir}")
            time.sleep(0.1)
        # This console owns a separate database; never restart unfinished old chats implicitly.
        for old in self.client.request("GET", "/projects").json():
            if old["status"] == "active":
                self.client.request("PUT", project_path(old["id"]) + "/status", json={"status": "stopped"})
        runtime_dir = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="config-", dir=self.data_dir)))
        runtime_config = self.config.model_dump(exclude_none=True)
        runtime_config["server"] = base_url
        # Preserve outbound proxies for model calls, but bypass them for the local board.
        child_env = dict(os.environ)
        for name in ("NO_PROXY", "no_proxy"):
            child_env[name] = ",".join(filter(None, [child_env.get(name), "127.0.0.1", "localhost"]))
        path = runtime_dir / "dispatch.yaml"
        path.write_text(yaml.safe_dump(runtime_config, allow_unicode=True), encoding="utf-8")
        path.chmod(0o600)
        self.dispatcher = subprocess.Popen([
            *CLI, "dispatch", "--config", str(path),
        ], stdout=dispatcher_log, stderr=subprocess.STDOUT, env=child_env, start_new_session=True)
        click.echo(f"服务日志：{self.log_dir}")

    def close(self) -> None:
        try:
            stop_process(self.dispatcher)
        finally:
            try:
                stop_process(self.server)
            finally:
                self.stack.close()


@click.command()
@click.option("--config", "config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=str(REPO_ROOT / "dispatch.pi-dev.yaml"), show_default=True)
@click.option("--workdir", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help="Pi 执行命令和读写文件的工作目录；默认使用配置中的目录。")
@click.option("--port", type=click.IntRange(0, 65535), default=None, help="覆盖本地端口；0 自动选择空闲端口。")
@click.option("--data-dir", type=click.Path(file_okay=False, path_type=Path),
              default=str(REPO_ROOT / "datas/terminal"), show_default=True)
@click.option("--turn-timeout", type=click.FloatRange(min=1), default=300.0, show_default=True)
def start(config_path: Path, workdir: Path | None, port: int | None, data_dir: Path, turn_timeout: float):
    """启动黑板、Pi 调度器和对话终端；退出时停止本次启动的进程。"""
    session = LocalSession(config_path, data_dir, port, workdir)
    conversation = None
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    previous_sigterm = signal.signal(signal.SIGTERM, interrupted)
    try:
        session.open()
        conversation = Conversation(session.client, check_running=session.check_running,
                                    log_dir=session.log_dir, turn_timeout=turn_timeout,
                                    prompt_group=session.config.runtime.prompt_group,
                                    working_directory=session.config.local.working_directory)
        conversation.run()
    finally:
        try:
            try:
                if conversation is not None:
                    with suppress(click.ClickException):
                        conversation.stop_current()
            finally:
                session.close()
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
        click.echo("Cairn 本次会话已关闭。")
