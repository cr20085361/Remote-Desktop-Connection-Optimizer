"""执行规则目录，按严重度排序输出 Finding。"""

from __future__ import annotations

from core.config import SEVERITY_ORDER
from core.models import Finding, Snapshot
from rules.catalog import RULES


def evaluate(snapshot: Snapshot) -> list[Finding]:
    findings: list[Finding] = []
    for rule in RULES:
        try:
            item = rule(snapshot)
        except Exception as exc:
            findings.append(
                Finding(
                    id="RX",
                    severity="info",
                    title=f"规则 {getattr(rule, '__name__', rule)} 执行失败",
                    evidence=str(exc),
                )
            )
            continue
        if item:
            findings.append(item)
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.id))
    return findings
