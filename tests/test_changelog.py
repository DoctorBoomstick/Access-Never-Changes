"""Pulling one release's notes out of CHANGELOG.md."""

import os
import unittest

from tools.changelog import CHANGELOG, section

SAMPLE = """# Changelog

## 1.0.1 (unreleased)

- Russian is read in Russian.

## 1.0.0 "Fat Man" (2026-10-23)

- The first release.
"""


class TestSection(unittest.TestCase):
    def test_a_section_stops_at_the_next_release(self):
        self.assertEqual(section(SAMPLE, "1.0.1"), "- Russian is read in Russian.")

    def test_the_last_section_runs_to_the_end(self):
        self.assertEqual(section(SAMPLE, "1.0.0"), "- The first release.")

    def test_a_version_is_not_matched_by_its_prefix(self):
        self.assertIsNone(section(SAMPLE, "1.0"))
        self.assertIsNone(section(SAMPLE, "1.0.10"))

    def test_the_real_file_has_the_first_release(self):
        with open(CHANGELOG, encoding="utf-8") as fh:
            self.assertTrue(section(fh.read(), "1.0.0"))


if __name__ == "__main__":
    unittest.main()
