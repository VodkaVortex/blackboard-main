from __future__ import annotations

import os
from pathlib import Path

from cairn.dispatcher.config import WorkerConfig
from cairn.dispatcher.prompting import load_prompt
from cairn.dispatcher.workers.adapters.pi import PiDriver
from cairn.dispatcher.workers.base import DriverResult
from cairn.dispatcher.workers.health import HealthResult


class PiDevDriver(PiDriver):
    """Checkout-local Pi with native tools and resource discovery for development.

    Keep Pi's default system prompt, tools, provider settings, and trust decisions.
    Only append the Cairn worker contract and request machine-readable events.
    """

    type_name = "pi_dev"

    def local_binary(self) -> str:
        return str(Path(__file__).resolve().parents[6] / "pi-coding-agent" / "pi")

    def check_health(self, worker: WorkerConfig, *, timeout: float) -> HealthResult:
        available = os.access(self.local_binary(), os.X_OK)
        return HealthResult(available, None, "CLI presence only; model credentials not checked")

    def describe_health(self, worker: WorkerConfig) -> str:
        return self.local_binary()

    def build_execute(self, worker: WorkerConfig, prompt: str, session: str | None) -> DriverResult:
        return DriverResult(self._argv(worker, prompt, session), session)

    def build_conclude(self, worker: WorkerConfig, prompt: str, session: str) -> list[str]:
        return self._argv(worker, prompt, session)

    def _argv(self, worker: WorkerConfig, prompt: str, session: str | None) -> list[str]:
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in worker.name)
        session_dir = Path.home() / ".local" / "state" / "cairn" / "pi-dev-sessions" / (safe_name or "worker")
        argv = [
            self.local_binary(),
            "--mode", "json",
            "--session-dir", str(session_dir),
            "--append-system-prompt", load_prompt("development", "worker.md"),
        ]
        if session:
            argv.extend(["--session", session])
        argv.extend(["-p", "--", prompt])
        return argv
