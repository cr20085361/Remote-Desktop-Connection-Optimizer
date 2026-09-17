from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.prompt import CHAT_PROMPT
from core.settings import DEFAULTS, save_settings
from rules.plain import IssueCard


class ChatPromptTest(unittest.TestCase):
    def test_identity_is_deepseek_not_other_models(self) -> None:
        self.assertIn("DeepSeek", CHAT_PROMPT)
        self.assertIn("禁止声称自己是 Claude", CHAT_PROMPT)
        self.assertIn("禁止复述", CHAT_PROMPT)
        self.assertIn("系统提示", CHAT_PROMPT)


class SettingsMergeTest(unittest.TestCase):
    def test_partial_save_keeps_assistant_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            with (
                patch("core.settings.SETTINGS_PATH", path),
                patch("core.settings.ensure_app_dirs"),
            ):
                save_settings({"assistant_open": False, "interval_sec": 60})
                save_settings({"interval_sec": 90})
                data = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(data["assistant_open"])
            self.assertEqual(data["interval_sec"], 90)
            self.assertIn("ai_model", data)
            self.assertEqual(data["ai_model"], DEFAULTS["ai_model"])


class DrawerUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_tech_page_has_four_tabs_and_no_chat(self) -> None:
        from ui.chat_panel import ChatPanel
        from ui.tech_page import TechPage

        page = TechPage()
        self.assertEqual(page.tabs.count(), 4)
        names = [page.tabs.tabText(i) for i in range(page.tabs.count())]
        self.assertEqual(names, ["关系图", "延迟曲线", "问题记录", "撤销"])
        self.assertEqual(page.findChildren(ChatPanel), [])

    def test_drawer_open_and_strip_widths(self) -> None:
        from ui.assistant_drawer import OPEN_WIDTH, STRIP_WIDTH, AssistantDrawer

        drawer = AssistantDrawer()
        drawer.set_open(True, persist=False)
        self.assertFalse(drawer.chat.isHidden())
        self.assertTrue(drawer.strip.isHidden())
        self.assertEqual(drawer.width(), OPEN_WIDTH)
        drawer.set_open(False, persist=False)
        self.assertTrue(drawer.chat.isHidden())
        self.assertFalse(drawer.strip.isHidden())
        self.assertEqual(drawer.width(), STRIP_WIDTH)

    def test_issue_card_ask_ai_emits_title(self) -> None:
        from ui.cards import IssueCardWidget

        card = IssueCard(
            finding_id="R01",
            severity="high",
            severity_label="优先",
            title="翻墙软件把远程桌面的路也带出国了",
            meaning="说明",
            impact="卡顿",
            next_step="处理",
            expected_gain="好转",
            evidence="出口 198.18.0.1",
        )
        widget = IssueCardWidget(card)
        received: list[str] = []
        widget.ask_ai.connect(received.append)
        widget._ask_ai()
        self.assertEqual(len(received), 1)
        self.assertIn(card.title, received[0])
        self.assertIn(card.evidence, received[0])

    def test_assistant_markdown_grows_and_hides_markers(self) -> None:
        from ui.chat_panel import AssistantMessage

        msg = AssistantMessage()
        msg.append_content("# 标题\n\n**加粗结论**\n\n- 第一项\n- 第二项\n\n")
        msg.append_content("尾段说明。\n\n" * 20)
        self.app.processEvents()
        plain = msg.view.toPlainText()
        self.assertIn("加粗结论", plain)
        self.assertNotIn("**加粗结论**", plain)
        self.assertGreater(msg.view.height(), 80)

    def test_verdict_page_has_ask_ai_button(self) -> None:
        from ui.verdict_page import VerdictPage

        page = VerdictPage()
        self.assertEqual(page.btn_ask_verdict.text(), "问 AI")
        self.assertTrue(page.btn_ask_verdict.isHidden())

    def test_thinking_stays_folded(self) -> None:
        from ui.chat_panel import AssistantMessage

        msg = AssistantMessage()
        msg.append_reason("先看延迟再下结论")
        self.app.processEvents()
        self.assertFalse(msg.think_btn.isHidden())
        self.assertTrue(msg.think_body.isHidden())
        self.assertFalse(msg.think_btn.isChecked())

    def test_long_reply_can_scroll(self) -> None:
        from ui.chat_panel import AssistantMessage, ChatPanel

        panel = ChatPanel()
        panel.setFixedSize(400, 360)
        panel.show()
        self.app.processEvents()
        msg = AssistantMessage()
        msg.append_content("段落说明，用来确认长回复可以完整滚完。\n\n" * 30)
        panel._insert(msg, align_right=False)
        self.app.processEvents()
        self.assertGreater(panel.scroll.verticalScrollBar().maximum(), 0)
        self.assertGreater(msg.view.height(), panel.scroll.viewport().height())


if __name__ == "__main__":
    unittest.main()
