from __future__ import annotations

from pathlib import Path
import sys

from pydantic import ValidationError
import pytest

from cairn.dispatcher.config import DispatchConfig, LocalConfig
from cairn.dispatcher.runtime.local_backend import LocalBackend
from cairn.dispatcher.tasks.common import write_graph_snapshot_reference
from cairn.dispatcher.tasks.common import TEXT_REJECTION_CREATOR, PI_DEV_REJECTION_CREATOR
from cairn.dispatcher.workers.adapters.pi_text import PiTextDriver
from cairn.dispatcher.workers.adapters.pi_dev import PiDevDriver

from test_mock_end_to_end import InProcessClient, _dispatch_and_wait, _loop, http_client


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_config() -> DispatchConfig:
    return DispatchConfig.load(REPO_ROOT / "dispatch.pi-text.yaml")


@pytest.mark.parametrize("setting,value", [("execution", "container"), ("prompt_group", "default")])
def test_pi_text_rejects_incompatible_modes(setting, value):
    data = load_config().model_dump()
    data["runtime"][setting] = value
    with pytest.raises(ValidationError, match="pi_text requires"):
        DispatchConfig.model_validate(data)


def test_pi_text_conclude_keeps_tools_disabled_and_resumes_session():
    driver = PiTextDriver()
    worker = load_config().workers[0]
    argv = driver.build_conclude(worker, "-literal prompt", "session-123")
    assert argv[0] == str(REPO_ROOT / "pi-coding-agent" / "pi")
    assert "--no-tools" in argv
    assert "--tools" not in argv
    assert "--no-extensions" in argv
    assert "--no-approve" in argv
    assert argv[argv.index("--session") + 1] == "session-123"
    assert argv[-3:] == ["-p", "--", "-literal prompt"]


def test_inline_graph_does_not_require_file_access():
    graph = "facts:\n- id: origin\n  description: Numbers 17 and 25"
    # A backend with no methods proves this path does not write a snapshot file.
    assert write_graph_snapshot_reference(object(), "unused", graph, phase="reason", inline=True) == graph


def test_pi_text_reason_explore_complete_roundtrip(http_client, tmp_path, monkeypatch):
    """Real subprocess and board API, with deterministic Pi-shaped JSON events.

    This is a protocol test, not a live-model test.
    """
    fake_pi = tmp_path / "pi"
    counter = tmp_path / "invocations"
    fake_pi.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "assert '--no-tools' in args and '--tools' not in args\n"
        "assert '--no-extensions' in args and '--no-context-files' in args\n"
        "assert '--no-approve' in args\n"
        "prompt = args[-1]\n"
        "assert 'facts:' in prompt and '17' in prompt and '25' in prompt\n"
        "assert 'stored in this file' not in prompt\n"
        f"counter = pathlib.Path({str(counter)!r})\n"
        "step = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(step + 1))\n"
        "outputs = [\n"
        " {'intents':[{'from':['origin'],'description':'Add the supplied numbers 17 and 25'}]},\n"
        " {'description':'17 + 25 = 42'},\n"
        " {'complete':{'from':['f001'],'description':'The sum is 42'}}\n"
        "]\n"
        "payload = {'accepted':True, 'data':outputs[step]}\n"
        "print(json.dumps({'type':'session','id':'text-test-session'}))\n"
        "print(json.dumps({'type':'agent_end','messages':[{'role':'assistant','content':[{'type':'text','text':json.dumps(payload)}]}]}))\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    monkeypatch.setattr(PiTextDriver, "local_binary", lambda self: str(fake_pi))
    config = load_config()
    client = InProcessClient(http_client)
    backend = LocalBackend(LocalConfig(workspace_root=str(tmp_path / "workspaces")))
    loop = _loop(config, client, backend)
    response = http_client.post("/projects", json={
        "title": "Pi text protocol test",
        "origin": "Numbers: 17 and 25",
        "goal": "Calculate the sum",
        "bootstrap_enabled": False,
    })
    assert response.status_code == 201
    project_id = response.json()["project"]["id"]
    try:
        for _ in range(3):
            _dispatch_and_wait(loop)
        project = client.get_project(project_id)
    finally:
        loop.close()
    assert project.project.status == "completed"
    assert any(fact.description == "17 + 25 = 42" for fact in project.facts)
    assert counter.read_text() == "3"


@pytest.mark.parametrize("phase", ["bootstrap", "reason", "explore"])
@pytest.mark.parametrize("profile,driver,creator", [
    ("text", PiTextDriver, TEXT_REJECTION_CREATOR),
    ("dev", PiDevDriver, PI_DEV_REJECTION_CREATOR),
])
def test_text_rejection_is_reported_and_not_redispatched(http_client, tmp_path, monkeypatch, phase, profile, driver, creator):
    fake_pi = tmp_path / "pi-reject"
    counter = tmp_path / "invocations"
    fake_pi.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib\n"
        f"counter = pathlib.Path({str(counter)!r})\n"
        "counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')\n"
        "payload = {'accepted':False,'reason':'缺少必要的输入说明'}\n"
        "print(json.dumps({'type':'agent_end','messages':[{'role':'assistant','content':[{'type':'text','text':json.dumps(payload)}]}]}))\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    monkeypatch.setattr(driver, "local_binary", lambda self: str(fake_pi))
    client = InProcessClient(http_client)
    config = DispatchConfig.load(REPO_ROOT / f"dispatch.pi-{profile}.yaml")
    loop = _loop(config, client, LocalBackend(LocalConfig(workspace_root=str(tmp_path / "work"))))
    response = http_client.post("/projects", json={
        "title": "text rejection", "origin": "question", "goal": "answer",
        "bootstrap_enabled": phase == "bootstrap",
    })
    project_id = response.json()["project"]["id"]
    if phase == "explore":
        assert client.create_intent(project_id, ["origin"], "Read supplied text", "test").ok
    try:
        _dispatch_and_wait(loop)
        project = client.get_project(project_id)
        assert project.project.status == "stopped"
        assert len(project.facts) == 2
        notices = [h for h in project.hints if h.creator == creator]
        assert len(notices) == 1 and "缺少必要的输入说明" in notices[0].content
        loop._dispatch_available(client.list_projects())
        assert not loop.futures
        assert counter.read_text() == "1"
    finally:
        loop.close()
