"""The agent board's data: every agent with what it is doing now, and the parallel job's stages."""
import os
import threading
import unittest

os.environ.setdefault("JARVIS_UNDER_TEST", "1")
import agent_board  # noqa: E402

NOW = 1_000_000.0


def session(name, status="completed", **more):
    return {"name": name, "project": "Jarvis", "cwd": "C:\\Users\\me\\Documents\\Trading Agent", "status": status,
            "task": "", "progress": "", "report": "", "provider": "claude", "timeline": [], **more}


class Groups:
    def __init__(self, *groups):
        self.lock = threading.Lock()
        self.groups = {g["id"]: g for g in groups}


def group(phase="working", round_=1, parts=(), earlier=(), lead=True):
    return {"id": "p1", "goal": "Build the backtester and check it", "mode": "work", "began": NOW - 900,
            "round": round_, "note": "", "earlier": list(earlier),
            "lead": {"choice": "fable", "words": "Claude Fable 5.2, high effort", "phase": phase} if lead else None,
            "parts": {p["name"].casefold(): p for p in parts}}


def part(name, done=False, outcome="", round_=1):
    return {"name": name, "words": "Claude Opus 5.5, high effort", "task": "Do a part", "mode": "work",
            "report": "the report" if done else None, "outcome": outcome, "round": round_}


