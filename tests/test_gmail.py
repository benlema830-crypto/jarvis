import base64
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import gmail
import privacy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import setup_gmail  # noqa: E402


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


MESSAGE = {"id": "18abc123def", "labelIds": ["INBOX", "UNREAD"], "internalDate": str(int(time.time() * 1000)),
           "snippet": "Can you send the drawings &amp; quote?",
           "payload": {"mimeType": "multipart/alternative",
                       "headers": [{"name": "From", "value": "Sam Lee <sam@example.com>"},
                                   {"name": "To", "value": "ben@example.com"},
                                   {"name": "Subject", "value": "Drawings"},
                                   {"name": "Date", "value": "Tue, 28 Oct 2026 09:00:00 -0500"}],
                       "parts": [{"mimeType": "text/html", "body": {"data": b64("<p>HTML <b>version</b></p>")}},
                                 {"mimeType": "text/plain", "body": {"data": b64("Hi Ben,\n\n\n\nPlain version.")}}]}}


class GmailTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for module, field, value in [(gmail, "STORE", root / "gmail.enc"), (privacy, "STORE", root / "privacy.json")]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_read_prefers_plain_text_and_marks_it_untrusted(self):
        with mock.patch.object(gmail, "api", return_value=MESSAGE) as api:
            text = gmail.read("18abc123def")
        api.assert_called_once_with("/messages/18abc123def", {"format": "full"})
        self.assertTrue(text.startswith(gmail.UNTRUSTED))
        self.assertIn("Subject: Drawings", text)
        self.assertIn("Hi Ben,\n\nPlain version.", text)
        self.assertNotIn("HTML", text)

    def test_html_only_mail_is_stripped_and_long_mail_is_cut(self):
        html_only = dict(MESSAGE, payload=dict(MESSAGE["payload"], parts=[
            {"mimeType": "text/html", "body": {"data": b64("<style>x{}</style><p>Hello &amp; welcome</p>" + "a" * 9000)}}]))
        with mock.patch.object(gmail, "api", return_value=html_only):
            text = gmail.read("18abc123def")
        self.assertIn("Hello & welcome", text)
        self.assertNotIn("x{}", text)
        self.assertIn("rest of the email cut off", text)

    def test_bad_ids_never_reach_the_api(self):
        with mock.patch.object(gmail, "api") as api:
            for bad in ("", "../profile", "abc", "18abc123def?alt=media"):
                with self.assertRaises(gmail.GmailError):
                    gmail.read(bad)
        api.assert_not_called()

    def test_search_lists_messages_with_ids(self):
        def api(path, params=None):
            if path == "/messages":
                self.assertEqual(params, {"q": "is:unread", "maxResults": 25})
                return {"messages": [{"id": "18abc123def"}]}
            return MESSAGE
        with mock.patch.object(gmail, "api", api):
            text = gmail.search("is:unread", 99)
        self.assertIn('1. UNREAD [18abc123def]', text)
        self.assertIn('from Sam Lee: "Drawings" - Can you send the drawings & quote?', text)
        with mock.patch.object(gmail, "api", return_value={}):
            self.assertIn("No emails match \"in:inbox newer_than:2d\"", gmail.search())

    def test_tokens_are_encrypted_and_refreshed_with_the_client_secret(self):
        gmail.save_credentials({"client_id": "id.apps.googleusercontent.com", "client_secret": "s3cret",
                                "access_token": "old", "refresh_token": "refresh", "expires_at": time.time() - 1})
        self.assertNotIn("refresh", gmail.STORE.read_text(encoding="utf-8"))
        reply = {"access_token": "new", "token_type": "Bearer", "expires_in": 3600}
        with mock.patch("mcp_oauth.request", return_value=reply) as request:
            self.assertEqual(gmail.access_token(), "new")
            self.assertEqual(gmail.access_token(), "new")  # cached until it expires
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["data"]["client_secret"], "s3cret")
        self.assertEqual(gmail.load_credentials()["refresh_token"], "refresh")

    def test_not_connected(self):
        self.assertFalse(gmail.connected())
        self.assertEqual(gmail.digest(), "")
        with self.assertRaises(gmail.GmailError):
            gmail.access_token()

    def test_setup_reads_only_desktop_client_files(self):
        path = Path(self.temp.name) / "client.json"
        path.write_text(json.dumps({"installed": {"client_id": "123.apps.googleusercontent.com",
                                                  "client_secret": "abc"}}), encoding="utf-8")
        self.assertEqual(setup_gmail.client(path), ("123.apps.googleusercontent.com", "abc"))
        path.write_text(json.dumps({"web": {"client_id": "123.apps.googleusercontent.com"}}), encoding="utf-8")
        with self.assertRaises(gmail.GmailError):
            setup_gmail.client(path)


if __name__ == "__main__":
    unittest.main()
