"""术语白话解释，给控件加悬停提示。"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ui.theme import MUTED

TERMS: dict[str, str] = {
    "中转": "直连失败时，组网会找一台公共服务器帮忙传画面。这台服务器如果在很远的地方，远程桌面就会卡。",
    "中转站": "直连失败时，组网会找一台公共服务器帮忙传画面。这台服务器如果在很远的地方，远程桌面就会卡。",
    "Tun": "翻墙软件的「全局接管」开关。打开后，电脑几乎所有上网都会先送到代理，远程组网也容易被带走。",
    "Tun 模式": "翻墙软件的「全局接管」开关。打开后，电脑几乎所有上网都会先送到代理，远程组网也容易被带走。",
    "直连": "两台电脑直接对话，不经过国外服务器。国内两地通常只要几十毫秒。",
    "延迟": "画面从一台电脑到另一台再回来的时间，单位毫秒。越小越跟手。超过 120 毫秒，拖窗口会有「拖果冻」的感觉。",
    "抖动": "延迟忽高忽低。远程桌面最怕这个，表现为画面一顿一顿。",
    "丢包": "有的画面数据包在路上丢了，需要重传。表现为卡一下或花一下。",
    "MTU": "一次能发出去的数据包最大尺寸。两边谈不拢时，包会被拆散甚至丢失。",
    "CGNAT": "运营商或组网用的特殊内网地址（100.x）。远程组网的电脑彼此用这类地址通话。",
    "系统代理": "Windows 给浏览器准备的翻墙入口。远程桌面和组网通常不应该走它。",
    "远程组网": "这里指 Tailscale：让家里和办公室的电脑像在同一个局域网里。",
}


def explain(term: str) -> str:
    return TERMS.get(term, "")


def attach(widget: QWidget, term: str) -> None:
    tip = explain(term)
    if not tip:
        return
    widget.setToolTip(tip)
    widget.setStyleSheet(widget.styleSheet() + f" text-decoration: underline; text-decoration-style: dotted; color: {MUTED};")
