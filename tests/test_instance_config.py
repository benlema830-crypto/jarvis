import os
import unittest

from instance_config import mutex_name


class InstanceIdentityTest(unittest.TestCase):
    def test_different_copies_have_different_locks(self):
        self.assertNotEqual(mutex_name(r"C:\Users\Lemab\jarvis"),
                            mutex_name(r"C:\Users\Lemab\Documents\Jarvis-CustomVoice"))

    def test_same_folder_alias_reuses_lock(self):
        if os.name != "nt":
            self.skipTest("Windows path identity")
        self.assertEqual(mutex_name(r"C:\Users\Lemab\jarvis"),
                         mutex_name(r"C:\Users\Lemab\JARVIS\."))
