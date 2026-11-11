"""Three decisions of the owner's from 2026-11-11: texts only when they are out of their room, updates with no
daily limit but cut to what matters, and the OpenAI key as a fallback when the ChatGPT plan is at its limit."""
import datetime
import io
import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import codex_brain
import direct_tools
import jarvis
import model_provider
import openai_api
import presence_greeting
import response_routing
import whereabouts
from tests.test_away_jobs import Base as AwayBase

NOW = datetime.datetime(2026, 11, 11, 15, 0).timestamp()   # mid-afternoon: not quiet hours


def house(phone="home", sensor="on", sensor_minutes=0):
    """A fake Home Assistant: where the phone is, and what the bedroom sensor says and for how long."""
    changed = datetime.datetime.fromtimestamp(NOW - sensor_minutes * 60, datetime.timezone.utc).isoformat()
    states = {presence_greeting.PERSON: {"state": phone, "last_changed": changed},
              presence_greeting.SENSOR: {"state": sensor, "last_changed": changed}}
    return mock.patch.object(whereabouts, "_read", lambda entity: states.get(entity))


class WhereaboutsTest(unittest.TestCase):
    def out(self, idle, **kwargs):
        with house(**kwargs):
            return whereabouts.out_of_room(idle_seconds=idle, now=NOW)

    def test_in_the_room_means_no_text(self):
        self.assertFalse(self.out(idle=5000, sensor="on"))                          # the sensor sees them
        self.assertFalse(self.out(idle=60, sensor="off", sensor_minutes=90))        # at the desk, the sensor's blind spot
        self.assertFalse(self.out(idle=5000, sensor="off", sensor_minutes=10))      # stepped out a few minutes ago

    def test_gone_for_half_an_hour_means_text(self):
        self.assertTrue(self.out(idle=2400, sensor="off", sensor_minutes=31))
        self.assertFalse(self.out(idle=2400, sensor="off", sensor_minutes=29))

    def test_a_phone_away_from_home_means_text_even_if_the_pc_is_in_use(self):
        self.assertTrue(self.out(idle=5, phone="not_home", sensor="on"))            # remote desktop from somewhere else
        self.assertTrue(self.out(idle=5, phone="Work", sensor="off", sensor_minutes=1))

    def test_when_the_house_cant_say_the_pc_decides(self):
        with mock.patch.object(whereabouts, "_read", lambda entity: None):
            self.assertFalse(whereabouts.out_of_room(idle_seconds=600, now=NOW))
            self.assertTrue(whereabouts.out_of_room(idle_seconds=3600, now=NOW))
        self.assertTrue(self.out(idle=3600, sensor="unavailable"))

    def test_someone_in_the_room_can_hear_but_never_at_night(self):
        with house(sensor="on"):
            self.assertTrue(whereabouts.can_hear(NOW))
            night = datetime.datetime(2026, 11, 11, 2, 0).timestamp()
            self.assertFalse(whereabouts.can_hear(night))                             # the sensor may see them asleep
        with house(sensor="off", sensor_minutes=2):
            self.assertFalse(whereabouts.can_hear(NOW))
        with house(phone="not_home", sensor="on"):
            self.assertFalse(whereabouts.can_hear(NOW))

    def test_a_test_run_never_asks_the_real_house(self):
        self.assertIsNone(whereabouts._read(presence_greeting.SENSOR))


class TextRuleTest(unittest.TestCase):
    def texted(self, out_of_room, from_telegram=False):
        sent = []
        with mock.patch("telegram_bridge.send_to_owner", sent.append), mock.patch("privacy.redact", lambda text: text), \
                mock.patch.object(whereabouts, "out_of_room", return_value=out_of_room):
            if from_telegram:
                with response_routing.telegram_turn(101):
                    jarvis.text_question("May I email Sam?", "Send this email?")
            else:
                jarvis.text_question("May I email Sam?", "Send this email?")
            time.sleep(0.1)
        return sent

    def test_a_question_is_texted_only_when_they_are_out_of_the_room(self):
        self.assertEqual(self.texted(out_of_room=False), [])
        self.assertEqual(len(self.texted(out_of_room=True)), 1)

    def test_a_question_from_a_job_they_texted_isnt_sent_twice(self):
        # It already goes to their chat with the rest of that conversation (response_routing.CommandQueue).
        self.assertEqual(self.texted(out_of_room=True, from_telegram=True), [])


