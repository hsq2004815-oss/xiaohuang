from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from xiaohuang.text_chat_web_service import TextChatWebApi
from xiaohuang.text_interaction_models import TextInteractionResult


class TextChatWebApiTests(unittest.TestCase):
    def test_send_message_returns_ok_with_data(self):
        fake = TextInteractionResult(
            ok=True,
            session_id="default",
            user_text="介绍一下你自己",
            reply_text="我是小黄",
            reply_source="llm",
        )
        with patch("xiaohuang.text_chat_web_service.run_text_interaction_turn", return_value=fake) as mock_run:
            api = TextChatWebApi()
            resp = api.send_message({"text": "介绍一下你自己"})
        self.assertTrue(resp["ok"])
        self.assertIn("data", resp)
        self.assertEqual(resp["data"]["reply_text"], "我是小黄")
        self.assertEqual(mock_run.call_args.kwargs["session_id"], "default")

    def test_send_message_exception_returns_sanitized_error(self):
        with patch("xiaohuang.text_chat_web_service.run_text_interaction_turn", side_effect=RuntimeError("boom")):
            api = TextChatWebApi()
            resp = api.send_message({"text": "hi"})
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["code"], "send_message_error")
        self.assertNotIn("boom", resp["error"])

    def test_clear_session_returns_ok(self):
        api = TextChatWebApi()
        api._sessions.clear = Mock()
        resp = api.clear_session({"session_id": "abc"})
        self.assertTrue(resp["ok"])
        api._sessions.clear.assert_called_once_with("abc")


if __name__ == "__main__":
    unittest.main()
