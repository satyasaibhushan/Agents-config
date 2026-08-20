#!/usr/bin/env python3
"""Regression checks for standalone HTML artifact delivery."""

import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "Skills" / "Skills"
BASE = REPO / "Instructions" / "fragments" / "base.md"


class HtmlArtifactPolicyTest(unittest.TestCase):
    def test_html_artifact_producers_route_through_slate(self):
        for name in ("frontend-design", "improve-codebase-architecture", "teach"):
            with self.subTest(skill=name):
                content = (SKILLS / name / "SKILL.md").read_text().lower()
                self.assertIn("`slate` skill", content)

    def test_shared_delivery_contract_keeps_approval_privacy_and_fallback(self):
        contracts = {
            "base": BASE.read_text().lower(),
            "slate": (SKILLS / "slate" / "SKILL.md").read_text().lower(),
            "architecture": (
                SKILLS / "improve-codebase-architecture" / "SKILL.md"
            ).read_text().lower(),
            "teach": (SKILLS / "teach" / "SKILL.md").read_text().lower(),
        }
        for name, content in contracts.items():
            with self.subTest(contract=name):
                self.assertIn("private", content)
                self.assertIn("local-only", content)
                self.assertIn("unauthenticated", content)
                self.assertIn("slate url", content)
                self.assertRegex(content, r"external-write|ask immediately before")
                self.assertRegex(content, r"(os|local|staged) temp|temp (directory|file)")

    def test_teaching_workspace_does_not_store_html_lessons(self):
        content = (SKILLS / "teach" / "SKILL.md").read_text().lower()
        self.assertNotIn("./lessons/*.html", content)
        self.assertNotIn("./reference/*.html", content)

    def test_architecture_report_scaffold_is_static(self):
        reference = (
            SKILLS / "improve-codebase-architecture" / "HTML-REPORT.md"
        ).read_text()
        scaffold = re.search(r"```html\n(.*?)\n```", reference, re.DOTALL).group(1)

        for forbidden in ("<script", "<form", "<iframe", "javascript:"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, scaffold.lower())


if __name__ == "__main__":
    unittest.main()
