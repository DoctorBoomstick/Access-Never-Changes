"""The manual, and the copy of it GitHub shows."""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import mkreadme  # noqa: E402


class TestManual(unittest.TestCase):
    def setUp(self):
        with open(mkreadme.MANUAL, encoding="utf-8") as fh:
            self.page = fh.read()

    def test_readme_is_the_manual(self):
        with open(mkreadme.README, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), mkreadme.render(),
                             "edit docs/manual.html, then run tools/mkreadme.py")

    def test_every_contents_link_has_its_heading(self):
        ids = set(re.findall(r'id="([^"]+)"', self.page))
        for target in re.findall(r'href="#([^"]+)"', self.page):
            self.assertIn(target, ids)

    def test_no_markdown_left_in_the_text(self):
        main = re.search(r"<main>(.*)</main>", self.page, re.S).group(1)
        text = re.sub(r"<pre>.*?</pre>", "", main, flags=re.S)
        text = re.sub(r"<[^>]+>", "", text)
        for mark in (r"\*\*", r"(?m)^#", r"(?m)^\s*\|", r"\]\("):
            self.assertIsNone(re.search(mark, text), mark)


if __name__ == "__main__":
    unittest.main()