class AwayTextTest(AwayBase):
    def test_in_the_room_an_away_job_sends_no_texts_and_says_so_truthfully(self):
        self.out_of_room = False
        job = self.add_build()
        self.agent_finishes(job, files={"widget.py": "x = 1\n", "tests/test_widget.py": "import unittest\n"})
        self.assertEqual(job["status"], "done")
        self.assertEqual(self.texts, [])
        self.idle = 5
        self.queue.tick()
        self.assertIn("make the widget finished", self.said[0]["say"])
        self.assertIn("Ask me for the details", self.said[0]["say"])             # not "I've texted you"
        self.assertNotIn("texted", self.said[0]["say"])

    def test_out_of_the_room_they_are_texted_and_told_so(self):
        job = self.add_build()
        self.agent_finishes(job, files={"widget.py": "x = 1\n", "tests/test_widget.py": "import unittest\n"})
        self.assertTrue(any("Started" in text for text in self.texts))
        self.assertTrue(job["texted"])
        self.idle = 5
        self.queue.tick()
        self.assertIn("I've texted you the details", self.said[0]["say"])

    def test_a_job_they_queued_by_text_is_answered_by_text_wherever_they_are(self):
        self.out_of_room = False
        with response_routing.telegram_turn(101):
            job = self.queue.add("make the widget", "build", project=str(self.repo))
        self.assertTrue(job["by_text"])
        self.queue.tick()
        self.assertTrue(any("Started" in text for text in self.texts))

    def test_if_where_they_are_cant_be_told_the_text_still_goes(self):
        self.queue.may_text = mock.Mock(side_effect=OSError("Home Assistant is down"))
        self.add_build()
        self.assertTrue(self.texts)


class BriefUpdateTest(unittest.TestCase):
    LONG = "I rebuilt the hat shop. " * 30

    def setUp(self):
        self.brain, self.voice = mock.Mock(), mock.Mock()
        patcher = mock.patch.object(jarvis.hud, "emit")
        self.emit = patcher.start()
        self.addCleanup(patcher.stop)

    def brief(self, item, says=None):
        self.brain.ask.side_effect = (lambda prompt, speak: speak(says)) if says else None
        return jarvis.brief_update(self.brain, self.voice, item)

    def test_a_long_report_becomes_what_he_makes_of_it(self):
        item = {"label": "Giant Builder finished", "say": self.LONG, "report": True, "note": "[TASK FINISHED] hat shop"}
        self.assertEqual(self.brief(item, "The hat shop is rebuilt and its tests pass."), "The hat shop is rebuilt and its tests pass.")
        prompt = self.brain.ask.call_args.args[0]
        for part in ("Giant Builder finished", "[TASK FINISHED] hat shop", self.LONG.strip(), "one or two sentences", "(quiet)"):
            self.assertIn(part, prompt)

    def test_what_the_owner_doesnt_need_is_not_said(self):
        self.assertIsNone(self.brief({"label": "Heartbeat", "say": self.LONG, "update": True}, "(quiet)"))
        self.assertIn("Not said", self.emit.call_args.kwargs["text"])

    def test_short_ones_and_his_own_words_go_as_they_are(self):
        self.assertEqual(self.brief({"label": "x", "say": "Roblox opened.", "report": True}), "Roblox opened.")
        self.assertEqual(self.brief({"label": "x", "say": self.LONG, "report": True, "brief": True}), jarvis.spoken_report(self.LONG))
        self.assertEqual(self.brief({"label": "Needs your OK", "say": "May I email Sam? " * 30}), "May I email Sam? " * 30)
        self.brain.ask.assert_not_called()

    def test_a_failed_turn_falls_back_to_the_first_sentences(self):
        self.brain.ask.side_effect = model_provider.ProviderError("My plan's usage limit is reached.")
        item = {"label": "x", "say": self.LONG, "report": True, "note": "[TASK FINISHED]"}
        self.assertEqual(jarvis.brief_update(self.brain, self.voice, item), jarvis.spoken_report(self.LONG))
        self.brain.note.assert_called_once_with("[TASK FINISHED]", self.LONG)        # and it is still on his record


