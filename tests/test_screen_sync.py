import unittest
from unittest import mock

import screen_sync as sync
import truth_guard

HOSTS = {"ASUS (left)": "10.0.0.2", "OLED (right)": "10.0.0.3"}


class ScreenSyncTest(unittest.TestCase):
    def setUp(self):
        self.running = True
        self.live = {h: True for h in HOSTS.values()}
        self.on = {h: True for h in HOSTS.values()}
        self.rpc_calls, self.posts = [], []
        for name, value in (("controllers", lambda: dict(HOSTS)), ("_rpc", self.fake_rpc),
                            ("_controller", self.fake_controller), ("_start", self.fake_start)):
            p = mock.patch.object(sync, name, side_effect=value)
            p.start()
            self.addCleanup(p.stop)
        for name, value in (("CONFIRM_SECONDS", 0.2), ("POLL", 0.01)):
            p = mock.patch.object(sync, name, value)
            p.start()
            self.addCleanup(p.stop)
        session = mock.MagicMock()
        session.__enter__.return_value.post.side_effect = lambda url, **kw: self.posts.append((url, kw["json"]))
        p = mock.patch.object(sync, "_session", return_value=session)
        p.start()
        self.addCleanup(p.stop)

    def fake_rpc(self, body):
        self.rpc_calls.append(body)
        if not self.running:
            return None
        if body["command"] == "componentstate":
            state = body["componentstate"]["state"]
            for h in self.live:
                self.live[h] = state if h not in getattr(self, "stuck", ()) else self.live[h]
        return {"success": True}

    def fake_controller(self, host):
        return self.live[host], self.on[host]

    def fake_start(self):
        self.running = True
        self.started = True

    def test_off_is_confirmed_from_the_controllers(self):
        out = sync.control("off")
        self.assertTrue(out.startswith("Confirmed:"), out)
        self.assertEqual(truth_guard.classify("screen_sync", True, out), truth_guard.CONFIRMED)

    def test_off_when_hyperhdr_is_not_running_changes_nothing(self):
        self.running = False
        out = sync.control("off")
        self.assertIn("already off", out)
        self.assertEqual(self.rpc_calls, [{"command": "serverinfo"}])

    def test_on_starts_hyperhdr_when_it_is_not_running(self):
        self.running = False
        self.live = {h: False for h in HOSTS.values()}
        out = sync.control("on")
        self.assertTrue(getattr(self, "started", False))
        self.assertIn("Confirmed: ASUS (left), OLED (right) now follow the screen.", out)

    def test_on_switches_on_a_strip_that_is_off(self):
        self.live = {h: False for h in HOSTS.values()}
        self.on["10.0.0.3"] = False
        out = sync.control("on")
        self.assertEqual(self.posts, [("http://10.0.0.3/json/state", {"on": True})])
        self.assertIn("switched on OLED (right)", out)

    def test_a_controller_that_never_follows_is_not_confirmed(self):
        self.live = {h: False for h in HOSTS.values()}
        self.stuck = {"10.0.0.2"}
        out = sync.control("on")
        self.assertIn("NOT CONFIRMED", out)
        self.assertIn("ASUS (left) did not start", out)
        self.assertEqual(truth_guard.classify("screen_sync", True, out), truth_guard.UNKNOWN)

    def test_status_is_a_look_up_not_an_action(self):
        out = sync.control("status")
        self.assertTrue(out.startswith("Status:"), out)
        self.assertIsNone(truth_guard.classify("screen_sync", True, out))

    def test_unknown_action_is_refused(self):
        with self.assertRaises(sync.SyncError):
            sync.control("blink")


if __name__ == "__main__":
    unittest.main()
