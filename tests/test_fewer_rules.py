"""The owner's decisions of 2026-11-11 ("there should be little to no rules"): what Jarvis is told, answering a
question from the phone, and sending email."""
import base64
import email
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import approvals
import gmail
import jarvis
import tools


class InstructionsTest(unittest.TestCase):
    def prompt(self, **env):
        with mock.patch.dict(jarvis.os.environ, {"JARVIS_BLOCK_WORK_APPS": "", **env}):
            return jarvis.SYSTEM_PROMPT.format(memory="", off_limits=jarvis.worksafe.rule(
                "- {apps} may hold the user's work data and are off-limits: never open, read, or operate them.\n"))

    def test_he_is_told_that_almost_nothing_needs_permission(self):
        prompt = self.prompt()
        for told in ("Almost nothing needs permission", "spending their money, and sending a message to other people",
                     "Don't lecture and don't cite rules", "never ask them to confirm it", "Keep doubt short",
                     "a yes sent from their phone or Telegram", "send_email sends a message or a reply"):
            self.assertIn(told, prompt)

    def test_the_old_holding_back_is_gone(self):
        prompt = self.prompt()
        for gone in ("Opening a session alone does not authorize implementation", "start the work only when the user says go",
                     "Neither goes around the approvals", "can't approve it", "Gmail is read-only",
                     "other ideas stay proposals", "off-limits"):
            self.assertNotIn(gone, prompt)

    def test_an_app_the_owner_blocks_is_named_again(self):
        self.assertIn("- Teams may hold the user's work data and are off-limits", self.prompt(JARVIS_BLOCK_WORK_APPS="teams"))

    def test_the_codex_brain_is_told_its_tools_are_not_read_only(self):
        # Codex tells the model its sandbox is read-only. Asked to make and delete a file, Jarvis answered "this
        # session has read-only file access" instead of using write_file (live, 2026-11-11).
        source = (Path(jarvis.__file__).parent / "codex_brain.py").read_text(encoding="utf-8")
        self.assertIn("Your JARVIS tools are not sandboxed", source)
        self.assertIn("Never say this session is ", source)

    def test_agents_are_told_the_same(self):
        import agent
        import agent_sessions
        import terminal
        for text in (terminal.RULES, agent_sessions.INSTRUCTIONS):
            self.assertIn("Everything the task needs is authorized", text)
            self.assertIn("sending a message to other people", text)
            self.assertNotIn("machine-wide installation", text)
        self.assertIn("before only two things", agent.SYSTEM)
        self.assertNotIn("installing or uninstalling software", agent.SYSTEM)


class AnswerFromPhoneTest(unittest.TestCase):
    def open_question(self, **kwargs):
        result = {}
        with mock.patch.object(approvals, "on_question", lambda speech: None), mock.patch.object(approvals, "on_text", None), \
                mock.patch.object(approvals.preferences, "read", return_value={}):
            asker = threading.Thread(target=lambda: result.update(answer=approvals.ask("May I email Sam?", **kwargs)), daemon=True)
            asker.start()
            while not approvals.waiting():
                time.sleep(0.01)
        self.addCleanup(lambda: approvals.answer("no") if approvals.waiting() else None)
        return asker, result

    def test_with_no_question_open_a_message_is_just_a_message(self):
        self.assertIsNone(jarvis.answer_from_phone("yes"))

    def test_a_yes_or_no_from_the_phone_answers_it(self):
        for said, reply, approved in (("Yes, go ahead", "Approved.", True), ("no don't", "Understood, I won't.", False)):
            asker, result = self.open_question()
            self.assertEqual(jarvis.answer_from_phone(said), reply)
            asker.join(5)
            self.assertEqual(result["answer"], (approved, said))

    def test_anything_else_stays_an_ordinary_message_and_the_question_stays_open(self):
        asker, result = self.open_question()
        self.assertIsNone(jarvis.answer_from_phone("what's the weather tomorrow?"))
        self.assertTrue(approvals.waiting())
        approvals.answer("no")
        asker.join(5)

    def test_an_agents_own_question_takes_whatever_they_write(self):
        asker, result = self.open_question(free_text=True)
        self.assertEqual(jarvis.answer_from_phone("make it blue"), "Passed on.")
        asker.join(5)
        self.assertEqual(result["answer"], (True, "make it blue"))

    def test_the_question_is_texted_with_its_details(self):
        sent = []
        with mock.patch("telegram_bridge.send_to_owner", sent.append), mock.patch("privacy.redact", lambda text: text):
            jarvis.text_question("May I send this email to sam@example.com?", "Send this email?\nTo: sam@example.com\n\nHi Sam")
            jarvis.text_question("Which colour?", "Builder: Which colour?", True)
            for _ in range(200):
                if len(sent) == 2:
                    break
                time.sleep(0.01)
        self.assertEqual(len(sent), 2)
        email_text = next(text for text in sent if "Hi Sam" in text)
        self.assertIn("Jarvis needs your OK.", email_text)
        self.assertTrue(email_text.endswith("Reply yes or no."))
        self.assertTrue(next(text for text in sent if "colour" in text).endswith("Reply with your answer."))


