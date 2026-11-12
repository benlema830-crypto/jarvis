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


class NarrationAndTakingOver(unittest.TestCase):
    def test_the_computer_tool_asks_for_a_spoken_line(self):
        computer = next(t for t in agent.TOOLS if t["name"] == "computer")
        self.assertIn("saying", computer["input_schema"]["properties"])
        self.assertEqual(computer["input_schema"]["required"], ["actions"])   # a bare screenshot needs no line
        self.assertIn("Narrate", agent.SYSTEM)

    def narrating(self, prefs=None):
        a = make_agent()
        a.on_narrate = mock.Mock(return_value=True)
        patches = [mock.patch.object(agent.preferences, "read", return_value=prefs or {}),
                   mock.patch.object(agent.hud, "emit")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return a

    def test_each_step_is_said_once_and_not_too_often(self):
        a = self.narrating()
        a._narrate("Clicking Create to start a new campaign.")
        a._narrate("Clicking Create to start a new campaign.")   # the same line again
        a._narrate("Naming the campaign.")                        # too soon after the last one
        a.on_narrate.assert_called_once_with("Clicking Create to start a new campaign.")
        a._narrated_at -= agent.NARRATE_GAP + 1
        a._narrate("Naming the campaign.")
        self.assertEqual(a.on_narrate.call_count, 2)
        a._narrate("")
        self.assertEqual(a.on_narrate.call_count, 2)

    def test_a_line_nobody_can_hear_is_shown_instead(self):
        a = self.narrating()
        a.on_narrate.return_value = False   # he is talking, or the room is empty
        a._narrate("Opening the settings page.")
        agent.hud.emit.assert_called_once_with("event", text="Computer: Opening the settings page.")
        a._narrate("Scrolling to the budget.")   # nothing was said, so the next line needn't wait
        self.assertEqual(a.on_narrate.call_count, 2)

    def test_narration_can_be_switched_off(self):
        a = self.narrating({"agent_narration": False})
        a._narrate("Opening the settings page.")
        a.on_narrate.assert_not_called()

    def test_the_line_is_said_before_the_actions_run(self):
        a = self.narrating()
        order = []
        a.on_narrate.side_effect = lambda line: order.append("say") or True
        with mock.patch.object(a, "_actions", side_effect=lambda actions: order.append("act") or []):
            a._tool(SimpleNamespace(name="computer", id="1", input={"saying": "Clicking Save.", "actions": [{"action": "left_click"}]}))
        self.assertEqual(order, ["say", "act"])

    def test_owner_input_is_a_moved_pointer_a_click_or_a_key(self):
        a = make_agent()
        keys = set()
        with mock.patch.object(agent.win32api, "GetCursorPos", return_value=(500, 500)), \
                mock.patch.object(agent.win32api, "GetAsyncKeyState", side_effect=lambda k: 0x8000 if k in keys else 0):
            self.assertEqual(a._owner_input((500, 500)), "")
            self.assertEqual(a._owner_input((495, 510)), "")          # a nudge of the desk
            self.assertEqual(a._owner_input((400, 500)), "mouse")
            keys.add(0x41)
            self.assertEqual(a._owner_input((500, 500)), "keyboard")
            keys.clear(); keys.add(1)
            self.assertEqual(a._owner_input((500, 500)), "mouse")     # a click
            keys.clear(); keys.add(0xAF)
            self.assertEqual(a._owner_input((500, 500)), "")          # volume up on the headset isn't taking over

    def test_taking_over_ends_the_task_and_is_not_held_against_it(self):
        a = make_agent()
        a.brain = brain = object()
        a._acted_at = 0
        with mock.patch.object(agent.win32api, "GetCursorPos", return_value=(0, 0)), \
                mock.patch.object(a, "_owner_input", side_effect=["", "", "keyboard"]) as asked:
            a._watch_owner(brain)
        self.assertEqual(asked.call_count, 3)
        self.assertTrue(a._cancel.is_set())
        self.assertEqual(a._stopped_why, "you took over the keyboard")
        self.assertEqual(a._taken, "keyboard")

    def test_the_agents_own_clicks_are_never_mistaken_for_the_owner(self):
        a = make_agent()
        a.brain = brain = object()
        a._acted_at = 0
        seen = []

        def acting(actions):
            seen.append(a._acting)
            return []
        with mock.patch.object(a, "_run_actions", side_effect=acting):
            a._actions([{"action": "left_click"}])
        self.assertEqual(seen, [True])
        self.assertFalse(a._acting)
        # Straight after its own input the pointer has "moved"; inside the grace period nobody is asked.
        with mock.patch.object(agent.win32api, "GetCursorPos", return_value=(0, 0)), \
                mock.patch.object(a, "_owner_input", return_value="mouse") as asked, \
                mock.patch.object(agent.time, "sleep", side_effect=lambda s: a._cancel.set()):
            a._watch_owner(brain)
        asked.assert_not_called()
