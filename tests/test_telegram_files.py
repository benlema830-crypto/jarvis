"""Files over Telegram. Nothing here reaches Telegram: the Bot API call is replaced."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import telegram_bridge
import tools


class TelegramFilesTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.calls = []

        def call(token, method, timeout=30, files=None, **params):
            self.calls.append((method, {k: v[0] for k, v in (files or {}).items()}, params))
            if method in self.refuse:
                raise RuntimeError("PHOTO_INVALID_DIMENSIONS")
            return {}

        self.refuse = set()
        token = self.root / "token"
        token.write_text("x")
        for target, name, value in [(telegram_bridge, "call", call), (telegram_bridge, "chat_id", lambda: 42),
                                    (telegram_bridge, "STORE", token), (telegram_bridge, "load_token", lambda: "t:1")]:
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def file(self, name, size=100):
        path = self.root / name
        path.write_bytes(b"x" * size)
        return path

    def test_a_picture_goes_as_a_photo_with_its_caption(self):
        result = telegram_bridge.send_file_to_owner(self.file("render.png"), "The villa, sir.")
        self.assertEqual(self.calls, [("sendPhoto", {"photo": "render.png"}, {"chat_id": "42", "caption": "The villa, sir."})])
        self.assertIn("render.png", result)
        self.assertIn("photo", result)

    def test_other_files_and_refused_photos_go_as_documents(self):
        telegram_bridge.send_file_to_owner(self.file("report.pdf"))
        self.assertEqual(self.calls[-1], ("sendDocument", {"document": "report.pdf"}, {"chat_id": "42"}))
        self.refuse.add("sendPhoto")
        result = telegram_bridge.send_file_to_owner(self.file("tall.jpg"))
        self.assertEqual([c[0] for c in self.calls[-2:]], ["sendPhoto", "sendDocument"])
        self.assertIn("document", result)

    def test_too_large_or_empty_is_refused_before_anything_is_sent(self):
        with mock.patch.object(telegram_bridge, "MAX_FILE", 50):
            with self.assertRaises(ValueError):
                telegram_bridge.send_file_to_owner(self.file("big.zip", 51))
        with self.assertRaises(ValueError):
            telegram_bridge.send_file_to_owner(self.file("empty.txt", 0))
        self.assertEqual(self.calls, [])

    def test_tool_sends_a_file_only_if_it_exists_and_is_not_a_credential(self):
        send = tools.TOOLS_BY_NAME["send_telegram"]
        path = self.file("notes.txt")
        self.assertIn("notes.txt", send.call({"text": "Your notes.", "file": str(path)}))
        with self.assertRaises(ValueError):
            send.call({"file": str(self.root / "missing.txt")})
        secret = self.file(".env")
        with self.assertRaises(ValueError):
            send.call({"file": str(secret)})
        with self.assertRaises(ValueError):
            send.call({})
        self.assertEqual(len(self.calls), 1)

    def test_a_plain_message_still_works(self):
        with mock.patch.object(telegram_bridge.BRIDGE, "send") as sent:
            self.assertEqual(tools.TOOLS_BY_NAME["send_telegram"].call({"text": "Hello"}), "Sent to your Telegram.")
        sent.assert_called_once_with(42, "Hello")


if __name__ == "__main__":
    unittest.main()
