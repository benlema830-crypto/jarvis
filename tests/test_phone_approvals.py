"""Approving from the phone: only the owner's own tap, with the same key as everything else."""
import http.client
import json
import threading
import time
import unittest
from unittest import mock

import approvals
import phone_bridge


class PhoneApprovalTest(unittest.TestCase):
    def setUp(self):
        self.bridge = phone_bridge.Bridge()
        self.bridge.token = "secret-token"
        self.server = phone_bridge.ThreadingHTTPServer(("127.0.0.1", 0), phone_bridge.make_handler(self.bridge))
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.settings = {"auto_approve": "none"}
        for patch in (mock.patch.object(phone_bridge, "owner_login", return_value=""),
                      mock.patch.object(phone_bridge.preferences, "read", lambda: dict(self.settings)),
                      mock.patch.object(approvals.preferences, "read", lambda: dict(self.settings)),
                      mock.patch.object(approvals.hud, "emit"), mock.patch.object(approvals, "on_question", None)):
            patch.start()
            self.addCleanup(patch.stop)

    def call(self, method, path, body=None, token="secret-token"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Authorization": f"Bearer {token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, json.dumps(body) if body is not None else None, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def open_question(self, question="Delete the old build folder?", **options):
        box = []
        thread = threading.Thread(target=lambda: box.append(approvals.ask(question, always=True, **options)), daemon=True)
        thread.start()
        for _ in range(100):
            if approvals.waiting():
                break
            time.sleep(0.01)
        return thread, box

    def test_question_shows_and_yes_approves(self):
        self.assertEqual(self.call("GET", "/pending"), (200, {"question": ""}))
        thread, box = self.open_question()
        self.assertEqual(self.call("GET", "/pending"), (200, {"question": "Delete the old build folder?"}))
        self.assertEqual(self.call("POST", "/answer", {"approve": True}), (200, {"ok": True, "reply": "Approved."}))
        thread.join(3)
        self.assertEqual(box, [(True, "yes")])
        self.assertEqual(self.call("GET", "/pending")[1], {"question": ""})

    def test_no_declines(self):
        thread, box = self.open_question()
        status, body = self.call("POST", "/answer", {"approve": False})
        thread.join(3)
        self.assertEqual((status, body["ok"]), (200, True))
        self.assertEqual(box, [(False, "no")])

    def test_wrong_key_can_neither_see_nor_answer(self):
        thread, box = self.open_question()
        self.assertEqual(self.call("GET", "/pending", token="nope")[0], 401)
        self.assertEqual(self.call("POST", "/answer", {"approve": True}, token="nope")[0], 401)
        self.assertTrue(approvals.waiting())
        approvals.answer("no")
        thread.join(3)
        self.assertEqual(box, [(False, "no")])

    def test_nothing_waiting_and_bad_answers(self):
        self.assertEqual(self.call("POST", "/answer", {"approve": True})[0], 409)
        thread, box = self.open_question()
        for bad in ({"approve": "yes"}, {"approve": 1}, {}):
            self.assertEqual(self.call("POST", "/answer", bad)[0], 409, bad)
        self.assertTrue(approvals.waiting())  # still open: only a real true or false decides
        approvals.answer("no")
        thread.join(3)

    def test_a_chat_message_from_the_phone_never_approves(self):
        said = []
        self.bridge.on_message = lambda text, reply, voice: (said.append(text), reply("Noted."))
        thread, box = self.open_question()
        self.call("POST", "/ask", {"text": "yes"})
        self.assertEqual(said, ["yes"])
        self.assertTrue(approvals.waiting())
        approvals.answer("no")
        thread.join(3)

    def test_questions_needing_words_stay_at_the_pc(self):
        thread, box = self.open_question("Which folder should I use?", free_text=True)
        self.assertEqual(self.call("GET", "/pending")[1], {"question": ""})
        self.assertEqual(self.call("POST", "/answer", {"approve": True})[0], 409)
        approvals.answer("the second one")
        thread.join(3)
        self.assertEqual(box, [(True, "the second one")])

    def test_the_owner_can_turn_phone_approvals_off(self):
        self.settings["phone_approvals"] = False
        thread, box = self.open_question()
        self.assertEqual(self.call("GET", "/pending")[1], {"question": ""})
        status, body = self.call("POST", "/answer", {"approve": True})
        self.assertEqual((status, body["ok"]), (409, False))
        self.assertTrue(approvals.waiting())
        approvals.answer("no")
        thread.join(3)


if __name__ == "__main__":
    unittest.main()