class PlanLimitTest(unittest.TestCase):
    def test_codex_usage_limit_is_told_apart_from_other_failures(self):
        for limit in ({"status": "failed", "error": {"message": "x", "codexErrorInfo": "usageLimitExceeded"}},
                      {"error": {"codexErrorInfo": {"usage_limit_exceeded": {}}}}, "You've hit your usage limit. Try again at 6pm."):
            self.assertTrue(codex_brain.says_limit(limit), limit)
        for other in ({"status": "failed", "error": {"codexErrorInfo": "rateLimitExceeded"}}, {"status": "interrupted"},
                      "Codex connection ended."):
            self.assertFalse(codex_brain.says_limit(other), other)

    def brain(self, plan):
        brain = jarvis.Brain.__new__(jarvis.Brain)
        brain.config = {"provider": "codex", "model": "gpt-6.1-terra"}
        brain.system, brain.messages, brain.cancel = "Be Jarvis.", [{"role": "user", "content": "hello"}], threading.Event()
        brain._tool = None
        brain._codex_brain = mock.Mock(ask=plan)
        return brain

    def fallback(self, answer="Hello, sir."):
        def ask(model, system, messages, definitions, run_tool, delta, cancel):
            delta(answer)
            return answer
        return mock.Mock(ask=mock.Mock(side_effect=ask))

    def test_at_the_plans_limit_the_conversation_moves_to_the_key_and_says_so_once(self):
        brain = self.brain(mock.Mock(side_effect=codex_brain.LimitReached("limit")))
        api, said = self.fallback(), []
        with mock.patch.object(openai_api, "available", return_value=True), \
                mock.patch.object(openai_api, "Conversation", return_value=api), mock.patch.object(jarvis.hud, "emit"), \
                mock.patch.object(openai_api.preferences, "read", return_value={}):
            brain._run_codex(said.append)
            self.assertEqual(" ".join(said), "Hello, sir. " + openai_api.SAYS_SO)
            self.assertEqual(api.ask.call_args.args[0], "gpt-6.1-terra")
            said.clear()
            brain._run_codex(said.append)                                        # the next turn: no second announcement,
            self.assertEqual(" ".join(said), "Hello, sir.")
            brain._codex_brain.ask.assert_called_once()                          # and the plan isn't hammered meanwhile
            brain._api_until = 0                                                 # fifteen minutes on: the plan answers again
            brain._codex_brain.ask = mock.Mock(return_value="Back, sir.")
            brain._run_codex(said.append)
            self.assertFalse(brain._api_told)
            self.assertEqual(api.ask.call_count, 2)

    def test_without_a_key_or_credit_he_says_exactly_that(self):
        brain = self.brain(mock.Mock(side_effect=codex_brain.LimitReached("limit")))
        with mock.patch.object(openai_api, "available", return_value=False), mock.patch.object(jarvis.hud, "emit"):
            with self.assertRaises(model_provider.ProviderError) as stopped:
                brain._run_codex(lambda sentence: None)
        self.assertIn("no OpenAI API key is saved", str(stopped.exception))
        api = mock.Mock(ask=mock.Mock(side_effect=openai_api.NoCredit(openai_api.NO_CREDIT)))
        said = []
        with mock.patch.object(openai_api, "available", return_value=True), mock.patch.object(jarvis.hud, "emit"), \
                mock.patch.object(openai_api, "Conversation", return_value=api), mock.patch.object(openai_api.preferences, "read", return_value={}):
            with self.assertRaises(model_provider.ProviderError) as stopped:
                brain._run_codex(said.append)
        self.assertIn("has no credit left", str(stopped.exception))
        self.assertEqual(said, [])                                               # never "I'm using your credit" when he isn't
        self.assertFalse(brain._api_told)

    def test_any_other_codex_failure_spends_nothing(self):
        brain = self.brain(mock.Mock(side_effect=RuntimeError("Codex connection ended.")))
        with mock.patch.object(openai_api, "Conversation") as api, self.assertRaises(model_provider.ProviderError) as stopped:
            brain._run_codex(lambda sentence: None)
        api.assert_not_called()
        self.assertIn("no API fallback was used", str(stopped.exception))


