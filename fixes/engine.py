"""修复引擎：precheck → apply → 记录回滚。"""

from __future__ import annotations

from core.models import Snapshot
from core.runner import is_admin
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
