#!/usr/bin/env python3
"""Package-level checks: skill metadata, cross-references, and safety baseline.

Run:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import re
import stat
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "SKILL.md"
SCRIPT = REPO_ROOT / "scripts" / "render_upload_pages.py"
README = REPO_ROOT / "README.md"
MANIFEST = REPO_ROOT / "agents" / "openai.yaml"

PALETTE = ("#005087", "#86B8CE", "#B23939", "#D88080")
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise AssertionError(f"{path.name} has no YAML frontmatter")
    raw = text.split("---", 2)[1]
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise AssertionError(f"{path.name} frontmatter is not a mapping")
    return data


class SkillPackageTest(unittest.TestCase):
    def test_frontmatter_parses_and_name_matches_folder(self) -> None:
        data = frontmatter(SKILL_MD)
        self.assertEqual(data["name"], REPO_ROOT.name)
        self.assertLessEqual(len(data["name"]), 64)

    def test_description_respects_spec_length_and_front_loads_triggers(self) -> None:
        description = frontmatter(SKILL_MD)["description"]
        self.assertTrue(description.strip())
        self.assertLessEqual(len(description), 1024, msg="description must stay within the spec limit")
        # Codex shortens long descriptions first, so triggers must not sit at the tail.
        for trigger in ("笔记图", "网页端出图"):
            position = description.find(trigger)
            self.assertGreater(position, -1, msg=f"missing trigger: {trigger}")
            self.assertLess(position / len(description), 0.7, msg=f"trigger too late: {trigger}")

    def test_description_has_no_yaml_comment_or_mapping_hazards(self) -> None:
        # A bare "#palette" or ": " inside an unquoted plain scalar silently truncates
        # the description; parsing must return the full text.
        raw = SKILL_MD.read_text(encoding="utf-8").split("---", 2)[1]
        match = re.search(r"^description:[ \t]*(.*)$", raw, re.M)
        self.assertIsNotNone(match)
        scalar = match.group(1).strip()
        if scalar and not scalar.startswith(('"', "'", ">", "|")):
            self.assertNotIn(" #", scalar, msg="unquoted description would be cut at a # comment")
            self.assertNotIn(": ", scalar, msg="unquoted description would break YAML parsing")
        for colour in PALETTE:
            self.assertIn(colour, frontmatter(SKILL_MD)["description"])

    def test_referenced_resource_paths_exist(self) -> None:
        text = SKILL_MD.read_text(encoding="utf-8")
        referenced = set(re.findall(r"`((?:references|scripts|tests)/[A-Za-z0-9._\-/]+)`", text))
        self.assertTrue(referenced, msg="SKILL.md should reference its resources")
        for relative in sorted(referenced):
            self.assertTrue((REPO_ROOT / relative).exists(), msg=f"missing resource: {relative}")

    def test_manifest_matches_documented_schema(self) -> None:
        data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
        interface = data["interface"]
        self.assertTrue(interface["display_name"])
        self.assertTrue(interface["short_description"])
        self.assertIn(interface["brand_color"], PALETTE)
        self.assertIn(interface["default_prompt"], (interface["default_prompt"],))
        allowed = {
            "display_name",
            "short_description",
            "icon_small",
            "icon_large",
            "brand_color",
            "default_prompt",
        }
        self.assertTrue(set(interface) <= allowed, msg=f"unknown interface keys: {set(interface) - allowed}")

    def test_readme_documents_every_script_flag(self) -> None:
        readme = README.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")
        flags = set(re.findall(r'add_argument\(\s*"(--[a-z\-]+)"', script))
        self.assertTrue(flags)
        for flag in sorted(flags):
            self.assertIn(flag, readme, msg=f"README does not document {flag}")

    def test_readme_lists_every_tracked_resource_file(self) -> None:
        readme = README.read_text(encoding="utf-8")
        for relative in (
            "SKILL.md",
            "references/visual-style.md",
            "references/output-patterns.md",
            "references/web-handoff.md",
            "scripts/render_upload_pages.py",
            "agents/openai.yaml",
        ):
            self.assertIn(relative, readme, msg=f"README does not mention {relative}")

    def test_script_is_executable(self) -> None:
        mode = SCRIPT.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, msg="scripts/render_upload_pages.py must be executable")

    def test_script_avoids_shell_and_dynamic_execution(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        for needle in ("shell=True", "os.system", "eval(", "exec(", "pickle.load", "yaml.load("):
            self.assertNotIn(needle, script, msg=f"unsafe construct: {needle}")
        self.assertNotIn("subprocess.run(cmd)", script.replace(" ", ""))

    def test_no_network_access_in_scripts(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        for module in ("import requests", "import urllib", "import socket", "import httpx"):
            self.assertNotIn(module, script)

    def test_no_absolute_local_paths_or_credentials_in_shipped_text(self) -> None:
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.suffix not in {".md", ".py", ".yaml", ".yml", ".txt", ""}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotRegex(text, r"/Users/[A-Za-z]+/", msg=f"absolute local path in {path.name}")
            self.assertNotRegex(text, r"/home/[A-Za-z]+/", msg=f"absolute local path in {path.name}")
            for pattern in SECRET_PATTERNS:
                self.assertIsNone(pattern.search(text), msg=f"possible secret in {path.name}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
