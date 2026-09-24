from __future__ import annotations

import json
from urllib.parse import urlsplit

from click.testing import CliRunner
import pytest
import requests

from cairn.cli import main
from test_mock_end_to_end import http_client


@pytest.fixture
def runner(http_client, monkeypatch):
    """CLI -> real board API/database, with no external network or model calls."""
    def request(_session, method, url, **kwargs):
        kwargs.pop("timeout", None)
        api_response = http_client.request(method, urlsplit(url).path, **kwargs)
        response = requests.Response()
        response.status_code = api_response.status_code
        response._content = api_response.content
        response.headers.update(api_response.headers)
        response.encoding = "utf-8"
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    return CliRunner()


def invoke(runner, *args):
    result = runner.invoke(main, ["project", *args])
    assert result.exit_code == 0, result.output
    return result.output


def create(runner):
    return invoke(runner, "create", "--title", "计算", "--origin", "17 和 25",
                  "--goal", "求和", "--no-bootstrap").strip()


def test_terminal_project_lifecycle(runner):
    project_id = create(runner)
    assert project_id.startswith("proj_")
    assert "计算" in invoke(runner, "list")
    data = json.loads(invoke(runner, "show", project_id, "--json"))
    assert data["project"]["bootstrap_enabled"] is False
    assert data["facts"][0]["description"] == "17 和 25"
    assert invoke(runner, "hint", project_id, "请用中文回答").strip()
    assert "请用中文回答" in invoke(runner, "show", project_id)
    assert "stopped" in invoke(runner, "stop", project_id)
    assert "stopped" in invoke(runner, "watch", project_id)
    assert "active" in invoke(runner, "resume", project_id)
    assert "17 和 25" in invoke(runner, "export", project_id)


def test_create_accepts_stdin_and_validates_origin(runner):
    result = runner.invoke(main, ["project", "create", "--title", "文档", "--origin-file", "-",
                                  "--goal", "总结"], input="这是一份待整理的文档。")
    assert result.exit_code == 0, result.output
    project_id = result.output.strip()
    assert "待整理的文档" in invoke(runner, "show", project_id)
    for args in ([], ["--origin", "a", "--origin-file", "-"], ["--origin", " "]):
        result = runner.invoke(main, ["project", "create", "--title", "test", "--goal", "test", *args])
        assert result.exit_code != 0


def test_watch_timeout_does_not_stop_project(runner):
    project_id = create(runner)
    result = runner.invoke(main, ["project", "watch", project_id, "--timeout", "0.01", "--interval", "0.2"])
    assert result.exit_code != 0
    assert "观察超时" in result.output
    data = json.loads(invoke(runner, "show", project_id, "--json"))
    assert data["project"]["status"] == "active"


def test_watch_prints_completion_result(runner, http_client):
    project_id = create(runner)
    response = http_client.post(f"/projects/{project_id}/complete", json={
        "from": ["origin"], "description": "17 + 25 = 42", "worker": "test",
    })
    assert response.status_code == 200
    output = invoke(runner, "watch", project_id)
    assert "completed" in output
    assert "17 + 25 = 42" in output


def test_terminal_shows_api_errors(runner):
    result = runner.invoke(main, ["project", "show", "missing"])
    assert result.exit_code != 0
    assert "404" in result.output


def test_terminal_connection_failure_is_actionable(monkeypatch):
    def offline(*args, **kwargs):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests.Session, "request", offline)
    result = CliRunner().invoke(main, ["project", "list"])
    assert result.exit_code != 0
    assert "cairn serve" in result.output


def test_server_exposes_api_without_web_pages(http_client):
    assert http_client.get("/settings").status_code == 200
    for path in ("/", "/static/index.html", "/docs", "/redoc", "/openapi.json"):
        assert http_client.get(path).status_code == 404
