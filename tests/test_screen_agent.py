"""do_on_computer on the owner's Claude plan: the task loop, the action tool, limits and safety."""
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import agent
import claude_code_brain


def make_agent():
    with mock.patch.object(agent.Agent, "_configure_screen"):
        a = agent.Agent()
    a.shot_size = (1456, 819)
    a.layout = mock.Mock()
    a.layout.describe.return_value = "one monitor"
    a.on_done = mock.Mock()
    return a


class FakeBrain:
    """Stands in for the Claude Code session: plays a scripted list of tool calls, then answers."""
    script, answer, error = [], "Notepad is open.", None

    def __init__(self):
        self.closed = False
        FakeBrain.last = self

    def ask(self, model, system, messages, definitions, run_tool, delta, cancel):
        self.model, self.system, self.request, self.definitions = model, system, messages, definitions
        delta("Menu not shown; take a screenshot.")  # thinking aloud before acting: not part of the report
        self.results = [run_tool(SimpleNamespace(name=name, id=str(n), input=args)) for n, (name, args) in enumerate(self.script)]
        if self.error:
            raise self.error
        delta(self.answer)
        if cancel.is_set():
            raise InterruptedError()
        return self.answer

    def close(self):
        self.closed = True


class TaskLoop(unittest.TestCase):
    def run_task(self, script=(), answer="Notepad is open.", error=None, computer=None):
        FakeBrain.script, FakeBrain.answer, FakeBrain.error = list(script), answer, error
        a = make_agent()
        shot = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}]
        with mock.patch.object(claude_code_brain, "ClaudeCodeBrain", FakeBrain), \
                mock.patch.object(a, "_screenshot", return_value=shot), \
                mock.patch.object(a, "_computer", computer or mock.Mock(return_value=[{"type": "text", "text": "OK"}])) as done, \
                mock.patch.object(agent.task_effort, "choose", return_value=("low", "new kind of task")), \
                mock.patch.object(agent.task_effort, "record") as record, \
                mock.patch.object(agent.hud, "emit"), mock.patch.object(agent.worksafe, "blocked_apps", return_value="Teams"), \
                mock.patch.object(agent, "SETTLE_SECONDS", 0):
            a._run("open Notepad")
        return a, done, record

    def test_a_finished_task_reports_and_runs_on_the_plan(self):
        a, done, record = self.run_task([("computer", {"actions": [{"action": "key", "text": "super"},
                                                                   {"action": "type", "text": "notepad"}]})])
        result = a.on_done.call_args.args[0]
        self.assertEqual((result["ok"], result["report"], result["steps"]), (True, "Notepad is open.", 1))
        brain = FakeBrain.last
        self.assertEqual((brain.max_turns, brain.web, brain.model), (agent.MAX_STEPS, False, agent.MODEL))
        self.assertTrue(brain.closed)
        self.assertIsNone(a.brain)
        self.assertEqual([t["name"] for t in brain.definitions], ["computer", "ask_user", "run_powershell"])
        self.assertIn("open Notepad", brain.request[0]["content"])
        self.assertEqual([c.args for c in done.call_args_list], [("key", {"text": "super"}), ("type", {"text": "notepad"})])
        content = brain.results[0]["content"]
        self.assertEqual(content[-1]["type"], "image")           # the screen after the actions
        self.assertIn("All 2 actions ran.", [b.get("text") for b in content])
        self.assertTrue(record.call_args.args[3])                 # recorded as finished

    def test_the_report_is_only_what_was_said_after_the_last_action(self):
        a, _, _ = self.run_task([("computer", {"actions": [{"action": "key", "text": "escape"}]})], answer="The menu is closed.")
        self.assertEqual(a.on_done.call_args.args[0]["report"], "The menu is closed.")

    def test_a_failed_action_stops_the_rest_and_still_shows_the_screen(self):
        computer = mock.Mock(side_effect=[[{"type": "text", "text": "OK"}], ValueError("That point is off-limits."), AssertionError("must not run")])
        a, done, _ = self.run_task([("computer", {"actions": [{"action": "left_click", "coordinate": [5, 5]},
                                                              {"action": "left_click", "coordinate": [9, 9]},
                                                              {"action": "type", "text": "x"}]})], computer=computer)
        self.assertEqual(computer.call_count, 2)
        content = FakeBrain.last.results[0]["content"]
        self.assertIn("Action 2 (left_click) failed: That point is off-limits.", content[0]["text"])
        self.assertEqual(content[-1]["type"], "image")

    def test_bad_tool_input_is_an_error_for_the_model_not_a_crash(self):
        a, done, _ = self.run_task([("computer", {"actions": []}), ("computer", {"actions": [{"action": "format_disk"}]}),
                                    ("launch_missiles", {}), ("computer", {})])
        self.assertTrue(all(r["is_error"] for r in FakeBrain.last.results))
        done.assert_not_called()
        self.assertTrue(a.on_done.call_args.args[0]["ok"])        # the session itself carried on

    def test_looking_does_not_add_a_second_screenshot(self):
        self.run_task([("computer", {"actions": [{"action": "screenshot"}]})],
                      computer=mock.Mock(return_value=[{"type": "image", "source": {}}]))
        self.assertEqual(len(FakeBrain.last.results[0]["content"]), 1)

    def test_plan_limit_is_reported_and_nothing_is_billed(self):
        a, _, record = self.run_task(error=claude_code_brain.LimitReached("limit"))
        result = a.on_done.call_args.args[0]
        self.assertFalse(result["ok"])
        self.assertIn("usage limit", result["report"])
        self.assertIn("Nothing was charged", result["report"])

    def test_not_signed_in_stops_instead_of_using_api_credits(self):
        a, _, _ = self.run_task(error=claude_code_brain.WouldBillAPI("key"))
        self.assertIn("won't use API credits", a.on_done.call_args.args[0]["report"])

    def test_mouse_in_a_corner_stops_the_task(self):
        a, _, record = self.run_task([("computer", {"actions": [{"action": "left_click", "coordinate": [1, 1]}]})],
                                     computer=mock.Mock(side_effect=agent.pyautogui.FailSafeException()))
        result = a.on_done.call_args.args[0]
        self.assertFalse(result["ok"])
        self.assertIn("the mouse was moved into a screen corner", result["report"])
        self.assertFalse(record.call_args.kwargs["stopped_by_user"] is None)

    def test_stop_from_the_owner(self):
        a = make_agent()
        FakeBrain.script, FakeBrain.error = [], None
        a._cancel.set()
        with mock.patch.object(claude_code_brain, "ClaudeCodeBrain", FakeBrain), mock.patch.object(agent.hud, "emit"), \
                mock.patch.object(agent.task_effort, "choose", return_value=("low", "x")), \
                mock.patch.object(agent.task_effort, "record") as record, \
                mock.patch.object(agent.worksafe, "blocked_apps", return_value="Teams"):
            a._run("anything")
        self.assertEqual(a.on_done.call_args.args[0]["report"], "Stopped by the user.")
        self.assertTrue(record.call_args.kwargs["stopped_by_user"])

    def test_time_limit_ends_the_task_and_says_why(self):
        a = make_agent()
        a._give_up("the task was taking too long")
        self.assertTrue(a._cancel.is_set())
        self.assertEqual(a._stopped_why, "the task was taking too long")

    def test_approval_question_goes_to_the_owner(self):
        with mock.patch.object(agent.approvals, "ask", return_value=(False, "no")) as ask:
            a, _, _ = self.run_task([("ask_user", {"question": "Shall I delete these 12 files?"})])
        ask.assert_called_once()
        self.assertIn("did NOT approve", FakeBrain.last.results[0]["content"][0]["text"])


