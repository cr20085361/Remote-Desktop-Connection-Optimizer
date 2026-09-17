from __future__ import annotations

import unittest

from ai.catalog import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODELS,
    chat_completions_url,
    default_model,
    migrate_ai_settings,
    model_uses_thinking,
)


class AiCatalogTest(unittest.TestCase):
    def test_official_models_are_listed(self) -> None:
        ids = {item["id"] for item in DEEPSEEK_MODELS}
        self.assertIn("deepseek-flash", ids)
        self.assertIn("deepseek-v4-pro", ids)
        self.assertEqual(default_model("deepseek"), "deepseek-flash")

    def test_chat_url_matches_docs(self) -> None:
        self.assertEqual(
            chat_completions_url(DEEPSEEK_BASE_URL),
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(
            chat_completions_url("https://api.deepseek.com/v1"),
            "https://api.deepseek.com/v1/chat/completions",
        )

    def test_legacy_chat_migrates_to_flash(self) -> None:
        data = migrate_ai_settings(
            {
                "ai_base_url": "https://api.deepseek.com/v1",
                "ai_model": "deepseek-chat",
            }
        )
        self.assertEqual(data["ai_base_url"], DEEPSEEK_BASE_URL)
        self.assertEqual(data["ai_model"], "deepseek-flash")
        self.assertEqual(data["ai_provider"], "deepseek")
        self.assertTrue(model_uses_thinking("deepseek-flash"))


if __name__ == "__main__":
    unittest.main()
