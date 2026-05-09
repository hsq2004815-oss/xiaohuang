from __future__ import annotations

import unittest

from xiaohuang.text_interaction_session_service import TextInteractionSessionStore


class TextInteractionSessionStoreTests(unittest.TestCase):
    def test_get_or_create_reuses_same_session(self):
        store = TextInteractionSessionStore()
        s1 = store.get_or_create("default")
        s2 = store.get_or_create("default")
        self.assertIs(s1, s2)

    def test_clear_session_clears_memory(self):
        store = TextInteractionSessionStore()
        session = store.get_or_create("default")
        session.memory.add_user("测试")
        store.clear("default")
        self.assertEqual(len(session.memory), 0)

    def test_build_context_uses_existing_memory(self):
        store = TextInteractionSessionStore()
        session = store.get_or_create("default")
        session.memory.add_user("我现在正在测试小黄项目")
        ctx = store.build_context_text("default")
        self.assertIn("小黄项目", ctx)


if __name__ == "__main__":
    unittest.main()
