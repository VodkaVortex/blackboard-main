from __future__ import annotations

from pathlib import Path
import os
import socket
import subprocess
from types import SimpleNamespace

import click
import pytest

from cairn.console import Conversation, LocalSession
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.tasks.common import TEXT_REJECTION_CREATOR, PI_DEV_REJECTION_CREATOR
from cairn.dispatcher.scheduler.loop import DispatcherLoop
from cairn.terminal import BoardClient
from test_terminal import runner, http_client


ROOT = Path(__file__).resolve().parents[2]


def complete(http_client, project_id, answer):
    response = http_client.post(f"/projects/{project_id}/complete", json={
        "from": ["origin"], "description": answer, "worker": "test",
    })
    assert response.status_code == 200


def test_conversation_preserves_user_and_worker_context(runner, http_client):
    board = BoardClient("http://127.0.0.1:8000")
    conversation = Conversation(board)
    first = conversation.submit("17加25等于多少？")
    complete(http_client, first, "42")
    assert conversation.wait_reply() == "42"
    second = conversation.submit("再加1呢？")
    assert second != first
    data = http_client.get(f"/projects/{second}").json()
    origin = next(f["description"] for f in data["facts"] if f["id"] == "origin")
    assert "17加25" in origin and "42" in origin and "再加1" in origin
    assert "窗口是用户界面，不是 worker" in origin
    assert "Dispatcher 是调度程序" in origin
    conversation.stop_current()
    assert http_client.get(f"/projects/{second}").json()["project"]["status"] == "stopped"


def test_conversation_timeout_stops_task(runner, http_client):
    conversation = Conversation(BoardClient("http://127.0.0.1:8000"), turn_timeout=0)
    project_id = conversation.submit("请总结这段文字。")
    with pytest.raises(click.ClickException, match="超时"):
        conversation.wait_reply()
    assert http_client.get(f"/projects/{project_id}").json()["project"]["status"] == "stopped"


def test_console_accepts_messages_and_new_without_manual_project_commands(runner, http_client, monkeypatch):
    conversation = Conversation(BoardClient("http://127.0.0.1:8000"))
    messages = iter(["计算17加25", "/new", "/quit"])
    monkeypatch.setattr(click, "prompt", lambda *a, **kw: next(messages))
    def finish_if_active():
        if conversation.project_id:
            data = http_client.get(f"/projects/{conversation.project_id}").json()
            if data["project"]["status"] == "active":
                complete(http_client, conversation.project_id, "42")
    conversation.check_running = finish_if_active
    conversation.run()
    assert conversation.history == []
    assert conversation.project_id is None
    assert len(http_client.get("/projects").json()) == 1


@pytest.mark.parametrize("creator", [TEXT_REJECTION_CREATOR, PI_DEV_REJECTION_CREATOR])
def test_conversation_displays_rejection_reason_without_waiting_for_timeout(runner, http_client, creator):
    conversation = Conversation(BoardClient("http://127.0.0.1:8000"), turn_timeout=0)
    project_id = conversation.submit("请说明这个架构。")
    http_client.post(f"/projects/{project_id}/hints", json={
        "content": "缺少架构说明", "creator": creator,
    })
    http_client.put(f"/projects/{project_id}/status", json={"status": "stopped"})
    answer = conversation.wait_reply()
    assert "缺少架构说明" in answer
    assert "不会自动重复请求" in answer
    assert conversation.history[-1]["content"] == answer


def test_dispatcher_interrupt_cancels_running_workers():
    cancellation = TaskCancellation()
    loop = DispatcherLoop.__new__(DispatcherLoop)
    loop.futures = {object(): SimpleNamespace(cancellation=cancellation)}
    def interrupt():
        raise KeyboardInterrupt
    loop.run_startup_healthchecks = interrupt
    closed = []
    loop.close = lambda: closed.append(True)
    with pytest.raises(KeyboardInterrupt):
        loop.run()
    assert cancellation.is_cancelled
    assert closed == [True]


@pytest.mark.parametrize("profile", ["text", "dev"])
def test_unified_session_starts_services_and_cleans_up(tmp_path, profile):
    """Real services on an ephemeral local port; no task or model request."""
    session = LocalSession(ROOT / f"dispatch.pi-{profile}.yaml", tmp_path, port=0)
    try:
        session.open()
        assert session.client.request("GET", "/projects").json() == []
        assert session.client.session.get(session.client.server + "/", timeout=3).status_code == 404
        assert session.server.poll() is None
        assert session.dispatcher.poll() is None
        port = session.port
        # A second launch may not share this database or stop the first session's tasks.
        second = LocalSession(ROOT / "dispatch.pi-text.yaml", tmp_path, port=0)
        try:
            with pytest.raises(click.ClickException, match="已有运行中的"):
                second.open()
        finally:
            second.close()
    finally:
        session.close()
    assert session.server.poll() is not None
    assert session.dispatcher.poll() is not None
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0


def test_start_command_accepts_quit_and_returns(tmp_path):
    result = subprocess.run([str(ROOT / "start-cairn.sh"), "--port", "0", "--data-dir", str(tmp_path),
                             "--workdir", str(tmp_path)],
                            input="/quit\n", text=True, capture_output=True, timeout=30,
                            cwd=tmp_path, env={**os.environ, "UV_OFFLINE": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Pi worker" in result.stdout
    assert "原生工具已启用" in result.stdout
    assert f"Pi 工作目录：{tmp_path}" in result.stdout
    assert "本次会话已关闭" in result.stdout


def test_busy_port_does_not_attach_to_or_stop_another_server(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        session = LocalSession(ROOT / "dispatch.pi-text.yaml", tmp_path, port=sock.getsockname()[1])
        try:
            with pytest.raises(click.ClickException, match="无法监听"):
                session.open()
            assert session.server is None and session.dispatcher is None
        finally:
            session.close()
        assert sock.fileno() >= 0