class BoardTest(unittest.TestCase):
    def board(self, sessions, groups=None):
        return agent_board.snapshot({"sessions": sessions}, groups or Groups(), NOW)

    def test_a_working_agent_shows_its_job_its_step_and_how_long(self):
        steps = [{"label": "Worker activity", "detail": "Read: C:\\x\\README.md", "status": "observed", "started_at": NOW - 40},
                 {"label": "Running command", "status": "finished", "started_at": NOW - 9,
                  "detail": '"C:\\\\Windows\\\\System32\\\\WindowsPowerShell\\\\v1.0\\\\powershell.exe" -Command "pytest -q"'}]
        card = self.board([session("Frontier", "running", task="Fix the\n  save bug " + "x" * 900, progress="Running the tests",
                                   model_words="Codex, high effort", mode="work", started_at=NOW - 125,
                                   updated_at=NOW - 9, timeline=steps, changed_files=["a.py", "b.py"])])["agents"][0]
        self.assertEqual((card["name"], card["role"], card["live"], card["status"]), ("Frontier", "solo", True, "running"))
        self.assertEqual((card["model"], card["mode"], card["folder"]), ("Codex, high effort", "work", "Trading Agent"))
        self.assertTrue(card["task"].startswith("Fix the save bug x"))
        self.assertLessEqual(len(card["task"]), 600)
        self.assertEqual((card["doing"], card["seconds"], card["quiet"], card["files"]), ("Running the tests", 125, 9, 2))
        self.assertEqual([s["text"] for s in card["steps"]], ["Read: C:\\x\\README.md", "Running command: pytest -q"])
        self.assertEqual(card["steps"][1]["at"], NOW - 9)

    def test_a_finished_agent_shows_how_it_ended(self):
        card = self.board([session("Teardowns", "failed", progress="The task ran out of time after 30 minutes.",
                                   report="Nothing usable.", started_at=NOW - 4000, updated_at=NOW - 2200,
                                   evidence="Jarvis observed: 101 commands, 0 files changed through its edit tool.")])["agents"][0]
        self.assertEqual((card["live"], card["status"], card["seconds"]), (False, "failed", 1800))
        self.assertEqual(card["report"], "Nothing usable.")
        self.assertIn("101 commands", card["evidence"])

    def test_working_agents_come_first_then_the_most_recent(self):
        names = [a["name"] for a in self.board([
            session("Old", updated_at=NOW - 9000), session("Never used", "ready"), session("Busy", "running", started_at=NOW - 5),
            session("Recent", "failed", updated_at=NOW - 60)])["agents"]]
        self.assertEqual(names, ["Busy", "Recent", "Old"])  # one never given a task has nothing to show
        self.assertEqual(self.board([session("Busy", "running"), session("Stuck", "failed")])["counts"],
                         {"working": 1, "done": 0, "failed": 1})

    def test_no_job_running(self):
        self.assertIsNone(self.board([session("Parallel A", updated_at=NOW - 60)])["job"])

    def test_the_lead_is_planning(self):
        board = self.board([session("Parallel Lead", "running", started_at=NOW - 30, group="p1")], Groups(group("planning")))
        job = board["job"]
        self.assertEqual((job["goal"], job["round"], job["max_rounds"], job["seconds"]),
                         ("Build the backtester and check it", 1, 5, 900))
        self.assertEqual(job["lead"], {"model": "Claude Fable 5.2, high effort", "phase": "planning"})
        self.assertEqual([(s["label"], s["state"]) for s in job["stages"]],
                         [("Plan", "now"), ("Round 1", "next"), ("Check", "next"), ("Answer", "next")])
        self.assertEqual((board["agents"][0]["name"], board["agents"][0]["role"]), ("Parallel Lead", "lead"))

    def test_round_two_is_running(self):
        earlier = [part("Parallel A", True, "done"), part("Parallel B", True, "failed")]
        now = [part("Parallel A", True, "done", 2), part("Parallel B", round_=2)]
        board = self.board([session("Parallel B", "running", group="p1"), session("Parallel A", group="p1"),
                            session("Parallel Lead", group="p1"), session("Parallel C", group="p1"),
                            session("Frontier", "running")],
                           Groups(group("working", 2, now, earlier)))
        job = board["job"]
        self.assertEqual([(s["label"], s["state"]) for s in job["stages"]],
                         [("Plan", "done"), ("Round 1", "done"), ("Check", "done"), ("Round 2", "now"), ("Check", "next"),
                          ("Answer", "next")])
        self.assertEqual(job["rounds"], [
            {"round": 1, "parts": [{"name": "Parallel A", "outcome": "done"}, {"name": "Parallel B", "outcome": "failed"}]},
            {"round": 2, "parts": [{"name": "Parallel A", "outcome": "done"}, {"name": "Parallel B", "outcome": ""}]}])
        # The lead, then this round's agents; an agent left over from an earlier round is not in this round
        self.assertEqual([(a["name"], a["role"]) for a in board["agents"]],
                         [("Parallel Lead", "lead"), ("Parallel A", "part"), ("Parallel B", "part"), ("Frontier", "solo"),
                          ("Parallel C", "solo")])
        self.assertEqual(board["counts"]["working"], 2)

    def test_the_lead_is_checking_the_reports(self):
        job = self.board([], Groups(group("merging", 1, [part("Parallel A", True, "done")])))["job"]
        self.assertEqual([(s["label"], s["state"]) for s in job["stages"]],
                         [("Plan", "done"), ("Round 1", "done"), ("Check", "now"), ("Answer", "next")])

    def test_a_job_holding_its_next_round_for_a_long_run(self):
        import parallel
        self.assertEqual(agent_board.MAX_ROUNDS, parallel.MAX_ROUNDS)   # the number the board names
        waiting = group("waiting", 2, [], earlier=[part("Parallel A", True, "done")])
        waiting["wait_until"] = NOW + 25 * 60
        job = self.board([], Groups(waiting))["job"]
        self.assertEqual((job["lead"]["phase"], job["wait"]), ("waiting", 25 * 60))
        self.assertEqual([(s["label"], s["state"]) for s in job["stages"]],
                         [("Plan", "done"), ("Round 1", "done"), ("Check", "done"), ("Round 2", "next"),
                          ("Check", "next"), ("Answer", "next")])
        self.assertEqual(self.board([], Groups(group("working", 1, [part("Parallel A")])))["job"]["wait"], 0)

    def test_a_job_without_a_lead(self):
        job = self.board([], Groups(group(parts=[part("Parallel A"), part("Parallel B")], lead=False)))["job"]
        self.assertIsNone(job["lead"])
        self.assertEqual([(s["label"], s["state"]) for s in job["stages"]], [("Agents", "now"), ("Answer", "next")])


class ServedTest(unittest.TestCase):
    def test_the_page_and_its_data_are_served(self):
        import brain
        for route in ("/board", "/board.css", "/board.js"):
            self.assertTrue((brain.ROOT / "hud" / brain.ASSETS[route][0]).is_file(), route)
        self.assertIn("/agents", brain.PROXY["GET"])

    def test_jarvis_answers_with_the_board(self):
        import http.client
        import json
        from http.server import ThreadingHTTPServer
        from unittest import mock
        import hud
        server = ThreadingHTTPServer(("127.0.0.1", 0), hud._Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        host = f"127.0.0.1:{server.server_port}"
        with mock.patch.object(hud, "ALLOWED_HOSTS", {host}):
            connection = http.client.HTTPConnection(host, timeout=10)
            connection.request("GET", "/agents")
            response = connection.getresponse()
            body = json.loads(response.read())
            connection.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(set(body), {"now", "job", "agents", "counts", "room"})
        self.assertIn(body["room"]["headset"], (True, False))


if __name__ == "__main__":
    unittest.main()
