"""把规则命中翻译成小白能看懂的结论、评分和卡片文案。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.config import SEVERITY_ORDER
from core.models import Finding, PeerState, Snapshot

SEVERITY_PENALTY = {"critical": 25, "high": 12, "medium": 6, "low": 2, "info": 0}
SEVERITY_LABEL = {
    "critical": "必须处理",
    "high": "建议处理",
    "medium": "可以优化",
    "low": "锦上添花",
    "info": "提示",
}
BAND_LABEL = (
    (85, "优秀"),
    (70, "良好"),
    (40, "需要处理"),
    (0, "严重"),
)

REGION_ZH = {
    "lax": "洛杉矶",
    "los angeles": "洛杉矶",
    "sfo": "旧金山",
    "san francisco": "旧金山",
    "sea": "西雅图",
    "den": "丹佛",
    "dfw": "达拉斯",
    "ord": "芝加哥",
    "iad": "华盛顿",
    "nyc": "纽约",
    "mia": "迈阿密",
    "hnl": "檀香山",
    "tor": "多伦多",
    "ams": "阿姆斯特丹",
    "lhr": "伦敦",
    "london": "伦敦",
    "par": "巴黎",
    "fra": "法兰克福",
    "frankfurt": "法兰克福",
    "mad": "马德里",
    "nue": "纽伦堡",
    "waw": "华沙",
    "hel": "赫尔辛基",
    "syd": "悉尼",
    "sao": "圣保罗",
    "hkg": "香港",
    "hong kong": "香港",
    "tok": "东京",
    "tokyo": "东京",
    "nrt": "东京",
    "sin": "新加坡",
    "singapore": "新加坡",
    "blr": "班加罗尔",
    "sel": "首尔",
}


@dataclass
class RuleCopy:
    plain_title: str
    meaning: str
    impact: str
    next_step: str
    expected_gain: str
    auto_fix: bool = True


@dataclass
class FixCopy:
    name: str
    what_changes: str
    post_action: str = ""
    risk: str = "低。随时可以撤销。"


@dataclass
class IssueCard:
    finding_id: str
    severity: str
    severity_label: str
    title: str
    meaning: str
    impact: str
    next_step: str
    expected_gain: str
    evidence: str
    fix_ids: list[str] = field(default_factory=list)
    primary_fix: str = ""
    auto_fix: bool = True


RULE_COPY: dict[str, RuleCopy] = {
    "R01": RuleCopy(
        plain_title="翻墙软件把远程桌面的路也带出国了",
        meaning=(
            "两台电脑本该在国内直接对话。现在翻墙软件开了「全局接管」"
            "（把电脑所有上网流量先送到代理），远程组网误以为自己在国外"
            "（对外报出的地址是 {exit_ip}），于是家和办公室之间的画面先出国再绕回来。"
        ),
        impact="远程桌面会明显卡顿，拖窗口像拖果冻，键盘也有迟滞。",
        next_step="点「修复这个」，让远程组网不再走翻墙通道。",
        expected_gain="{gain}",
    ),
    "R02": RuleCopy(
        plain_title="备用中转站选到了很远的地方",
        meaning=(
            "直连失败时，组网会找一个「中转站」帮忙传画面。"
            "现在它选的是{derp_place}，往返大约 {derp_ms} 毫秒。"
            "在国内，正常应就近走香港或东京，大约几十毫秒。"
        ),
        impact="一旦直连断开，远程桌面几乎不可用。",
        next_step="先修好「翻墙把路带出国」的问题，中转站通常会自动回到亚洲。",
        expected_gain="{gain}",
    ),
    "R03": RuleCopy(
        plain_title="有 {relay_count} 台电脑没能直连，正在绕路",
        meaning=(
            "在线的电脑里，{relay_names} 没走直线，而是经{derp_place}中转。"
            "最慢的一台往返 {worst_ms} 毫秒。"
        ),
        impact="这些电脑上的远程桌面会特别卡，几乎没法流畅操作。",
        next_step="先让组网不再走翻墙；若仍绕路，再固定组网端口帮助打洞。",
        expected_gain="{gain}",
    ),
    "R04": RuleCopy(
        plain_title="虽然连上了，但还是比正常慢很多",
        meaning=(
            "{slow_names} 看起来是直连，但往返超过 120 毫秒。"
            "国内两地之间通常只要 20 到 60 毫秒。多出来的时间，往往是数据仍在绕行，或运营商跨网拥堵。"
        ),
        impact="画面能用，但拖动和打字会有可感知的延迟。",
        next_step="先排除翻墙绕路，再看是不是 Wi-Fi 或不必要的画质设置。",
        expected_gain="{gain}",
    ),
    "R05": RuleCopy(
        plain_title="翻墙通道抢了电脑的默认出路",
        meaning=(
            "系统现在把「所有上网」优先送给翻墙网卡。"
            "远程组网探测自己在哪的时候，也会被送进这条通道，于是误报成国外地址。"
        ),
        impact="不只远程桌面，组网的握手和备用中转都会变慢。",
        next_step="让远程组网从翻墙里豁免；这比去改网卡优先级更安全。",
        expected_gain="{gain}",
    ),
    "R06": RuleCopy(
        plain_title="系统代理名单漏了远程组网的地址",
        meaning=(
            "浏览器翻墙用的「系统代理」会拦截一部分软件。"
            "名单里已经放过了家里的网段，但漏了远程组网用的 100.x 地址。"
        ),
        impact="远程桌面有可能被塞进翻墙软件，画面变慢或连不上。",
        next_step="点「修复这个」，把 100.x 加入「不要走代理」名单。马上生效，不用重启。",
        expected_gain="远程桌面不再被系统代理拐走。",
    ),
    "R07": RuleCopy(
        plain_title="远程桌面被限制成只走较慢的通道",
        meaning=(
            "远程桌面可以同时用两条通道：一条稳、一条快。"
            "这台电脑的设置不是默认值，可能关掉了较快的那条。"
        ),
        impact="网络稍差时更容易卡顿、花屏。",
        next_step="点「修复这个」恢复双通道。需要管理员权限。",
        expected_gain="弱网下画面会更稳一些。",
    ),
    "R08": RuleCopy(
        plain_title="数据包太大，路上可能被拆散",
        meaning=(
            "每张画面拆成小包裹发送。组网和翻墙通道允许的包裹大小差得太多，"
            "包裹可能在路上被拆开甚至丢失。"
        ),
        impact="偶发卡一下、花一下，或突然断一下。",
        next_step="把组网通道的包裹大小调到更稳妥的值。",
        expected_gain="减少无故卡顿和闪断。",
    ),
    "R09": RuleCopy(
        plain_title="线路不稳：一会儿快一会儿慢，还丢包",
        meaning=(
            "{jitter_text}"
            "远程桌面最怕的不是带宽不够，而是延迟忽高忽低。"
        ),
        impact="画面会一顿一顿，鼠标指针会「跳」。",
        next_step="先确认不是翻墙绕路；仍不稳的话，尽量改用网线，并换一份更省流量的远程桌面配置。",
        expected_gain="{gain}",
    ),
    "R10": RuleCopy(
        plain_title="这台电脑正在用 Wi-Fi，而不是网线",
        meaning="当前上网走的是无线。远程桌面对延迟抖动很敏感，隔壁微波炉、隔壁 Wi-Fi 都可能让画面顿一下。",
        impact="即使带宽显示「千兆」，操作仍可能时不时卡一下。",
        next_step="有条件时插上网线。同时可以生成一份更省流量的远程桌面配置。",
        expected_gain="插网线后，一般会立刻稳很多。",
        auto_fix=True,
    ),
    "R11": RuleCopy(
        plain_title="正在用的远程桌面画质偏高，弱网会更吃力",
        meaning="检测到正在连远程桌面。默认配置会传壁纸、平滑字体和高色深，线路稍差时这些都是负担。",
        impact="在绕路或 Wi-Fi 场景下，卡顿会被放大。",
        next_step="生成一份「弱网友好」的连接文件，用它来连，而不是直接打开系统自带的远程桌面。",
        expected_gain="同样的线路下，画面会更跟手。",
    ),
}

FIX_COPY: dict[str, FixCopy] = {
    "F01": FixCopy(
        name="让远程组网不再走翻墙",
        what_changes="会改 v2rayN 的分流规则：远程组网相关程序改为直连，不进代理。",
        post_action="请到 v2rayN 窗口底部，关掉再打开「启用 Tun」。改完规则必须这一步才会生效。",
        risk="只改分流规则，可随时撤销。改完需要你手动重启一次 Tun。",
    ),
    "F02": FixCopy(
        name="关掉翻墙的全局接管（备选）",
        what_changes="尝试关闭 v2rayN 的 Tun。关不掉的话会告诉你怎么手动关。",
        post_action="若提示需要手动操作：打开 v2rayN，关掉底部「启用 Tun」。浏览器用系统代理即可。",
        risk="关闭后，只有浏览器等走代理的软件继续翻墙；远程桌面和组网不再被带走。可再打开 Tun 撤销。",
    ),
    "F03": FixCopy(
        name="让系统代理放过远程组网地址",
        what_changes="在当前用户的代理绕过名单里加上 100.*。",
        post_action="",
        risk="只改当前 Windows 用户的代理名单，可随时撤销，不用重启。",
    ),
    "F04": FixCopy(
        name="远程组网地址一律直连",
        what_changes="在 v2rayN 分流里加入 100.64.0.0/10 直连，并让 Tun 排除这段地址。",
        post_action="请到 v2rayN 窗口底部，关掉再打开「启用 Tun」。",
        risk="只改分流和 Tun 排除名单，可随时撤销。",
    ),
    "F05": FixCopy(
        name="降低翻墙网卡的抢路优先级",
        what_changes="把翻墙虚拟网卡的接口跃点调高，让普通网卡更容易当默认出路。",
        post_action="",
        risk="可能影响 Tun 的全局接管效果。优先用「让远程组网不再走翻墙」。需要管理员权限，可撤销。",
    ),
    "F06": FixCopy(
        name="恢复远程桌面的双通道",
        what_changes="把远程桌面传输设置改回默认（同时使用稳的和快的两条通道）。",
        post_action="",
        risk="改系统设置，需要管理员权限。可撤销。",
    ),
    "F07": FixCopy(
        name="把组网包裹大小调稳妥",
        what_changes="按常见稳妥值调整 Tailscale 网卡的最大包裹大小。",
        post_action="",
        risk="只改网卡参数，可撤销。",
    ),
    "F08": FixCopy(
        name="生成更省流量的远程桌面配置",
        what_changes="在本机生成若干 .rdp 文件：降低色深、关掉壁纸和字体平滑。不改系统设置。",
        post_action="以后请双击生成的文件来连远程桌面，不要直接打开系统自带的远程桌面。",
        risk="只新建文件，不改系统。不想用了删掉即可。",
    ),
    "F09": FixCopy(
        name="固定组网端口，方便路由器打洞",
        what_changes="把 Tailscale 的端口固定为 41641，方便路由器做端口映射。",
        post_action="若你能打开路由器管理页，把 UDP 41641 映射到这台电脑，直连会更稳。",
        risk="只改 Tailscale 端口设置，可改回自动端口。",
    ),
}


def region_zh(code: str, name: str = "") -> str:
    blob = f"{code} {name}".strip().lower()
    for key, zh in REGION_ZH.items():
        if key in blob:
            return zh
    text = (name or code or "").strip()
    if text.isdigit() or not text:
        return "较远的地方"
    return text


def _peer_display(peer: PeerState) -> str:
    return peer.hostname or peer.ip or "未命名电脑"


def is_relaying(peer: PeerState) -> bool:
    via = (peer.ping_via or "").lower()
    return bool(peer.relay) or via.startswith("derp") or "derp(" in via


def relay_peers(snapshot: Snapshot) -> list[PeerState]:
    return [p for p in snapshot.online_peers() if is_relaying(p)]


def worst_online(snapshot: Snapshot) -> Optional[PeerState]:
    ranked = [p for p in snapshot.online_peers() if p.ping_rtt_ms is not None]
    if not ranked:
        return None
    return max(ranked, key=lambda p: p.ping_rtt_ms or 0)


def reference_direct(snapshot: Snapshot) -> Optional[PeerState]:
    good = [
        p
        for p in snapshot.online_peers()
        if not is_relaying(p) and p.ping_rtt_ms is not None and p.ping_rtt_ms <= 80
    ]
    if not good:
        return None
    return min(good, key=lambda p: p.ping_rtt_ms or 9999)


def expected_gain_text(snapshot: Snapshot) -> str:
    ref = reference_direct(snapshot)
    if ref and ref.ping_rtt_ms is not None:
        return f"另一台已直连的电脑只有 {ref.ping_rtt_ms:.0f} 毫秒。修好绕路后，卡的那几台有望接近这个水平。"
    return "国内两地直连通常只要 20 到 60 毫秒。修好绕路后，远程桌面一般会从「拖果冻」变成跟手。"


def _ctx(snapshot: Snapshot, finding: Finding) -> dict[str, str]:
    derp_place = region_zh(snapshot.netcheck.preferred_derp_code, snapshot.netcheck.preferred_derp)
    derp_ms = snapshot.netcheck.preferred_derp_latency_ms
    relays = relay_peers(snapshot)
    worst = worst_online(snapshot)
    slow = []
    for peer in snapshot.online_peers():
        if peer.ping_rtt_ms is not None and peer.ping_rtt_ms > 120 and not is_relaying(peer):
            slow.append(f"{_peer_display(peer)}（{peer.ping_rtt_ms:.0f} 毫秒）")
    jitter_bits = []
    for peer in snapshot.online_peers():
        if peer.ping_jitter_ms is not None and peer.ping_jitter_ms > 30:
            jitter_bits.append(f"{_peer_display(peer)} 延迟忽高忽低")
        if peer.ping_loss_pct is not None and peer.ping_loss_pct > 1:
            jitter_bits.append(f"{_peer_display(peer)} 丢了 {peer.ping_loss_pct:.0f}% 的包")
    if not jitter_bits:
        jitter_bits.append("探测到延迟波动或丢包偏高。")
    return {
        "exit_ip": snapshot.netcheck.global_v4 or "未知",
        "derp_place": derp_place,
        "derp_ms": f"{derp_ms:.0f}" if derp_ms is not None else "很高",
        "relay_count": str(len(relays)),
        "relay_names": "、".join(_peer_display(p) for p in relays) or "部分电脑",
        "worst_ms": f"{worst.ping_rtt_ms:.0f}" if worst and worst.ping_rtt_ms is not None else "很高",
        "slow_names": "、".join(slow) or "有的电脑",
        "jitter_text": "、".join(dict.fromkeys(jitter_bits)) + "。",
        "gain": expected_gain_text(snapshot),
        "evidence": finding.evidence,
    }


def _fill(template: str, ctx: dict[str, str]) -> str:
    try:
        return template.format(**ctx)
    except KeyError:
        return template


def score_band(score: int) -> str:
    for threshold, label in BAND_LABEL:
        if score >= threshold:
            return label
    return "严重"


def health_score(snapshot: Snapshot) -> tuple[int, str]:
    score = 100
    for finding in snapshot.findings:
        score -= SEVERITY_PENALTY.get(finding.severity, 0)
    if any(
        is_relaying(p) and p.ping_rtt_ms is not None and p.ping_rtt_ms > 300
        for p in snapshot.online_peers()
    ):
        score = min(score, 40)
    score = max(0, min(100, score))
    return score, score_band(score)


def issue_cards(snapshot: Snapshot) -> list[IssueCard]:
    cards: list[IssueCard] = []
    for finding in snapshot.findings:
        copy = RULE_COPY.get(finding.id)
        if not copy:
            continue
        ctx = _ctx(snapshot, finding)
        primary = finding.fix_ids[0] if finding.fix_ids else ""
        cards.append(
            IssueCard(
                finding_id=finding.id,
                severity=finding.severity,
                severity_label=SEVERITY_LABEL.get(finding.severity, finding.severity),
                title=_fill(copy.plain_title, ctx),
                meaning=_fill(copy.meaning, ctx),
                impact=_fill(copy.impact, ctx),
                next_step=_fill(copy.next_step, ctx),
                expected_gain=_fill(copy.expected_gain, ctx),
                evidence=finding.evidence,
                fix_ids=list(finding.fix_ids),
                primary_fix=primary,
                auto_fix=bool(copy.auto_fix and primary),
            )
        )
    cards.sort(key=lambda c: (SEVERITY_ORDER.get(c.severity, 9), c.finding_id))
    return cards


def verdict(snapshot: Snapshot) -> str:
    cards = issue_cards(snapshot)
    if not cards:
        online = len(snapshot.online_peers())
        if online:
            return f"远程桌面通路看起来正常。当前有 {online} 台电脑在线，可以按平时的方式去连。"
        return "还没有发现需要处理的问题。等其他电脑上线后，再点一次「重新检测」。"

    relays = relay_peers(snapshot)
    worst = worst_online(snapshot)
    derp_place = region_zh(snapshot.netcheck.preferred_derp_code, snapshot.netcheck.preferred_derp)
    top = cards[0]
    if top.finding_id in {"R01", "R02", "R05"}:
        extra = ""
        if relays and worst and worst.ping_rtt_ms is not None:
            extra = (
                f"{len(relays)} 台电脑没能直连，正经{derp_place}绕路，"
                f"最慢 {worst.ping_rtt_ms:.0f} 毫秒 —— 这就是卡的原因。"
            )
        elif snapshot.netcheck.preferred_derp_latency_ms:
            extra = (
                f"备用中转落在{derp_place}，往返 "
                f"{snapshot.netcheck.preferred_derp_latency_ms:.0f} 毫秒。"
            )
        return "翻墙软件把远程桌面的路也带出国了。" + (extra and " " + extra)
    if top.finding_id == "R03" and worst and worst.ping_rtt_ms is not None:
        return (
            f"{len(relays)} 台电脑没能直连，正在经{derp_place}中转，"
            f"往返 {worst.ping_rtt_ms:.0f} 毫秒 —— 这就是你觉得卡的原因。"
        )
    if top.finding_id == "R04" and worst and worst.ping_rtt_ms is not None:
        return f"已经连上，但往返还有 {worst.ping_rtt_ms:.0f} 毫秒，比国内直连慢一截。"
    return top.title + "。" if not top.title.endswith("。") else top.title


def summary_line(snapshot: Snapshot) -> str:
    cards = issue_cards(snapshot)
    urgent = [c for c in cards if c.severity in {"critical", "high"}]
    if not cards:
        return "这次没有发现需要处理的问题。"
    return f"共发现 {len(cards)} 项，其中 {len(urgent)} 项需要马上处理。"


def snapshot_compare(before: Snapshot, after: Snapshot) -> list[tuple[str, str, str]]:
    def _derp(snap: Snapshot) -> str:
        place = region_zh(snap.netcheck.preferred_derp_code, snap.netcheck.preferred_derp)
        ms = snap.netcheck.preferred_derp_latency_ms
        if ms is None:
            return place
        return f"{place} · {ms:.0f} 毫秒"

    rows = [
        ("对外地址", before.netcheck.global_v4 or "未知", after.netcheck.global_v4 or "未知"),
        ("备用中转", _derp(before), _derp(after)),
    ]
    names = sorted({_peer_display(p) for p in before.online_peers() + after.online_peers()})
    after_map = {_peer_display(p): p for p in after.online_peers()}
    before_map = {_peer_display(p): p for p in before.online_peers()}
    for name in names:
        b, a = before_map.get(name), after_map.get(name)

        def _peer_line(peer: Optional[PeerState]) -> str:
            if not peer:
                return "—"
            rtt = f"{peer.ping_rtt_ms:.0f} 毫秒" if peer.ping_rtt_ms is not None else "未测到"
            path = "绕路" if is_relaying(peer) else "直连"
            return f"{path} · {rtt}"

        rows.append((name, _peer_line(b), _peer_line(a)))
    return rows


def catalog_rule_ids() -> list[str]:
    from rules.catalog import RULES

    ids: list[str] = []
    for fn in RULES:
        prefix = fn.__name__.split("_", 1)[0]
        ids.append(prefix.upper())
    return ids
