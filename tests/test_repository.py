from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "engineering"
EXPECTED_SKILL_FILES = {
    "SKILL.md",
    "manifest.json",
    "agents/openai.yaml",
    "references/controller-contract.md",
    "scripts/engineering.py",
    "tests/scenarios.json",
    "tests/test_engineering.py",
}
FORBIDDEN_CONTENT = re.compile(
    "(?i)(?:" + "|".join(
        [
            "ka" + "ka",
            "phi" + "lips",
            "requirements[ _-]?" + "agent",
            "ar" + "nab",
            "abis" + "was",
            "tm" + "id",
            "office " + "automations",
        ]
    ) + ")"
)
ABSOLUTE_USER_PATH = re.compile(
    r"(?i)(?:[a-z]:\\" + "us" + r"ers\\[^<]|/" + "us" + r"ers/[^<]|/" + "ho" + r"me/[^<])"
)


class RepositoryContractTests(unittest.TestCase):
    def test_skill_tree_is_generic_and_exact(self) -> None:
        actual = {
            path.relative_to(SKILL_ROOT).as_posix()
            for path in SKILL_ROOT.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        self.assertEqual(EXPECTED_SKILL_FILES, actual)
        for relative in sorted(actual):
            text = (SKILL_ROOT / relative).read_text(encoding="utf-8")
            self.assertIsNone(FORBIDDEN_CONTENT.search(text), relative)
            self.assertIsNone(ABSOLUTE_USER_PATH.search(text), relative)

    def test_repository_has_no_generated_or_private_state(self) -> None:
        forbidden_names = {
            "__pycache__",
            "graphify-out",
            "engineering-graphs",
            "contribution-queue.json",
            "applied-practices.json",
            "attestation.key",
            "install-receipt.json",
        }
        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8").split("\0")
        tracked_offenders = [
            path
            for path in tracked
            if path and any(part in forbidden_names for part in Path(path).parts)
        ]
        local_offenders = [
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if ".git" not in path.parts
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
            and any(part in forbidden_names - {"__pycache__"} for part in path.parts)
        ]
        self.assertEqual([], tracked_offenders)
        self.assertEqual([], local_offenders)

    def test_public_export_is_allowlisted_and_history_independent(self) -> None:
        if not (ROOT / "tools" / "export_public.py").is_file():
            self.skipTest("canonical-only exporter is intentionally absent")
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "public"
            subprocess.run(
                ["git", "init", "--initial-branch=main", str(destination)],
                check=True,
                capture_output=True,
            )
            marker = destination / ".git" / "independent-marker"
            marker.write_text("retained\n", encoding="utf-8")

            result = module.export_tree(ROOT, destination)

            self.assertTrue(marker.is_file())
            self.assertTrue(result["publication_ready"])
            self.assertEqual([], result["blockers"])
            self.assertFalse((destination / "release" / "public-export.json").exists())
            self.assertFalse((destination / "release" / "migration-receipt.json").exists())
            self.assertFalse((destination / "tools" / "export_public.py").exists())
            expected = set(
                json.loads((ROOT / "release" / "public-export.json").read_text(encoding="utf-8"))["files"]
            )
            actual = {
                path.relative_to(destination).as_posix()
                for path in destination.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }
            self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
