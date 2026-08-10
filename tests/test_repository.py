from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "engineering"
EXPECTED_SKILL_FILES = {
    "SKILL.md",
    "manifest.json",
    "agents/openai.yaml",
    "references/controller-contract.md",
    "scripts/engineering",
    "scripts/engineering.cmd",
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
    def test_release_manifest_is_v2_2_4_with_pinned_graphify(self) -> None:
        manifest = json.loads((SKILL_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("2.2.4", manifest["version"])
        self.assertEqual(1, manifest["controller_schema"])
        self.assertEqual(
            {
                "repository": "https://github.com/safishamsi/graphify",
                "tag": "v0.9.5",
                "version": "0.9.5",
                "commit": "d89ec68af95e0cad801b56d88df383991e659823",
            },
            manifest["graphify"],
        )

    def test_ci_installs_the_pinned_graphify_dependency(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "python -m pip install \"git+https://github.com/safishamsi/graphify.git"
            "@d89ec68af95e0cad801b56d88df383991e659823\"",
            workflow,
        )

    def test_ci_runs_windows_controller_and_installer_isolation_regression(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("matrix:\n        os: [ubuntu-latest, windows-latest]", workflow)
        self.assertIn(
            "python -m unittest discover -s .agents/skills/engineering/tests",
            workflow,
        )
        self.assertIn("if: runner.os == 'Windows'", workflow)
        self.assertIn(
            "Task7ContractTests."
            "test_temporary_home_install_replay_and_rollback_do_not_mutate_windows_path",
            workflow,
        )
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("self-hosted", workflow)

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

    def test_human_skill_is_compact_and_defers_protocol_detail(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(re.findall(r"\S+", skill)), 700)
        for required in (
            "automatically",
            "canonical default-branch checkpoint",
            "Unknown",
            "Outcome:",
            "authorize",
            "controller-contract.md",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill)

    def test_readme_states_the_operating_and_evidence_boundaries(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for required in (
            "## Why, what, how",
            "## Deterministic and LLM-assisted work",
            "## Dependencies and prerequisites",
            "## Quick start",
            "## Scale and limits",
            "Unknown",
            "semantic_matrices",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)

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
            receipt = json.loads(
                (destination / ".git" / "engineering-public-export.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("engineering.public-export-receipt.v2", receipt["schema"])
            self.assertTrue(result["publication_ready"])
            self.assertEqual([], result["blockers"])
            self.assertFalse((destination / "release" / "migration-receipt.json").exists())
            expected = set(
                json.loads((ROOT / "release" / "public-export.json").read_text(encoding="utf-8"))["files"]
            )
            actual = {
                path.relative_to(destination).as_posix()
                for path in destination.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }
            self.assertEqual(expected, actual)
            for relative in expected:
                self.assertEqual(
                    (ROOT / relative).read_bytes(),
                    (destination / relative).read_bytes(),
                    relative,
                )
            required_generic_payload = {
                ".agents/skills/engineering/SKILL.md",
                ".agents/skills/engineering/scripts/engineering",
                ".agents/skills/engineering/scripts/engineering.cmd",
                ".agents/skills/engineering/scripts/engineering.py",
                ".agents/skills/engineering/tests/test_engineering.py",
                ".github/workflows/security.yml",
                "README.md",
                "release/public-export.json",
                "tests/test_repository.py",
                "tools/export_public.py",
            }
            self.assertLessEqual(required_generic_payload, actual)
            self.assertIn("docs/specs/engineering-v2.2.3-design.md", actual)
            self.assertIn("docs/specs/engineering-v2.2.4-authority-persistence.md", actual)
            workflow = (destination / ".github/workflows/security.yml").read_text(
                encoding="utf-8"
            )
            self.assertIn("ubuntu-latest", workflow)
            self.assertIn("windows-latest", workflow)
            self.assertNotIn("self-hosted", workflow)

    def test_public_export_cannot_delete_an_absolute_retained_path(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "public"
            subprocess.run(
                ["git", "init", "--initial-branch=main", str(destination)],
                check=True,
                capture_output=True,
            )
            sentinel = base / "outside.txt"
            sentinel.write_text("keep\n", encoding="utf-8")
            receipt = destination / ".git" / "engineering-public-export.json"
            receipt.write_text(
                json.dumps({"files": [str(sentinel)]}), encoding="utf-8"
            )
            module.export_tree(ROOT, destination)
            self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))

    def test_public_export_preserves_unverified_or_modified_relative_files(self) -> None:
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
            retained = destination / "retained.txt"
            retained.write_text("keep\n", encoding="utf-8")
            receipt = destination / ".git" / "engineering-public-export.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schema": "engineering.public-export-receipt.v2",
                        "files": {"retained.txt": "sha256:" + "0" * 64},
                    }
                ),
                encoding="utf-8",
            )
            module.export_tree(ROOT, destination)
            self.assertEqual("keep\n", retained.read_text(encoding="utf-8"))

    def test_public_export_rejects_a_linked_destination_parent(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "public"
            external = base / "external"
            subprocess.run(
                ["git", "init", "--initial-branch=main", str(destination)],
                check=True,
                capture_output=True,
            )
            external.mkdir()
            linked = destination / "redirect"
            try:
                linked.symlink_to(external, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlink unavailable: {error}")
            stale = external / "stale.txt"
            stale.write_text("generated\n", encoding="utf-8")
            receipt = destination / ".git" / "engineering-public-export.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schema": "engineering.public-export-receipt.v2",
                        "files": {"redirect/stale.txt": module._file_digest(stale)},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(module.ExportError):
                module.export_tree(ROOT, destination)

    def test_public_export_rejects_a_broken_leaf_link(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "public"
            subprocess.run(
                ["git", "init", "--initial-branch=main", str(destination)],
                check=True,
                capture_output=True,
            )
            target = destination / "README.md"
            try:
                target.symlink_to(base / "missing.txt")
            except OSError as error:
                self.skipTest(f"file symlink unavailable: {error}")
            with self.assertRaises(module.ExportError):
                module.export_tree(ROOT, destination)

    def test_public_export_rejects_a_hard_linked_leaf(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "public"
            subprocess.run(
                ["git", "init", "--initial-branch=main", str(destination)],
                check=True,
                capture_output=True,
            )
            external = base / "outside.txt"
            external.write_text("keep\n", encoding="utf-8")
            os.link(external, destination / "README.md")
            with self.assertRaises(module.ExportError):
                module.export_tree(ROOT, destination)
            self.assertEqual("keep\n", external.read_text(encoding="utf-8"))

    def test_public_export_rejects_a_hard_linked_receipt(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "public"
            subprocess.run(
                ["git", "init", "--initial-branch=main", str(destination)],
                check=True,
                capture_output=True,
            )
            external = base / "outside.json"
            external.write_text(
                json.dumps({"schema": "engineering.public-export-receipt.v2", "files": {}}),
                encoding="utf-8",
            )
            os.link(external, destination / ".git" / "engineering-public-export.json")
            with self.assertRaises(module.ExportError):
                module.export_tree(ROOT, destination)
            self.assertEqual(
                {"schema": "engineering.public-export-receipt.v2", "files": {}},
                json.loads(external.read_text(encoding="utf-8")),
            )


if __name__ == "__main__":
    unittest.main()
