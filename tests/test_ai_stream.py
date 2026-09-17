from __future__ import annotations

import unittest

from ai.advisor import parse_sse_line


class SseParseTest(unittest.TestCase):
    def test_content_delta(self) -> None:
        line = 'data: {"choices":[{"delta":{"content":"已接通"}}]}'
        self.assertEqual(parse_sse_line(line), ("content", "已接通"))

    def test_reasoning_delta(self) -> None:
        line = 'data: {"choices":[{"delta":{"reasoning_content":"先看延迟"}}]}'
        self.assertEqual(parse_sse_line(line), ("reasoning", "先看延迟"))

    def test_done_and_junk(self) -> None:
        self.assertEqual(parse_sse_line("data: [DONE]"), ("done", ""))
        self.assertIsNone(parse_sse_line(""))
        self.assertIsNone(parse_sse_line("event: ping"))
        self.assertEqual(
            parse_sse_line('data: {"error":{"message":"bad key"}}'),
            ("error", "bad key"),
        )


if __name__ == "__main__":
    unittest.main()
