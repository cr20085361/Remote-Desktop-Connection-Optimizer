from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.models import Snapshot


@dataclass
class FixResult:
    ok: bool
    message: str
    rollback_path: str = ""
    changed: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class FixAction:
    id: str
    title: str
    summary: str
    risk: str
    need_admin: bool = True
    reversible: bool = True

    def precheck(self, snapshot: Snapshot) -> tuple[bool, str]:
        raise NotImplementedError

    def apply(self, snapshot: Snapshot) -> FixResult:
        raise NotImplementedError

    def verify(self, snapshot: Snapshot) -> tuple[bool, str]:
        return True, "未实现专项校验，请重新采集确认。"
