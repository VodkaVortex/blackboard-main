"""Native Pi integration: deterministic local model, real tools and board writes."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shlex
import shutil
import threading

from pydantic import ValidationError
import pytest

from cairn.console import LocalSession
from cairn.dispatcher.config import DispatchConfig, LocalConfig
from cairn.dispatcher.runtime.local_backend import LocalBackend
from cairn.dispatcher.workers.adapters.pi_dev import PiDevDriver
from test_mock_end_to_end import InProcessClient, _loop, http_client


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("setting,value", [("execution", "container"), ("prompt_group", "default")])
def test_development_profile_uses_its_own_task_contract(setting, value):
    data = DispatchConfig.load(ROOT / "dispatch.pi-dev.yaml").model_dump()
    data["runtime"][setting] = value
    with pytest.raises(ValidationError, match="pi_dev requires"):
        DispatchConfig.model_validate(data)


def test_shared_checkout_survives_task_completion(tmp_path):
    config = LocalConfig(working_directory=str(tmp_path))
    backend = LocalBackend(config)
    assert backend.ensure_running("project-1") == backend.ensure_running("project-2") == str(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("keep")
    assert not backend.needs_completed_cleanup("project-1")
    backend.cleanup_completed("project-1")
    assert source.read_text() == "keep"
    with pytest.raises(ValidationError, match="completed_action=keep"):
        LocalConfig(working_directory=str(tmp_path), completed_action="remove")


def test_console_resolves_default_checkout_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session = LocalSession(ROOT / "dispatch.pi-dev.yaml", tmp_path / "logs")
    assert session.config.local.working_directory == str(ROOT)
    override = LocalSession(ROOT / "dispatch.pi-dev.yaml", tmp_path / "logs", workdir=tmp_path)
    assert override.config.local.working_directory == str(tmp_path)


def test_native_pi_tools_return_results_to_blackboard(http_client, tmp_path, monkeypatch):
    """No external model/API key: a local SSE fixture requests four native tools.

    Only Pi's configuration directory is substituted. The driver, CLI, tools,
    subprocess backend, dispatcher task, and blackboard API run for real.
    """
    cli = ROOT / "pi-coding-agent/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
    node = shutil.which("node")
    if not cli.is_file() or not node:
        pytest.skip("Install the project-local Pi and Node.js to exercise native tools")
    requests = []
    calls = [
        ("write", {"path": "result.txt", "content": "before\n"}),
        ("edit", {"path": "result.txt", "oldText": "before", "newText": "after"}),
        ("read", {"path": "result.txt"}),
        ("bash", {"command": "pwd; cat result.txt; printf 'shell-ok\\n' > shell-result.txt"}),
    ]
    class ModelHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            tool_results = [m for m in body["messages"] if m["role"] == "tool"]
            step = len(tool_results)
            if step < len(calls):
                name, arguments = calls[step]
                delta = {"role": "assistant", "tool_calls": [{
                    "index": 0, "id": f"call-{step}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }]}
                finish = "tool_calls"
            else:
                payload = {"accepted": True, "data": {
                    "fact": {"description": "Native read/write/edit/bash completed; result.txt contains after and shell-result.txt contains shell-ok."},
                    "complete": {"description": "Verified the native tool results"},
                }}
                delta = {"role": "assistant", "content": json.dumps(payload)}
                finish = "stop"
            chunks = [
                {"id": "fixture", "object": "chat.completion.chunk", "created": 0, "model": "fixture",
                 "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"id": "fixture", "object": "chat.completion.chunk", "created": 0, "model": "fixture",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
            ]
            stream = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
            encoded = stream.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "settings.json").write_text(json.dumps({
        "defaultProvider": "cairn-fixture", "defaultModel": "fixture", "retry": {"enabled": False},
    }))
    (agent / "models.json").write_text(json.dumps({"providers": {"cairn-fixture": {
        "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "api": "openai-completions",
        "apiKey": "local-test-placeholder", "models": [{"id": "fixture"}],
    }}}))
    wrapper = tmp_path / "pi"
    # Offline applies only to startup checks, so all model traffic stays on the local fixture.
    wrapper.write_text("#!/bin/sh\nexec env " + shlex.quote(f"PI_CODING_AGENT_DIR={agent}") +
                       " PI_OFFLINE=1 " + shlex.quote(node) + " " + shlex.quote(str(cli)) + ' "$@"\n')
    wrapper.chmod(0o755)
    monkeypatch.setattr(PiDevDriver, "local_binary", lambda self: str(wrapper))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
    work = tmp_path / "work"
    work.mkdir()
    config = DispatchConfig.load(ROOT / "dispatch.pi-dev.yaml")
    config.local = LocalConfig(working_directory=str(work))
    client = InProcessClient(http_client)
    loop = _loop(config, client, LocalBackend(config.local))
    project_id = http_client.post("/projects", json={
        "title": "Native tools", "origin": "Use the temporary workspace",
        "goal": "Write, edit, read result.txt and use shell to inspect it", "bootstrap_enabled": True,
    }).json()["project"]["id"]
    try:
        summaries = client.list_projects()
        loop._initialize_reason_checkpoints(summaries)
        loop._refresh_runtime_projects(summaries)
        loop._dispatch_available(summaries)
        assert loop.futures
        for future in list(loop.futures):
            future.result(timeout=40)
        loop._reap_futures()
        project = client.get_project(project_id)
        assert project.project.status == "completed"
        assert (work / "result.txt").read_text() == "after\n"
        assert (work / "shell-result.txt").read_text() == "shell-ok\n"
        assert len(requests) == 5
        advertised = {tool["function"]["name"] for tool in requests[0]["tools"]}
        assert {"read", "write", "edit", "bash"} <= advertised
        final_results = [m for m in requests[-1]["messages"] if m["role"] == "tool"]
        assert "after" in json.dumps(final_results[2])
        assert str(work) in json.dumps(final_results[3])
        assert any("shell-result.txt" in f.description for f in project.facts)
    finally:
        loop.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