class ToolShape(unittest.TestCase):
    def test_every_action_the_executor_knows_is_offered(self):
        offered = agent.TOOLS[0]["input_schema"]["properties"]["actions"]["items"]["properties"]["action"]["enum"]
        self.assertEqual(offered, agent.ACTIONS)
        for name in ("screenshot", "zoom", "left_click", "type", "key", "scroll", "left_click_drag", "wait"):
            self.assertIn(name, offered)

    def test_do_on_computer_is_no_longer_blocked(self):
        import tools
        started = []
        with mock.patch.object(tools.AGENT, "start", side_effect=lambda task: started.append(task) or "Started."), \
                mock.patch.object(tools.preferences, "read", return_value={"subscription_only": True}, create=True), \
                mock.patch.object(tools.hud, "emit"):
            result = tools.run_tool(SimpleNamespace(name="do_on_computer", id="1", input={"task": "open Notepad"}))
        self.assertFalse(result.get("is_error"), result)
        self.assertEqual(started, ["open Notepad"])

    def test_the_session_settings_reach_claude_code(self):
        brain = claude_code_brain.ClaudeCodeBrain.__new__(claude_code_brain.ClaudeCodeBrain)
        brain.max_turns, brain.effort, brain.web = 60, "medium", False
        brain.cancel, brain.run_tool, brain.tool_count = threading.Event(), lambda block: {"content": "ok"}, 45
        self.assertFalse(brain._call_tool("computer", {})["is_error"])   # past the conversation's 40, inside its own 60
        brain.tool_count = 60
        self.assertTrue(brain._call_tool("computer", {})["is_error"])


if __name__ == "__main__":
    unittest.main()