class OpenAIApiTest(unittest.TestCase):
    def test_a_test_run_has_no_key_so_nothing_paid_can_be_reached(self):
        self.assertEqual(openai_api.key(), "")
        self.assertFalse(openai_api.available())
        with self.assertRaises(model_provider.ProviderError):
            openai_api._post({"model": "x", "input": "hi"})

    def response(self, status, body):
        reply = mock.Mock(status_code=status)
        reply.json.return_value = body
        session = mock.Mock()
        session.post.return_value = reply
        return mock.patch.object(openai_api.requests, "Session", return_value=session)

    def test_an_empty_balance_is_said_as_that(self):
        with mock.patch.object(openai_api, "key", return_value="sk-test"), \
                self.response(429, {"error": {"code": "credit_balance_exhausted", "type": "insufficient_quota"}}):
            with self.assertRaises(openai_api.NoCredit) as stopped:
                openai_api._post({"model": "gpt-6.1-terra", "input": "hi"})
        self.assertIn("no credit left", str(stopped.exception))
        with mock.patch.object(openai_api, "key", return_value="sk-test"), self.response(429, {"error": {"code": "rate_limit_exceeded"}}):
            with self.assertRaises(model_provider.ProviderError) as stopped:
                openai_api._post({"model": "gpt-6.1-terra", "input": "hi"})
        self.assertNotIsInstance(stopped.exception, openai_api.NoCredit)

    def test_a_turn_streams_words_runs_tools_and_keeps_the_exchange(self):
        call = {"type": "function_call", "name": "get_weather", "call_id": "c1", "arguments": "{\"place\": \"Rosemount\"}"}
        rounds = [[{"type": "response.completed", "response": {"status": "completed", "output": [call]}}],
                  [{"type": "response.output_text.delta", "delta": "Forty-six "}, {"type": "response.output_text.delta", "delta": "degrees."},
                   {"type": "response.completed", "response": {"status": "completed", "output": [
                       {"type": "message", "content": [{"type": "output_text", "text": "Forty-six degrees."}]}]}}]]
        sent, heard, ran = [], [], []

        def events(payload, cancel):
            sent.append(json.loads(json.dumps(payload)))
            yield from rounds[len(sent) - 1]

        def run_tool(block):
            ran.append((block.name, block.input))
            return {"content": "46F, overcast"}
        conversation = openai_api.Conversation()
        definitions = [{"name": "get_weather", "description": "Weather", "input_schema": {"type": "object"}}]
        with mock.patch.object(openai_api, "events", events):
            answer = conversation.ask("gpt-6.1-terra", "Be Jarvis.", [{"role": "user", "content": "weather?"}], definitions,
                                      run_tool, heard.append, threading.Event())
        self.assertEqual((answer, heard), ("Forty-six degrees.", ["Forty-six ", "degrees."]))
        self.assertEqual(ran, [("get_weather", {"place": "Rosemount"})])
        self.assertEqual(sent[0]["model"], "gpt-6.1-terra")
        self.assertEqual(sent[0]["tools"][0]["name"], "get_weather")
        self.assertIn({"type": "function_call_output", "call_id": "c1", "output": "46F, overcast"}, sent[1]["input"])
        self.assertEqual((len(conversation.turns), conversation.sent), (1, 2))

    def test_the_model_can_be_chosen(self):
        with mock.patch.object(openai_api.preferences, "read", return_value={}):
            self.assertEqual(openai_api.model("gpt-6.1-terra"), "gpt-6.1-terra")
            self.assertEqual(openai_api.model("claude-opus-5-5"), openai_api.DEFAULT_MODEL)
        with mock.patch.object(openai_api.preferences, "read", return_value={"api_fallback_model": "gpt-6-luna"}):
            self.assertEqual(openai_api.model("gpt-6.1-terra"), "gpt-6-luna")

    def test_a_command_given_the_key_gets_it_for_that_run_only_and_cant_print_it(self):
        started = {}

        class FakeProcess:
            returncode = 0

            def __init__(self):
                self.stdout = io.StringIO("the key is sk-secret-123\n")

            def poll(self):
                return 0

            def wait(self):
                return 0

        def popen(command, **kwargs):
            started.update(kwargs["env"])
            return FakeProcess()
        with mock.patch.object(openai_api, "key", return_value="sk-secret-123"), \
                mock.patch.object(direct_tools.subprocess, "Popen", popen):
            output = direct_tools.execute("python make_image.py", ".", 5, True)
        self.assertEqual(started["OPENAI_API_KEY"], "sk-secret-123")
        self.assertNotIn("sk-secret-123", output)
        self.assertIn("[the OpenAI key]", output)
        with mock.patch.object(direct_tools.subprocess, "Popen", popen):
            started.clear()
            direct_tools.execute("python other.py", ".", 5)
        self.assertNotIn("OPENAI_API_KEY", {name for name, value in started.items() if value})
        self.assertIn("was not run", direct_tools.execute("python make_image.py", ".", 5, True))   # no key saved (a test run)

    def test_jarvis_is_told_when_the_key_may_be_used(self):
        prompt = jarvis.SYSTEM_PROMPT
        self.assertIn("with_openai_key true", prompt)
        self.assertIn("Never use the key for something a plan or a local tool can do", prompt)
        call = SimpleNamespace(name="run_command", id="t", input={"command": "Write-Output hi", "with_openai_key": True})
        self.assertIn("was not run", jarvis.run_tool(call)["content"])


if __name__ == "__main__":
    unittest.main()
