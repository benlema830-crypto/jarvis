import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import knowledge
import meeting_prep as prep

NOW = datetime.datetime(2026, 11, 12, 14, 0).astimezone()
BRIEF = """## Spoken summary
You have the kitchen quote from Harlow at eighteen thousand and one open question on the worktops. Have the floor plan ready.
## What you have on it
- Quote of 18,000 from Harlow (Kitchen refit.md).
## Open items
- Choose the worktop material.
## Worth raising
- Whether the quote includes fitting."""


def event(title, minutes, **extra):
    return dict({"start": NOW + datetime.timedelta(minutes=minutes), "title": title, "location": "", "all_day": False}, **extra)


def search(query, limit):
    notes = [{"path": "Projects/Kitchen refit.md", "title": "Kitchen refit", "excerpt": "Harlow quoted 18,000 for the kitchen."},
             {"path": "Journal/2026-11-01.md", "title": "2026-11-01", "excerpt": "Had lunch. Talked about a kitchen once."},
             {"path": "Briefs/Meetings/2026-11-05 Kitchen refit with Harlow.md", "title": "old brief", "excerpt": "kitchen Harlow"}]
    return [n for n in notes if any(w in (n["title"] + n["excerpt"]).lower() for w in query.split())]


class MeetingPrepTest(unittest.TestCase):
    def found(self, title):
        return prep.material(title, search=search,
                             recall=lambda q, n: "Saved facts matching 'x' (user-provided memory):\n- Harlow does the kitchen refit. (saved 2026-10-01)\n- The owner likes golf. (saved 2026-09-01)",
                             tasks=lambda: [{"text": "Pick worktops for the kitchen with Harlow", "done": False},
                                            {"text": "Renew passport", "done": False},
                                            {"text": "Call Harlow about the kitchen", "done": True}])

    def test_keywords_drop_the_words_every_meeting_has(self):
        self.assertEqual(prep.keywords("Weekly sync: Kitchen refit with Harlow"), ["kitchen", "refit", "harlow"])
        self.assertEqual(prep.keywords("Lunch"), [])
        self.assertEqual(prep.keywords("Team standup 10"), [])

    def test_material_keeps_only_what_names_the_event(self):
        found = self.found("Kitchen refit with Harlow")
        self.assertEqual([n["path"] for n in found["notes"]], ["Projects/Kitchen refit.md"])   # not the journal, not an old brief
        self.assertIn("Harlow does the kitchen refit", found["facts"])
        self.assertNotIn("golf", found["facts"])
        self.assertEqual(found["tasks"], ["Pick worktops for the kitchen with Harlow"])

    def test_an_event_with_nothing_on_file_costs_nothing_and_says_nothing(self):
        ask = mock.Mock()
        self.assertIsNone(prep.brief(event("Lunch", 25), ask))
        self.assertIsNone(prep.brief(event("Dentist", 25), ask, found=prep.material("Dentist", search=lambda q, n: [], recall=lambda q, n: "No saved fact matches", tasks=lambda: [])))
        ask.assert_not_called()

    def test_brief_is_written_from_the_material_and_saved(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(knowledge, "VAULT", Path(temp)):
            asked = []
            result = prep.brief(event("Kitchen refit with Harlow", 25, location="Showroom"),
                                lambda system, text, label: asked.append(text) or BRIEF, found=self.found("Kitchen refit with Harlow"))
            self.assertTrue(result["summary"].startswith("You have the kitchen quote"))
            self.assertIn("Harlow quoted 18,000", asked[0])
            self.assertIn("Pick worktops", asked[0])
            self.assertIn("Where: Showroom", asked[0])
            note = (Path(temp) / result["note"]).read_text(encoding="utf-8")
            self.assertTrue(result["note"].startswith("Briefs/Meetings/2026-11-12 Kitchen refit with Harlow"))
            self.assertIn("[[Projects/Kitchen refit]]", note)
            self.assertIn("nothing about the meeting itself is known", note)

    def test_the_model_saying_the_material_is_unrelated_means_no_brief(self):
        found = self.found("Kitchen refit with Harlow")
        self.assertIsNone(prep.brief(event("Kitchen refit with Harlow", 25), lambda *a: "NOTHING", found=found))
        self.assertIsNone(prep.brief(event("Kitchen refit with Harlow", 25), lambda *a: None, found=found))

    def test_due_is_once_half_an_hour_ahead_and_leaves_the_last_minutes_to_the_heads_up(self):
        done = set()
        events = [event("Soon", 8), event("Half hour", 28), event("Later", 90), event("All day", 20, all_day=True)]
        self.assertEqual([e["title"] for e in prep.due(events, done, 30, now=NOW)], ["Half hour"])
        self.assertEqual(prep.due(events, done, 30, now=NOW), [])

    def test_prepare_picks_the_named_event_or_the_next_one(self):
        events = [event("Dentist", 60), event("Kitchen refit with Harlow", 180)]
        with mock.patch.object(prep, "brief", side_effect=lambda e, ask=None: None) as brief, \
                mock.patch.object(prep.datetime, "datetime", wraps=datetime.datetime) as clock:
            clock.now.return_value = NOW
            self.assertIn("Dentist", prep.prepare("my three o'clock", events))
            self.assertIn("Kitchen refit with Harlow", prep.prepare("the kitchen one", events))
            self.assertIn("no brief", prep.prepare("", events))
            self.assertEqual(brief.call_count, 3)
            self.assertIn("Nothing timed", prep.prepare("", []))

    def test_settings(self):
        with mock.patch.object(prep.preferences, "read", return_value={"meeting_prep": {"enabled": False, "minutes": 5}}):
            self.assertEqual(prep.settings(), {"enabled": False, "minutes": prep.MINUTES})
        with mock.patch.object(prep.preferences, "read", return_value={"meeting_prep": {"minutes": 45}}):
            self.assertEqual(prep.settings(), {"enabled": True, "minutes": 45})


if __name__ == "__main__":
    unittest.main()