class SendEmailTest(unittest.TestCase):
    def test_a_message_is_checked_before_anyone_is_asked(self):
        ok = gmail.draft("Sam <sam@example.com>, pat@example.org", "Friday", "Hi Sam,\n\nSee you Friday.\n\nBen")
        self.assertEqual((ok["to"], ok["subject"], ok["thread"]), ("sam@example.com, pat@example.org", "Friday", ""))
        for to, subject, body in (("", "x", "y"), ("sam", "x", "y"), ("sam@example.com", "", "y"), ("sam@example.com", "x", " "),
                                  ("sam@example.com", "x", "y" * (gmail.MAX_SEND + 1))):
            with self.assertRaises(gmail.GmailError):
                gmail.draft(to, subject, body)

    def test_a_reply_goes_to_the_sender_in_the_same_thread(self):
        original = {"threadId": "thread9", "payload": {"headers": [
            {"name": "From", "value": "Sam Lee <sam@example.com>"}, {"name": "Subject", "value": "Quote for the deck"},
            {"name": "Message-ID", "value": "<abc@mail.example.com>"}, {"name": "References", "value": "<first@mail.example.com>"}]}}
        with mock.patch.object(gmail, "api", return_value=original) as api:
            reply = gmail.draft(body="Thanks, go ahead.", reply_to="18c2f0aa11bb22cc")
        self.assertIn("/messages/18c2f0aa11bb22cc", api.call_args.args[0])
        self.assertEqual((reply["to"], reply["subject"], reply["thread"]), ("sam@example.com", "Re: Quote for the deck", "thread9"))
        self.assertEqual(reply["headers"], {"In-Reply-To": "<abc@mail.example.com>",
                                            "References": "<first@mail.example.com> <abc@mail.example.com>"})
        with self.assertRaises(gmail.GmailError):
            gmail.draft(body="x", reply_to="../../drafts")           # only an id from check_email

    def test_send_posts_exactly_the_approved_message(self):
        message = {"to": "sam@example.com", "subject": "Re: Quote", "body": "Thanks, go ahead.\n\nBen", "thread": "thread9",
                   "headers": {"In-Reply-To": "<abc@mail.example.com>"}}
        with mock.patch.object(gmail, "_post", return_value={"id": "m1"}) as post:
            self.assertIn("accepted the email to sam@example.com", gmail.send(message))
        path, payload = post.call_args.args
        self.assertEqual((path, payload["threadId"]), ("/messages/send", "thread9"))
        sent = email.message_from_bytes(base64.urlsafe_b64decode(payload["raw"]))
        self.assertEqual((sent["To"], sent["Subject"], sent["In-Reply-To"]), ("sam@example.com", "Re: Quote", "<abc@mail.example.com>"))
        self.assertIn("Thanks, go ahead.", sent.get_payload())
        with mock.patch.object(gmail, "_post", return_value={}), self.assertRaises(gmail.GmailError):
            gmail.send(message)                                       # no id back: never "sent"

    def test_a_sign_in_that_can_only_read_says_how_to_fix_it(self):
        response = mock.Mock(status_code=403, ok=False)
        session = mock.MagicMock()
        session.__enter__.return_value.post.return_value = response
        with mock.patch.object(gmail, "access_token", return_value="t"), mock.patch.object(gmail.requests, "Session", return_value=session):
            with self.assertRaises(gmail.GmailError) as refused:
                gmail._post("/messages/send", {"raw": "x"})
        self.assertIn("setup_gmail.py --renew", str(refused.exception))
        setup = (Path(gmail.__file__).parent / "scripts" / "setup_gmail.py").read_text(encoding="utf-8")
        self.assertIn("gmail.SEND_SCOPE", setup)

    def test_the_tool_sends_only_after_the_owners_yes_to_the_exact_text(self):
        call = SimpleNamespace(name="send_email", id="t", input={"to": "sam@example.com", "subject": "Friday",
                                                                 "body": "Hi Sam,\n\nSee you Friday.\n\nBen"})
        with mock.patch.object(tools, "_after_approval", return_value="asked") as ask, mock.patch.object(gmail, "send") as send:
            self.assertEqual(tools.run_tool(call)["content"], "asked")
            send.assert_not_called()                                  # nothing goes until they answer
            question, apply = ask.call_args.args[:2]
            self.assertEqual(ask.call_args.kwargs["kind"], approvals.MESSAGE)
            for shown in ("To: sam@example.com", "Subject: Friday", "See you Friday."):
                self.assertIn(shown, question)
            send.return_value = "Gmail accepted the email to sam@example.com (id m1)."
            self.assertIn("Gmail accepted the email", apply()["prompt"])
            self.assertEqual(send.call_args.args[0]["body"], "Hi Sam,\n\nSee you Friday.\n\nBen")
        self.assertFalse(approvals.auto_approved(question, approvals.MESSAGE))
        bad = SimpleNamespace(name="send_email", id="t", input={"to": "sam", "subject": "x", "body": "y"})
        with mock.patch.object(tools, "_after_approval") as ask:
            self.assertTrue(tools.run_tool(bad).get("is_error"))
        ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
