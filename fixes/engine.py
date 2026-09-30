"""修复引擎：precheck → apply → 记录回滚。"""

from __future__ import annotations

import json
from pathlib import Path

from core.models import Snapshot
from core.runner import is_admin, run_powershell
from fixes import v2rayn
from fixes.base import FixResult
from fixes.catalog import ACTIONS


def list_actions():
    return list(ACTIONS.values())


def run_fix(fix_id: str, snapshot: Snapshot, *, confirmed: bool) -> FixResult:
    if not confirmed:
        return FixResult(False, "未确认，已跳过")
    action = ACTIONS.get(fix_id)
    if not action:
        return FixResult(False, f"未知修复项 {fix_id}")
    if action.need_admin and not is_admin():
        return FixResult(False, "此操作需要管理员权限，请以管理员重新启动。")
    ok, msg = action.precheck(snapshot)
    if not ok:
        return FixResult(False, f"预检查未通过: {msg}")
    return action.apply(snapshot)


def run_rollback(script_path: str) -> tuple[bool, str]:
    """撤销一次修复。有精确撤销记录（.json）时只删本工具加的内容，否则运行回滚脚本。"""
    path = Path(script_path)
    meta_path = path.with_suffix(".json")
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        if meta.get("kind") == "v2rayn":
            return v2rayn.undo_from_meta(meta)
    result = run_powershell(f'& "{script_path}"', timeout=40)
    return result.ok, (result.stdout or result.stderr or "已执行撤销脚本。").strip()
