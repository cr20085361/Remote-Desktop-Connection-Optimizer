"""统一子进程执行器：UTF-8、超时、JSON 优先、敏感信息脱敏。"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Optional, Sequence

REDACT_KEYS = (
    "PrivateNodeKey",
    "OldPrivateNodeKey",
    "NetworkLockKey",
    "authkey",
    "AuthKey",
    "api_key",
    "apiKey",
    "password",
    "Password",
)

_PRIVKEY_RE = re.compile(r"(privkey|nlpriv|tskey)[:\-][A-Za-z0-9+/=_\-]{8,}", re.I)


@dataclass
class RunResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def json(self) -> Any:
        text = self.stdout.strip()
        if not text:
            raise ValueError("empty stdout")
        return json.loads(text)


def redact_text(text: str) -> str:
    if not text:
        return text
    return _PRIVKEY_RE.sub(lambda m: m.group(1) + ":[REDACTED]", text)


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if any(k.lower() == key.lower() for k in REDACT_KEYS):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact_obj(value)
        return out
    if isinstance(obj, list):
        return [redact_obj(item) for item in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def which(name: str) -> Optional[str]:
    path = shutil.which(name)
    return path


def run(
    argv: Sequence[str],
    *,
    timeout: float = 30,
    cwd: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> RunResult:
    merged = os.environ.copy()
    merged["PYTHONIOENCODING"] = "utf-8"
    merged["PYTHONUTF8"] = "1"
    if env:
        merged.update(env)
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
            env=merged,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        return RunResult(
            argv=list(argv),
            returncode=completed.returncode,
            stdout=redact_text(stdout),
            stderr=redact_text(stderr),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, (bytes, bytearray)) else str(exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, (bytes, bytearray)) else str(exc.stderr or "")
        return RunResult(
            argv=list(argv),
            returncode=-1,
            stdout=redact_text(stdout),
            stderr=redact_text(stderr or f"timeout after {timeout}s"),
            timed_out=True,
        )
    except FileNotFoundError as exc:
        return RunResult(list(argv), 127, "", str(exc))


def run_powershell(script: str, *, timeout: float = 45) -> RunResult:
    wrapped = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$ProgressPreference = 'SilentlyContinue'; "
        "$ErrorActionPreference = 'Continue'; "
        + script
    )
    encoded = base64.b64encode(wrapped.encode("utf-16le")).decode("ascii")
    return run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        timeout=timeout,
    )


def powershell_json(script: str, *, timeout: float = 45) -> Any:
    result = run_powershell(script, timeout=timeout)
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout or f"powershell failed: {result.returncode}")
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        start_arr = text.find("[")
        if start == -1 and start_arr == -1:
            raise
        idx = start if start != -1 and (start_arr == -1 or start < start_arr) else start_arr
        return json.loads(text[idx:])


def is_admin() -> bool:
    if sys.platform != "win32":
        return os.geteuid() == 0  # type: ignore[attr-defined]
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
