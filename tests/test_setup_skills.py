"""scripts/setup_skills.py: what gets copied, what is left out, and that other people's folders are safe."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import setup_skills  # noqa: E402

PAGE = "---\nname: demo\ndescription: A demo.\n---\n\n# Demo\n\nBody --- with dashes.\n"


class SetupSkillsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / "source"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "reference").mkdir()
        (self.source / "SKILL.md").write_text(PAGE, encoding="utf-8")
        (self.source / "README.md").write_text("readme", encoding="utf-8")
        (self.source / "scripts" / "engine.cmd").write_text("download", encoding="utf-8")
        (self.source / "reference" / "more.md").write_text("more", encoding="utf-8")
        self.target = self.root / "home" / "demo"
        self.target.parent.mkdir()

    def install(self, **skill):
        return setup_skills.install(self.source, self.target, "someone/demo", "abc", {"name": "demo", **skill})

    def test_copies_the_skill_and_marks_it(self):
        self.assertEqual(self.install(), "")
        self.assertEqual((self.target / "SKILL.md").read_text(encoding="utf-8"), PAGE)
        self.assertTrue((self.target / "reference" / "more.md").is_file())
        self.assertTrue(setup_skills.ours(self.target))

    def test_skip_leaves_a_folder_out_and_the_note_follows_the_frontmatter(self):
        self.assertEqual(self.install(skip=("scripts",), note="No engine here."), "")
        self.assertFalse((self.target / "scripts").exists())
        page = (self.target / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(page.startswith("---\nname: demo\ndescription: A demo.\n---\n\n> No engine here.\n"))
        self.assertIn("Body --- with dashes.", page)

    def test_only_keeps_the_named_top_level_files(self):
        self.assertEqual(self.install(only=("SKILL.md",)), "")
        self.assertEqual(sorted(path.name for path in self.target.iterdir()), [setup_skills.MARKER, "SKILL.md"])

    def test_a_folder_that_is_not_ours_is_neither_replaced_nor_removed(self):
        self.target.mkdir()
        (self.target / "SKILL.md").write_text("the owner's own skill", encoding="utf-8")
        self.assertIn("left alone", self.install())
        self.assertFalse(setup_skills.remove(self.target))
        self.assertEqual((self.target / "SKILL.md").read_text(encoding="utf-8"), "the owner's own skill")

    def test_installing_again_replaces_ours_and_remove_takes_it_out(self):
        self.install()
        (self.target / "stale.txt").write_text("old", encoding="utf-8")
        self.assertEqual(self.install(), "")
        self.assertFalse((self.target / "stale.txt").exists())
        self.assertTrue(setup_skills.remove(self.target))
        self.assertFalse(self.target.exists())

    def test_a_source_without_a_skill_page_is_refused(self):
        (self.source / "SKILL.md").unlink()
        self.assertIn("no SKILL.md", self.install())
        self.assertFalse(self.target.exists())

    def test_every_listed_skill_is_pinned_to_a_full_commit(self):
        names = [skill["name"] for _repo, _commit, skill in setup_skills.skills()]
        self.assertEqual(len(names), len(set(names)))
        for _repo, commit, _skill in setup_skills.skills():
            self.assertRegex(commit, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
