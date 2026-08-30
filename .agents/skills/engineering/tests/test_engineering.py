import importlib.util
import ast
import contextlib
import hashlib
import inspect
import io
import json
import os
import re
import runpy
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path, PosixPath
from unittest.mock import Mock, patch


SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL = SKILL_DIR / "SKILL.md"
MANIFEST = SKILL_DIR / "manifest.json"
SCENARIOS = SKILL_DIR / "tests" / "scenarios.json"
ENGINEERING_SCRIPT = SKILL_DIR / "scripts" / "engineering.py"
V1_SCRIPT = (
    Path.home()
    / ".codex"
    / "skills"
    / "engineering-traceability"
    / "scripts"
    / "engineering_traceability.py"
)


def load_engineering():
    if not ENGINEERING_SCRIPT.is_file():
        return None
    spec = importlib.util.spec_from_file_location("engineering_v2", ENGINEERING_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


engineering = load_engineering()


def synthetic_owner_private(path: Path) -> None:
    path = Path(path)
    os.chmod(path, 0o700 if path.is_dir() else 0o600)


class CrossPlatformFilesystemTests(unittest.TestCase):
    def test_unittest_terminal_parser_covers_authoritative_summary_variants(self):
        fixtures = {
            "Ran 3 tests in 0.1s\n\nOK\n": {
                "run": 3, "failures": 0, "errors": 0, "skipped": 0,
            },
            "Ran 4 tests in 0.1s\n\nOK (skipped=2)\n": {
                "run": 4, "failures": 0, "errors": 0, "skipped": 2,
            },
            "Ran 5 tests in 0.1s\n\nFAILED (failures=1)\n": {
                "run": 5, "failures": 1, "errors": 0, "skipped": 0,
            },
            "Ran 6 tests in 0.1s\n\nFAILED (errors=2)\n": {
                "run": 6, "failures": 0, "errors": 2, "skipped": 0,
            },
            "Ran 7 tests in 0.1s\n\nFAILED ( skipped = 3 , errors=2, failures = 1 )\n": {
                "run": 7, "failures": 1, "errors": 2, "skipped": 3,
            },
        }
        for log, expected in fixtures.items():
            with self.subTest(log=log):
                self.assertEqual(expected, engineering.parse_unittest_terminal_summary(log))

    def test_unittest_terminal_parser_fails_closed_on_absent_or_conflicting_summary(self):
        invalid = (
            "test output without a terminal summary",
            "Ran 1 test in 0.1s\n",
            (
                "Ran 1 test in 0.1s\n\nOK\n"
                "Ran 2 tests in 0.2s\n\nFAILED (failures=1)\n"
            ),
            "Ran 1 test in 0.1s\n\nFAILED (failures=1, failures=2)\n",
        )
        for log in invalid:
            with self.subTest(log=log):
                with self.assertRaises(engineering.EngineeringError):
                    engineering.parse_unittest_terminal_summary(log)

    def test_unittest_terminal_parser_rejects_nonterminal_or_multiple_summaries(self):
        invalid = (
            "Ran 1 test in 0.1s\n\nOK\ntrailing output\n",
            "Ran 1 test in 0.1s\n\nFAILED (failures=1)\ntrailing output\n",
            "Ran 1 test in 0.1s\n\nOK\nRan 1 test in 0.2s\n\nOK\n",
            "Ran 1 test in 0.1s\n\nOK\nRan 2 tests in 0.2s\n\nFAILED (failures=x)\n",
        )
        for log in invalid:
            with self.subTest(log=log):
                with self.assertRaises(engineering.EngineeringError):
                    engineering.parse_unittest_terminal_summary(log)

    def test_unittest_terminal_parser_rejects_impossible_totals(self):
        invalid = (
            "Ran 1 test in 0.1s\n\nOK (skipped=2)\n",
            "Ran 1 test in 0.1s\n\nFAILED (failures=2)\n",
            "Ran 1 test in 0.1s\n\nFAILED (errors=2)\n",
            "Ran 2 tests in 0.1s\n\nFAILED (failures=1, errors=1, skipped=1)\n",
            "Ran 2 tests in 0.1s\n\nFAILED (failures=-1)\n",
            "Ran 2 tests in 0.1s\n\nFAILED (errors=1, errors=1)\n",
            "Ran 2 tests in 0.1s\n\nOK (failures=0)\n",
            "Ran 2 tests in 0.1s\n\nFAILED (errors=1, skipped=0)\n",
        )
        for log in invalid:
            with self.subTest(log=log):
                with self.assertRaises(engineering.EngineeringError):
                    engineering.parse_unittest_terminal_summary(log)

    @unittest.skipUnless(os.name == "nt", "Windows legacy path budget only")
    def test_isolated_temp_preflight_selects_short_root_and_rolls_back(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g4-") as temporary:
            base = Path(temporary) / "t"
            base.mkdir()
            receipt = engineering.prepare_isolated_temp_root(
                [base],
                run_id="gate-1",
                candidate_root=Path("C:/candidate"),
                test_suffixes=["case/" + "x" * 40],
                max_path=259,
                long_paths_enabled=False,
            )
            root = Path(receipt["root"])
            self.assertTrue(root.is_dir())
            self.assertRegex(root.name, r"^eg-[0-9a-f]{12}$")
            self.assertLessEqual(receipt["worst_case_path_length"], 259)
            self.assertGreaterEqual(
                receipt["worst_case_path_length"],
                len(str(root)) + 1 + engineering.ENGINEERING_TEMP_WORST_CASE_SUFFIX_LENGTH,
            )
            self.assertEqual(
                {"applied": True, "verified": True, "contract": "owner-private-directory-v1"},
                receipt["owner_private_acl"],
            )
            (root / "owned-payload.txt").write_text("temporary\n", encoding="utf-8")
            cleanup = engineering.rollback_isolated_temp_root(receipt)
            self.assertEqual("path-unverified", cleanup["state"])
            self.assertFalse(cleanup["post_removal_verified"])
            self.assertEqual(
                "original-object-removed", cleanup["original_object_disposition"]
            )
            self.assertEqual(
                "absent-at-observation", cleanup["pathname_observation"]["state"]
            )
            self.assertTrue(cleanup["owner_private_verified_before_delete"])
            self.assertEqual(receipt["root_identity"], cleanup["root_identity"])
            self.assertFalse(root.exists())

    @unittest.skipUnless(os.name == "nt", "Windows legacy path budget only")
    def test_isolated_temp_preflight_rejects_a_caller_understated_suffix_budget(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g4-") as temporary:
            base = Path(temporary) / "t"
            base.mkdir()
            required = (
                len(str(base / ("eg-" + "x" * 12)))
                + 1
                + engineering.ENGINEERING_TEMP_WORST_CASE_SUFFIX_LENGTH
            )
            with self.assertRaises(engineering.EngineeringError):
                engineering.prepare_isolated_temp_root(
                    [base], "understated", Path("C:/candidate"), ["x"],
                    required - 1, False,
                )

    @unittest.skipUnless(os.name == "nt", "Windows owner-private TEMP contract only")
    def test_isolated_temp_root_is_owner_private_before_marker_or_use(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g5-") as temporary:
            base = Path(temporary)
            events = []

            def enforce(path):
                events.append(("enforce", Path(path), (Path(path) / ".engineering-temp-owner.json").exists()))

            def verify(path, *, directory):
                events.append(("verify", Path(path), (Path(path) / ".engineering-temp-owner.json").exists()))
                self.assertTrue(directory)

            with (
                patch.object(engineering, "_enforce_owner_private", side_effect=enforce),
                patch.object(engineering, "_verify_owner_private", side_effect=verify),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "acl-order", Path("C:/candidate"), ["case"], 259, False
                )
                root = Path(receipt["root"])
                self.assertEqual(["enforce", "verify"], [item[0] for item in events])
                self.assertEqual([False, False], [item[2] for item in events])
                engineering.rollback_isolated_temp_root(receipt)
            self.assertFalse(root.exists())

    @unittest.skipUnless(os.name == "nt", "Windows owner-private TEMP contract only")
    def test_isolated_temp_acl_failure_rolls_back_before_use(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g5-") as temporary:
            base = Path(temporary)
            root = base / ("eg-" + hashlib.sha256(b"acl-failure").hexdigest()[:12])
            with (
                patch.object(
                    engineering,
                    "_enforce_owner_private",
                    side_effect=engineering.EngineeringError("synthetic ACL failure"),
                ),
                self.assertRaises(engineering.EngineeringError),
            ):
                engineering.prepare_isolated_temp_root(
                    [base], "acl-failure", Path("C:/candidate"), ["case"], 259, False
                )
            self.assertFalse(root.exists())

    @unittest.skipUnless(os.name == "nt", "Windows owner-private TEMP contract only")
    def test_isolated_temp_acl_spoof_verification_rolls_back_before_use(self):
        for index, defect in enumerate(
            ("spoofed principal/tool/runtime", "inherited unauthorized ACE", "widened ACE")
        ):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory(
                dir=r"C:\Temp", prefix="g5-"
            ) as temporary:
                base = Path(temporary)
                run_id = f"acl-spoof-{index}"
                root = base / (
                    "eg-" + hashlib.sha256(run_id.encode("ascii")).hexdigest()[:12]
                )
                with (
                    patch.object(engineering, "_enforce_owner_private", return_value=None),
                    patch.object(
                        engineering,
                        "_verify_owner_private",
                        side_effect=engineering.EngineeringError(f"synthetic {defect}"),
                    ),
                    self.assertRaises(engineering.EngineeringError),
                ):
                    engineering.prepare_isolated_temp_root(
                        [base], run_id, Path("C:/candidate"), ["case"], 259, False
                    )
                self.assertFalse(root.exists())

    @unittest.skipUnless(os.name == "nt", "Windows owner-private TEMP contract only")
    def test_isolated_temp_post_create_replacement_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g5-") as temporary:
            base = Path(temporary)
            root = base / ("eg-" + hashlib.sha256(b"replacement").hexdigest()[:12])
            retained = base / "retained-original"

            def substitute(path, *, directory):
                self.assertTrue(directory)
                Path(path).rename(retained)
                Path(path).mkdir()

            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", side_effect=substitute),
                self.assertRaises(engineering.EngineeringError),
            ):
                engineering.prepare_isolated_temp_root(
                    [base], "replacement", Path("C:/candidate"), ["case"], 259, False
                )
            self.assertTrue(root.is_dir(), "substituted target must not be deleted")
            self.assertTrue(retained.is_dir(), "original target must remain recoverable")
            root.rmdir()
            retained.rmdir()

    def test_isolated_temp_budget_covers_preserved_suffix_and_margin(self):
        self.assertEqual(202, engineering.PRESERVED_WINDOWS_TEMP_SUFFIX_LENGTH)
        self.assertGreaterEqual(engineering.ENGINEERING_TEMP_PATH_SAFETY_MARGIN, 8)
        self.assertGreaterEqual(
            engineering.ENGINEERING_TEMP_WORST_CASE_SUFFIX_LENGTH,
            engineering.PRESERVED_WINDOWS_TEMP_SUFFIX_LENGTH
            + engineering.ENGINEERING_TEMP_PATH_SAFETY_MARGIN,
        )

    @unittest.skipUnless(os.name == "nt", "Windows owner-private TEMP contract only")
    def test_isolated_temp_rollback_rejects_marker_ownership_mismatch(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g5-") as temporary:
            base = Path(temporary)
            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", return_value=None),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "marker-mismatch", Path("C:/candidate"), ["case"], 259, False
                )
                with self.assertRaises(engineering.EngineeringError):
                    engineering.rollback_isolated_temp_root(
                        {**receipt, "marker_digest": "sha256:" + "0" * 64}
                    )
                self.assertTrue(Path(receipt["root"]).is_dir())
                engineering.rollback_isolated_temp_root(receipt)

    @unittest.skipUnless(os.name == "nt", "Windows rollback identity contract only")
    def test_isolated_temp_rollback_rejects_post_traversal_root_replacement(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g6-") as temporary:
            base = Path(temporary)
            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", return_value=None),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "rollback-replace", Path("C:/candidate"), ["case"], 259, False
                )
            root = Path(receipt["root"])
            retained = base / "retained-original"
            marker_bytes = (root / ".engineering-temp-owner.json").read_bytes()
            original_rglob = Path.rglob

            def substitute_after_traversal(path, pattern):
                yield from original_rglob(path, pattern)
                root.rename(retained)
                root.mkdir()
                (root / ".engineering-temp-owner.json").write_bytes(marker_bytes)

            with (
                patch.object(engineering, "_verify_owner_private", return_value=None),
                patch.object(Path, "rglob", new=substitute_after_traversal),
                self.assertRaisesRegex(engineering.EngineeringError, "state=identity-changed"),
            ):
                engineering.rollback_isolated_temp_root(receipt)
            self.assertTrue(root.is_dir(), "replacement must survive rollback rejection")
            self.assertTrue(retained.is_dir(), "original must remain retained")
            shutil.rmtree(root)
            shutil.rmtree(retained)

    @unittest.skipUnless(os.name == "nt", "Windows rollback identity contract only")
    def test_isolated_temp_rollback_rejects_post_traversal_marker_or_acl_change(self):
        for defect in ("marker", "acl"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory(
                dir=r"C:\Temp", prefix="g6-"
            ) as temporary:
                base = Path(temporary)
                with (
                    patch.object(engineering, "_enforce_owner_private", return_value=None),
                    patch.object(engineering, "_verify_owner_private", return_value=None),
                ):
                    receipt = engineering.prepare_isolated_temp_root(
                        [base], f"rollback-{defect}", Path("C:/candidate"), ["case"], 259, False
                    )
                root = Path(receipt["root"])
                traversed = {"value": False}
                original_rglob = Path.rglob

                def change_after_traversal(path, pattern):
                    yield from original_rglob(path, pattern)
                    traversed["value"] = True
                    if defect == "marker":
                        (root / ".engineering-temp-owner.json").write_text(
                            "spoofed\n", encoding="utf-8"
                        )

                def verify(path, *, directory):
                    self.assertTrue(directory)
                    if defect == "acl" and traversed["value"]:
                        raise engineering.EngineeringError("synthetic ACL binding changed")

                expected = "state=marker-changed" if defect == "marker" else "state=acl-changed"
                with (
                    patch.object(engineering, "_verify_owner_private", side_effect=verify),
                    patch.object(Path, "rglob", new=change_after_traversal),
                    self.assertRaisesRegex(engineering.EngineeringError, expected),
                ):
                    engineering.rollback_isolated_temp_root(receipt)
                self.assertTrue(root.is_dir())
                shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows rollback identity contract only")
    def test_isolated_temp_rollback_rejects_post_traversal_missing_or_reparse_root(self):
        for defect in ("missing", "reparse"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory(
                dir=r"C:\Temp", prefix="g6-"
            ) as temporary:
                base = Path(temporary)
                with (
                    patch.object(engineering, "_enforce_owner_private", return_value=None),
                    patch.object(engineering, "_verify_owner_private", return_value=None),
                ):
                    receipt = engineering.prepare_isolated_temp_root(
                        [base], f"rollback-{defect}", Path("C:/candidate"), ["case"], 259, False
                    )
                root = Path(receipt["root"])
                retained = base / "retained-original"
                injected = {"value": False}
                original_rglob = Path.rglob
                original_reparse = engineering._is_reparse_point

                def change_after_traversal(path, pattern):
                    yield from original_rglob(path, pattern)
                    injected["value"] = True
                    if defect == "missing":
                        root.rename(retained)

                def reparse_after_traversal(path):
                    if defect == "reparse" and injected["value"] and Path(path) == root:
                        return True
                    return original_reparse(path)

                with (
                    patch.object(engineering, "_verify_owner_private", return_value=None),
                    patch.object(Path, "rglob", new=change_after_traversal),
                    patch.object(engineering, "_is_reparse_point", side_effect=reparse_after_traversal),
                    self.assertRaisesRegex(engineering.EngineeringError, f"state={defect}"),
                ):
                    engineering.rollback_isolated_temp_root(receipt)
                if defect == "missing":
                    self.assertFalse(root.exists())
                    self.assertTrue(retained.is_dir())
                    shutil.rmtree(retained)
                else:
                    self.assertTrue(root.is_dir())
                    shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows rollback identity contract only")
    def test_isolated_temp_rollback_rejects_post_traversal_identity_mismatch_or_unknown(self):
        for defect in ("identity-changed", "unknown"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory(
                dir=r"C:\Temp", prefix="g6-"
            ) as temporary:
                base = Path(temporary)
                with (
                    patch.object(engineering, "_enforce_owner_private", return_value=None),
                    patch.object(engineering, "_verify_owner_private", return_value=None),
                ):
                    receipt = engineering.prepare_isolated_temp_root(
                        [base], f"rollback-{defect}", Path("C:/candidate"), ["case"], 259, False
                    )
                root = Path(receipt["root"])
                injected = {"value": False}
                original_rglob = Path.rglob
                original_identity = engineering._temp_root_identity

                def inject_after_traversal(path, pattern):
                    yield from original_rglob(path, pattern)
                    injected["value"] = True

                def changed_identity(path):
                    if injected["value"]:
                        if defect == "unknown":
                            raise OSError("synthetic unavailable identity")
                        return {"device": -1, "inode": -1}
                    return original_identity(path)

                with (
                    patch.object(engineering, "_verify_owner_private", return_value=None),
                    patch.object(Path, "rglob", new=inject_after_traversal),
                    patch.object(engineering, "_temp_root_identity", side_effect=changed_identity),
                    self.assertRaisesRegex(engineering.EngineeringError, f"state={defect}"),
                ):
                    engineering.rollback_isolated_temp_root(receipt)
                self.assertTrue(root.is_dir())
                shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows rollback identity contract only")
    def test_isolated_temp_rollback_reports_removed_only_for_exact_unchanged_root(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g6-") as temporary:
            base = Path(temporary)
            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", return_value=None),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "rollback-control", Path("C:/candidate"), ["case"], 259, False
                )
                cleanup = engineering.rollback_isolated_temp_root(receipt)
            self.assertEqual("path-unverified", cleanup["state"])
            self.assertFalse(cleanup["post_removal_verified"])
            self.assertEqual("original-object-removed", cleanup["original_object_disposition"])
            self.assertEqual(
                "absent-at-observation", cleanup["pathname_observation"]["state"]
            )
            self.assertEqual(receipt["root_identity"], cleanup["removed_identity"])
            self.assertEqual("windows-handle-disposition", cleanup["removal_primitive"])
            self.assertFalse(Path(receipt["root"]).exists())

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_rollback_blocks_exact_post_validator_auditor_sequence(self):
        for attempt in range(3):
            with self.subTest(attempt=attempt), tempfile.TemporaryDirectory(
                dir=r"C:\Temp", prefix="g7-"
            ) as temporary:
                base = Path(temporary)
                with (
                    patch.object(engineering, "_enforce_owner_private", return_value=None),
                    patch.object(engineering, "_verify_owner_private", return_value=None),
                ):
                    receipt = engineering.prepare_isolated_temp_root(
                        [base], f"auditor-sequence-{attempt}", Path("C:/candidate"),
                        ["case"], 259, False,
                    )
                root = Path(receipt["root"])
                retained = base / "retained-original"
                real_validate = engineering._validate_isolated_temp_root_before_delete

                def substitute_after_validation(root_arg, base_arg, receipt_arg):
                    validated = real_validate(root_arg, base_arg, receipt_arg)
                    root.rename(retained)
                    root.mkdir()
                    (root / "substitute-sentinel.txt").write_text(
                        "must survive\n", encoding="utf-8"
                    )
                    return validated

                with (
                    patch.object(engineering, "_verify_owner_private", return_value=None),
                    patch.object(
                        engineering,
                        "_validate_isolated_temp_root_before_delete",
                        side_effect=substitute_after_validation,
                    ),
                    self.assertRaises(OSError),
                ):
                    engineering.rollback_isolated_temp_root(receipt)
                self.assertTrue(root.is_dir(), "locked original must remain after blocked injection")
                self.assertFalse(retained.exists())
                self.assertFalse((root / "substitute-sentinel.txt").exists())
                shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_rollback_never_deletes_matching_marker_replacement(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g7-") as temporary:
            base = Path(temporary)
            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", return_value=None),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "matching-replacement", Path("C:/candidate"), ["case"], 259, False
                )
            root = Path(receipt["root"])
            retained = base / "retained-original"
            marker_bytes = (root / ".engineering-temp-owner.json").read_bytes()
            root.rename(retained)
            root.mkdir()
            (root / ".engineering-temp-owner.json").write_bytes(marker_bytes)
            with (
                patch.object(engineering, "_verify_owner_private", return_value=None),
                self.assertRaisesRegex(engineering.EngineeringError, "state=identity-changed"),
            ):
                engineering.rollback_isolated_temp_root(receipt)
            self.assertTrue(root.is_dir())
            self.assertTrue(retained.is_dir())
            shutil.rmtree(root)
            shutil.rmtree(retained)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_rollback_retains_renamed_original_and_reparse_replacement(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g7-") as temporary:
            base = Path(temporary)
            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", return_value=None),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "renamed-original", Path("C:/candidate"), ["case"], 259, False
                )
            root = Path(receipt["root"])
            retained = base / "retained-original"
            root.rename(retained)
            with self.assertRaisesRegex(engineering.EngineeringError, "state=missing"):
                engineering.rollback_isolated_temp_root(receipt)
            self.assertTrue(retained.is_dir())
            root.mkdir()
            with (
                patch.object(engineering, "_is_reparse_point", side_effect=lambda path: Path(path) == root),
                self.assertRaisesRegex(engineering.EngineeringError, "state=reparse"),
            ):
                engineering.rollback_isolated_temp_root(receipt)
            self.assertTrue(root.is_dir())
            shutil.rmtree(root)
            shutil.rmtree(retained)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_rollback_fails_closed_when_handle_proof_is_unavailable(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g7-") as temporary:
            base = Path(temporary)
            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", return_value=None),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "missing-handle-proof", Path("C:/candidate"), ["case"], 259, False
                )
            root = Path(receipt["root"])
            with (
                patch.object(engineering, "_verify_owner_private", return_value=None),
                patch.object(
                    engineering,
                    "_open_windows_directory_delete_handle",
                    side_effect=engineering.EngineeringError("synthetic unavailable handle proof"),
                ),
                self.assertRaisesRegex(engineering.EngineeringError, "unavailable handle proof"),
            ):
                engineering.rollback_isolated_temp_root(receipt)
            self.assertTrue(root.is_dir())
            shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_rollback_fails_closed_when_handle_identity_changes(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g7-") as temporary:
            base = Path(temporary)
            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", return_value=None),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "changed-handle-proof", Path("C:/candidate"), ["case"], 259, False
                )
            root = Path(receipt["root"])
            calls = {"count": 0}
            original_identity = engineering._windows_directory_handle_identity

            def identity_changes(handle):
                calls["count"] += 1
                identity = original_identity(handle)
                if calls["count"] > 1:
                    return {**identity, "file_index": identity["file_index"] + 1}
                return identity

            with (
                patch.object(engineering, "_verify_owner_private", return_value=None),
                patch.object(
                    engineering,
                    "_windows_directory_handle_identity",
                    side_effect=identity_changes,
                ),
                self.assertRaisesRegex(engineering.EngineeringError, "state=identity-changed"),
            ):
                engineering.rollback_isolated_temp_root(receipt)
            self.assertTrue(root.is_dir())
            shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_rollback_reports_post_close_replacement_truthfully(self):
        for attempt in range(3):
            with self.subTest(attempt=attempt), tempfile.TemporaryDirectory(
                dir=r"C:\Temp", prefix="g8-"
            ) as temporary:
                base = Path(temporary)
                with (
                    patch.object(engineering, "_enforce_owner_private", return_value=None),
                    patch.object(engineering, "_verify_owner_private", return_value=None),
                ):
                    receipt = engineering.prepare_isolated_temp_root(
                        [base], f"post-close-replacement-{attempt}", Path("C:/candidate"),
                        ["case"], 259, False,
                    )
                root = Path(receipt["root"])
                marker_bytes = (root / ".engineering-temp-owner.json").read_bytes()
                real_close = engineering._close_windows_handle

                def close_then_replace(handle):
                    real_close(handle)
                    root.mkdir()
                    (root / ".engineering-temp-owner.json").write_bytes(marker_bytes)
                    (root / "replacement-sentinel.txt").write_text(
                        "replacement must survive\n", encoding="utf-8"
                    )

                with (
                    patch.object(engineering, "_verify_owner_private", return_value=None),
                    patch.object(
                        engineering, "_close_windows_handle", side_effect=close_then_replace
                    ),
                ):
                    cleanup = engineering.rollback_isolated_temp_root(receipt)
                self.assertEqual("path-unverified", cleanup["state"])
                self.assertEqual(
                    "identity-changed", cleanup["pathname_observation"]["state"]
                )
                self.assertEqual(
                    "original-object-removed", cleanup["original_object_disposition"]
                )
                self.assertFalse(cleanup["post_removal_verified"])
                self.assertTrue((root / "replacement-sentinel.txt").is_file())
                shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_rollback_reports_post_close_reparse_replacement_truthfully(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g8-") as temporary:
            base = Path(temporary)
            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", return_value=None),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "post-close-reparse", Path("C:/candidate"), ["case"], 259, False
                )
            root = Path(receipt["root"])
            real_close = engineering._close_windows_handle
            injected = {"value": False}
            real_reparse = engineering._is_reparse_point

            def close_then_replace(handle):
                real_close(handle)
                root.mkdir()
                (root / "replacement-sentinel.txt").write_text(
                    "replacement must survive\n", encoding="utf-8"
                )
                injected["value"] = True

            def post_close_reparse(path):
                return (injected["value"] and Path(path) == root) or real_reparse(path)

            with (
                patch.object(engineering, "_verify_owner_private", return_value=None),
                patch.object(
                    engineering, "_close_windows_handle", side_effect=close_then_replace
                ),
                patch.object(
                    engineering, "_is_reparse_point", side_effect=post_close_reparse
                ),
            ):
                cleanup = engineering.rollback_isolated_temp_root(receipt)
            self.assertEqual("path-unverified", cleanup["state"])
            self.assertEqual("reparse-present", cleanup["pathname_observation"]["state"])
            self.assertFalse(cleanup["post_removal_verified"])
            self.assertTrue((root / "replacement-sentinel.txt").is_file())
            shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_rollback_reports_unknown_post_close_identity_truthfully(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g8-") as temporary:
            base = Path(temporary)
            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", return_value=None),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "post-close-unknown", Path("C:/candidate"), ["case"], 259, False
                )
            root = Path(receipt["root"])
            real_close = engineering._close_windows_handle
            real_identity = engineering._temp_root_identity
            injected = {"value": False}

            def close_then_replace(handle):
                real_close(handle)
                root.mkdir()
                injected["value"] = True

            def unavailable_identity(path):
                if injected["value"] and Path(path) == root:
                    raise OSError("synthetic post-close identity unavailable")
                return real_identity(path)

            with (
                patch.object(engineering, "_verify_owner_private", return_value=None),
                patch.object(
                    engineering, "_close_windows_handle", side_effect=close_then_replace
                ),
                patch.object(
                    engineering, "_temp_root_identity", side_effect=unavailable_identity
                ),
            ):
                cleanup = engineering.rollback_isolated_temp_root(receipt)
            self.assertEqual("path-unverified", cleanup["state"])
            self.assertEqual("unknown", cleanup["pathname_observation"]["state"])
            self.assertEqual("unknown", cleanup["original_object_disposition"])
            self.assertFalse(cleanup["post_removal_verified"])
            self.assertTrue(root.is_dir())
            shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_rollback_detects_recreation_during_absence_postcondition(self):
        with tempfile.TemporaryDirectory(dir=r"C:\Temp", prefix="g8-") as temporary:
            base = Path(temporary)
            with (
                patch.object(engineering, "_enforce_owner_private", return_value=None),
                patch.object(engineering, "_verify_owner_private", return_value=None),
            ):
                receipt = engineering.prepare_isolated_temp_root(
                    [base], "post-close-during-absence", Path("C:/candidate"),
                    ["case"], 259, False,
                )
            root = Path(receipt["root"])
            real_close = engineering._close_windows_handle
            real_identity = engineering._temp_root_identity
            closed = {"value": False}
            injected = {"value": False}

            def close_then_arm(handle):
                real_close(handle)
                closed["value"] = True

            def recreate_during_absence_check(path):
                try:
                    return real_identity(path)
                except FileNotFoundError:
                    if closed["value"] and not injected["value"]:
                        root.mkdir()
                        (root / "replacement-sentinel.txt").write_text(
                            "replacement must survive\n", encoding="utf-8"
                        )
                        injected["value"] = True
                    raise

            with (
                patch.object(engineering, "_verify_owner_private", return_value=None),
                patch.object(
                    engineering, "_close_windows_handle", side_effect=close_then_arm
                ),
                patch.object(
                    engineering, "_temp_root_identity", side_effect=recreate_during_absence_check
                ),
            ):
                cleanup = engineering.rollback_isolated_temp_root(receipt)
            self.assertEqual("path-unverified", cleanup["state"])
            self.assertEqual(
                "identity-changed", cleanup["pathname_observation"]["state"]
            )
            self.assertFalse(cleanup["post_removal_verified"])
            self.assertTrue((root / "replacement-sentinel.txt").is_file())
            shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_post_close_final_observation_never_claims_path_removed(self):
        for attempt in range(3):
            with self.subTest(attempt=attempt), tempfile.TemporaryDirectory(
                dir=r"C:\Temp", prefix="g9-"
            ) as temporary:
                root = Path(temporary) / "target"
                calls = {"count": 0}

                def recreate_after_final_observation(path):
                    calls["count"] += 1
                    if calls["count"] == 2:
                        root.mkdir()
                        (root / "replacement-sentinel.txt").write_text(
                            "replacement must survive\n", encoding="utf-8"
                        )
                    raise FileNotFoundError(str(path))

                with patch.object(
                    engineering,
                    "_temp_root_identity",
                    side_effect=recreate_after_final_observation,
                ):
                    result = engineering._inspect_isolated_temp_root_after_handle_close(
                        root, {"root_identity": {"device": 1, "inode": 1}}
                    )
                self.assertEqual("path-unverified", result["state"])
                self.assertFalse(result["post_removal_verified"])
                self.assertEqual(
                    "original-object-removed", result["original_object_disposition"]
                )
                self.assertEqual(
                    "absent-at-observation", result["pathname_observation"]["state"]
                )
                self.assertTrue((root / "replacement-sentinel.txt").is_file())
                shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_recreation_after_observer_return_remains_path_unverified(self):
        for attempt in range(3):
            with self.subTest(attempt=attempt), tempfile.TemporaryDirectory(
                dir=r"C:\Temp", prefix="g9-"
            ) as temporary:
                root = Path(temporary) / "target"
                real_observe = engineering._observe_isolated_temp_root_after_handle_close

                def observe_then_replace(root_arg, receipt_arg):
                    observation = real_observe(root_arg, receipt_arg)
                    root.mkdir()
                    (root / "replacement-sentinel.txt").write_text(
                        "replacement must survive\n", encoding="utf-8"
                    )
                    return observation

                with patch.object(
                    engineering,
                    "_observe_isolated_temp_root_after_handle_close",
                    side_effect=observe_then_replace,
                ):
                    result = engineering._inspect_isolated_temp_root_after_handle_close(
                        root, {"root_identity": {"device": 1, "inode": 1}}
                    )
                self.assertEqual("path-unverified", result["state"])
                self.assertFalse(result["post_removal_verified"])
                self.assertEqual(
                    "absent-at-observation", result["pathname_observation"]["state"]
                )
                self.assertRegex(
                    result["pathname_observation"]["observed_at"], r"Z$"
                )
                self.assertTrue((root / "replacement-sentinel.txt").is_file())
                shutil.rmtree(root)

    @unittest.skipUnless(os.name == "nt", "Windows identity-bound deletion only")
    def test_isolated_temp_no_finite_absence_observation_claims_path_removed(self):
        for inject_after in (1, 2):
            with self.subTest(inject_after=inject_after), tempfile.TemporaryDirectory(
                dir=r"C:\Temp", prefix="g9-"
            ) as temporary:
                root = Path(temporary) / "target"
                real_identity = engineering._temp_root_identity
                calls = {"count": 0}

                def recreate_at_observation(path):
                    calls["count"] += 1
                    try:
                        return real_identity(path)
                    except FileNotFoundError:
                        if calls["count"] == inject_after:
                            root.mkdir()
                            (root / "replacement-sentinel.txt").write_text(
                                "replacement must survive\n", encoding="utf-8"
                            )
                        raise

                with patch.object(
                    engineering, "_temp_root_identity", side_effect=recreate_at_observation
                ):
                    result = engineering._inspect_isolated_temp_root_after_handle_close(
                        root, {"root_identity": {"device": 1, "inode": 1}}
                    )
                self.assertEqual("path-unverified", result["state"])
                self.assertFalse(result["post_removal_verified"])
                self.assertTrue((root / "replacement-sentinel.txt").is_file())
                shutil.rmtree(root)

    def test_isolated_temp_result_keeps_unknown_object_disposition_separate(self):
        observation = {
            "state": "unknown",
            "observed_at": "2026-08-29T00:00:00Z",
            "identity": None,
        }
        result = engineering._publish_isolated_temp_cleanup_result(
            "unknown", observation
        )
        self.assertEqual("path-unverified", result["state"])
        self.assertFalse(result["post_removal_verified"])
        self.assertEqual("unknown", result["original_object_disposition"])
        self.assertEqual(observation, result["pathname_observation"])

    def test_isolated_temp_pathname_observation_contract_matches_runtime_exactly(self):
        expected = (
            "absent-at-observation",
            "identity-changed",
            "original-present",
            "reparse-present",
            "unknown",
        )
        self.assertEqual(
            expected, engineering.ISOLATED_TEMP_PATHNAME_OBSERVATION_STATES
        )
        for state in expected:
            with self.subTest(state=state):
                observation = {
                    "state": state,
                    "observed_at": "2026-08-29T00:00:00Z",
                    "identity": None,
                }
                result = engineering._publish_isolated_temp_cleanup_result(
                    "unknown", observation
                )
                self.assertEqual(observation, result["pathname_observation"])
        with self.assertRaises(engineering.EngineeringError):
            engineering._publish_isolated_temp_cleanup_result(
                "unknown",
                {
                    "state": "replacement-present",
                    "observed_at": "2026-08-29T00:00:00Z",
                    "identity": None,
                },
            )

    def test_isolated_temp_preflight_rejects_unsafe_bases_budgets_and_collisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            with self.assertRaises(engineering.EngineeringError):
                engineering.prepare_isolated_temp_root(
                    [missing], "gate", Path("C:/candidate"), ["case"], 120, False
                )
            base = Path(temporary) / "base"
            base.mkdir()
            with self.assertRaises(engineering.EngineeringError):
                engineering.prepare_isolated_temp_root(
                    [base], "gate", Path("C:/" + "c" * 100), ["x" * 100], 80, False
                )
            collision = base / (
                "eg-" + hashlib.sha256(b"gate").hexdigest()[:12]
            )
            collision.mkdir()
            with self.assertRaises(engineering.EngineeringError):
                engineering.prepare_isolated_temp_root(
                    [base], "gate", Path("C:/candidate"), ["case"], 240, False
                )
            with self.assertRaises(engineering.EngineeringError):
                engineering.prepare_isolated_temp_root(
                    [base], "gate-2", Path("C:/candidate"), ["../escape"], 240, False
                )
            with (
                patch.object(engineering, "_is_reparse_point", return_value=True),
                self.assertRaises(engineering.EngineeringError),
            ):
                engineering.prepare_isolated_temp_root(
                    [base], "gate-3", Path("C:/candidate"), ["case"], 240, False
                )

    def test_checkpoint_diagnostic_is_read_only_and_evidence_classified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            checkpoint.write_text('{"freshness":"stale"}\n', encoding="utf-8")
            before = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            snapshot = engineering.capture_checkpoint_diagnostic(
                paths={"checkpoint": checkpoint, "catalogue": root / "missing.json"},
                environment={"TEMP": str(root), "TMP": str(root)},
                processes=[{"pid": 11, "role": "consumer", "started_at": 2}],
                observations={"path_error": True, "longest_path": 272, "path_limit": 259},
            )
            self.assertEqual(before, hashlib.sha256(checkpoint.read_bytes()).hexdigest())
            self.assertEqual("PATH_ENVIRONMENT", snapshot["classification"])
            self.assertEqual("missing", snapshot["paths"]["catalogue"]["state"])

    def test_checkpoint_diagnostic_never_infers_a_cause_without_complete_evidence(self):
        cases = (
            ({}, "UNKNOWN"),
            (
                {
                    "isolated_reproduction": True,
                    "expected_mismatch": True,
                    "clean_precondition": True,
                },
                "CODE_DEFECT",
            ),
            ({"shared_identity_conflict": True, "overlap_proven": True}, "PROCESS_SHARED_STATE_INTERFERENCE"),
        )
        for observations, expected in cases:
            with self.subTest(expected=expected):
                result = engineering.capture_checkpoint_diagnostic(
                    paths={}, environment={}, processes=[], observations=observations
                )
                self.assertEqual(expected, result["classification"])

    def test_posix_ignores_windows_reparse_attributes(self):
        class OrdinaryPath:
            def is_symlink(self):
                return False

            def lstat(self):
                return type(
                    "StatResult",
                    (),
                    {"st_file_attributes": getattr(engineering.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)},
                )()

        with patch.object(engineering.os, "name", "posix"):
            self.assertFalse(engineering._is_reparse_point(OrdinaryPath()))

    def test_interpreter_alias_is_validated_after_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            alias = Path(temporary) / "python-alias"
            try:
                os.symlink(sys.executable, alias)
            except OSError:
                self.skipTest("test environment cannot create interpreter aliases")

            identity = engineering._interpreter_identity(Path(temporary).resolve(), alias)

        self.assertEqual(str(Path(sys.executable).resolve()), identity["path"])

    def test_fake_graphify_fixture_uses_a_copied_interpreter(self):
        """The Linux fixture must survive canonical interpreter resolution."""
        source = inspect.getsource(
            Task2ContractTests.start_fake_graphify_interpreter
        )
        self.assertIn('"--copies"', source)

    @unittest.skipUnless(os.name == "nt", "Windows ACL transport only")
    def test_windows_owner_private_directory_is_idempotent_for_task_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller = Path(temporary) / "controller"
            controller.mkdir()
            try:
                engineering._windows_owner_private(controller, enforce=True)
            except engineering.EngineeringError as error:
                self.skipTest(
                    "Windows host cannot establish the owner-private ACL required "
                    f"by the controller: {error}"
                )
            engineering._windows_owner_private(controller, enforce=True)
            engineering._verify_owner_private(controller, directory=True)


class SkillShapeTests(unittest.TestCase):
    def test_skill_is_engineering_and_human_readable(self):
        self.assertTrue(SKILL.exists(), "SKILL.md must exist")
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("name: engineering", text)
        self.assertIn("What Engineering does", text)
        self.assertIn("What always needs approval", text)
        self.assertNotIn("PRIVATE_PROJECT_ALPHA", text)
        self.assertNotIn("ORG_INTERNAL_NAME", text)

    def test_manifest_pins_graphify(self):
        self.assertTrue(MANIFEST.exists(), "manifest.json must exist")
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual("0.9.5", manifest["graphify"]["version"])
        self.assertEqual(
            "d89ec68af95e0cad801b56d88df383991e659823",
            manifest["graphify"]["commit"],
        )

    def test_skill_explains_local_first_operation_and_performance(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())
        for required in (
            "local-first",
            "Graphify supplies the base graph",
            "deterministic Engineering overlay",
            "Same-machine worktrees share the Git-common local checkpoint catalogue",
            "Separate machines recreate their own evidence",
            "Enterprise graph sharing is an inactive opt-in",
            "cold start",
            "incremental change",
            "cache hit",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_controller_prohibits_global_graphs_and_live_hook_changes(self):
        contract = " ".join(
            (SKILL_DIR / "references" / "controller-contract.md")
            .read_text(encoding="utf-8")
            .split()
        )
        for required in (
            "Graphify `global`",
            "Graphify `merge-graphs`",
            "canonical umbrella graph",
            "separate explicit authorization",
            "Ordinary task authorization is insufficient",
        ):
            with self.subTest(required=required):
                self.assertIn(required, contract)

    def test_skill_explains_setup_storage_maintenance_and_install_boundaries(self):
        skill = " ".join(SKILL.read_text(encoding="utf-8").split())
        contract = " ".join(
            (SKILL_DIR / "references" / "controller-contract.md")
            .read_text(encoding="utf-8")
            .split()
        )
        for required in (
            "Setup is always a preview first",
            "Installing or upgrading Graphify is a separate approval",
            "Maintenance is one foreground pass",
            "Outcome:",
            "references/controller-contract.md",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill)
        for required in (
            "controller-private",
            "credential-reduced environment",
            "Graphify is exactly version",
        ):
            with self.subTest(required=required):
                self.assertIn(required, contract)

    def test_authority_docs_mark_the_candidate_git_anchor_as_superseded(self):
        root = Path(__file__).resolve().parents[4]
        readme = (root / "README.md").read_text(encoding="utf-8")
        authority = (
            root / "docs" / "specs" / "engineering-v2.2.4-authority-persistence.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("live canonical remote default", readme)
        self.assertIn("host-owned", readme)
        self.assertNotIn("allowed signer is pinned in the governed repository", authority)
        self.assertIn("Superseded trust transport", authority)
        self.assertIn("outside candidate Git", authority)

    def test_portable_policy_and_scenarios_are_executable_contracts(self):
        scenario_payload = json.loads(SCENARIOS.read_text(encoding="utf-8"))
        scenarios = {
            item["id"]: item
            for item in scenario_payload["scenarios"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for identifier in (
            "seed-feedback-scope",
            "traceability-debt-maintenance",
            "outcome-survival",
        ):
            with self.subTest(identifier=identifier):
                self.assertIn(identifier, scenarios)
                self.assertTrue(scenarios[identifier]["must"])
                self.assertTrue(scenarios[identifier]["must_not"])
        behavior = {
            "seed-feedback-scope": (
                Task5ContractTests,
                ("test_legacy_material_scope_handoff_remains_readable_but_owner_intent_unknown",),
            ),
            "traceability-debt-maintenance": (
                Task6ContractTests,
                (
                    "test_unrelated_blocked_maintenance_is_advisory_even_when_in_scope",
                    "test_queued_maintenance_serializes_shared_state_without_broad_authority",
                    "test_traceability_debt_scenario_executes_controller_blocking_matrix",
                    "test_required_current_contract_maintenance_blocks_preparation",
                    "test_unsafe_checkpoint_maintenance_blocks_preparation",
                ),
            ),
            "outcome-survival": (
                Task5ContractTests,
                (
                    "test_material_replacement_rejects_candidate_local_success_without_equivalence",
                    "test_outcome_survival_lists_each_missing_baseline_mapping",
                    "test_unmanaged_material_redesign_is_advisory_and_never_accepted",
                    "test_managed_material_redesign_without_owner_intent_blocks_with_external_boundary",
                    "test_legacy_material_scope_handoff_remains_readable_but_owner_intent_unknown",
                ),
            ),
        }
        for identifier, (owner, methods) in behavior.items():
            for method in methods:
                with self.subTest(identifier=identifier, method=method):
                    self.assertTrue(callable(getattr(owner, method, None)))

        distributable = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                SKILL,
                SKILL_DIR / "references" / "controller-contract.md",
                Path(__file__).resolve().parents[4] / "README.md",
                Path(__file__).resolve().parents[4] / "docs" / "specs" / "engineering-v2.2.3-design.md",
            )
        )
        self.assertRegex(distributable, r"requested.{0,40}actual.{0,40}fallback")
        for forbidden in ("Luna Max", "Terra High", "Populated Consumer", "top_level_project_task", "root_task"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, distributable)

    def test_seed_feedback_scope_handoff_requires_signed_approval(self):
        self.assertIsNotNone(engineering)
        handoff = {
            "seed_evidence": ["REQ-ORDERS-EXPORT"],
            "reconstructed_scope": ["REQ-ORDERS-EXPORT", "FLOW-ORDERS-EXPORT-API"],
            "architect_scope": ["REQ-ORDERS-EXPORT", "FLOW-ORDERS-EXPORT-API"],
            "result_scope": ["REQ-ORDERS-EXPORT", "FLOW-ORDERS-EXPORT-API"],
        }
        with self.assertRaises(engineering.EngineeringError):
            engineering._scope_envelope(
                {"scope": ["README.md"], "forbidden": [], "scope_handoff": handoff}
            )
        self.assertRaises(
            engineering.EngineeringError,
            engineering._scope_envelope,
            {
                "scope": ["README.md"],
                "forbidden": [],
                "scope_handoff": {**handoff, "architect_approved": True},
            },
        )


class Task2ContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.start_fake_graphify_interpreter()
        self.private_files = patch.object(
            engineering, "_enforce_owner_private", side_effect=synthetic_owner_private
        )
        self.enforce_private = self.private_files.start()
        self.addCleanup(self.private_files.stop)
        self.private_verifier = patch.object(
            engineering, "_verify_owner_private", return_value=None
        )
        self.verify_private = self.private_verifier.start()
        self.addCleanup(self.private_verifier.stop)
        self.fixture_recovery = patch.object(
            engineering,
            "_recover_initial_checkpoint",
            side_effect=self.recover_fixture_checkpoint,
        )
        self.fixture_recovery.start()
        self.addCleanup(self.fixture_recovery.stop)

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def init_repo(self, name: str | None = None) -> Path:
        root = Path(self.temporary_directory.name)
        if name is not None:
            root /= name
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(root)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "synthetic"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Synthetic Test"],
            check=True,
        )
        # Named fixtures represent independent repositories.  Make their
        # immutable root lineage distinct instead of relying on Git's
        # second-resolution commit timestamp.
        title = "Synthetic" if name is None else f"Synthetic {name}"
        (root / "README.md").write_text(f"# {title}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-m", "initial"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "update-ref",
                "refs/remotes/origin/main",
                "HEAD",
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            ],
            check=True,
        )
        return root

    def git(self, root: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit_all(self, root: Path, message: str) -> str:
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", message)
        return self.git(root, "rev-parse", "HEAD")

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ENGINEERING_SCRIPT), *map(str, arguments)],
            capture_output=True,
            text=True,
        )

    def require_cli_private_acl(self, root: Path) -> None:
        """Normalize a synthetic controller before testing its real child process."""
        if os.name != "nt":
            return
        controller = self.module()._project_controller_dir(root)
        controller.mkdir(parents=True, exist_ok=True)
        try:
            for candidate in [
                controller,
                *sorted(
                    controller.rglob("*"),
                    key=lambda path: (len(path.parts), str(path)),
                ),
            ]:
                self.module()._windows_owner_private(candidate, enforce=True)
        except self.module().EngineeringError:
            self.skipTest(
                "Windows host cannot establish the owner-private ACL required by the CLI"
            )

    def write_controls(
        self,
        root: Path,
        *,
        generation: str = "v1",
        provenance: str = "direct",
        complete: bool = True,
    ) -> None:
        (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
        (root / "requirements.md").write_text("# REQ-1\n", encoding="utf-8")
        (root / "design.md").write_text("# DEC-1\n", encoding="utf-8")
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_app.py").write_text(
            "import unittest\n\n"
            "class ValueTests(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        if generation == "v1":
            manifest_name = "engineering-traceability.json"
            trace_name = "engineering-traceability"
            manifest_version = 1
        else:
            manifest_name = "engineering.json"
            trace_name = "engineering"
            manifest_version = 2
        trace_dir = root / "docs" / trace_name
        trace_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "version": manifest_version,
            "mode": "mid-flight",
            "project": {"name": root.name, "default_branch": "main"},
            "graphify": {"version": "0.9.5"},
            "overlay": {"version": 1},
            "inputs": [f"docs/{trace_name}/links.json"],
            "integrity": {"min_retained_ratio": 0.8},
        }
        nodes = [
            {
                "id": "REQ-1",
                "type": "requirement",
                "title": "Keep a stable value",
                "source": {"path": "requirements.md", "line": 1},
            },
            {
                "id": "DEC-1",
                "type": "decision",
                "title": "Use a module constant",
                "source": {"path": "design.md", "line": 1},
            },
            {
                "id": "CODE-1",
                "type": "code_symbol",
                "title": "README",
                "source": {"path": "README.md", "line": 1},
            },
            {
                "id": "TEST-1",
                "type": "test",
                "title": "test_value",
                "source": {"path": "tests/test_app.py", "line": 1},
            },
        ]
        edges = [
            {
                "id": "EDGE-1",
                "from": "REQ-1",
                "to": "DEC-1",
                "type": "decided_by",
                "provenance": provenance,
                "source": {"path": "requirements.md", "line": 1},
            }
        ]
        if complete:
            edges.extend(
                [
                    {
                        "id": "EDGE-2",
                        "from": "DEC-1",
                        "to": "CODE-1",
                        "type": "implements",
                        "provenance": "derived",
                        "source": {"path": "README.md", "line": 1},
                    },
                    {
                        "id": "EDGE-3",
                        "from": "CODE-1",
                        "to": "TEST-1",
                        "type": "verified_by",
                        "provenance": "direct",
                        "source": {"path": "tests/test_app.py", "line": 1},
                    },
                ]
            )
        (root / manifest_name).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        (trace_dir / "links.json").write_text(
            json.dumps({"version": 1, "nodes": nodes, "edges": edges}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        (trace_dir / "decision-ledger.md").write_text(
            "# Engineering Traceability Decision Ledger\n", encoding="utf-8"
        )
        (trace_dir / "README.md").write_text(
            "# Engineering traceability\n", encoding="utf-8"
        )

    def control_paths(self, root: Path, generation: str) -> tuple[Path, Path]:
        if generation == "v1":
            return (
                root / "engineering-traceability.json",
                root / "docs" / "engineering-traceability",
            )
        return root / "engineering.json", root / "docs" / "engineering"

    def write_fake_graphify(self) -> Path:
        root = Path(self.temporary_directory.name) / "fake-graphify"
        package = root / "graphify"
        metadata = root / "graphifyy-0.9.5.dist-info"
        package.mkdir(parents=True, exist_ok=True)
        metadata.mkdir(exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "__main__.py").write_text(
            "import json, os, pathlib, subprocess, sys\n"
            "control_path = pathlib.Path(__file__).with_name('fixture-controls.json')\n"
            "try:\n"
            "    controls = json.loads(control_path.read_text(encoding='utf-8'))\n"
            "except (OSError, json.JSONDecodeError):\n"
            "    controls = {}\n"
            "def control(name):\n"
            "    return controls.get(name) or os.environ.get(name)\n"
            "if '--help' in sys.argv:\n"
            "    print('  update PATH\\n  query TEXT\\n  path A B\\n  explain X')\n"
            "elif len(sys.argv) > 1 and sys.argv[1] == 'query':\n"
            "    print('No matching nodes found.')\n"
            "elif len(sys.argv) > 2 and sys.argv[1] == 'update':\n"
            "    if control('FAKE_GRAPHIFY_RECORD'):\n"
            "        pathlib.Path(control('FAKE_GRAPHIFY_RECORD')).open('a', encoding='utf-8').write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "    if control('FAKE_GRAPHIFY_SLOW'):\n"
            "        __import__('time').sleep(float(control('FAKE_GRAPHIFY_SLOW')))\n"
            "    out = pathlib.Path(os.environ['GRAPHIFY_OUT'])\n"
            "    out.mkdir(parents=True, exist_ok=True)\n"
            "    commit = subprocess.run(['git', '-C', sys.argv[2], 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()\n"
            "    (out / 'graph.json').write_text(json.dumps({'directed': True, 'multigraph': False, 'graph': {}, 'nodes': [], 'links': [], 'built_at_commit': commit}))\n"
            "    if control('FAKE_GRAPHIFY_FAIL'):\n"
            "        raise SystemExit(7)\n"
            "else:\n"
            "    raise SystemExit(3)\n",
            encoding="utf-8",
        )
        (package / "detect.py").write_text(
            "CODE_EXTENSIONS = {'.py', '.mjs', '.ps1'}\n",
            encoding="utf-8",
        )
        (package / "watch.py").write_text(
            "import json, os, pathlib, subprocess, sys, time\n"
            "control_path = pathlib.Path(__file__).with_name('fixture-controls.json')\n"
            "try:\n"
            "    controls = json.loads(control_path.read_text(encoding='utf-8'))\n"
            "except (OSError, json.JSONDecodeError):\n"
            "    controls = {}\n"
            "def control(name):\n"
            "    return controls.get(name) or os.environ.get(name)\n"
            "def _rebuild_code(watch_path, *, changed_paths=None, follow_symlinks=False, force=False, no_cluster=False, acquire_lock=True, block_on_lock=False):\n"
            "    if control('FAKE_GRAPHIFY_RECORD'):\n"
            "        pathlib.Path(control('FAKE_GRAPHIFY_RECORD')).open('a', encoding='utf-8').write(json.dumps(['private_rebuild_code', str(pathlib.Path.cwd()), *[str(p) for p in (changed_paths or [])]]) + '\\n')\n"
            "    if control('FAKE_GRAPHIFY_SLOW'):\n"
            "        if control('FAKE_GRAPHIFY_CHILD_PID'):\n"
            "            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            "            pathlib.Path(control('FAKE_GRAPHIFY_CHILD_PID')).write_text(str(child.pid))\n"
            "        time.sleep(float(control('FAKE_GRAPHIFY_SLOW')))\n"
            "    out = pathlib.Path(os.environ['GRAPHIFY_OUT'])\n"
            "    out.mkdir(parents=True, exist_ok=True)\n"
            "    graph_path = out / 'graph.json'\n"
            "    graph = json.loads(graph_path.read_text()) if graph_path.exists() else {'directed': True, 'multigraph': False, 'graph': {}, 'nodes': [], 'links': []}\n"
            "    graph['built_at_commit'] = subprocess.run(['git', '-C', str(watch_path), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()\n"
            "    graph_path.write_text(json.dumps(graph))\n"
            "    return not bool(control('FAKE_GRAPHIFY_FAIL'))\n",
            encoding="utf-8",
        )
        (metadata / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: graphifyy\nVersion: 0.9.5\n",
            encoding="utf-8",
        )
        (metadata / "direct_url.json").write_text(
            json.dumps(
                {
                    "url": "https://github.com/safishamsi/graphify.git",
                    "vcs_info": {
                        "vcs": "git",
                        "commit_id": (
                            "d89ec68af95e0cad801b56d88df383991e659823"
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )
        return root

    def start_fake_graphify_interpreter(self) -> None:
        """Use an isolated interpreter for synthetic Graphify, never PYTHONPATH."""
        host_python = Path(sys.executable)
        fake_graphify = self.write_fake_graphify()
        environment = Path(self.temporary_directory.name) / "fake-graphify-venv"
        subprocess.run(
            [
                str(host_python),
                "-m",
                "venv",
                "--copies",
                "--without-pip",
                str(environment),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.assertFalse(
            interpreter.is_symlink(),
            "The Graphify fixture interpreter must survive canonical path resolution.",
        )
        site_packages = Path(
            subprocess.run(
                [str(interpreter), "-c", "import site; print(site.getsitepackages()[0])"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        shutil.copytree(fake_graphify / "graphify", site_packages / "graphify")
        shutil.copytree(
            fake_graphify / "graphifyy-0.9.5.dist-info",
            site_packages / "graphifyy-0.9.5.dist-info",
        )
        self.fake_graphify_control = site_packages / "graphify" / "fixture-controls.json"
        self.fake_graphify_control.write_text("{}\n", encoding="utf-8")
        self.fake_graphify_interpreter = patch.object(sys, "executable", str(interpreter))
        self.fake_graphify_interpreter.start()
        self.addCleanup(self.fake_graphify_interpreter.stop)

    def set_fake_graphify_controls(self, **controls: str) -> None:
        self.fake_graphify_control.write_text(
            json.dumps(controls, sort_keys=True) + "\n", encoding="utf-8"
        )

    def test_project_discovery_contract_surface(self):
        module = self.module()
        for name in (
            "resolve_project",
            "load_project_config",
            "discover_checks",
            "verify_graphify",
        ):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(module, name, None)))

    def test_check_capability_approval_is_lineage_and_command_bound(self):
        module = self.module()
        root, commit = self.prepared_repo("check-capability")
        manifest = root / "engineering-traceability.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["checks"] = [[sys.executable, "-m", "unittest", "--help"]]
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        commit = self.commit_all(root, "configure safe check")
        fake = self.write_fake_graphify()
        with patch.dict(os.environ, {"PYTHONPATH": str(fake)}, clear=False):
            module.rebuild(root, commit, sys.executable)

        blocked = module.prepare(root, "change REQ-1", {"scope": ["README.md"]})
        self.assertEqual("blocked", blocked["readiness"])
        self.assertTrue(any("check capability" in item for item in blocked["blockers"]))

        approval = module.approve_checks(root)
        self.assertRegex(approval["approval_id"], r"^attestation-[0-9a-f]{32}$")
        ready = module.prepare(root, "change REQ-1", {"scope": ["README.md"]})
        self.assertNotEqual("blocked", ready["readiness"], ready)

        (root / "README.md").write_text("# ordinary source edit\n", encoding="utf-8")
        still_ready = module.prepare(root, "change REQ-1", {"scope": ["README.md"]})
        self.assertNotEqual("blocked", still_ready["readiness"])

        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["checks"] = [[sys.executable, "-m", "unittest", "discover"]]
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.commit_all(root, "change check capability")
        changed = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md", "engineering-traceability.json"]},
        )
        self.assertEqual("blocked", changed["readiness"])

    def test_inline_interpreter_code_requires_separate_explicit_approval(self):
        module = self.module()
        root, commit = self.prepared_repo("inline-check-capability")
        manifest = root / "engineering-traceability.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["checks"] = [[sys.executable, "-c", "print('unsafe inline')"]]
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        commit = self.commit_all(root, "configure inline check")
        fake = self.write_fake_graphify()
        with patch.dict(os.environ, {"PYTHONPATH": str(fake)}, clear=False):
            module.rebuild(root, commit, sys.executable)

        with self.assertRaisesRegex(module.EngineeringError, "inline"):
            module.approve_checks(root)
        approval = module.approve_checks(root, allow_inline_code=True)
        self.assertTrue(approval["inline_code_approved"])
        claims = module._check_capability_claims(
            root, [[sys.executable, "-c", "print('unsafe inline')"]]
        )
        self.assertTrue(claims["allow_inline_code"])

    def test_task_authority_replaces_legacy_attestation_only_for_exact_safe_checks(self):
        module = self.module()
        root, commit = self.prepared_repo("task-check-authority")
        manifest = root / "engineering-traceability.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        checks = [[sys.executable, "-m", "unittest", "--help"]]
        payload["checks"] = checks
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        commit = self.commit_all(root, "configure declared check")
        fake = self.write_fake_graphify()
        with patch.dict(os.environ, {"PYTHONPATH": str(fake)}, clear=False):
            module.rebuild(root, commit, sys.executable)
        controller = module._project_controller_dir(root)
        controller.mkdir(parents=True)
        key = controller / "attestation.key"
        key.write_text("1" * 64 + "\n", encoding="ascii")
        module._enforce_owner_private(controller)
        module._enforce_owner_private(key)
        authority = module.issue_task_check_authority(root, "task-authorized-check")
        prepared = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "task_authority": authority},
        )
        self.assertNotEqual("blocked", prepared["readiness"])
        self.assertEqual("task-authorized-check", prepared["check_authority"]["task_id"])

        with self.assertRaisesRegex(module.EngineeringError, "authority"):
            module.prepare(
                root,
                "change REQ-1",
                {
                    "scope": ["README.md"],
                    "task_authority": {
                        **authority,
                        "effects": {**authority["effects"], "deployment": True},
                    },
                },
            )

    def test_inline_interpreter_detection_covers_joined_and_encoded_modes(self):
        module = self.module()
        vectors = (
            ["python", "-cx"],
            ["python", "-cprint(1)"],
            ["node", "-eprocess.exit()"],
            ["node", "--eval=process.exit()"],
            ["node", "-p1+1"],
            ["node", "--print=1+1"],
            ["powershell", "-Command:Write-Host x"],
            ["pwsh", "-EncodedCommand", "AA=="],
            ["pwsh", "-encAA=="],
            ["cmd", "/cwhoami"],
            ["cmd.exe", "/k", "whoami"],
            ["bash", "-cecho x"],
            ["sh", "-c", "echo x"],
            ["py", "-c", "print(1)"],
            ["python3.12", "-c", "print(1)"],
            ["node20", "-e", "process.exit()"],
            ["pwsh7", "-Command", "Write-Host x"],
            ["zsh", "-c", "echo x"],
            ["ruby", "-e", "puts 1"],
            ["perl", "-E", "say 1"],
        )
        for argv in vectors:
            with self.subTest(argv=argv):
                self.assertTrue(module._contains_inline_code(argv))
        for argv in (["python", "-Qunknown"], ["node", "--unknown-mode"], ["pwsh", "-NoExit"]):
            with self.subTest(argv=argv), self.assertRaisesRegex(module.EngineeringError, "mode"):
                module._contains_inline_code(argv)

    def test_known_interpreters_require_a_positive_non_inline_mode(self):
        module = self.module()
        benign = (
            ["py", "-m", "unittest"],
            ["py.exe", "-3.12", "-m", "unittest"],
            ["python3.12", "check.py"],
            ["node20", "check.js"],
            ["pwsh7", "-NoProfile", "-File", "check.ps1"],
            ["zsh", "check.sh"],
            ["ruby3.3", "check.rb"],
            ["perl", "check.pl"],
        )
        for argv in benign:
            with self.subTest(argv=argv):
                self.assertFalse(module._contains_inline_code(argv))
        for argv in (["py", "-3.12"], ["zsh", "-x"], ["ruby", "-w"]):
            with self.subTest(argv=argv), self.assertRaisesRegex(module.EngineeringError, "mode"):
                module._contains_inline_code(argv)

    def test_legacy_check_attestation_is_non_inline_only(self):
        module = self.module()
        root, _ = self.prepared_repo("legacy-check-attestation")
        safe = module._check_capability_claims(
            root, [[sys.executable, "-m", "unittest", "--help"]]
        )
        legacy_safe = dict(safe)
        legacy_safe.pop("allow_inline_code")
        controller = module._project_controller_dir(root)
        registry, _, key = module._append_attestation(
            controller, "check_capability", legacy_safe
        )
        module._transactional_json_documents(
            [(module._attestation_path(controller), registry)],
            [(module._controller_key_path(controller), key)] if key else None,
        )
        self.assertEqual(
            legacy_safe,
            module._require_attestation(controller, "check_capability", safe)["claims"],
        )

        inline = module._check_capability_claims(
            root, [[sys.executable, "-c", "print(1)"]]
        )
        retained_inline = dict(inline)
        retained_inline.pop("allow_inline_code")
        self.assertFalse(
            module._attestation_claims_match(
                "check_capability", retained_inline, inline
            )
        )

    def test_check_execution_uses_credential_reduced_environment(self):
        module = self.module()
        captured = {}

        def run(argv, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout=b"ok", stderr=b"")

        with (
            patch.dict(os.environ, {"SYNTHETIC_SECRET_TOKEN": "do-not-pass"}, clear=False),
            patch.object(module.subprocess, "run", side_effect=run),
        ):
            module._execute_check([sys.executable, "--version"], timeout_seconds=1)

        self.assertNotIn("SYNTHETIC_SECRET_TOKEN", captured["env"])
        self.assertFalse(captured["shell"])

    def test_project_resolution_keeps_exact_git_identity(self):
        module = self.module()
        root = self.init_repo()

        project = module.resolve_project(root)

        self.assertEqual(root.resolve(), project.root)
        self.assertEqual("main", project.branch)
        self.assertEqual("main", project.default_branch)
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            project.commit,
        )

    def test_v1_paths_are_adopted_before_v2_defaults(self):
        module = self.module()
        root = self.init_repo()
        legacy = root / "engineering-traceability.json"
        legacy.write_text('{"version": 1}\n', encoding="utf-8")
        (root / "engineering.json").write_text('{"version": 2}\n', encoding="utf-8")

        config = module.load_project_config(root)

        self.assertEqual(legacy, config["source_path"])

    def test_setup_commands_adopt_complete_controls_without_parallel_files(self):
        for generation in ("v1", "v2"):
            for command in ("bootstrap", "reconstruct"):
                with self.subTest(generation=generation, command=command):
                    root = self.init_repo(f"{generation}-{command}")
                    self.write_controls(root, generation=generation)
                    manifest_path, trace_dir = self.control_paths(root, generation)
                    other_manifest, other_trace_dir = self.control_paths(
                        root, "v2" if generation == "v1" else "v1"
                    )
                    self.commit_all(root, "existing controls")
                    original = manifest_path.read_bytes()

                    result = self.run_cli(
                        command,
                        root,
                        "--graphify-python",
                        sys.executable,
                    )

                    self.assertEqual(1, result.returncode, result.stderr)
                    proposal = json.loads(result.stdout)
                    self.assertEqual("setup", proposal["forwarded_to"])
                    self.assertFalse(proposal["writes_applied"])
                    self.assertEqual(original, manifest_path.read_bytes())
                    self.assertTrue(trace_dir.is_dir())
                    self.assertFalse(other_manifest.exists())
                    self.assertFalse(other_trace_dir.exists())

    def test_setup_commands_fail_closed_for_config_only_controls(self):
        for generation in ("v1", "v2"):
            with self.subTest(generation=generation):
                root = self.init_repo(generation)
                self.write_controls(root, generation=generation)
                _, trace_dir = self.control_paths(root, generation)
                shutil.rmtree(trace_dir)
                self.commit_all(root, "legacy controls")

                result = self.run_cli(
                    "bootstrap",
                    root,
                    "--graphify-python",
                    sys.executable,
                )

                self.assertEqual(2, result.returncode)
                self.assertIn("missing_links", result.stderr)

    def test_setup_commands_fail_closed_for_incomplete_controls(self):
        for generation in ("v1", "v2"):
            with self.subTest(generation=generation):
                root = self.init_repo(generation)
                self.write_controls(root, generation=generation)
                _, trace_dir = self.control_paths(root, generation)
                (trace_dir / "decision-ledger.md").unlink()
                self.commit_all(root, "incomplete controls")

                result = self.run_cli(
                    "reconstruct",
                    root,
                    "--graphify-python",
                    sys.executable,
                )

                self.assertEqual(2, result.returncode)
                self.assertIn("missing_ledger", result.stderr)

    def test_python_project_uses_unittest_discovery(self):
        module = self.module()
        root = self.init_repo()
        (root / "pyproject.toml").write_text("[project]\nname='synthetic'\n")

        self.assertIn(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            module.discover_checks(root),
        )

    def test_node_project_uses_existing_test_command(self):
        module = self.module()
        root = self.init_repo()
        (root / "package-lock.json").write_text("{}\n", encoding="utf-8")

        self.assertIn(["npm", "test", "--", "--run"], module.discover_checks(root))

    def test_explicit_stack_neutral_argv_takes_precedence(self):
        module = self.module()
        root = self.init_repo()
        (root / "package-lock.json").write_text("{}\n", encoding="utf-8")
        (root / "engineering.json").write_text(
            json.dumps({"version": 2, "checks": [["make", "verify"]]}),
            encoding="utf-8",
        )

        self.assertEqual([["make", "verify"]], module.discover_checks(root))

    def test_shell_string_check_is_rejected(self):
        module = self.module()
        root = self.init_repo()
        (root / "engineering.json").write_text(
            json.dumps({"version": 2, "checks": ["make verify"]}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(module.EngineeringError, "argv"):
            module.discover_checks(root)

    def test_managed_instruction_argv_takes_precedence_over_config(self):
        module = self.module()
        root = self.init_repo()
        (root / "engineering.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "checks": [["config-check"]],
                    "managed_instructions": {"checks": [["managed-check"]]},
                }
            ),
            encoding="utf-8",
        )

        self.assertEqual([["managed-check"]], module.discover_checks(root))

    def test_managed_instruction_free_text_is_rejected(self):
        module = self.module()
        root = self.init_repo()
        (root / "engineering.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "checks": [["config-check"]],
                    "managed_instructions": {"checks": "make verify"},
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(module.EngineeringError, "managed.*argv"):
            module.discover_checks(root)

    def test_free_text_instructions_are_never_parsed_as_commands(self):
        module = self.module()
        root = self.init_repo()
        (root / "pyproject.toml").write_text("[project]\nname='synthetic'\n")
        (root / "AGENTS.md").write_text(
            "Run checks with: powershell -Command Remove-Item important.txt\n",
            encoding="utf-8",
        )

        self.assertEqual(
            [[sys.executable, "-m", "unittest", "discover", "-s", "tests"]],
            module.discover_checks(root),
        )

    def test_installed_graphify_matches_exact_reviewed_identity(self):
        module = self.module()

        identity = module.verify_graphify(Path(sys.executable))

        self.assertEqual("0.9.5", identity.version)
        self.assertEqual(
            "d89ec68af95e0cad801b56d88df383991e659823",
            identity.commit,
        )
        self.assertEqual(
            ("update", "path", "explain"),
            identity.required_commands,
        )

    def test_synthetic_repo_has_an_owner_private_controller_directory(self):
        module = self.module()
        root = self.init_repo("private-controller")
        controller = module._project_controller_dir(root)
        controller.mkdir(parents=True)

        module._enforce_owner_private(controller)
        module._verify_owner_private(controller, directory=True)
        self.enforce_private.assert_called_once_with(controller)
        self.verify_private.assert_called_once_with(controller, directory=True)

    def test_graphify_install_argv_is_exact_and_pinned(self):
        module = self.module()

        self.assertEqual(
            [
                "uv",
                "tool",
                "install",
                "git+https://github.com/safishamsi/graphify.git"
                "@d89ec68af95e0cad801b56d88df383991e659823",
            ],
            module.graphify_install_argv("v0.9.5"),
        )

    def test_unpinned_graphify_is_rejected(self):
        module = self.module()

        with self.assertRaisesRegex(module.EngineeringError, "pinned"):
            module.graphify_install_argv("main")

    def test_ambiguous_overlay_provenance_is_rejected(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root, provenance="ambiguous")
        commit = self.commit_all(root, "ambiguous overlay")

        with self.assertRaisesRegex(module.EngineeringError, "Invalid edge schema"):
            module.construct_checkpoint(root, commit, None)

    def test_v1_hook_migration_preserves_original_and_runs_controller_once(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root)
        self.commit_all(root, "legacy controls")
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        hooks.mkdir(parents=True, exist_ok=True)
        original = hooks / "pre-commit"
        original.write_text(
            "#!/bin/sh\nprintf 'original\\n' >> \"$PWD/hook.log\"\n",
            encoding="utf-8",
            newline="\n",
        )
        original.chmod(0o755)
        preserved = hooks / "engineering-preserved"
        preserved.mkdir(parents=True)
        (preserved / "pre-commit").write_bytes(original.read_bytes())
        original.write_bytes(module._round_one_hook_wrapper("pre-commit"))

        module._install_hooks_authorized(
            root,
            sys.executable,
            ENGINEERING_SCRIPT,
            module._hook_plan_state(root),
        )
        result = subprocess.run(
            ["git", "-C", str(root), "hook", "run", "pre-commit"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((root / "hook.log").exists())
        self.assertEqual(
            ["original"],
            (root / "hook.log").read_text(encoding="utf-8").splitlines(),
        )
        self.assertEqual("", result.stdout)
        self.assertEqual("", result.stderr)

    def test_round_one_hook_marker_migrates_only_original_preserved_body(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root)
        self.commit_all(root, "legacy controls")
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        preserved = hooks / "engineering-preserved"
        preserved.mkdir(parents=True)
        (preserved / "pre-commit").write_text(
            "#!/bin/sh\nprintf 'original\\n' >> \"$PWD/hook.log\"\n",
            encoding="utf-8",
            newline="\n",
        )
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\n"
            "# engineering-hook\n"
            'exec "$(dirname -- "$0")/engineering-dispatcher" pre-commit "$@"\n',
            encoding="utf-8",
            newline="\n",
        )

        original_bytes = (preserved / "pre-commit").read_bytes()
        module._install_hooks_authorized(
            root,
            sys.executable,
            ENGINEERING_SCRIPT,
            module._hook_plan_state(root),
        )
        result = subprocess.run(
            ["git", "-C", str(root), "hook", "run", "pre-commit"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((root / "hook.log").exists())
        self.assertEqual(
            ["original"],
            (root / "hook.log").read_text(encoding="utf-8").splitlines(),
        )
        self.assertEqual("", result.stdout)
        self.assertEqual("", result.stderr)
        self.assertEqual(
            original_bytes,
            (
                hooks
                / "engineering-traceability-preserved"
                / "pre-commit"
            ).read_bytes(),
        )

    def test_query_commands_preserve_v1_results(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root)
        commit = self.commit_all(root, "query overlay")
        module.construct_checkpoint(root, commit, None)

        cases = {
            ("status", root): lambda value: self.assertTrue(value["fresh"]),
            ("coverage", root): lambda value: self.assertTrue(
                value["requirements"][0]["covered"]
            ),
            ("trace", root, "REQ-1"): lambda value: self.assertEqual(
                ["REQ-1", "DEC-1", "CODE-1", "TEST-1"], value["path"]
            ),
            ("impact", root, "REQ-1"): lambda value: self.assertEqual(
                ["DEC-1", "CODE-1", "TEST-1"], value["exact"]
            ),
            ("why-code", root, "CODE-1"): lambda value: self.assertEqual(
                ["REQ-1"], value["requirements"]
            ),
            ("why-test", root, "TEST-1"): lambda value: self.assertEqual(
                ["REQ-1"], value["requirements"]
            ),
            ("compare", root, commit, commit): lambda value: self.assertEqual(
                {"added": [], "removed": [], "changed": []}, value["nodes"]
            ),
        }
        for arguments, assertion in cases.items():
            with self.subTest(command=arguments[0]):
                result = self.run_cli(*arguments)
                self.assertEqual(0, result.returncode, result.stderr)
                assertion(json.loads(result.stdout))

    def prepared_repo(
        self,
        name: str,
        *,
        baseline_accepted: bool = True,
        provenance: str = "direct",
        source_body: str | None = None,
    ) -> tuple[Path, str]:
        root = self.init_repo(name)
        self.write_controls(root, provenance=provenance)
        if source_body is not None:
            (root / "requirements.md").write_text(
                "# REQ-1\n" + source_body + "\n", encoding="utf-8"
            )
        manifest = root / "engineering-traceability.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["baseline"] = {"accepted": baseline_accepted}
        payload["context"] = {"token_budget": 128}
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        commit = self.commit_all(root, "preparation fixture")
        self.write_canonical_checkpoint(root, commit)
        return root, commit

    def write_canonical_checkpoint(self, root: Path, commit: str) -> Path:
        destination, checkpoint = engineering._checkpoint_candidate_at(
            root,
            commit,
            branch="main",
            kind="canonical",
            graphify_version=engineering.GRAPHIFY_VERSION,
            manifest_name="engineering-traceability.json",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        graph_path = destination.parent / "graph.json"
        graph_path.write_text(
            json.dumps(
                {
                    "directed": True,
                    "multigraph": False,
                    "graph": {},
                    "nodes": [],
                    "links": [],
                    "built_at_commit": commit,
                }
            ),
            encoding="utf-8",
        )
        checkpoint["metadata"]["graph_digest"] = hashlib.sha256(
            graph_path.read_bytes()
        ).hexdigest()
        destination.write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")
        self.assertTrue(engineering.validate_checkpoint(root, destination, commit)["valid"])
        return destination

    def recover_fixture_checkpoint(self, project):
        checkpoint = self.write_canonical_checkpoint(project.root, project.commit)
        return {"recovered": True, "checkpoint": str(checkpoint)}

    def set_base_graph_nodes(self, root: Path, nodes: list[dict]) -> Path:
        module = self.module()
        commit = self.git(root, "rev-parse", "HEAD")
        checkpoint_path = module._checkpoint_path(root, commit)
        graph_path = checkpoint_path.parent / "graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        graph["nodes"] = nodes
        graph["links"] = []
        graph_path.write_text(json.dumps(graph), encoding="utf-8")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["metadata"]["graph_digest"] = hashlib.sha256(
            graph_path.read_bytes()
        ).hexdigest()
        checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
        return checkpoint_path

    def test_prepare_returns_bounded_ready_contract_and_atomic_metadata(self):
        module = self.module()
        root, commit = self.prepared_repo(
            "prepare-ready", source_body="PRIVATE SYNTHETIC BODY"
        )
        module.approve_checks(root)

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md", "tests/test_app.py"], "forbidden": ["publish", "deploy"]},
            None,
        )

        self.assertEqual(
            {
                "schema",
                "run_id",
                "project",
                "intent",
                "authorization",
                "autonomy",
                "readiness",
                "blockers",
                "advisories",
                "context",
                "impact",
                "required_checks",
                "check_authority",
            },
            set(result),
        )
        self.assertEqual("engineering.prepare.v1", result["schema"])
        self.assertRegex(result["run_id"], r"^run-[0-9a-f]{6}$")
        self.assertEqual(commit, result["project"]["commit"])
        self.assertEqual("main", result["project"]["branch"])
        self.assertRegex(result["project"]["root_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual("ready", result["readiness"])
        self.assertEqual("implementation", result["intent"]["purpose"])
        self.assertRegex(result["intent"]["digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual([{"id": "REQ-1", "provenance": "direct"}], result["context"][:1])
        self.assertTrue(any(item["id"] == "README.md" for item in result["impact"]))
        retained = (
            module.common_graph_dir(root)
            / "runs"
            / result["run_id"]
            / "preparation.json"
        )
        self.assertEqual(result, json.loads(retained.read_text(encoding="utf-8")))
        self.assertNotIn("PRIVATE SYNTHETIC BODY", retained.read_text(encoding="utf-8"))
        self.assertFalse(any(path.name.startswith(".preparation.json") for path in retained.parent.iterdir()))

    def test_prepare_deduplicates_graphify_context_and_exact_neighbours(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-context")
        graphify_context = {
            "status": "success",
            "context": [{"id": "REQ-1", "provenance": "inferred"}],
        }

        with patch.object(module, "_graphify_query_context", return_value=graphify_context) as query:
            result = module.prepare(
                root,
                "change REQ-1",
                {"scope": ["README.md"], "forbidden": []},
                None,
            )

        query.assert_called_once()
        self.assertEqual(1, sum(item["id"] == "REQ-1" for item in result["context"]))
        self.assertIn({"id": "DEC-1", "provenance": "direct"}, result["context"])
        self.assertIn({"id": "REQ-1", "provenance": "direct"}, result["context"])

    def test_prepare_reports_baseline_remote_and_unrelated_maintenance_advisories(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-advisory", baseline_accepted=False)
        module.approve_checks(root)
        module.queue_maintenance(
            root,
            {
                "area": "docs",
                "artifact": "docs/guide.md",
                "kind": "stale_artifact",
                "impact": "routine",
            },
        )
        self.git(root, "remote", "add", "upstream", str(root / "missing.git"))

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )

        self.assertEqual("ready_with_advisories", result["readiness"])
        self.assertEqual(
            [
                "canonical remote freshness is unknown",
                "historical gaps remain before baseline acceptance",
                "Engineering maintenance: 1 queued artifact(s). Run `engineering maintain` "
                "once to repair safe items; blocked items still require review. The command "
                "does not change autonomy.",
            ],
            result["advisories"],
        )

    def test_prepare_blocks_missing_exact_context_and_dirty_out_of_scope_work(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-blocked")
        (root / "outside.txt").write_text("existing user work\n", encoding="utf-8")

        result = module.prepare(
            root,
            "change REQ-MISSING",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("required source or exact context is missing", result["blockers"])
        self.assertIn("dirty work exists outside the authorized scope", result["blockers"])

    def test_prepare_blocks_unapproved_contract_impact(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-contract")
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        checkpoint["nodes"].append(
            {
                "id": "CONTRACT-1",
                "type": "contract",
                "title": "Synthetic contract",
                "source": {"path": "design.md", "line": 1},
            }
        )
        checkpoint["edges"].append(
            {
                "id": "EDGE-CONTRACT",
                "from": "REQ-1",
                "to": "CONTRACT-1",
                "type": "specified_in",
                "provenance": "direct",
                "source": {"path": "requirements.md", "line": 1},
            }
        )

        with patch.object(module, "_load_checkpoint", return_value=checkpoint):
            result = module.prepare(
                root,
                "change REQ-1 contract",
                {"scope": ["design.md"], "forbidden": []},
                None,
            )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("public contract change lacks explicit approval", result["blockers"])

    def test_prepare_cli_emits_json_and_uses_blocked_exit_code(self):
        root, _ = self.prepared_repo("prepare-cli")
        self.module().approve_checks(root)
        self.require_cli_private_acl(root)

        ready = self.run_cli(
            "prepare",
            root,
            "change REQ-1",
            "--scope-json",
            json.dumps({"scope": ["README.md"], "forbidden": []}),
        )
        blocked = self.run_cli(
            "prepare",
            root,
            "change REQ-MISSING",
            "--scope-json",
            json.dumps({"scope": ["README.md"], "forbidden": []}),
        )

        self.assertEqual(0, ready.returncode, ready.stderr)
        self.assertEqual("engineering.prepare.v1", json.loads(ready.stdout)["schema"])
        self.assertEqual(1, blocked.returncode, blocked.stderr)
        self.assertEqual("blocked", json.loads(blocked.stdout)["readiness"])

    def test_prepare_exact_run_cache_does_not_rewrite_metadata(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-exact-cache")
        arguments = (
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )
        first = module.prepare(*arguments)

        with patch.object(module, "_atomic_text") as atomic_write:
            second = module.prepare(*arguments)

        self.assertEqual(first, second)
        atomic_write.assert_not_called()

    def test_scaffold_and_legacy_prepare_use_the_documented_context_budget(self):
        module = self.module()
        for generation in ("current", "legacy"):
            with self.subTest(generation=generation):
                root = self.init_repo(f"prepare-budget-{generation}")
                if generation == "current":
                    self.write_controls(root, generation="v2")
                else:
                    self.write_controls(root, generation="v1")
                commit = self.commit_all(root, "bounded context budget")
                fake_graphify = self.write_fake_graphify()
                with patch.dict(os.environ, {"PYTHONPATH": str(fake_graphify)}, clear=False):
                    module.rebuild(root, commit, sys.executable)
                empty = {"status": "empty", "context": []}
                with patch.object(
                    module, "_graphify_query_context", return_value=empty
                ) as query:
                    result = module.prepare(
                        root,
                        "change REQ-1",
                        {"scope": ["README.md"], "forbidden": []},
                        None,
                    )

                self.assertEqual("engineering.prepare.v1", result["schema"])
                self.assertEqual(1000, query.call_args.args[2])

    def test_graphify_query_uses_only_validated_bounded_node_text(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "query-contract"
        checkpoint = root / "checkpoint.json"
        root.mkdir()
        (root / "graph.json").write_text(
            json.dumps(
                {
                    "nodes": [
                        {"id": "base:auth", "label": "Authentication requirement"},
                        {"id": "base:code", "label": "Authentication code"},
                    ],
                    "links": [],
                }
            ),
            encoding="utf-8",
        )
        with patch.object(module.subprocess, "run") as runner:
            result = module._graphify_query_context("change auth", checkpoint, 16)

        self.assertEqual("success", result["status"])
        self.assertEqual(
            [
                {"id": "base:auth", "provenance": "derived"},
            ],
            result["context"],
        )
        runner.assert_not_called()

    def test_graph_context_reports_empty_without_a_graphify_runtime(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "query-outcomes"
        checkpoint = root / "checkpoint.json"
        root.mkdir()
        (root / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "base:req", "label": "Requirement"}], "links": []}),
            encoding="utf-8",
        )
        with patch.object(module.subprocess, "run") as runner:
            result = module._graphify_query_context("change auth", checkpoint, 16)
        self.assertEqual("empty", result["status"])
        runner.assert_not_called()

    def test_empty_graph_needs_no_graphify_subprocess(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "empty-query"
        checkpoint = root / "checkpoint.json"
        root.mkdir()
        (root / "graph.json").write_text(
            json.dumps({"nodes": [], "links": []}), encoding="utf-8"
        )

        with patch.object(module.subprocess, "run") as runner:
            result = module._graphify_query_context("change auth", checkpoint, 16)

        self.assertEqual("empty", result["status"])
        runner.assert_not_called()

    def test_query_never_returns_credential_shaped_graph_ids(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "credential-query-id"
        checkpoint = root / "checkpoint.json"
        root.mkdir()
        credential_id = "sk-synthetic123456789"
        (root / "graph.json").write_text(
            json.dumps(
                {"nodes": [{"id": credential_id, "label": "Credential node"}], "links": []}
            ),
            encoding="utf-8",
        )
        with patch.object(module.subprocess, "run") as runner:
            result = module._graphify_query_context("change credential", checkpoint, 16)

        self.assertEqual("invalid", result["status"])
        self.assertNotIn(credential_id, json.dumps(result))
        runner.assert_not_called()

    def test_context_merge_keeps_strongest_provenance_and_first_id_order(self):
        module = self.module()

        result = module._merge_context(
            [
                {"id": "REQ-1", "provenance": "inferred"},
                {"id": "DEC-1", "provenance": "ambiguous"},
                {"id": "REQ-1", "provenance": "direct"},
                {"id": "DEC-1", "provenance": "derived"},
            ]
        )

        self.assertEqual(
            [
                {"id": "REQ-1", "provenance": "direct"},
                {"id": "DEC-1", "provenance": "derived"},
            ],
            result,
        )

    def test_prepare_blocks_contract_intent_without_exact_context_or_impact(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-contract-no-id")

        result = module.prepare(
            root,
            "change the synthetic authentication contract",
            {"scope": ["design.md"], "forbidden": []},
            None,
        )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("required source or exact context is missing", result["blockers"])
        self.assertEqual([], result["impact"])

    def test_successful_empty_query_still_blocks_empty_exact_evidence(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-empty-evidence")

        with patch.object(
            module,
            "_graphify_query_context",
            return_value={"status": "empty", "context": []},
        ):
            result = module.prepare(
                root,
                "change authentication behavior",
                {"scope": ["README.md"], "forbidden": []},
                None,
            )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("required source or exact context is missing", result["blockers"])

    def test_exact_context_carries_derived_provenance_across_the_full_path(self):
        module = self.module()
        checkpoint = {
            "edges": [
                {
                    "id": "EDGE-1",
                    "from": "ORIGIN",
                    "to": "A",
                    "provenance": "derived",
                },
                {
                    "id": "EDGE-2",
                    "from": "A",
                    "to": "X",
                    "provenance": "direct",
                },
            ]
        }

        self.assertEqual(
            [
                {"id": "A", "provenance": "derived"},
                {"id": "X", "provenance": "derived"},
            ],
            module._exact_context_neighbours(checkpoint, ["ORIGIN"]),
        )

    def test_exact_context_upgrades_a_later_all_direct_path_without_duplicates(self):
        module = self.module()
        checkpoint = {
            "edges": [
                {
                    "id": "EDGE-1",
                    "from": "ORIGIN",
                    "to": "X",
                    "provenance": "derived",
                },
                {
                    "id": "EDGE-2",
                    "from": "ORIGIN",
                    "to": "A",
                    "provenance": "direct",
                },
                {
                    "id": "EDGE-3",
                    "from": "A",
                    "to": "X",
                    "provenance": "direct",
                },
            ]
        }

        result = module._exact_context_neighbours(checkpoint, ["ORIGIN"])

        self.assertEqual(
            [
                {"id": "X", "provenance": "direct"},
                {"id": "A", "provenance": "direct"},
            ],
            result,
        )
        self.assertEqual(1, sum(item["id"] == "X" for item in result))
        self.assertEqual(
            result,
            module._exact_context_neighbours(checkpoint, ["ORIGIN"]),
        )

    def test_query_selected_id_drives_exact_contract_impact_and_approval_gate(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-query-contract")
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        checkpoint["nodes"].append(
            {
                "id": "CONTRACT-1",
                "type": "contract",
                "title": "Synthetic contract",
                "source": {"path": "design.md", "line": 1},
            }
        )
        checkpoint["edges"].append(
            {
                "id": "EDGE-CONTRACT",
                "from": "REQ-1",
                "to": "CONTRACT-1",
                "type": "specified_in",
                "provenance": "direct",
                "source": {"path": "requirements.md", "line": 1},
            }
        )
        query = {"status": "success", "context": [{"id": "REQ-1", "provenance": "inferred"}]}

        with patch.object(module, "_load_checkpoint", return_value=checkpoint), patch.object(
            module, "_graphify_query_context", return_value=query
        ):
            result = module.prepare(
                root,
                "change the authentication contract",
                {"scope": ["design.md"], "forbidden": []},
                None,
            )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("public contract change lacks explicit approval", result["blockers"])
        self.assertTrue(any(item["id"] == "design.md" for item in result["impact"]))

    def test_query_unavailable_requires_exact_safe_task_authority(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-deterministic-only")
        unavailable = {"status": "unavailable", "context": [], "reason": "query_timeout"}
        controller = module._project_controller_dir(root)
        controller.mkdir(parents=True)
        key = controller / "attestation.key"
        key.write_text("1" * 64 + "\n", encoding="ascii")
        module._enforce_owner_private(controller)
        module._enforce_owner_private(key)
        authority = module.issue_task_check_authority(root, "deterministic-context-recovery")

        with patch.object(module, "_graphify_query_context", return_value=unavailable):
            blocked = module.prepare(
                root,
                "change REQ-1",
                {"scope": ["README.md"], "forbidden": []},
                None,
            )
            legacy_only = module.prepare(
                root,
                "change REQ-1",
                {
                    "scope": ["README.md"],
                    "forbidden": [],
                    "deterministic_only_approved": True,
                },
                None,
            )
            approved = module.prepare(
                root,
                "change REQ-1",
                {"scope": ["README.md"], "forbidden": [], "task_authority": authority},
                None,
            )
            empty_approved = module.prepare(
                root,
                "change authentication behavior",
                {
                    "scope": ["README.md"],
                    "forbidden": [],
                    "task_authority": authority,
                },
                None,
            )

        self.assertEqual("blocked", blocked["readiness"])
        self.assertEqual("blocked", legacy_only["readiness"])
        self.assertEqual("ready", approved["readiness"])
        self.assertTrue(legacy_only["authorization"]["legacy_deterministic_only_approved"])
        self.assertEqual("blocked", empty_approved["readiness"])

    def test_direct_contract_origin_requires_only_documented_approval_key(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-direct-contract")
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        checkpoint["nodes"].append(
            {
                "id": "CONTRACT-1",
                "type": "contract",
                "title": "Synthetic contract",
                "source": {"path": "design.md", "line": 1},
            }
        )
        checkpoint["edges"].append(
            {
                "id": "EDGE-CONTRACT",
                "from": "REQ-1",
                "to": "CONTRACT-1",
                "type": "specified_in",
                "provenance": "direct",
                "source": {"path": "requirements.md", "line": 1},
            }
        )
        empty = {"status": "empty", "context": []}
        base_scope = {
            "scope": ["design.md"],
            "forbidden": [],
            "context_ids": ["CONTRACT-1"],
        }
        aliases = (
            {"approve_contract_change": True},
            {"contract_change": "approved"},
            {"approvals": ["contract_change"]},
        )
        with patch.object(module, "_load_checkpoint", return_value=checkpoint), patch.object(
            module, "_graphify_query_context", return_value=empty
        ):
            blocked = [
                module.prepare(root, "change contract", {**base_scope, **alias}, None)
                for alias in aliases
            ]
            forged = module.prepare(
                root,
                "change contract",
                {**base_scope, "contract_change_approved": True},
                None,
            )

        for result in blocked:
            self.assertIn("public contract change lacks explicit approval", result["blockers"])
        self.assertIn("public contract change lacks explicit approval", forged["blockers"])
        self.assertTrue(any(item["id"] == "design.md" for item in forged["impact"]))

    def test_upstream_contract_in_exact_context_requires_approval(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-upstream-contract")
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        decision = next(node for node in checkpoint["nodes"] if node["id"] == "DEC-1")
        decision.update({"id": "CONTRACT-1", "type": "contract"})
        for edge in checkpoint["edges"]:
            if edge["to"] == "DEC-1":
                edge["to"] = "CONTRACT-1"
            if edge["from"] == "DEC-1":
                edge["from"] = "CONTRACT-1"
        empty = {"status": "empty", "context": []}
        base_scope = {
            "scope": ["README.md"],
            "forbidden": [],
            "context_ids": ["CODE-1"],
        }

        with patch.object(module, "_load_checkpoint", return_value=checkpoint), patch.object(
            module, "_graphify_query_context", return_value=empty
        ):
            blocked = module.prepare(root, "change CODE-1", base_scope, None)
            forged = module.prepare(
                root,
                "change CODE-1",
                {**base_scope, "contract_change_approved": True},
                None,
            )

        contract_blocker = "public contract change lacks explicit approval"
        self.assertIn(
            {"id": "CONTRACT-1", "provenance": "derived"}, blocked["context"]
        )
        self.assertIn(contract_blocker, blocked["blockers"])
        self.assertIn(contract_blocker, forged["blockers"])

    def test_contract_approval_requires_an_approved_ledger_entry_not_a_boolean(self):
        module = self.module()
        root, _ = self.prepared_repo("ledger-contract-approval")
        manifest = module.load_project_config(root)
        with patch.object(module, "_ledger_decisions", return_value={"PROJECT-DEC-1": 1}), patch.object(
            module,
            "_text_at",
            return_value=(
                "## PROJECT-DEC-1 - Contract\n\n"
                "Status: Approved\n\n"
                "## PROJECT-DEC-2 - Other\nStatus: Not approved\n"
            ),
        ):
            self.assertTrue(
                module._contract_change_approved(
                    root, module.git(root, "rev-parse", "HEAD"), manifest,
                    {"contract_approval_id": "PROJECT-DEC-1"},
                )
            )
        self.assertFalse(
            module._contract_change_approved(
                root, module.git(root, "rev-parse", "HEAD"), manifest,
                {"contract_change_approved": True},
            )
        )
        with patch.object(module, "_ledger_decisions", return_value={"PROJECT-DEC-1": 1}), patch.object(
            module,
            "_text_at",
            return_value="## PROJECT-DEC-1 - Contract\nStatus: Not approved\n",
        ):
            self.assertFalse(
                module._contract_change_approved(
                    root, module.git(root, "rev-parse", "HEAD"), manifest,
                    {"contract_approval_id": "PROJECT-DEC-1"},
                )
            )
        relationship_text = (
            "## PROJECT-DEC-1 - First\nStatus: Approved\n"
            "Supersedes: PROJECT-DEC-2\n\n"
            "## PROJECT-DEC-2 - Second\nStatus: Not approved\n"
        )
        with patch.object(module, "_text_at", return_value=relationship_text):
            decisions = module._ledger_decisions(root, "WORKTREE", manifest)
            self.assertEqual({"PROJECT-DEC-1": 1, "PROJECT-DEC-2": 5}, decisions)
            self.assertFalse(
                module._contract_change_approved(
                    root, "WORKTREE", manifest,
                    {"contract_approval_id": "PROJECT-DEC-2"},
                )
            )
        table_text = (
            "| ID | Date | Status | Decision |\n"
            "|---|---|---|---|\n"
            "| PROJECT-DEC-3 | 2026-08-04 | approved | Third |\n"
        )
        with patch.object(module, "_text_at", return_value=table_text):
            self.assertTrue(
                module._contract_change_approved(
                    root, "WORKTREE", manifest,
                    {"contract_approval_id": "PROJECT-DEC-3"},
                )
            )
        misleading_table = (
            "| ID | Status | Approved by |\n"
            "|---|---|---|\n"
            "| PROJECT-DEC-4 | Not approved | Approved |\n"
        )
        with patch.object(module, "_text_at", return_value=misleading_table):
            self.assertFalse(
                module._contract_change_approved(
                    root, "WORKTREE", manifest,
                    {"contract_approval_id": "PROJECT-DEC-4"},
                )
            )
        deceptive_table = (
            "| ID | Status | Note |\n"
            "|---|---|---|\n"
            "| PROJECT-DEC-0 | Approved | status |\n"
            "| PROJECT-DEC-4 | Not approved | Approved |\n"
        )
        with patch.object(module, "_text_at", return_value=deceptive_table):
            self.assertFalse(
                module._contract_change_approved(
                    root, "WORKTREE", manifest,
                    {"contract_approval_id": "PROJECT-DEC-4"},
                )
            )
        conflicting_heading = (
            "## PROJECT-DEC-4 - Conflicting status\n"
            "Status: Not approved\n"
            "Status: Approved\n"
        )
        with patch.object(module, "_text_at", return_value=conflicting_heading):
            self.assertFalse(
                module._contract_change_approved(
                    root, "WORKTREE", manifest,
                    {"contract_approval_id": "PROJECT-DEC-4"},
                )
            )
        conflicting_duplicate = (
            "| ID | Status |\n"
            "|---|---|\n"
            "| PROJECT-DEC-5 | Not approved |\n\n"
            "## PROJECT-DEC-5 - Conflicting duplicate\n"
            "Status: Approved\n"
        )
        with patch.object(module, "_text_at", return_value=conflicting_duplicate):
            with self.assertRaisesRegex(module.EngineeringError, "reuses a stable ID"):
                module._contract_change_approved(
                    root, "WORKTREE", manifest,
                    {"contract_approval_id": "PROJECT-DEC-5"},
                )

    def test_impact_provenance_tracks_each_path_and_keeps_strongest(self):
        module = self.module()
        checkpoint = {
            "nodes": [
                {
                    "id": identifier,
                    "type": "code_symbol",
                    "source": {"path": path, "line": 1},
                }
                for identifier, path in (
                    ("ORIGIN", "origin.py"),
                    ("DIRECT", "direct.py"),
                    ("DERIVED", "derived.py"),
                    ("SHARED", "shared.py"),
                )
            ],
            "edges": [
                {
                    "id": "EDGE-DIRECT",
                    "from": "ORIGIN",
                    "to": "DIRECT",
                    "provenance": "direct",
                },
                {
                    "id": "EDGE-DERIVED",
                    "from": "ORIGIN",
                    "to": "DERIVED",
                    "provenance": "derived",
                },
                {
                    "id": "EDGE-SHARED-DERIVED",
                    "from": "DERIVED",
                    "to": "SHARED",
                    "provenance": "direct",
                },
                {
                    "id": "EDGE-SHARED-DIRECT",
                    "from": "ORIGIN",
                    "to": "SHARED",
                    "provenance": "direct",
                },
            ],
        }

        impact = module._context_impact(checkpoint, ["ORIGIN"])

        self.assertEqual(
            {
                "derived.py": "derived",
                "direct.py": "direct",
                "origin.py": "direct",
                "shared.py": "direct",
            },
            {item["id"]: item["provenance"] for item in impact},
        )
        self.assertEqual(
            sorted(item["id"] for item in impact),
            [item["id"] for item in impact],
        )
        self.assertEqual(impact, module._context_impact(checkpoint, ["ORIGIN"]))

    def test_prepare_cli_query_failure_is_bounded_without_traceback(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-cli-query-failure")
        self.set_base_graph_nodes(
            root, [{"id": "REQ-1", "label": "Synthetic requirement"}]
        )
        fake_graphify = self.write_fake_graphify()

        with patch.dict(os.environ, {"PYTHONPATH": str(fake_graphify)}, clear=False):
            result = self.run_cli(
                "prepare",
                root,
                "change REQ-1",
                "--scope-json",
                json.dumps({"scope": ["README.md"], "forbidden": []}),
            )

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual("blocked", json.loads(result.stdout)["readiness"])
        self.assertNotIn("Traceback", result.stderr)
        self.assertLess(len(result.stderr), 512)

    def test_prepare_redacts_credentials_and_rejects_them_in_authorization(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-credentials")
        intent = (
            'change REQ-1 with Authorization: Bearer abc.def.ghi, '
            'password is "two word secret", api_key=sk-synthetic123456789'
        )

        result = module.prepare(
            root,
            intent,
            {"scope": ["README.md"], "forbidden": []},
            None,
        )
        retained = (
            module.common_graph_dir(root)
            / "runs"
            / result["run_id"]
            / "preparation.json"
        ).read_text(encoding="utf-8")
        for secret in ("abc.def.ghi", "two word secret", "sk-synthetic123456789"):
            self.assertNotIn(secret, json.dumps(result["intent"]))
            self.assertNotIn(secret, retained)
        for key, value in (
            ("scope", ["password: secret value"]),
            ("forbidden", ["Bearer secret-token"]),
        ):
            with self.subTest(key=key), self.assertRaisesRegex(
                module.EngineeringError, "credential"
            ):
                module.prepare(
                    root,
                    "change REQ-1",
                    {"scope": value if key == "scope" else ["README.md"],
                     "forbidden": value if key == "forbidden" else []},
                    None,
                )
        with self.assertRaisesRegex(module.EngineeringError, "bounded"):
            module.prepare(
                root,
                "change REQ-1",
                {"scope": ["a" * 513], "forbidden": []},
                None,
            )
        with self.assertRaisesRegex(module.EngineeringError, "credential"):
            module.prepare(
                root,
                "change authentication",
                {
                    "scope": ["README.md"],
                    "forbidden": [],
                    "context_ids": ["ghp_synthetic123456789"],
                },
                None,
            )

    def test_credential_predicate_preserves_legitimate_repeated_space_paths(self):
        module = self.module()
        value = "docs/password  reset guide.md"

        authorization = module._scope_envelope(
            {"scope": [value], "forbidden": []}
        )

        self.assertEqual([value], authorization["scope"])

    def test_integrity_failure_retains_previous_atomic_checkpoint(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root)
        first_commit = self.commit_all(root, "covered overlay")
        first_path = module.construct_checkpoint(root, first_commit, None)
        first_bytes = first_path.read_bytes()
        links = root / "docs" / "engineering-traceability" / "links.json"
        value = json.loads(links.read_text(encoding="utf-8"))
        value["nodes"] = []
        value["edges"] = []
        links.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        second_commit = self.commit_all(root, "unexpected shrink")

        with self.assertRaisesRegex(module.EngineeringError, "Unexpected shrink"):
            module.construct_checkpoint(root, second_commit, first_commit)

        self.assertEqual(first_bytes, first_path.read_bytes())
        with self.assertRaises(module.EngineeringError):
            module._checkpoint_path(root, second_commit)

    def test_rebuild_failure_retains_previous_atomic_checkpoint(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root)
        first_commit = self.commit_all(root, "covered overlay")
        self.git(root, "update-ref", "refs/remotes/origin/main", first_commit)
        fake_graphify = self.write_fake_graphify()
        environment = {
            "PYTHONPATH": str(fake_graphify),
        }
        with patch.dict(os.environ, environment, clear=False):
            first_path = module.rebuild(root, first_commit, sys.executable)
        first_checkpoint = first_path.read_bytes()
        first_graph = (first_path.parent / "graph.json").read_bytes()
        (root / "README.md").write_text("# Changed\n", encoding="utf-8")
        second_commit = self.commit_all(root, "changed source")

        self.set_fake_graphify_controls(FAKE_GRAPHIFY_FAIL="1")
        with patch.dict(os.environ, environment, clear=False):
            with self.assertRaises(module.EngineeringError):
                module.rebuild(root, second_commit, sys.executable)

        self.assertEqual(first_checkpoint, first_path.read_bytes())
        self.assertEqual(first_graph, (first_path.parent / "graph.json").read_bytes())
        expected = (
            module._common_graph_dir(root)
            / "features"
            / "main"
            / second_commit
        )
        self.assertFalse(expected.exists())

    def test_all_provenance_classes_have_exact_coverage_semantics(self):
        module = self.module()
        expected = {
            "direct": (True, ["DEC-1", "CODE-1", "TEST-1"], []),
            "derived": (True, ["DEC-1", "CODE-1", "TEST-1"], []),
            "inferred": (False, [], ["DEC-1", "CODE-1", "TEST-1"]),
            "missing": (False, [], []),
        }
        for provenance, (covered, exact, suggested) in expected.items():
            with self.subTest(provenance=provenance):
                root = self.init_repo(provenance)
                self.write_controls(root, provenance=provenance)
                commit = self.commit_all(root, f"{provenance} overlay")
                module.construct_checkpoint(root, commit, None)
                checkpoint = module._load_checkpoint(root, commit)

                coverage = module.coverage(checkpoint)
                impact = module.query_result("impact", checkpoint, "REQ-1")

                self.assertEqual(covered, coverage[0]["covered"])
                self.assertEqual(exact, impact["exact"])
                self.assertEqual(suggested, impact["suggested"])

    def test_hook_project_identity_uses_tracked_manifest(self):
        module = self.module()
        resolver = getattr(module, "resolve_hook_project", None)
        self.assertTrue(callable(resolver))
        for generation in ("v1", "v2"):
            with self.subTest(generation=generation):
                root = self.init_repo(generation)
                self.write_controls(root, generation=generation)
                manifest_path, _ = self.control_paths(root, generation)
                self.assertIsNone(resolver(root))
                self.git(root, "add", manifest_path.name)
                self.assertEqual(root.resolve(), resolver(root).root)

    def test_hook_downstream_operations_use_indexed_manifest_identity(self):
        module = self.module()
        fake_graphify = self.write_fake_graphify()
        for generation in ("v1", "v2"):
            for event in ("post-commit", "pre-push"):
                with self.subTest(generation=generation, event=event):
                    root = self.init_repo(f"{generation}-{event}")
                    self.write_controls(root, generation=generation)
                    commit = self.commit_all(root, f"tracked {generation} controls")
                    environment = {"PYTHONPATH": str(fake_graphify)}
                    if event == "pre-push":
                        with patch.dict(os.environ, environment, clear=False):
                            module.rebuild(root, commit, sys.executable)
                    opposite = "v2" if generation == "v1" else "v1"
                    opposite_manifest, _ = self.control_paths(root, opposite)
                    opposite_manifest.write_text(
                        '{"version": 1}\n', encoding="utf-8"
                    )

                    with patch.dict(os.environ, environment, clear=False):
                        result = module.handle_hook(event, root, sys.executable)

                    if event == "post-commit":
                        self.assertEqual("stale", result["action"])
                        self.assertEqual("hook_budget_exceeded", result["reason"])
                        self.assertEqual(commit, result["commit"])
                    else:
                        self.assertEqual("validate", result["action"])
                        self.assertIn(commit, result["checkpoint"])

    def test_local_pre_commit_does_not_require_remote_head(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root, generation="v2")
        self.commit_all(root, "local controls")
        self.git(root, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        self.git(root, "update-ref", "-d", "refs/remotes/origin/main")

        result = module.handle_hook("pre-commit", root, sys.executable)

        self.assertEqual({"event": "pre-commit", "action": "validate"}, result)

    def test_post_merge_rejects_missing_or_invalid_default_branch(self):
        module = self.module()
        invalid_values = (("missing", None), ("empty", ""), ("non-string", 7))
        for generation in ("v1", "v2"):
            for case, value in invalid_values:
                with self.subTest(generation=generation, case=case):
                    root = self.init_repo(f"{generation}-{case}")
                    self.write_controls(root, generation=generation)
                    manifest_path, _ = self.control_paths(root, generation)
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if case == "missing":
                        manifest["project"].pop("default_branch")
                    else:
                        manifest["project"]["default_branch"] = value
                    manifest_path.write_text(
                        json.dumps(manifest), encoding="utf-8"
                    )
                    self.git(root, "add", "-A")

                    with self.assertRaisesRegex(
                        module.EngineeringError,
                        "invalid_manifest.*default_branch",
                    ):
                        module.handle_hook("post-merge", root, sys.executable)

    def test_hook_is_no_op_for_sanitized_and_export_repositories(self):
        module = self.module()
        for kind in ("sanitized", "export"):
            with self.subTest(kind=kind):
                root = self.init_repo(kind)

                result = module.handle_hook("pre-commit", root, sys.executable)

                self.assertEqual(
                    {
                        "event": "pre-commit",
                        "action": "no_op",
                        "reason": "manifest_not_tracked",
                    },
                    result,
                )

    def test_hook_is_no_op_for_manifest_free_peer_worktree(self):
        module = self.module()
        root = self.init_repo("main")
        self.write_controls(root)
        self.commit_all(root, "main controls")
        peer = Path(self.temporary_directory.name) / "peer"
        self.git(root, "worktree", "add", "-b", "peer", str(peer))
        self.addCleanup(
            lambda: subprocess.run(
                ["git", "-C", str(root), "worktree", "remove", "--force", str(peer)],
                capture_output=True,
                text=True,
            )
        )
        manifest_path, trace_dir = self.control_paths(peer, "v1")
        manifest_path.unlink()
        shutil.rmtree(trace_dir)
        self.git(peer, "add", "-A")

        result = module.handle_hook("pre-commit", peer, sys.executable)

        self.assertEqual("manifest_not_tracked", result["reason"])

    def test_hook_fails_closed_for_invalid_tracked_controls(self):
        module = self.module()
        defects = (
            "invalid_manifest",
            "missing_ledger",
            "invalid_ledger",
            "missing_links",
            "invalid_links",
            "missing_governed_artifact",
            "invalid_governed_artifact",
        )
        for generation in ("v1", "v2"):
            for defect in defects:
                with self.subTest(generation=generation, defect=defect):
                    root = self.init_repo(f"{generation}-{defect}")
                    self.write_controls(root, generation=generation)
                    manifest_path, trace_dir = self.control_paths(root, generation)
                    if defect == "invalid_manifest":
                        manifest_path.write_text("{", encoding="utf-8")
                    elif defect == "missing_ledger":
                        (trace_dir / "decision-ledger.md").unlink()
                    elif defect == "invalid_ledger":
                        (trace_dir / "decision-ledger.md").write_text(
                            "not a heading\n", encoding="utf-8"
                        )
                    elif defect == "missing_links":
                        (trace_dir / "links.json").unlink()
                    elif defect == "invalid_links":
                        (trace_dir / "links.json").write_text("{", encoding="utf-8")
                    elif defect == "missing_governed_artifact":
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        manifest["inputs"].append("governed.txt")
                        manifest_path.write_text(
                            json.dumps(manifest), encoding="utf-8"
                        )
                    else:
                        links_path = trace_dir / "links.json"
                        links = json.loads(links_path.read_text(encoding="utf-8"))
                        links["nodes"][0]["source"]["line"] = 999
                        links_path.write_text(json.dumps(links), encoding="utf-8")
                    self.git(root, "add", "-A")

                    with self.assertRaisesRegex(module.EngineeringError, defect):
                        module.handle_hook("pre-commit", root, sys.executable)

    def test_canonical_and_feature_checkpoints_remain_separate(self):
        module = self.module()
        root = self.init_repo("main")
        self.write_controls(root)
        main_commit = self.commit_all(root, "main overlay")
        self.git(root, "update-ref", "refs/remotes/origin/main", main_commit)
        canonical = module.construct_checkpoint(root, main_commit, None)
        linked = Path(self.temporary_directory.name) / "linked"
        self.git(root, "worktree", "add", "-b", "feature/example", str(linked))
        self.addCleanup(
            lambda: subprocess.run(
                ["git", "-C", str(root), "worktree", "remove", "--force", str(linked)],
                capture_output=True,
                text=True,
            )
        )
        (linked / "README.md").write_text("# Feature\n", encoding="utf-8")
        feature_commit = self.commit_all(linked, "feature change")
        feature = module.construct_checkpoint(linked, feature_commit, None)

        self.assertIn("main", canonical.parts)
        self.assertIn("features", feature.parts)
        self.assertNotEqual(canonical, feature)


class Task3ContractTests(unittest.TestCase):
    def setUp(self):
        Task2ContractTests.setUp(self)

    module = Task2ContractTests.module
    init_repo = Task2ContractTests.init_repo
    git = Task2ContractTests.git
    commit_all = Task2ContractTests.commit_all
    write_controls = Task2ContractTests.write_controls
    write_fake_graphify = Task2ContractTests.write_fake_graphify
    write_canonical_checkpoint = Task2ContractTests.write_canonical_checkpoint
    recover_fixture_checkpoint = Task2ContractTests.recover_fixture_checkpoint
    start_fake_graphify_interpreter = Task2ContractTests.start_fake_graphify_interpreter
    set_fake_graphify_controls = Task2ContractTests.set_fake_graphify_controls

    def graphify_environment(self, fake_graphify: Path, **extra: str) -> dict[str, str]:
        self.set_fake_graphify_controls(
            **{
                name: value
                for name, value in extra.items()
                if name.startswith("FAKE_GRAPHIFY_")
            }
        )
        return extra

    def adversarial_graphify_environment(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return a fixed runtime baseline plus values Graphify must never inherit."""
        temporary = Path(self.temporary_directory.name) / "graphify-runtime"
        temporary.mkdir(exist_ok=True)
        runtime = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get(
                "SYSTEMROOT", os.environ.get("SystemRoot", r"C:\\Windows")
            ),
            "WINDIR": os.environ.get("WINDIR", r"C:\\Windows"),
            "COMSPEC": os.environ.get("COMSPEC", r"C:\\Windows\\System32\\cmd.exe"),
            "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "LANG": "C",
            "LC_ALL": "C",
            "LC_CTYPE": "C",
            "TZ": "UTC",
        }
        forbidden = {
            "AWS_ACCESS_KEY_ID": "synthetic-aws-access-key",
            "AWS_PROFILE": "synthetic-aws-profile",
            "HTTPS_PROXY": "https://credential:synthetic-password@127.0.0.1:8080",
            "GIT_ASKPASS": "synthetic-git-askpass",
            "SSH_AUTH_SOCK": "synthetic-ssh-agent",
            "AZURE_CLIENT_ID": "synthetic-azure-client",
            "PYTHONPATH": "synthetic-untrusted-import-path",
            "UNRELATED_APPLICATION_STATE": "synthetic-unknown-secret",
            "OPENAI_API_KEY": "synthetic-provider-secret",
            "GRAPHIFY_OUT": "spoofed-output",
        }
        return runtime, forbidden

    def governed_repo(self, name: str = "governed") -> Path:
        root = self.init_repo(name)
        self.write_controls(root, generation="v2")
        commit = self.commit_all(root, "engineering controls")
        self.git(root, "update-ref", "refs/remotes/origin/main", commit)
        return root

    def add_linked_worktree(self, root: Path, branch: str = "feature/example") -> Path:
        linked = Path(self.temporary_directory.name) / branch.replace("/", "-")
        self.git(root, "worktree", "add", "-b", branch, str(linked))
        self.addCleanup(
            lambda: subprocess.run(
                ["git", "-C", str(root), "worktree", "remove", "--force", str(linked)],
                capture_output=True,
                text=True,
            )
        )
        return linked

    def commit_file(self, root: Path, relative: str, content: str) -> str:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return self.commit_all(root, f"change {relative}")

    def cold_checkpoint(self, root: Path) -> tuple[Path, dict[str, str]]:
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            result = self.module().rebuild(root, sys.executable)
        self.assertEqual("full", result["mode"])
        return fake, environment

    def test_all_worktrees_share_one_git_common_graph_root(self):
        module = self.module()
        root = self.governed_repo()
        linked = self.add_linked_worktree(root)

        self.assertEqual(
            module.common_graph_dir(root),
            module.common_graph_dir(linked),
        )

    def test_controller_git_and_project_resolution_ignore_hostile_git_routing(self):
        """Ordinary controller Git calls stay bound to each requested project."""
        module = self.module()
        internal = self.init_repo("routing-internal")
        public = self.init_repo("routing-public")
        injected = {
            "GIT_DIR": str(public / ".git"),
            "GIT_WORK_TREE": str(public),
            "GIT_COMMON_DIR": str(public / ".git"),
            "GIT_OBJECT_DIRECTORY": str(public / ".git" / "objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(public / ".git" / "objects"),
            "GIT_INDEX_FILE": str(public / ".git" / "hostile.index"),
            "GIT_PREFIX": str(public),
            "GIT_CEILING_DIRECTORIES": str(public.parent),
            "GIT_DISCOVERY_ACROSS_FILESYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(public / "hostile.gitconfig"),
            "GIT_CONFIG_SYSTEM": str(public / "hostile-system.gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "0",
            "GIT_REPLACE_REF_BASE": "refs/heads",
            "GIT_NO_REPLACE_OBJECTS": "0",
        }

        with patch.dict(os.environ, injected, clear=False):
            self.assertEqual(
                internal.resolve(),
                Path(module.git(internal, "rev-parse", "--show-toplevel")).resolve(),
            )
            self.assertEqual(
                public.resolve(),
                Path(module.git(public, "rev-parse", "--show-toplevel")).resolve(),
            )
            self.assertEqual(internal.resolve(), module.resolve_project_root(str(internal)))
            self.assertEqual(public.resolve(), module.resolve_project_root(str(public)))

    def test_three_worktrees_share_one_common_cache_root(self):
        module = self.module()
        root = self.governed_repo()
        first = self.add_linked_worktree(root, "feature/one")
        second = self.add_linked_worktree(root, "feature/two")

        self.assertEqual(
            {module.common_graph_dir(root)},
            {
                module.common_graph_dir(root),
                module.common_graph_dir(first),
                module.common_graph_dir(second),
            },
        )

    def test_feature_rebuild_never_publishes_canonical(self):
        module = self.module()
        root = self.governed_repo()
        feature = self.add_linked_worktree(root)
        fake = self.write_fake_graphify()

        with patch.dict(
            os.environ, self.graphify_environment(fake), clear=False
        ):
            result = module.rebuild(feature, sys.executable)

        checkpoint = Path(result["checkpoint"])
        self.assertIn("features", checkpoint.parts)
        self.assertNotIn("main", checkpoint.parts)

    def test_invalid_checkpoint_is_losslessly_quarantined_before_regeneration(self):
        module = self.module()
        root = self.governed_repo("invalid-checkpoint-quarantine")
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            first = module.rebuild(root, sys.executable)
        self.assertEqual("full", first["mode"])
        commit = self.git(root, "rev-parse", "HEAD")
        destination = module._checkpoint_path(root, commit)
        marker = destination.parent / "opaque-preserved.bin"
        marker.write_bytes(b"synthetic-preserved-bytes\x00")
        invalid = json.loads(destination.read_text(encoding="utf-8"))
        invalid["metadata"]["project_identity"] = "0" * 64
        destination.write_text(json.dumps(invalid), encoding="utf-8")
        before = {
            path.relative_to(destination.parent).as_posix(): path.read_bytes()
            for path in destination.parent.rglob("*")
            if path.is_file()
        }

        with patch.dict(os.environ, environment, clear=False):
            result = module.rebuild(root, sys.executable)

        self.assertEqual("current", result["freshness"])
        quarantine = result["quarantine"]
        self.assertEqual("root_binding_mismatch", quarantine["reason"])
        quarantine_path = module.common_graph_dir(root) / quarantine["relative_path"]
        self.assertEqual(
            before,
            {
                path.relative_to(quarantine_path).as_posix(): path.read_bytes()
                for path in quarantine_path.rglob("*")
                if path.is_file()
            },
        )
        self.assertTrue(module.validate_checkpoint(root, destination, commit)["valid"])
        catalogue = module.graph_checkpoint_catalogue(root)
        self.assertIn(
            quarantine["relative_path"],
            [item["relative_path"] for item in catalogue["quarantined"]],
        )

    def test_failed_regeneration_rolls_back_quarantined_checkpoint_losslessly(self):
        module = self.module()
        root = self.governed_repo("invalid-checkpoint-rollback")
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            first = module.rebuild(root, sys.executable)
        self.assertEqual("full", first["mode"])
        commit = self.git(root, "rev-parse", "HEAD")
        destination = module._checkpoint_path(root, commit)
        invalid = json.loads(destination.read_text(encoding="utf-8"))
        invalid["metadata"]["project_identity"] = "0" * 64
        destination.write_text(json.dumps(invalid), encoding="utf-8")
        before = {
            path.relative_to(destination.parent).as_posix(): path.read_bytes()
            for path in destination.parent.rglob("*")
            if path.is_file()
        }

        quarantined = module._quarantine_invalid_checkpoint(
            root, destination, commit, branch="main", kind="canonical"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.assertEqual(
            {"restored": True, "already_regenerated": False},
            module._restore_quarantined_checkpoint(root, quarantined),
        )

        self.set_fake_graphify_controls(FAKE_GRAPHIFY_FAIL="1")
        with patch.dict(
            os.environ, {**environment, "FAKE_GRAPHIFY_FAIL": "1"}, clear=False
        ):
            result = module.rebuild(root, sys.executable)

        self.assertEqual("stale", result["freshness"])
        self.assertIn(result["reason"], {"EngineeringError", "graphify_adapter_failed"})
        self.assertEqual(
            before,
            {
                path.relative_to(destination.parent).as_posix(): path.read_bytes()
                for path in destination.parent.rglob("*")
                if path.is_file()
            },
        )
        catalogue = module.graph_checkpoint_catalogue(root)
        self.assertTrue(catalogue["quarantined"])
        self.assertEqual("root_binding_mismatch", catalogue["quarantined"][0]["reason"])

    def test_legacy_rebuild_quarantines_invalid_immutable_address(self):
        module = self.module()
        root = self.governed_repo("legacy-invalid-checkpoint-quarantine")
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        commit = self.git(root, "rev-parse", "HEAD")
        with patch.dict(os.environ, environment, clear=False):
            first = module.rebuild(root, commit, sys.executable)
        destination = module._checkpoint_destination(
            root, commit, branch="main", kind="feature"
        )
        self.assertEqual(destination, first)
        invalid = json.loads(destination.read_text(encoding="utf-8"))
        invalid["metadata"]["project_identity"] = "0" * 64
        destination.write_text(json.dumps(invalid), encoding="utf-8")

        with patch.dict(os.environ, environment, clear=False):
            rebuilt = module.rebuild(root, commit, sys.executable)

        self.assertEqual(destination, rebuilt)
        self.assertTrue(module.validate_checkpoint(root, destination, commit)["valid"])

    def test_legacy_rebuild_uses_exact_credentialless_graphify_environment(self):
        """Legacy rebuild passes only the fixed runtime environment to Graphify."""
        module = self.module()
        root = self.governed_repo("legacy-rebuild-exact-environment")
        commit = self.git(root, "rev-parse", "HEAD")
        captured = []
        original_run = module.run

        def capture_graphify_environment(command, *args, **kwargs):
            if command[1:4] == ["-m", "graphify", "update"]:
                captured.append(dict(kwargs["env"]))
                output = Path(kwargs["env"]["GRAPHIFY_OUT"])
                snapshot = Path(command[-1])
                output.mkdir(parents=True, exist_ok=True)
                (output / "graph.json").write_text(
                    json.dumps(
                        {
                            "directed": True,
                            "multigraph": False,
                            "graph": {},
                            "nodes": [],
                            "links": [],
                            "built_at_commit": module.git(snapshot, "rev-parse", "HEAD"),
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0)
            return original_run(command, *args, **kwargs)

        runtime, forbidden = self.adversarial_graphify_environment()
        with (
            patch.dict(os.environ, {**runtime, **forbidden}, clear=True),
            patch.object(
                module,
                "verify_graphify",
                return_value=module.GraphifyIdentity(
                    Path(sys.executable),
                    module.GRAPHIFY_REPOSITORY,
                    module.GRAPHIFY_VERSION,
                    module.GRAPHIFY_COMMIT,
                    module.REQUIRED_GRAPHIFY_COMMANDS,
                ),
            ),
            patch.object(module, "run", side_effect=capture_graphify_environment),
        ):
            module.rebuild(root, commit, sys.executable)

        self.assertEqual(1, len(captured))
        self.assertEqual(
            {**runtime, "GRAPHIFY_OUT": captured[0]["GRAPHIFY_OUT"]}, captured[0]
        )
        for name in forbidden:
            if name == "GRAPHIFY_OUT":
                self.assertNotEqual(forbidden[name], captured[0][name])
                continue
            with self.subTest(name=name):
                self.assertNotIn(name, captured[0])

    def test_current_rebuild_uses_exact_credentialless_graphify_environment(self):
        """Current cold rebuild passes the same fixed environment to its child."""
        module = self.module()
        root = self.governed_repo("current-rebuild-exact-environment")
        commit = self.git(root, "rev-parse", "HEAD")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            {
                "root": str(root),
                "commit": commit,
                "branch": "main",
                "kind": "canonical",
                "manifest_name": "engineering.json",
                "hook": False,
                "authority": {"branch": "main", "remote": None},
            }
        )
        module._write_operation(record)
        captured = []
        adapter_environments = []
        original_run = module.run

        def capture_graphify_environment(command, *args, **kwargs):
            if command[1:4] == ["-m", "graphify", "update"]:
                captured.append(dict(kwargs["env"]))
                output = Path(kwargs["env"]["GRAPHIFY_OUT"])
                snapshot = Path(command[-1])
                output.mkdir(parents=True, exist_ok=True)
                (output / "graph.json").write_text(
                    json.dumps(
                        {
                            "directed": True,
                            "multigraph": False,
                            "graph": {},
                            "nodes": [],
                            "links": [],
                            "built_at_commit": module.git(snapshot, "rev-parse", "HEAD"),
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0)
            return original_run(command, *args, **kwargs)

        def capture_adapter_environment():
            adapter_environments.append(dict(os.environ))
            return ({"version": module.GRAPHIFY_VERSION, "code_extensions": []}, object())

        runtime, forbidden = self.adversarial_graphify_environment()
        with (
            patch.dict(os.environ, {**runtime, **forbidden}, clear=True),
            patch.object(
                module,
                "_verify_graphify_adapter_in_process",
                side_effect=capture_adapter_environment,
            ),
            patch.object(module, "_compatible_ancestor", return_value=None),
            patch.object(module, "_mutate_maintenance_locked", return_value=None),
            patch.object(module, "run", side_effect=capture_graphify_environment),
        ):
            self.assertEqual(0, module._graph_worker_entry(root, operation["operation_id"]))

        self.assertEqual(1, len(captured))
        self.assertEqual(
            {**runtime, "GRAPHIFY_OUT": captured[0]["GRAPHIFY_OUT"]}, captured[0]
        )
        self.assertEqual(
            {**runtime, "GRAPHIFY_OUT": captured[0]["GRAPHIFY_OUT"]},
            adapter_environments[0],
        )
        for name in forbidden:
            if name == "GRAPHIFY_OUT":
                self.assertNotEqual(forbidden[name], captured[0][name])
                continue
            with self.subTest(name=name):
                self.assertNotIn(name, captured[0])

    def test_incremental_outer_worker_uses_exact_environment_before_python_start(self):
        """The worker cannot resolve Graphify from ambient proxy, Git, or Python paths."""
        module = self.module()
        runtime, forbidden = self.adversarial_graphify_environment()
        captured = []

        def capture_start(command, **kwargs):
            captured.append((list(command), dict(kwargs.get("env", {}))))
            return object()

        with (
            patch.dict(os.environ, {**runtime, **forbidden}, clear=True),
            patch.object(module.subprocess, "Popen", side_effect=capture_start),
        ):
            module._start_worker([sys.executable, "-c", "import graphify"])

        self.assertEqual(
            [[sys.executable, "-B", "-c", "import graphify"]],
            [item[0] for item in captured],
        )
        self.assertEqual(runtime, captured[0][1])
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, captured[0][1])

    def test_incremental_outer_worker_cannot_write_python_bytecode(self):
        """A worker cannot mutate its source checkout through import caches."""
        module = self.module()
        runtime, _ = self.adversarial_graphify_environment()
        source = Path(self.temporary_directory.name) / "worker-import"
        source.mkdir()
        (source / "worker_probe.py").write_text("VALUE = 1\n", encoding="utf-8")
        cwd_before = Path.cwd()
        try:
            os.chdir(source)
            with patch.dict(os.environ, runtime, clear=True):
                process = module._start_worker(
                    [sys.executable, "-c", "import worker_probe"]
                )
                stdout, stderr = process.communicate(timeout=30)
        finally:
            os.chdir(cwd_before)

        self.assertEqual("", stdout)
        self.assertEqual("", stderr)
        self.assertEqual(0, process.returncode)
        self.assertFalse((source / "__pycache__").exists())

    def test_incremental_outer_worker_cannot_import_graphify_from_ambient_pythonpath(self):
        """The strict worker environment applies before the child resolves Graphify."""
        module = self.module()
        runtime, forbidden = self.adversarial_graphify_environment()
        untrusted = Path(self.temporary_directory.name) / "untrusted-graphify"
        package = untrusted / "graphify"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            "raise RuntimeError('ambient PYTHONPATH graphify loaded')\n",
            encoding="utf-8",
        )
        observed = Path(self.temporary_directory.name) / "resolved-graphify.txt"
        script = (
            "import graphify,pathlib,sys;"
            "pathlib.Path(sys.argv[1]).write_text(graphify.__file__,encoding='utf-8')"
        )

        with patch.dict(
            os.environ,
            {**runtime, **forbidden, "PYTHONPATH": str(untrusted)},
            clear=True,
        ):
            process = module._start_worker([sys.executable, "-c", script, str(observed)])
            stdout, stderr = process.communicate(timeout=30)

        self.assertEqual("", stdout)
        self.assertEqual("", stderr)
        self.assertEqual(0, process.returncode)
        self.assertTrue(observed.is_file())
        self.assertNotIn(str(untrusted), observed.read_text(encoding="utf-8"))

    def test_graph_worker_restores_host_environment_after_early_stale_return(self):
        """The in-process worker cannot leak its reduced environment to its caller."""
        module = self.module()
        root = self.governed_repo("graph-worker-environment-restoration")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            {
                "root": str(root),
                "commit": self.git(root, "rev-parse", "HEAD"),
                "branch": "main",
                "kind": "canonical",
                "manifest_name": "engineering.json",
                "hook": True,
                "authority": {"branch": "main", "remote": None},
            }
        )
        module._write_operation(record)
        runtime, forbidden = self.adversarial_graphify_environment()
        host_environment = {**runtime, **forbidden}

        with (
            patch.dict(os.environ, host_environment, clear=True),
            patch.object(
                module,
                "_verify_graphify_adapter_in_process",
                return_value=({"version": module.GRAPHIFY_VERSION, "code_extensions": []}, object()),
            ),
            patch.object(module, "_compatible_ancestor", return_value=None),
            patch.object(module, "_semantic_changes", return_value=[]),
            patch.object(module, "_queue_graph_worker_stale", return_value=None),
        ):
            self.assertEqual(0, module._graph_worker_entry(root, operation["operation_id"]))
            self.assertEqual(host_environment, dict(os.environ))

    def test_recover_checkpoint_returns_machine_recovery_envelope(self):
        module = self.module()
        root = self.governed_repo("checkpoint-recovery-command")
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            first = module.rebuild(root, sys.executable)
        commit = self.git(root, "rev-parse", "HEAD")
        destination = module._checkpoint_path(root, commit)
        invalid = json.loads(destination.read_text(encoding="utf-8"))
        invalid["metadata"]["project_identity"] = "0" * 64
        destination.write_text(json.dumps(invalid), encoding="utf-8")

        with patch.dict(os.environ, environment, clear=False):
            result = module.recover_checkpoint(root, commit, sys.executable)

        self.assertEqual("engineering.checkpoint-recovery.v1", result["schema"])
        self.assertEqual("current", result["freshness"])
        self.assertEqual(commit, result["commit"])
        self.assertTrue(module.validate_checkpoint(root, destination, commit)["valid"])

    def test_recover_checkpoint_targets_canonical_address_in_remote_repo(self):
        module = self.module()
        root = self.governed_repo("remote-canonical-recovery")
        self.git(root, "remote", "add", "origin", "https://example.invalid/engineering.git")
        self.git(
            root,
            "config",
            "remote.origin.fetch",
            "+refs/heads/*:refs/remotes/origin/*",
        )
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            first = module.reconcile_canonical(
                root,
                refresh_remote=False,
                allow_cached_remote=True,
                graphify_python=sys.executable,
            )
        self.assertEqual("current", first["freshness"])
        commit = self.git(root, "rev-parse", "HEAD")
        destination = module._checkpoint_destination(
            root, commit, branch="main", kind="canonical"
        )
        invalid = json.loads(destination.read_text(encoding="utf-8"))
        invalid["metadata"]["project_identity"] = "0" * 64
        destination.write_text(json.dumps(invalid), encoding="utf-8")

        with patch.dict(os.environ, environment, clear=False):
            result = module.recover_checkpoint(root, commit, sys.executable)

        self.assertEqual("current", result["freshness"])
        self.assertIn("main", Path(result["checkpoint"]).parts)
        self.assertNotIn("features", Path(result["checkpoint"]).parts)
        self.assertTrue(module.validate_checkpoint(root, destination, commit)["valid"])

    def test_quarantine_catalogue_rejects_tampered_sidecar_identity(self):
        module = self.module()
        root = self.governed_repo("tampered-quarantine-record")
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            first = module.rebuild(root, sys.executable)
        commit = self.git(root, "rev-parse", "HEAD")
        destination = module._checkpoint_path(root, commit)
        invalid = json.loads(destination.read_text(encoding="utf-8"))
        invalid["metadata"]["project_identity"] = "0" * 64
        destination.write_text(json.dumps(invalid), encoding="utf-8")
        with patch.dict(os.environ, environment, clear=False):
            result = module.rebuild(root, sys.executable)
        quarantine_path = module.common_graph_dir(root) / result["quarantine"]["relative_path"]
        metadata_path = quarantine_path.with_name(quarantine_path.name + ".json")
        tampered = json.loads(metadata_path.read_text(encoding="utf-8"))
        tampered["commit"] = "../escape"
        metadata_path.write_text(json.dumps(tampered), encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "record_invalid|identity_invalid"):
            module.graph_checkpoint_catalogue(root)

    def test_empty_invalid_checkpoint_address_is_quarantined_and_regenerated(self):
        module = self.module()
        root = self.governed_repo("empty-invalid-checkpoint")
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            first = module.rebuild(root, sys.executable)
        commit = self.git(root, "rev-parse", "HEAD")
        destination = module._checkpoint_path(root, commit)
        shutil.rmtree(destination.parent)
        destination.parent.mkdir(parents=True)

        with patch.dict(os.environ, environment, clear=False):
            result = module.rebuild(root, sys.executable)

        self.assertEqual("current", result["freshness"])
        self.assertEqual(0, result["quarantine"]["file_count"])
        self.assertTrue(module.validate_checkpoint(root, destination, commit)["valid"])

    def test_exact_checkpoint_hit_skips_graphify_update(self):
        module = self.module()
        root = self.governed_repo()
        fake = self.write_fake_graphify()
        record = Path(self.temporary_directory.name) / "graphify-record.jsonl"
        environment = self.graphify_environment(
            fake, FAKE_GRAPHIFY_RECORD=str(record)
        )

        with patch.dict(os.environ, environment, clear=False):
            first = module.rebuild(root, sys.executable)
        first_calls = record.read_text(encoding="utf-8").splitlines()
        with patch.dict(
            os.environ,
            {**environment, "FAKE_GRAPHIFY_FAIL": "1"},
            clear=False,
        ):
            second = module.rebuild(root, sys.executable)

        self.assertEqual(first["checkpoint"], second["checkpoint"])
        self.assertEqual("exact_cache", second["mode"])
        self.assertEqual(first_calls, record.read_text(encoding="utf-8").splitlines())

    def test_nearest_compatible_ancestor_uses_update_for_changed_code(self):
        module = self.module()
        root = self.governed_repo()
        fake, environment = self.cold_checkpoint(root)
        record = Path(self.temporary_directory.name) / "incremental.jsonl"
        self.commit_file(root, "src/example.py", "changed = True\n")
        self.set_fake_graphify_controls(FAKE_GRAPHIFY_RECORD=str(record))

        with patch.dict(os.environ, environment, clear=False):
            result = module.rebuild(root, sys.executable)

        self.assertEqual("changed_path_adapter", result["mode"])
        self.assertEqual([], result["argv"])
        self.assertEqual(["src/example.py"], result["changed_files"])
        recorded = json.loads(record.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual("private_rebuild_code", recorded[0])
        self.assertEqual("src/example.py", recorded[-1].replace("\\", "/"))

    def test_hook_defers_semantic_and_document_media_changes(self):
        module = self.module()
        root = self.governed_repo()
        manifest_path = root / "engineering.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["graphify"]["hook_budget_seconds"] = 60
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.commit_all(root, "configure measured hook budget")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "docs/design.md", "# Changed meaning\n")

        with patch.dict(os.environ, environment, clear=False):
            result = module.dispatch_hook(
                root, "post-commit", graphify_python=sys.executable
            )

        self.assertEqual("stale", result["freshness"])
        self.assertEqual("semantic_update_deferred", result["reason"])

    def test_hook_budget_preserves_prior_checkpoint_and_marks_stale(self):
        module = self.module()
        root = self.governed_repo()
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            baseline = module.rebuild(
                root,
                sys.executable,
                cleanup_timeout_seconds=30,
            )
        self.assertEqual("full", baseline["mode"])
        prior = module._checkpoint_path(root, self.git(root, "rev-parse", "HEAD"))
        self.commit_file(root, "src/example.py", "changed = True\n")
        self.set_fake_graphify_controls(FAKE_GRAPHIFY_SLOW="120")

        with patch.dict(os.environ, environment, clear=False):
            result = module.rebuild(
                root,
                sys.executable,
                hook_budget_seconds=0.01,
                cleanup_timeout_seconds=30,
            )

        self.assertEqual("stale", result["freshness"])
        self.assertEqual("hook_budget_exceeded", result["reason"])
        self.assertTrue(result["previous_checkpoint_preserved"])
        self.assertTrue(prior.exists())

    def test_post_commit_uses_only_the_configured_hook_budget(self):
        module = self.module()
        root = self.governed_repo()
        manifest_path = root / "engineering.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["graphify"]["hook_budget_seconds"] = 60
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.commit_all(root, "configure measured hook budget")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/budgeted.py", "budgeted = True\n")

        captured = []

        def bounded_operation(*args, **kwargs):
            captured.append(kwargs["timeout_seconds"])
            return {"mode": "changed_path_adapter", "freshness": "current"}

        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(module, "_run_graph_operation", side_effect=bounded_operation),
        ):
            result = module.dispatch_hook(
                root, "post-commit", graphify_python=sys.executable
            )

        self.assertEqual("changed_path_adapter", result["mode"])
        self.assertEqual("current", result["freshness"])
        self.assertEqual(1, len(captured))
        self.assertGreater(captured[0], 0)
        self.assertLessEqual(captured[0], 60)

    def test_post_commit_never_runs_a_cold_full_rebuild(self):
        module = self.module()
        root = self.governed_repo()
        fake = self.write_fake_graphify()

        with patch.dict(
            os.environ, self.graphify_environment(fake), clear=False
        ):
            result = module.dispatch_hook(
                root, "post-commit", graphify_python=sys.executable
            )

        self.assertNotEqual("full", result["mode"])
        self.assertEqual("stale", result["freshness"])

    def test_two_clones_recreate_local_checkpoints_from_tracked_sources(self):
        module = self.module()
        source = self.governed_repo("source")
        first = Path(self.temporary_directory.name) / "clone-one"
        second = Path(self.temporary_directory.name) / "clone-two"
        self.git(source, "clone", str(source), str(first))
        self.git(source, "clone", str(source), str(second))

        self.assertNotEqual(
            module.common_graph_dir(first),
            module.common_graph_dir(second),
        )
        self.assertEqual(
            module.overlay_fingerprints(first),
            module.overlay_fingerprints(second),
        )

    def test_v2_has_no_enterprise_graph_import_config_or_argv_surface(self):
        source = ENGINEERING_SCRIPT.read_text(encoding="utf-8")
        imports = {
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        manifest = MANIFEST.read_text(encoding="utf-8").lower()

        self.assertFalse(any("enterprise" in item.lower() for item in imports))
        self.assertNotIn("enterprise_endpoint", source.lower())
        self.assertNotIn("enterprise_client", source.lower())
        self.assertNotIn("prefer-enterprise", manifest)
        self.assertNotIn("require-enterprise", manifest)

    def test_no_remote_uses_configured_local_default_branch(self):
        module = self.module()
        root = self.governed_repo()
        local_main = self.commit_file(root, "src/local.py", "local = True\n")

        result = module.reconcile_canonical(
            root, refresh_remote=False, graphify_python=sys.executable
        )

        self.assertEqual("not_configured", result["freshness"])
        self.assertEqual(local_main, result["commit"])

    def test_ambiguous_remotes_block_canonical_publication(self):
        module = self.module()
        root = self.governed_repo()
        self.git(root, "remote", "add", "origin", "https://example.test/one.git")
        self.git(root, "remote", "add", "upstream", "https://example.test/two.git")

        with self.assertRaisesRegex(module.EngineeringError, "remote"):
            module.reconcile_canonical(root, refresh_remote=False)

    def test_advanced_origin_main_rebuilds_without_active_main_worktree(self):
        module = self.module()
        root = self.governed_repo()
        feature = self.add_linked_worktree(root)
        self.git(root, "remote", "add", "origin", "https://example.test/origin.git")
        self.git(root, "checkout", "-b", "advance-main")
        advanced = self.commit_file(root, "src/advanced.py", "advanced = True\n")
        self.git(root, "update-ref", "refs/remotes/origin/main", advanced)
        fake = self.write_fake_graphify()

        with patch.dict(
            os.environ, self.graphify_environment(fake), clear=False
        ):
            result = module.reconcile_canonical(
                feature,
                refresh_remote=False,
                graphify_python=sys.executable,
            )

        self.assertEqual("unknown", result["freshness"])
        self.assertFalse(result["canonical_published"])

    def test_ci_rejects_stale_inexact_and_commit_mismatched_checkpoints(self):
        module = self.module()
        for state in ("stale", "inexact", "commit_mismatch"):
            with self.subTest(state=state):
                root = self.governed_repo(state)
                fake, _ = self.cold_checkpoint(root)
                if state == "stale":
                    module._record_stale(root, self.git(root, "rev-parse", "HEAD"), "test")
                elif state == "inexact":
                    Path(module._checkpoint_path(root, self.git(root, "rev-parse", "HEAD")).parent / "graph.json").unlink()
                else:
                    path = module._checkpoint_path(root, self.git(root, "rev-parse", "HEAD"))
                    checkpoint = json.loads(path.read_text(encoding="utf-8"))
                    checkpoint["metadata"]["commit"] = "0" * 40
                    path.write_text(json.dumps(checkpoint), encoding="utf-8")

                result = module.check_merge_readiness(root)

                self.assertFalse(result["ready"])
                expected = {
                    "stale": "stale",
                    "inexact": "invalid_json",
                    "commit_mismatch": "commit_mismatch",
                }[state]
                self.assertEqual(expected, result["reason"])

    def test_ci_accepts_exact_current_commit_checkpoint(self):
        module = self.module()
        root = self.governed_repo()
        self.cold_checkpoint(root)

        result = module.check_merge_readiness(root)

        self.assertTrue(result["ready"])

    def test_legacy_cleanup_requires_recognized_files_and_replacement(self):
        module = self.module()
        root = self.governed_repo()
        self.cold_checkpoint(root)
        exclude = Path(self.git(root, "rev-parse", "--git-path", "info/exclude"))
        if not exclude.is_absolute():
            exclude = root / exclude
        exclude.write_text("graphify-out/\n", encoding="utf-8")
        legacy = root / "graphify-out"
        legacy.mkdir()
        (legacy / "graph.json").write_text("{}\n", encoding="utf-8")
        (legacy / "graph.html").write_text("<html></html>\n", encoding="utf-8")

        candidate = module.inventory_legacy_outputs(root)[0]

        self.assertTrue(candidate["safe_generated"])
        self.assertTrue(module.clean_legacy_output(root, Path(candidate["path"])))
        self.assertFalse(legacy.exists())

    def test_unignored_legacy_output_is_never_deleted(self):
        module = self.module()
        root = self.governed_repo()
        self.cold_checkpoint(root)
        legacy = root / "graphify-out"
        legacy.mkdir()
        (legacy / "graph.json").write_text("{}\n", encoding="utf-8")

        candidate = module.inventory_legacy_outputs(root)[0]

        self.assertFalse(candidate["safe_generated"])
        self.assertFalse(module.clean_legacy_output(root, Path(candidate["path"])))
        self.assertTrue(legacy.exists())

    def test_unknown_legacy_output_is_preserved_and_queued(self):
        module = self.module()
        root = self.governed_repo()
        self.cold_checkpoint(root)
        legacy = root / "graphify-out"
        legacy.mkdir()
        (legacy / "graph.json").write_text("{}\n", encoding="utf-8")
        (legacy / "notes.txt").write_text("keep me\n", encoding="utf-8")

        candidate = module.inventory_legacy_outputs(root)[0]
        result = module.reconcile_legacy_outputs(root)

        self.assertFalse(candidate["safe_generated"])
        self.assertFalse(module.clean_legacy_output(root, Path(candidate["path"])))
        self.assertTrue((legacy / "notes.txt").exists())
        self.assertEqual("legacy_graph_ambiguous", result["maintenance"][0]["kind"])

    def test_cold_incremental_and_exact_cache_wall_times_are_recordable(self):
        module = self.module()
        root = self.governed_repo()
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)

        started = time.perf_counter()
        with patch.dict(os.environ, environment, clear=False):
            cold = module.rebuild(root, sys.executable)
        cold_seconds = time.perf_counter() - started
        self.commit_file(root, "src/timed.py", "value = 1\n")
        started = time.perf_counter()
        with patch.dict(os.environ, environment, clear=False):
            incremental = module.rebuild(root, sys.executable)
        incremental_seconds = time.perf_counter() - started
        started = time.perf_counter()
        with patch.dict(os.environ, environment, clear=False):
            exact = module.rebuild(root, sys.executable)
        exact_seconds = time.perf_counter() - started

        self.assertEqual(("full", "changed_path_adapter", "exact_cache"), (
            cold["mode"], incremental["mode"], exact["mode"]
        ))
        self.assertTrue(all(value >= 0 for value in (
            cold_seconds, incremental_seconds, exact_seconds
        )))
        print(
            "TASK3_CONTROLLER_STUB_PERF "
            f"cold={cold_seconds:.6f}s "
            f"incremental={incremental_seconds:.6f}s "
            f"exact_cache={exact_seconds:.6f}s"
        )


class Task3AmendedContractTests(unittest.TestCase):
    setUp = Task3ContractTests.setUp
    module = Task3ContractTests.module
    init_repo = Task3ContractTests.init_repo
    write_canonical_checkpoint = Task2ContractTests.write_canonical_checkpoint
    recover_fixture_checkpoint = Task2ContractTests.recover_fixture_checkpoint
    git = Task3ContractTests.git
    commit_all = Task3ContractTests.commit_all
    write_controls = Task3ContractTests.write_controls
    write_fake_graphify = Task3ContractTests.write_fake_graphify
    graphify_environment = Task3ContractTests.graphify_environment
    governed_repo = Task3ContractTests.governed_repo
    add_linked_worktree = Task3ContractTests.add_linked_worktree
    commit_file = Task3ContractTests.commit_file
    cold_checkpoint = Task3ContractTests.cold_checkpoint
    start_fake_graphify_interpreter = Task2ContractTests.start_fake_graphify_interpreter
    set_fake_graphify_controls = Task2ContractTests.set_fake_graphify_controls

    def create_test_reparse(self, link: Path, target: Path, *, directory: bool) -> bool:
        try:
            os.symlink(target, link, target_is_directory=directory)
            return True
        except OSError:
            if os.name != "nt" or not directory:
                return False
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        return created.returncode == 0

    def remove_test_reparse(self, link: Path, *, directory: bool) -> None:
        if not (link.exists() or link.is_symlink()):
            return
        if link.is_symlink() or not directory:
            link.unlink()
        else:
            os.rmdir(link)

    def semantic_suffix_source(self, suffix: str, version: int) -> str:
        name = f"semantic_symbol_{version}"
        normalized = suffix.lower()
        if normalized == ".json":
            return json.dumps({name: {"value": version}}) + "\n"
        if normalized in {".csproj", ".fsproj", ".vbproj"}:
            return (
                "<Project><PropertyGroup>"
                f"<AssemblyName>{name}</AssemblyName>"
                "</PropertyGroup></Project>\n"
            )
        if normalized == ".sln":
            return (
                "Microsoft Visual Studio Solution File, Format Version 12.00\n"
                f'Project("{{00000000-0000-0000-0000-000000000001}}") = '
                f'"{name}", "{name}.csproj", '
                '"{00000000-0000-0000-0000-000000000002}"\nEndProject\n'
            )
        if normalized == ".slnx":
            return f'<Solution><Project Path="{name}.csproj" /></Solution>\n'
        if normalized == ".xaml":
            return (
                f'<Window x:Class="Example.{name}" '
                'xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
                'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" />\n'
            )
        if normalized in {".py", ".rb", ".jl"}:
            return f"def {name}():\n    return {version}\n"
        if normalized == ".r":
            return f"{name} <- function() {{ {version} }}\n"
        if normalized in {".sh", ".bash"}:
            return f"{name}() {{ echo {version}; }}\n"
        if normalized in {".ps1", ".psm1"}:
            return f"function {name} {{ return {version} }}\n"
        if normalized == ".psd1":
            return f"@{{ RootModule = '{name}.psm1'; ModuleVersion = '1.0.{version}' }}\n"
        if normalized == ".sql":
            return f"CREATE TABLE {name} (id INTEGER);\n"
        if normalized in {
            ".vue", ".svelte", ".astro", ".razor", ".cshtml", ".ejs"
        }:
            return f"<script>function {name}() {{ return {version}; }}</script>\n"
        if normalized in {
            ".f", ".f03", ".f08", ".f90", ".f95"
        }:
            return f"subroutine {name}()\nend subroutine {name}\n"
        if normalized in {
            ".pas", ".pp", ".dpr", ".dpk", ".lpr", ".inc"
        }:
            return f"procedure {name}; begin end;\n"
        if normalized in {".tf", ".hcl"}:
            return f'resource "example" "{name}" {{ value = {version} }}\n'
        if normalized == ".tfvars":
            return f'{name} = "{version}"\n'
        if normalized == ".go":
            return f"package sample\nfunc {name}() int {{ return {version} }}\n"
        if normalized in {".js", ".jsx", ".mjs", ".ts", ".tsx", ".ets"}:
            return f"export function {name}() {{ return {version}; }}\n"
        if normalized == ".rs":
            return f"fn {name}() -> i32 {{ {version} }}\n"
        return f"int {name}(void) {{ return {version}; }}\n"

    def timed_out_registered_worker(self, module):
        test_case = self

        class TimedOutProcess:
            pid = 2_147_000_000

            def __init__(self, command):
                self.command = command
                self.dead = False

            def communicate(self, timeout=None):
                test_case.worker_timeout_seconds = timeout
                raise subprocess.TimeoutExpired(self.command, timeout)

            def poll(self):
                return 0 if self.dead else None

            def wait(self, timeout=None):
                self.dead = True
                return 0

            def kill(self):
                self.dead = True

            terminate = kill

        def start(command):
            root, operation_id = command[-2:]
            record_path = (
                module.common_graph_dir(Path(root))
                / "state"
                / "operations"
                / operation_id
                / "resources.json"
            )
            record = json.loads(record_path.read_text(encoding="utf-8"))
            worktree = Path(record["worktree_path"])
            stage = Path(record["staging_path"])
            worktree.mkdir()
            stage.mkdir()
            return TimedOutProcess(command)

        return start

    def test_pinned_changed_path_adapter_signature_is_exact(self):
        identity, _ = self.module()._verify_graphify_adapter_in_process()

        self.assertEqual("0.9.5", identity["version"])
        self.assertEqual(
            "d89ec68af95e0cad801b56d88df383991e659823",
            identity["commit"],
        )
        self.assertEqual(
            [
                "watch_path",
                "changed_paths",
                "follow_symlinks",
                "force",
                "no_cluster",
                "acquire_lock",
                "block_on_lock",
            ],
            identity["parameters"],
        )
        self.assertTrue(identity["changed_paths_keyword_only"])

    def test_incremental_refresh_has_no_suffix_table_or_per_file_public_cli(self):
        module = self.module()
        source = ENGINEERING_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertFalse(hasattr(module, "CODE_SUFFIXES"))
        self.assertIn("_rebuild_code", source)
        self.assertIn("changed_paths=[Path(path) for path in changed]", source)
        self.assertIn("run_full_graph_maintenance", source)

    def test_stub_incremental_adapter_receives_git_a_m_d_r_paths_once(self):
        module = self.module()
        root = self.governed_repo()
        (root / "src").mkdir()
        (root / "src" / "modify.py").write_text("value = 1\n", encoding="utf-8")
        (root / "src" / "delete.py").write_text("gone = 1\n", encoding="utf-8")
        (root / "src" / "rename.py").write_text("old = 1\n", encoding="utf-8")
        self.commit_all(root, "baseline code")
        fake, environment = self.cold_checkpoint(root)
        record = Path(self.temporary_directory.name) / "private-adapter.jsonl"
        (root / "src" / "add.mjs").write_text("export const added = 1;\n", encoding="utf-8")
        (root / "src" / "modify.py").write_text("value = 2\n", encoding="utf-8")
        (root / "src" / "delete.py").unlink()
        self.git(root, "mv", "src/rename.py", "src/renamed.py")
        target = self.commit_all(root, "a m d r")
        self.set_fake_graphify_controls(FAKE_GRAPHIFY_RECORD=str(record))

        with patch.dict(os.environ, environment, clear=False):
            result = module.rebuild(root, sys.executable, target_commit=target)

        self.assertTrue(record.is_file(), result)
        adapter_call = json.loads(record.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual("changed_path_adapter", result["mode"])
        self.assertEqual("private_rebuild_code", adapter_call[0])
        self.assertEqual(
            {
                "src/add.mjs",
                "src/delete.py",
                "src/modify.py",
                "src/rename.py",
                "src/renamed.py",
            },
            set(result["changed_paths"]),
        )
        self.assertEqual(target, result["built_at_commit"])
        self.assertEqual(Path(result["snapshot"]), Path(result["child_cwd"]))

    def test_real_pinned_adapter_matches_cold_graph_for_a_m_d_r(self):
        module = self.module()
        root = self.governed_repo("real-adapter")
        (root / "src").mkdir()
        (root / "src" / "modify.py").write_text(
            "def modify(value):\n    return value + 1\n", encoding="utf-8"
        )
        (root / "src" / "delete.py").write_text(
            "def deleted():\n    return True\n", encoding="utf-8"
        )
        (root / "src" / "rename.py").write_text(
            "def renamed():\n    return 'old'\n", encoding="utf-8"
        )
        self.commit_all(root, "real graph baseline")
        module.rebuild(root, sys.executable)
        (root / "src" / "add.py").write_text(
            "def added():\n    return 1\n", encoding="utf-8"
        )
        (root / "src" / "modify.py").write_text(
            "def modify(value):\n    return value + 2\n", encoding="utf-8"
        )
        (root / "src" / "delete.py").unlink()
        self.git(root, "mv", "src/rename.py", "src/renamed.py")
        target = self.commit_all(root, "real a m d r")

        started = time.monotonic()
        incremental = module.rebuild(root, sys.executable)
        incremental_seconds = time.monotonic() - started
        cold_root = Path(self.temporary_directory.name) / "real-cold"
        self.git(root, "clone", str(root), str(cold_root))
        started = time.monotonic()
        cold = module.rebuild(cold_root, sys.executable)
        cold_seconds = time.monotonic() - started
        started = time.monotonic()
        exact = module.rebuild(root, sys.executable)
        exact_seconds = time.monotonic() - started

        def digest(result):
            graph = json.loads(
                (Path(result["checkpoint"]).parent / "graph.json").read_text(
                    encoding="utf-8"
                )
            )
            comparable = {
                "nodes": sorted(
                    graph["nodes"], key=lambda item: json.dumps(item, sort_keys=True)
                ),
                "links": sorted(
                    graph.get("links", graph.get("edges", [])),
                    key=lambda item: json.dumps(item, sort_keys=True),
                ),
            }
            return hashlib.sha256(
                json.dumps(comparable, sort_keys=True).encode("utf-8")
            ).hexdigest()

        self.assertEqual(
            "changed_path_adapter", incremental["mode"], incremental
        )
        self.assertEqual(target, incremental["built_at_commit"])
        self.assertEqual(
            {
                "src/add.py",
                "src/delete.py",
                "src/modify.py",
                "src/rename.py",
                "src/renamed.py",
            },
            set(incremental["changed_paths"]),
        )
        self.assertEqual(digest(cold), digest(incremental))
        self.assertEqual("exact_cache", exact["mode"])
        print(
            "TASK3_REAL_GRAPHIFY_PERF "
            f"cold={cold_seconds:.6f}s "
            f"changed_path_adapter={incremental_seconds:.6f}s "
            f"exact_cache={exact_seconds:.6f}s"
        )

    def test_real_pinned_adapter_covers_every_supported_suffix_and_matches_cold(self):
        module = self.module()
        identity, _ = module._verify_graphify_adapter_in_process()
        # This contract exercises the real adapter surface.  Give the isolated
        # child fixture the same pinned suffix inventory so its pre-flight
        # semantic classifier cannot disagree with the inspected adapter.
        (self.fake_graphify_control.parent / "detect.py").write_text(
            "CODE_EXTENSIONS = {"
            + ", ".join(repr(suffix) for suffix in identity["code_extensions"])
            + "}\n",
            encoding="utf-8",
        )
        root = self.governed_repo("all-suffixes")
        suffix_root = root / "suffixes"
        suffix_root.mkdir()
        (suffix_root / "anchor.py").write_text(
            "def anchor():\n    return 1\n", encoding="utf-8"
        )
        paths = []
        for index, suffix in enumerate(identity["code_extensions"]):
            paths.append(suffix_root / f"sample_{index:03d}{suffix}")
        self.commit_all(root, "all suffix baseline")
        baseline_result = module.rebuild(root, sys.executable)
        baseline_graph = json.loads(
            (Path(baseline_result["checkpoint"]).parent / "graph.json").read_text(
                encoding="utf-8"
            )
        )
        for path, suffix in zip(paths, identity["code_extensions"]):
            path.write_text(
                self.semantic_suffix_source(suffix, 1), encoding="utf-8"
            )
        target = self.commit_all(root, "add every supported suffix")

        incremental = module.rebuild(root, sys.executable)
        cold_root = Path(self.temporary_directory.name) / "all-suffixes-cold"
        self.git(root, "clone", str(root), str(cold_root))
        cold = module.rebuild(cold_root, sys.executable)
        cold_graph = json.loads(
            (Path(cold["checkpoint"]).parent / "graph.json").read_text(
                encoding="utf-8"
            )
        )

        def semantic_graph(graph):
            node_semantics = {
                item["id"]: {
                    key: value
                    for key, value in item.items()
                    if key not in {"id", "community", "community_name"}
                }
                for item in graph["nodes"]
            }
            links = []
            for item in graph.get("links", graph.get("edges", [])):
                projected = {
                    key: value
                    for key, value in item.items()
                    if key not in {"source", "target"}
                }
                projected["source_semantics"] = node_semantics[item["source"]]
                projected["target_semantics"] = node_semantics[item["target"]]
                links.append(projected)
            return {"nodes": list(node_semantics.values()), "links": links}

        def graph_digest(result):
            graph = json.loads(
                (Path(result["checkpoint"]).parent / "graph.json").read_text(
                    encoding="utf-8"
                )
            )
            semantics = semantic_graph(graph)
            comparable = {
                "nodes": sorted(
                    semantics["nodes"],
                    key=lambda item: json.dumps(item, sort_keys=True),
                ),
                "links": sorted(
                    semantics["links"],
                    key=lambda item: json.dumps(item, sort_keys=True),
                ),
            }
            return hashlib.sha256(
                json.dumps(comparable, sort_keys=True).encode("utf-8")
            ).hexdigest()

        self.assertEqual(
            "changed_path_adapter", incremental["mode"], incremental
        )
        self.assertEqual(target, incremental["built_at_commit"])
        self.assertEqual(
            {path.relative_to(root).as_posix() for path in paths},
            set(incremental["changed_paths"]),
        )
        incremental_graph = json.loads(
            (Path(incremental["checkpoint"]).parent / "graph.json").read_text(
                encoding="utf-8"
            )
        )
        incremental_semantics = semantic_graph(incremental_graph)
        cold_semantics = semantic_graph(cold_graph)
        for path in paths:
            relative = path.relative_to(root).as_posix()
            before = [
                item
                for collection in ("nodes", "links")
                for item in baseline_graph.get(collection, [])
                if item.get("source_file") == relative
            ]
            after = [
                item
                for collection in ("nodes", "links")
                for item in incremental_semantics[collection]
                if item.get("source_file") == relative
            ]
            cold_after = [
                item
                for collection in ("nodes", "links")
                for item in cold_semantics[collection]
                if item.get("source_file") == relative
            ]
            with self.subTest(suffix=path.suffix):
                self.assertEqual([], before, relative)
                self.assertEqual(
                    sorted(cold_after, key=lambda item: json.dumps(item, sort_keys=True)),
                    sorted(after, key=lambda item: json.dumps(item, sort_keys=True)),
                    relative,
                )
        self.assertEqual(graph_digest(cold), graph_digest(incremental))

    def test_checkpoint_identity_is_clone_and_worktree_stable(self):
        module = self.module()
        source = self.governed_repo("stable-identity")
        first = Path(self.temporary_directory.name) / "identity-one"
        second = Path(self.temporary_directory.name) / "identity-two"
        self.git(source, "clone", str(source), str(first))
        self.git(source, "clone", str(source), str(second))
        linked = self.add_linked_worktree(first, "feature/identity")

        self.assertEqual(
            module.checkpoint_identity(first),
            module.checkpoint_identity(second),
        )
        self.assertEqual(
            module.checkpoint_identity(first),
            module.checkpoint_identity(linked),
        )

    def test_mixed_code_and_document_changes_require_semantic_completion(self):
        module = self.module()
        root = self.governed_repo()
        (root / "src").mkdir()
        (root / "src" / "base.py").write_text("value = 1\n", encoding="utf-8")
        self.commit_all(root, "baseline source")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/base.py", "value = 2\n")
        self.commit_file(root, "docs/meaning.md", "# New meaning\n")

        with patch.dict(os.environ, environment, clear=False):
            result = module.rebuild(root, sys.executable)

        self.assertEqual("stale", result["freshness"])
        self.assertEqual("semantic_completion_required", result["reason"])
        self.assertFalse(module.check_merge_readiness(root)["ready"])

    def test_base_graph_integrity_binds_parse_schema_commit_root_and_digest(self):
        module = self.module()
        defects = (
            "invalid_json",
            "invalid_schema",
            "commit_mismatch",
            "root_binding_mismatch",
            "digest_mismatch",
        )
        for defect in defects:
            with self.subTest(defect=defect):
                root = self.governed_repo(f"graph-{defect}")
                fake, environment = self.cold_checkpoint(root)
                commit = self.git(root, "rev-parse", "HEAD")
                checkpoint = module._checkpoint_path(root, commit)
                graph_path = checkpoint.parent / "graph.json"
                metadata = json.loads(checkpoint.read_text(encoding="utf-8"))
                if defect == "invalid_json":
                    graph_path.write_text("{", encoding="utf-8")
                elif defect == "invalid_schema":
                    graph_path.write_text('{"nodes": "wrong", "links": []}', encoding="utf-8")
                elif defect == "commit_mismatch":
                    graph = json.loads(graph_path.read_text(encoding="utf-8"))
                    graph["built_at_commit"] = "0" * 40
                    graph_path.write_text(json.dumps(graph), encoding="utf-8")
                elif defect == "root_binding_mismatch":
                    metadata["metadata"]["project_identity"] = "wrong"
                    checkpoint.write_text(json.dumps(metadata), encoding="utf-8")
                else:
                    metadata["metadata"]["graph_digest"] = "0" * 64
                    checkpoint.write_text(json.dumps(metadata), encoding="utf-8")

                validation = module.validate_checkpoint(root, checkpoint, commit)
                self.assertFalse(validation["valid"])
                self.assertEqual(defect, validation["reason"])
                self.assertFalse(module.check_merge_readiness(root)["ready"])
                with patch.dict(os.environ, environment, clear=False):
                    rebuilt = module.rebuild(root, sys.executable)
                self.assertNotEqual("exact_cache", rebuilt["mode"])

    def test_configured_remote_requires_successful_exact_destination_refresh(self):
        module = self.module()
        root = self.governed_repo()
        remote = Path(self.temporary_directory.name) / "authority.git"
        self.git(root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "config", "--unset-all", "remote.origin.fetch")
        self.git(
            root,
            "config",
            "--add",
            "remote.origin.fetch",
            "+refs/heads/main:refs/heads/main",
        )

        rejected = module.reconcile_canonical(root, refresh_remote=True)
        self.assertEqual("unknown", rejected["freshness"])
        self.assertFalse(rejected["canonical_published"])
        self.assertEqual([], rejected["fetch_argv"])

        self.git(root, "config", "--unset-all", "remote.origin.fetch")
        self.git(
            root,
            "config",
            "--add",
            "remote.origin.fetch",
            "+refs/heads/main:refs/remotes/origin/main",
        )
        without_refresh = module.reconcile_canonical(root, refresh_remote=False)
        self.assertEqual("unknown", without_refresh["freshness"])
        self.assertFalse(without_refresh["canonical_published"])

    def test_canonical_authority_binds_and_revalidates_remote_url(self):
        module = self.module()
        root = self.governed_repo("remote-url-authority")
        remote = Path(self.temporary_directory.name) / "remote-url-authority.git"
        self.git(root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "push", "-u", "origin", "main")

        authority = module._canonical_authority_details(root, refresh_remote=False)
        self.assertRegex(authority["remote_url_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(module._worker_authority_valid(root, authority, authority.get("commit") or self.git(root, "rev-parse", "refs/remotes/origin/main")))

        replacement = Path(self.temporary_directory.name) / "replacement.git"
        self.git(root, "init", "--bare", str(replacement))
        self.git(root, "remote", "set-url", "origin", str(replacement))
        self.assertFalse(
            module._worker_authority_valid(
                root, authority, self.git(root, "rev-parse", "refs/remotes/origin/main")
            )
        )

    def test_two_clone_push_fetch_reconcile_advance_and_ci(self):
        module = self.module()
        source = self.governed_repo("publisher")
        (source / "src").mkdir()
        (source / "src" / "value.py").write_text(
            "def value():\n    return 1\n", encoding="utf-8"
        )
        baseline = self.commit_all(source, "baseline source")
        remote = Path(self.temporary_directory.name) / "team.git"
        self.git(source, "init", "--bare", str(remote))
        self.git(source, "remote", "add", "origin", str(remote))
        self.git(source, "push", "-u", "origin", "main")
        self.git(source, "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
        receiver = Path(self.temporary_directory.name) / "receiver"
        self.git(source, "clone", str(remote), str(receiver))
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            first = module.reconcile_canonical(
                receiver, refresh_remote=True, graphify_python=sys.executable
            )
        self.assertEqual(baseline, first["commit"])
        (source / "src" / "value.py").write_text(
            "def value():\n    return 2\n", encoding="utf-8"
        )
        correction = self.commit_all(source, "correct value")
        self.git(source, "push", "origin", "main")

        self.assertEqual(
            "stale", module.status(receiver, target_commit=correction)["freshness"]
        )
        with patch.dict(os.environ, environment, clear=False):
            reconciled = module.reconcile_canonical(
                receiver, refresh_remote=True, graphify_python=sys.executable
            )
        self.assertEqual(correction, reconciled["commit"])
        self.assertEqual(correction, reconciled["fetched_commit"])
        self.assertEqual(
            "refs/remotes/origin/main", reconciled["fetched_destination"]
        )
        self.assertTrue(reconciled["authority_revalidated_before_publication"])
        self.git(receiver, "merge", "--ff-only", "refs/remotes/origin/main")
        self.assertEqual(correction, self.git(receiver, "rev-parse", "HEAD"))
        self.assertTrue(module.check_merge_readiness(receiver)["ready"])

    def test_legacy_cleanup_revalidates_inventory_and_replacement(self):
        module = self.module()
        root = self.governed_repo()
        self.cold_checkpoint(root)
        exclude = Path(self.git(root, "rev-parse", "--git-path", "info/exclude"))
        if not exclude.is_absolute():
            exclude = root / exclude
        exclude.write_text("graphify-out/\n", encoding="utf-8")
        legacy = root / "graphify-out"
        legacy.mkdir()
        (legacy / "graph.json").write_text("{}\n", encoding="utf-8")
        (legacy / "graph.html").write_text("<html></html>\n", encoding="utf-8")
        candidate = module.inventory_legacy_outputs(root)[0]
        (legacy / "private.txt").write_text("must survive\n", encoding="utf-8")

        self.assertFalse(module.clean_legacy_output(root, Path(candidate["path"])))
        self.assertTrue(legacy.exists())

        (legacy / "private.txt").unlink()
        module._record_stale(root, self.git(root, "rev-parse", "HEAD"), "test")
        self.assertFalse(module.clean_legacy_output(root, legacy))
        self.assertTrue(legacy.exists())

    def test_non_positive_hook_budget_starts_no_operation_or_worker(self):
        module = self.module()
        root = self.governed_repo()

        result = module.dispatch_hook(
            root,
            "post-commit",
            graphify_python=sys.executable,
            hook_budget_seconds=0,
        )

        self.assertEqual("stale", result["freshness"])
        self.assertEqual("hook_budget_exceeded", result["reason"])
        operations = module.common_graph_dir(root) / "state" / "operations"
        self.assertFalse(operations.exists())

    def test_hook_operation_uses_one_exact_repository_lock_and_bound_paths(self):
        module = self.module()
        root = self.governed_repo()

        operation = module.register_hook_operation(root)

        operation_root = Path(operation["operation_root"]).resolve()
        self.assertTrue(Path(operation["record_path"]).resolve().is_relative_to(operation_root))
        self.assertTrue(Path(operation["worktree_path"]).resolve().is_relative_to(operation_root))
        self.assertTrue(Path(operation["staging_path"]).resolve().is_relative_to(operation_root))
        self.assertEqual(
            module.common_graph_dir(root) / "state" / "lock",
            Path(operation["repository_lock_path"]),
        )
        self.assertFalse((operation_root / "lock").exists())

    def test_live_registered_operation_survives_second_controller_reconciliation(self):
        module = self.module()
        root = self.governed_repo("registration-barrier")
        barrier = threading.Barrier(2)
        holder = {}

        def register_controller():
            holder["operation"] = module.register_hook_operation(root)
            barrier.wait()
            barrier.wait()

        thread = threading.Thread(target=register_controller)
        thread.start()
        barrier.wait()
        operation = holder["operation"]
        try:
            reconciled = module.reconcile_orphaned_operations(
                root, timeout_seconds=1
            )

            self.assertTrue(Path(operation["record_path"]).is_file())
            self.assertIn(operation["operation_id"], reconciled["live"])
            self.assertEqual([], reconciled["reconciled"])
        finally:
            barrier.wait()
            thread.join()

    def test_operation_record_rejects_every_tampered_serialized_path(self):
        module = self.module()
        root = self.governed_repo("tampered-operation-paths")
        outside = Path(self.temporary_directory.name) / "outside-sentinel"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("keep\n", encoding="utf-8")
        operation = module.register_hook_operation(root)
        original = json.loads(
            Path(operation["record_path"]).read_text(encoding="utf-8")
        )

        for key in (
            "operation_root",
            "record_path",
            "worktree_path",
            "staging_path",
            "repository_lock_path",
            "result_path",
        ):
            with self.subTest(key=key):
                tampered = dict(original)
                tampered[key] = str(outside / key)
                Path(operation["record_path"]).write_text(
                    json.dumps(tampered), encoding="utf-8"
                )
                with self.assertRaisesRegex(
                    module.EngineeringError,
                    "invalid_hook_operation_(record|boundary)",
                ):
                    module._read_operation(root, operation["operation_id"])
                self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))
                Path(operation["record_path"]).write_text(
                    json.dumps(original), encoding="utf-8"
                )

    def test_cleanup_never_uses_tampered_operation_root_for_deletion(self):
        module = self.module()
        root = self.governed_repo("tampered-deletion-root")
        outside = Path(self.temporary_directory.name) / "deletion-sentinel"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("keep\n", encoding="utf-8")
        operation = module.register_hook_operation(root)
        record = json.loads(
            Path(operation["record_path"]).read_text(encoding="utf-8")
        )
        record.update(
            operation_root=str(outside),
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        Path(operation["record_path"]).write_text(
            json.dumps(record), encoding="utf-8"
        )

        result = module.cleanup_hook_operation(
            root, operation["operation_id"], timeout_seconds=5
        )

        self.assertFalse(result["completed"])
        self.assertEqual("invalid_hook_operation_record", result["reason"])
        self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))

    def test_child_reparse_plus_resolved_serialized_path_is_rejected(self):
        module = self.module()
        fields = {
            "worktree_path": True,
            "staging_path": True,
            "repository_lock_path": True,
            "record_path": False,
            "result_path": False,
        }
        tested = []
        for field, directory in fields.items():
            with self.subTest(field=field):
                root = self.governed_repo(f"child-reparse-{field}")
                operation = module.register_hook_operation(root)
                record_path = Path(operation["record_path"])
                record = json.loads(record_path.read_text(encoding="utf-8"))
                link = Path(operation[field])
                outside = (
                    Path(self.temporary_directory.name)
                    / f"outside-{field}"
                )
                if directory:
                    outside.mkdir()
                    sentinel = outside / "keep.txt"
                    sentinel.write_text("keep\n", encoding="utf-8")
                else:
                    sentinel = outside
                record[field] = str(outside.resolve())
                if field == "record_path":
                    outside.write_text(json.dumps(record), encoding="utf-8")
                    record_path.unlink()
                else:
                    record_path.write_text(json.dumps(record), encoding="utf-8")
                    if field == "result_path":
                        outside.write_text("keep\n", encoding="utf-8")
                if not self.create_test_reparse(
                    link, outside, directory=directory
                ):
                    continue
                tested.append(field)

                try:
                    with self.assertRaisesRegex(
                        module.EngineeringError,
                        "invalid_hook_operation_(record|boundary)",
                    ):
                        module._read_operation(root, operation["operation_id"])
                    self.assertTrue(sentinel.exists())
                finally:
                    self.remove_test_reparse(link, directory=directory)
        if not tested:
            self.skipTest("reparse-point fixtures unavailable")
        self.assertIn("worktree_path", tested)

    def test_every_existing_registered_resource_is_checked_for_reparse(self):
        module = self.module()
        root = self.governed_repo("every-resource-reparse")
        operation = module.register_hook_operation(root)
        Path(operation["worktree_path"]).mkdir()
        Path(operation["staging_path"]).mkdir()
        Path(operation["repository_lock_path"]).mkdir()
        Path(operation["result_path"]).write_text("{}\n", encoding="utf-8")

        for field in (
            "operation_root",
            "record_path",
            "worktree_path",
            "staging_path",
            "repository_lock_path",
            "result_path",
        ):
            expected = Path(operation[field])
            with self.subTest(field=field), patch.object(
                module,
                "_is_reparse_point",
                side_effect=lambda path, expected=expected: path == expected,
            ):
                with self.assertRaisesRegex(
                    module.EngineeringError, "invalid_hook_operation_boundary"
                ):
                    module._read_operation(root, operation["operation_id"])

    def test_intermediate_state_and_operations_reparse_ancestors_are_rejected(self):
        module = self.module()
        tested = []
        for ancestor_name in ("state", "operations"):
            with self.subTest(ancestor=ancestor_name):
                root = self.governed_repo(f"ancestor-{ancestor_name}")
                operation = module.register_hook_operation(root)
                state = module.common_graph_dir(root) / "state"
                ancestor = state if ancestor_name == "state" else state / "operations"
                outside = (
                    Path(self.temporary_directory.name)
                    / f"outside-{ancestor_name}"
                )
                shutil.move(ancestor, outside)
                sentinel = outside / "keep.txt"
                sentinel.write_text("keep\n", encoding="utf-8")
                if not self.create_test_reparse(
                    ancestor, outside, directory=True
                ):
                    shutil.move(outside, ancestor)
                    continue
                tested.append(ancestor_name)
                try:
                    with self.assertRaisesRegex(
                        module.EngineeringError,
                        "invalid_hook_operation_boundary",
                    ):
                        module._read_operation(root, operation["operation_id"])
                    self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))
                finally:
                    self.remove_test_reparse(ancestor, directory=True)
        if not tested:
            self.skipTest("reparse-point fixtures unavailable")
        self.assertEqual(["state", "operations"], tested)

    def test_operation_root_symlink_is_rejected_without_touching_target(self):
        module = self.module()
        root = self.governed_repo("symlink-operation-root")
        operation = module.register_hook_operation(root)
        operation_root = Path(operation["operation_root"])
        target = Path(self.temporary_directory.name) / "symlink-target"
        target.mkdir()
        sentinel = target / "keep.txt"
        sentinel.write_text("keep\n", encoding="utf-8")
        shutil.rmtree(operation_root)
        try:
            os.symlink(target, operation_root, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"directory symlink unavailable: {error}")
        (target / "resources.json").write_text(
            json.dumps(operation), encoding="utf-8"
        )
        record = json.loads((target / "resources.json").read_text(encoding="utf-8"))
        record.update(owner_pid=-1, worker_process_tree_dead=True, phase="orphaned")
        (target / "resources.json").write_text(json.dumps(record), encoding="utf-8")

        result = module.cleanup_hook_operation(
            root, operation["operation_id"], timeout_seconds=1
        )

        self.assertFalse(result["completed"])
        self.assertEqual("invalid_hook_operation_boundary", result["reason"])
        self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))

    def test_operation_root_reparse_point_is_rejected(self):
        module = self.module()
        root = self.governed_repo("reparse-operation-root")
        operation = module.register_hook_operation(root)

        with patch.object(module, "_is_reparse_point", return_value=True):
            with self.assertRaisesRegex(
                module.EngineeringError, "invalid_hook_operation_boundary"
            ):
                module._read_operation(root, operation["operation_id"])

    def test_every_dead_in_flight_phase_is_orphaned_then_recovered(self):
        module = self.module()
        phases = (
            "registered",
            "worktree_created",
            "staging_ready",
            "validating",
            "published",
        )
        for phase in phases:
            with self.subTest(phase=phase):
                root = self.governed_repo(f"recover-{phase}")
                operation = module.register_hook_operation(root)
                record = module._read_operation(root, operation["operation_id"])
                record.update(
                    owner_pid=-1,
                    worker_process_tree_dead=True,
                    phase=phase,
                    created_at=(
                        time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1
                    ),
                )
                module._write_operation(record)

                result = module.reconcile_orphaned_operations(
                    root, timeout_seconds=30
                )

                self.assertEqual([operation["operation_id"]], result["reconciled"])
                self.assertFalse(Path(operation["record_path"]).exists())

    def test_cleanup_wait_recomputes_deadline_after_process_start(self):
        module = self.module()
        marker = Path(self.temporary_directory.name) / "cleanup-started"
        command = [
            sys.executable,
            "-c",
            (
                "import pathlib,sys,time;"
                "pathlib.Path(sys.argv[1]).write_text('started');"
                "time.sleep(30)"
            ),
            str(marker),
        ]
        started = time.monotonic()

        completed, reason, surviving_pid = module._bounded_cleanup_command(
            command, started + 5
        )
        elapsed = time.monotonic() - started

        self.assertFalse(completed)
        self.assertEqual("cleanup_timeout", reason)
        self.assertIsNone(surviving_pid)
        self.assertEqual("started", marker.read_text(encoding="utf-8"))
        self.assertLess(elapsed, 6)

    def test_cleanup_wait_uses_post_start_remaining_time(self):
        module = self.module()
        process = Mock(returncode=0)
        process.communicate.return_value = ("", "")

        with (
            patch.object(module.time, "monotonic", side_effect=[1.0, 4.0]),
            patch.object(module, "_start_cleanup", return_value=process),
        ):
            completed, reason, surviving_pid = module._bounded_cleanup_command(
                ["python", "cleanup"], deadline=10.0
            )

        self.assertTrue(completed)
        self.assertEqual("clean", reason)
        self.assertIsNone(surviving_pid)
        process.communicate.assert_called_once_with(timeout=5.75)

    def test_cleanup_timeout_kills_and_reaps_a_started_process(self):
        module = self.module()
        process = Mock(returncode=None)
        process.communicate.return_value = ("", "")

        with (
            patch.object(module.time, "monotonic", side_effect=[1.0, 9.9]),
            patch.object(module, "_start_cleanup", return_value=process),
        ):
            completed, reason, surviving_pid = module._bounded_cleanup_command(
                ["python", "cleanup"], deadline=10.0
            )

        self.assertFalse(completed)
        self.assertEqual("cleanup_timeout", reason)
        self.assertIsNone(surviving_pid)
        process.kill.assert_called_once_with()
        process.wait.assert_called_once()
        self.assertAlmostEqual(
            0.1, process.wait.call_args.kwargs["timeout"]
        )
        process.communicate.assert_not_called()

    def test_cleanup_child_only_deletes_staging_payload(self):
        module = self.module()
        root = self.governed_repo("cleanup-child-scope")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        staging = Path(record["staging_path"])
        staging.mkdir()
        (staging / "large.bin").write_bytes(b"payload")
        captured = []
        real_rmtree_argv = module._rmtree_argv

        def record_rmtree(*paths):
            captured.append(paths)
            return real_rmtree_argv(*paths)

        with patch.object(module, "_rmtree_argv", side_effect=record_rmtree):
            result = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        self.assertTrue(result["completed"], result)
        self.assertEqual([(staging,)], captured)
        self.assertFalse(Path(record["operation_root"]).exists())

    def test_cleanup_revalidates_lock_ancestry_before_child_spawn(self):
        module = self.module()
        root = self.governed_repo("cleanup-lock-race")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        lock = Path(record["repository_lock_path"])
        outside = Path(self.temporary_directory.name) / "outside-lock-race"
        real_read = module._read_operation
        swapped = False

        def read_then_swap(*args):
            nonlocal swapped
            current = real_read(*args)
            if not swapped:
                shutil.move(lock, outside)
                self.assertTrue(
                    self.create_test_reparse(lock, outside, directory=True)
                )
                swapped = True
            return current

        with (
            patch.object(module, "_read_operation", side_effect=read_then_swap),
            patch.object(
                module,
                "_bounded_worktree_remove",
                return_value=(False, "unexpected_child_spawn", None),
            ),
        ):
            try:
                result = module.cleanup_hook_operation(
                    root, operation["operation_id"], timeout_seconds=30
                )
            finally:
                self.remove_test_reparse(lock, directory=True)

        self.assertFalse(result["completed"])
        self.assertEqual("invalid_hook_operation_boundary", result["reason"])
        self.assertTrue((outside / "owner.json").is_file())

    def test_cleanup_revalidates_after_child_before_parent_unlink(self):
        module = self.module()
        root = self.governed_repo("cleanup-parent-race")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        staging = Path(record["staging_path"])
        staging.mkdir()
        result_path = Path(record["result_path"])
        result_path.write_text("keep\n", encoding="utf-8")
        operations = Path(record["operation_root"]).parent
        outside = Path(self.temporary_directory.name) / "outside-parent-race"
        swapped = False

        def remove_then_swap(paths, _deadline):
            nonlocal swapped
            self.assertEqual([staging], paths)
            shutil.rmtree(staging)
            shutil.move(operations, outside)
            self.assertTrue(
                self.create_test_reparse(operations, outside, directory=True)
            )
            swapped = True
            return True, "clean", None

        with patch.object(
            module, "_bounded_rmtree_many", side_effect=remove_then_swap
        ):
            try:
                result = module.cleanup_hook_operation(
                    root, operation["operation_id"], timeout_seconds=30
                )
            finally:
                if swapped:
                    self.remove_test_reparse(operations, directory=True)

        outside_result = outside / operation["operation_id"] / "result.json"
        self.assertFalse(result["completed"])
        self.assertEqual("invalid_hook_operation_boundary", result["reason"])
        self.assertEqual("keep\n", outside_result.read_text(encoding="utf-8"))

    def test_cleanup_revalidates_between_parent_removals(self):
        module = self.module()
        root = self.governed_repo("cleanup-between-parent-removals")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        result_path = Path(record["result_path"])
        result_path.write_text("result\n", encoding="utf-8")
        lock = Path(record["repository_lock_path"])
        outside = Path(self.temporary_directory.name) / "outside-between-removals"
        real_unlink = Path.unlink
        swapped = False

        def unlink_then_swap(path, *args, **kwargs):
            nonlocal swapped
            value = real_unlink(path, *args, **kwargs)
            if path == result_path and not swapped:
                shutil.move(lock, outside)
                self.assertTrue(
                    self.create_test_reparse(lock, outside, directory=True)
                )
                swapped = True
            return value

        with (
            patch.object(module, "_process_state", return_value="dead"),
            patch.object(Path, "unlink", new=unlink_then_swap),
        ):
            try:
                result = module.cleanup_hook_operation(
                    root, operation["operation_id"], timeout_seconds=30
                )
            finally:
                if swapped:
                    self.remove_test_reparse(lock, directory=True)

        self.assertFalse(result["completed"])
        self.assertEqual("invalid_hook_operation_boundary", result["reason"])
        self.assertTrue((outside / "owner.json").is_file())

    def test_child_failure_revalidates_orphan_write_after_path_swap(self):
        module = self.module()
        for swapped_path in ("operations", "worktree"):
            with self.subTest(swapped_path=swapped_path):
                root = self.governed_repo(f"orphan-write-{swapped_path}")
                operation = module.register_hook_operation(root)
                record = module._read_operation(root, operation["operation_id"])
                record.update(
                    owner_pid=-1,
                    worker_process_tree_dead=True,
                    phase="worktree_created",
                )
                module._write_operation(record)
                worktree = Path(record["worktree_path"])
                worktree.mkdir()
                operations = Path(record["operation_root"]).parent
                selected = operations if swapped_path == "operations" else worktree
                outside = (
                    Path(self.temporary_directory.name)
                    / f"outside-orphan-write-{swapped_path}"
                )
                sentinel = None

                def fail_after_swap(_root, _worktree, _deadline):
                    nonlocal sentinel
                    shutil.move(selected, outside)
                    self.assertTrue(
                        self.create_test_reparse(selected, outside, directory=True)
                    )
                    sentinel = (
                        outside / operation["operation_id"] / "resources.json"
                        if swapped_path == "operations"
                        else Path(record["record_path"])
                    )
                    sentinel.write_text("outside sentinel\n", encoding="utf-8")
                    return False, "registered_worktree_remove_failed", None

                with patch.object(
                    module,
                    "_bounded_worktree_remove",
                    side_effect=fail_after_swap,
                ):
                    try:
                        result = module.cleanup_hook_operation(
                            root,
                            operation["operation_id"],
                            timeout_seconds=30,
                        )
                    finally:
                        self.remove_test_reparse(selected, directory=True)

                self.assertFalse(result["completed"])
                self.assertEqual(
                    "invalid_hook_operation_boundary", result["reason"]
                )
                self.assertEqual(
                    "outside sentinel\n", sentinel.read_text(encoding="utf-8")
                )

    def test_windows_shaped_exited_worker_without_confirmation_blocks(self):
        module = self.module()
        root = self.governed_repo("windows-shaped-worker-recovery")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=2_147_000_100,
            worker_pid=2_147_000_100,
            phase="orphaned",
        )
        record.pop("worker_process_tree_dead", None)
        module._write_operation(record)

        with patch.object(module, "_process_state", return_value="dead"):
            result = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        self.assertFalse(result["completed"])
        self.assertEqual("live_worker_process_tree", result["reason"])
        self.assertTrue(Path(record["record_path"]).is_file())

    def test_timed_out_recovery_persists_process_tree_evidence_for_supported_reap(self):
        module = self.module()
        root = self.governed_repo("timed-out-recovery-orphan")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=4242,
            worker_pid=4242,
            phase="orphaned",
            commit=self.git(root, "rev-parse", "HEAD"),
            branch="main",
            kind="canonical",
            worker_process_tree_dead=False,
            worker_identity={"pid": 4242, "start_time": "worker-start"},
            worker_process_tree=[
                {"pid": 4242, "parent_pid": 1, "start_time": "worker-start"}
            ],
            created_at=time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1,
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        Path(record["repository_lock_path"], "owner.json").write_text(
            json.dumps(
                {
                    "operation_id": operation["operation_id"],
                    "lock_token": record["lock_token"],
                    "owner_pid": record["worker_pid"],
                    "owner_identity": record["worker_identity"],
                    "created_at": record["created_at"],
                }
            ),
            encoding="utf-8",
        )

        with patch.object(
            module,
            "_process_tree_status",
            return_value={"state": "dead", "evidence": "saved_identity_absent"},
            create=True,
        ):
            status = module.orphan_operation_status(root)
            reap = module.reap_orphan_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        self.assertEqual("dead", status["operations"][0]["process_tree"]["state"])
        self.assertTrue(reap["completed"], reap)
        self.assertFalse(Path(record["operation_root"]).exists())

    def test_orphan_reap_preserves_live_child_and_exact_lock(self):
        module = self.module()
        root = self.governed_repo("orphan-live-child")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=4242,
            worker_pid=4242,
            phase="orphaned",
            worker_process_tree_dead=False,
            worker_identity={"pid": 4242, "start_time": "worker-start"},
            worker_process_tree=[
                {"pid": 4242, "parent_pid": 1, "start_time": "worker-start"},
                {"pid": 4343, "parent_pid": 4242, "start_time": "child-start"},
            ],
            created_at=time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1,
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        Path(record["repository_lock_path"], "owner.json").write_text(
            json.dumps(
                {
                    "operation_id": operation["operation_id"],
                    "lock_token": record["lock_token"],
                    "owner_pid": record["worker_pid"],
                    "owner_identity": record["worker_identity"],
                    "created_at": record["created_at"],
                }
            ),
            encoding="utf-8",
        )

        with patch.object(
            module,
            "_process_tree_status",
            return_value={"state": "live", "evidence": "saved_child_alive"},
            create=True,
        ):
            result = module.reap_orphan_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        self.assertFalse(result["completed"])
        self.assertEqual("live_worker_process_tree", result["reason"])
        self.assertTrue(Path(record["record_path"]).exists())
        self.assertTrue(Path(record["repository_lock_path"]).exists())

    def test_orphan_reap_rejects_windows_pid_reuse_as_identity_ambiguous(self):
        module = self.module()
        root = self.governed_repo("orphan-pid-reuse")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=4242,
            worker_pid=4242,
            phase="orphaned",
            worker_process_tree_dead=False,
            worker_identity={"pid": 4242, "start_time": "old-start"},
            worker_process_tree=[
                {"pid": 4242, "parent_pid": 1, "start_time": "old-start"}
            ],
            created_at=time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1,
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        Path(record["repository_lock_path"], "owner.json").write_text(
            json.dumps(
                {
                    "operation_id": operation["operation_id"],
                    "lock_token": record["lock_token"],
                    "owner_pid": record["worker_pid"],
                    "owner_identity": record["worker_identity"],
                    "created_at": record["created_at"],
                }
            ),
            encoding="utf-8",
        )

        with patch.object(
            module,
            "_process_tree_status",
            return_value={"state": "identity_ambiguous", "evidence": "pid_reused"},
            create=True,
        ):
            result = module.reap_orphan_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        self.assertFalse(result["completed"])
        self.assertEqual("ambiguous_worker_process_identity", result["reason"])
        self.assertTrue(Path(record["record_path"]).exists())
        self.assertTrue(Path(record["repository_lock_path"]).exists())

    def test_orphan_reap_rejects_exact_lock_token_mismatch(self):
        module = self.module()
        root = self.governed_repo("orphan-lock-mismatch")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=4242,
            worker_pid=4242,
            phase="orphaned",
            worker_process_tree_dead=False,
            worker_identity={"pid": 4242, "start_time": "worker-start"},
            worker_process_tree=[
                {"pid": 4242, "parent_pid": 1, "start_time": "worker-start"}
            ],
            created_at=time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1,
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        Path(record["repository_lock_path"], "owner.json").write_text(
            json.dumps(
                {
                    "operation_id": operation["operation_id"],
                    "lock_token": "wrong-token",
                    "owner_pid": record["worker_pid"],
                    "owner_identity": record["worker_identity"],
                    "created_at": record["created_at"],
                }
            ),
            encoding="utf-8",
        )
        with patch.object(
            module,
            "_process_tree_status",
            return_value={"state": "dead", "evidence": "saved_identity_absent"},
            create=True,
        ):
            result = module.reap_orphan_operation(
                root, operation["operation_id"], timeout_seconds=30
            )
        self.assertFalse(result["completed"])
        self.assertEqual("repository_lock_owner_mismatch", result["reason"])
        self.assertTrue(Path(record["record_path"]).exists())

    def test_orphan_reap_never_removes_live_pre_worker_registration(self):
        module = self.module()
        root = self.governed_repo("orphan-live-registration")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            phase="registered",
            created_at=time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1,
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        owner = json.loads(
            Path(record["repository_lock_path"], "owner.json").read_text(encoding="utf-8")
        )
        owner["created_at"] = record["created_at"]
        Path(record["repository_lock_path"], "owner.json").write_text(
            json.dumps(owner), encoding="utf-8"
        )
        with patch.object(module, "_process_tree_status", return_value={"state": "dead"}), patch.object(
            module, "_process_alive", return_value=True
        ):
            result = module.reap_orphan_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        self.assertFalse(result["completed"])
        self.assertIn(
            result["reason"],
            {"live_hook_operation", "ambiguous_worker_process_identity"},
        )
        self.assertTrue(Path(record["record_path"]).exists())
        self.assertEqual(owner["lock_token"], module._lock_owner(record)["lock_token"])

    def test_orphan_status_exposes_saved_identity_and_tree_evidence(self):
        module = self.module()
        root = self.governed_repo("orphan-status-evidence")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        identity = {"pid": 4242, "start_time": "worker-start"}
        tree = [
            {"pid": 4242, "parent_pid": 1, "start_time": "worker-start"},
            {"pid": 4343, "parent_pid": 4242, "start_time": "child-start"},
        ]
        record.update(worker_pid=4242, worker_identity=identity, worker_process_tree=tree)
        module._write_operation(record)
        with patch.object(module, "_process_tree_status", return_value={"state": "unknown"}):
            result = module.orphan_operation_status(root)
        item = result["operations"][0]
        self.assertEqual(identity, item["worker_identity"])
        self.assertEqual(tree, item["worker_process_tree"])

    def test_process_tree_status_rejects_fresh_unrecorded_child(self):
        module = self.module()
        identity = {"pid": 4242, "start_time": "worker-start"}
        tree = [{"pid": 4242, "parent_pid": 1, "start_time": "worker-start"}]
        record = {
            "worker_pid": 4242,
            "worker_identity": identity,
            "worker_process_tree": tree,
            "worker_process_tree_complete": True,
        }
        with (
            patch.object(
                module,
                "_capture_process_tree",
                return_value=tree + [
                    {"pid": 4343, "parent_pid": 4242, "start_time": "child-start"}
                ],
            ),
            patch.object(module, "_same_process_identity", side_effect=lambda current, expected: current.get("pid") == expected.get("pid") and current.get("start_time") == expected.get("start_time")),
        ):
            status = module._process_tree_status(record)
        self.assertEqual("live", status["state"])
        self.assertEqual("fresh_process_tree_child", status["evidence"])
        self.assertEqual(4343, status["pid"])

    def test_dead_marker_rechecks_live_lock_owner_before_reconcile(self):
        module = self.module()
        root = self.governed_repo("orphan-dead-marker-live-owner")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=4242,
            owner_identity={"pid": 4242, "start_time": "owner-start"},
            worker_pid=4242,
            worker_identity={"pid": 4242, "start_time": "worker-start"},
            worker_process_tree=[
                {"pid": 4242, "parent_pid": 1, "start_time": "worker-start"}
            ],
            worker_process_tree_dead=True,
            phase="orphaned",
            created_at=time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1,
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        owner_path = Path(record["repository_lock_path"], "owner.json")
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        owner.update(
            owner_pid=4242,
            owner_identity=record["owner_identity"],
            created_at=record["created_at"],
        )
        owner_path.write_text(json.dumps(owner), encoding="utf-8")
        with (
            patch.object(module, "_process_tree_status", return_value={"state": "dead", "evidence": "confirmed"}),
            patch.object(module, "_owner_process_state", return_value="live"),
        ):
            result = module.reconcile_orphaned_operations(root, timeout_seconds=30)
        self.assertEqual([operation["operation_id"]], result["live"])
        self.assertTrue(Path(record["record_path"]).exists())

    def test_orphan_status_and_reap_cli_are_supported_controller_commands(self):
        module = self.module()
        root = self.governed_repo("orphan-cli")
        output = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                ["engineering", "orphan-status", str(root)],
            ),
            patch.object(
                module,
                "orphan_operation_status",
                return_value={"schema": "engineering.orphan-status.v1", "operations": []},
            ) as status,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())
        status.assert_called_once_with(module.resolve_project_root(str(root)))
        self.assertEqual(
            "engineering.orphan-status.v1", json.loads(output.getvalue())["schema"]
        )

    def test_posix_recovery_blocks_while_saved_group_exists(self):
        module = self.module()
        root = self.governed_repo("posix-live-group-recovery")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=4242,
            worker_pid=4242,
            worker_pgid=4242,
            phase="orphaned",
        )
        record.pop("worker_process_tree_dead", None)
        module._write_operation(record)

        with (
            patch.object(module.os, "killpg", return_value=None, create=True),
            patch.object(module, "_process_alive", return_value=False),
        ):
            result = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        self.assertFalse(result["completed"])
        self.assertEqual("live_worker_process_tree", result["reason"])
        self.assertTrue(Path(record["record_path"]).is_file())

    def test_posix_recovery_marks_absent_saved_group_before_cleanup(self):
        module = self.module()
        root = self.governed_repo("posix-absent-group-recovery")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=4242,
            worker_pid=4242,
            worker_pgid=4242,
            phase="orphaned",
        )
        record.pop("worker_process_tree_dead", None)
        module._write_operation(record)
        worktree = Path(record["worktree_path"])
        worktree.mkdir()

        with (
            patch.object(
                module.os,
                "killpg",
                side_effect=ProcessLookupError,
                create=True,
            ),
            patch.object(module, "_process_alive", return_value=False),
            patch.object(
                module,
                "_bounded_worktree_remove",
                return_value=(False, "registered_worktree_remove_failed", None),
            ),
        ):
            result = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        retained = json.loads(
            Path(record["record_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual("registered_worktree_remove_failed", result["reason"])
        self.assertTrue(retained.get("worker_process_tree_dead"))

    def test_parent_cleanup_preserves_unregistered_operation_payload(self):
        module = self.module()
        root = self.governed_repo("parent-cleanup-scope")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        unexpected = Path(record["operation_root"]) / "unexpected"
        unexpected.mkdir()
        sentinel = unexpected / "keep.txt"
        sentinel.write_text("keep\n", encoding="utf-8")

        result = module.cleanup_hook_operation(
            root, operation["operation_id"], timeout_seconds=30
        )

        self.assertFalse(result["completed"])
        self.assertEqual("registered_operation_remove_failed", result["reason"])
        self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))
        self.assertTrue(Path(record["record_path"]).exists())

    def test_surviving_cleanup_child_retains_record_and_blocks_recovery(self):
        module = self.module()
        root = self.governed_repo("surviving-cleanup-child")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        staging = Path(record["staging_path"])
        staging.mkdir()
        (staging / "large.bin").write_bytes(b"payload")

        class SurvivingProcess:
            pid = 2_147_000_001
            returncode = None
            stdout = None
            stderr = None

            def communicate(self, timeout=None):
                raise subprocess.TimeoutExpired("cleanup", timeout)

            def kill(self):
                pass

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("cleanup", timeout)

        with patch.object(
            module, "_start_cleanup", return_value=SurvivingProcess()
        ):
            first = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        retained = json.loads(
            Path(record["record_path"]).read_text(encoding="utf-8")
        )
        self.assertFalse(first["completed"])
        self.assertEqual("cleanup_timeout", first["reason"])
        self.assertEqual(SurvivingProcess.pid, retained.get("cleanup_pid"))
        self.assertFalse(retained.get("cleanup_process_dead", True))
        self.assertTrue(staging.exists())

        with patch.object(
            module,
            "_process_alive",
            side_effect=lambda pid: pid == SurvivingProcess.pid,
        ):
            blocked = module.reconcile_orphaned_operations(
                root, timeout_seconds=1
            )

        self.assertEqual([operation["operation_id"]], blocked["live"])
        self.assertTrue(Path(record["record_path"]).exists())

        retained["created_at"] = (
            time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1
        )
        Path(record["record_path"]).write_text(
            json.dumps(retained), encoding="utf-8"
        )
        owner_path = Path(record["repository_lock_path"]) / "owner.json"
        if owner_path.is_file():
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            owner["created_at"] = retained["created_at"]
            owner_path.write_text(json.dumps(owner), encoding="utf-8")

        with patch.object(module, "_process_state", return_value="dead"):
            recovered = module.reconcile_orphaned_operations(
                root, timeout_seconds=30
            )

        self.assertEqual([operation["operation_id"]], recovered["reconciled"])
        self.assertFalse(Path(record["operation_root"]).exists())

    def test_one_deleted_source_cannot_waive_adversarial_graph_shrink(self):
        module = self.module()
        previous = {
            "nodes": [
                {
                    "id": f"node-{index}",
                    "source_file": (
                        "src/deleted.py" if index == 0 else f"src/kept-{index}.py"
                    ),
                }
                for index in range(100)
            ]
        }
        current = {"nodes": [previous["nodes"][0]]}

        with self.assertRaisesRegex(module.EngineeringError, "unexpected_shrink"):
            module._guard_base_graph(
                current,
                previous,
                ratio=0.8,
                deleted_sources={"src/deleted.py"},
            )

    def test_cleanup_deadline_bounds_rmtree_and_leaves_durable_orphan(self):
        module = self.module()
        root = self.governed_repo("cleanup-deadline")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record["owner_pid"] = -1
        record["worker_process_tree_dead"] = True
        record["phase"] = "orphaned"
        module._write_operation(record)
        stage = Path(record["staging_path"])
        stage.mkdir()
        (stage / "owned.tmp").write_text("owned\n", encoding="utf-8")
        slow = [
            sys.executable,
            "-c",
            "import time; time.sleep(1)",
        ]
        started = time.monotonic()
        with patch.object(module, "_rmtree_argv", return_value=slow):
            result = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=0.01
            )
        elapsed = time.monotonic() - started

        self.assertFalse(result["completed"])
        self.assertEqual("cleanup_timeout", result["reason"])
        self.assertLess(elapsed, 0.5)
        self.assertTrue(Path(record["record_path"]).is_file())
        self.assertEqual(
            "orphaned",
            json.loads(Path(record["record_path"]).read_text(encoding="utf-8"))[
                "phase"
            ],
        )

    def test_reconcile_same_valid_canonical_commit_is_exact_cache(self):
        module = self.module()
        root = self.governed_repo("canonical-cache")
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            first = module.reconcile_canonical(
                root, refresh_remote=False, graphify_python=sys.executable
            )
            with patch.object(
                module,
                "_run_graph_operation",
                side_effect=AssertionError("exact cache must not start a worker"),
            ):
                second = module.reconcile_canonical(
                    root, refresh_remote=False, graphify_python=sys.executable
                )

        self.assertTrue(first["canonical_published"])
        self.assertEqual("exact_cache", second["mode"])
        self.assertEqual(first["checkpoint"], second["checkpoint"])
        self.assertTrue(second["authority_revalidated_before_publication"])

    def test_non_object_checkpoint_is_invalid_for_cache_ancestor_and_ci(self):
        module = self.module()
        root = self.governed_repo("non-object-checkpoint")
        fake, environment = self.cold_checkpoint(root)
        commit = self.git(root, "rev-parse", "HEAD")
        checkpoint = module._checkpoint_path(root, commit)
        checkpoint.write_text("[]\n", encoding="utf-8")

        validation = module.validate_checkpoint(root, checkpoint, commit)
        self.assertFalse(validation["valid"])
        self.assertEqual("invalid_schema", validation["reason"])
        self.assertFalse(module.check_merge_readiness(root)["ready"])
        self.commit_file(root, "src/next.py", "def next_value():\n    return 1\n")
        with patch.dict(os.environ, environment, clear=False):
            result = module.rebuild(root, sys.executable)
        self.assertEqual("full", result["mode"])

    def test_base_graph_requires_unique_nodes_and_resolved_link_endpoints(self):
        module = self.module()
        defects = {
            "missing_node_id": {
                "nodes": [{"source_file": "src/a.py"}],
                "links": [],
            },
            "duplicate_node_id": {
                "nodes": [{"id": "same"}, {"id": "same"}],
                "links": [],
            },
            "dangling_link": {
                "nodes": [{"id": "present"}],
                "links": [{"source": "present", "target": "missing"}],
            },
            "duplicate_link": {
                "nodes": [{"id": "source"}, {"id": "target"}],
                "links": [
                    {
                        "source": "source",
                        "target": "target",
                        "relation": "calls",
                        "confidence": "EXTRACTED",
                        "source_file": "src/source.py",
                        "source_location": "L7",
                    },
                    {
                        "source": "source",
                        "target": "target",
                        "relation": "calls",
                        "confidence": "EXTRACTED",
                        "source_file": "src/source.py",
                        "source_location": "L7",
                    },
                ],
            },
        }
        for defect, replacement in defects.items():
            with self.subTest(defect=defect):
                root = self.governed_repo(f"base-{defect}")
                self.cold_checkpoint(root)
                commit = self.git(root, "rev-parse", "HEAD")
                checkpoint_path = module._checkpoint_path(root, commit)
                graph_path = checkpoint_path.parent / "graph.json"
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
                graph.update(replacement)
                graph_path.write_text(json.dumps(graph), encoding="utf-8")
                checkpoint = json.loads(
                    checkpoint_path.read_text(encoding="utf-8")
                )
                checkpoint["metadata"]["graph_digest"] = hashlib.sha256(
                    graph_path.read_bytes()
                ).hexdigest()
                checkpoint_path.write_text(
                    json.dumps(checkpoint), encoding="utf-8"
                )

                result = module.validate_checkpoint(
                    root, checkpoint_path, commit
                )

                self.assertFalse(result["valid"])
                self.assertEqual("invalid_schema", result["reason"])

    def test_same_graphify_relation_at_distinct_locations_is_not_duplicate(self):
        module = self.module()
        graph_path = Path(self.temporary_directory.name) / "distinct-links.json"
        graph_path.write_text(
            json.dumps(
                {
                    "nodes": [{"id": "source"}, {"id": "target"}],
                    "links": [
                        {
                            "source": "source",
                            "target": "target",
                            "relation": "calls",
                            "confidence": "EXTRACTED",
                            "source_file": "src/source.py",
                            "source_location": "L7",
                        },
                        {
                            "source": "source",
                            "target": "target",
                            "relation": "calls",
                            "confidence": "EXTRACTED",
                            "source_file": "src/source.py",
                            "source_location": "L9",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        graph = module._read_base_graph(graph_path)

        self.assertEqual(2, len(graph["links"]))

    def test_checkpoint_recompiles_and_compares_exact_overlay(self):
        module = self.module()
        defects = ("nodes", "edges", "integrity", "input_digest")
        for defect in defects:
            with self.subTest(defect=defect):
                root = self.governed_repo(f"overlay-{defect}")
                self.cold_checkpoint(root)
                commit = self.git(root, "rev-parse", "HEAD")
                checkpoint_path = module._checkpoint_path(root, commit)
                checkpoint = json.loads(
                    checkpoint_path.read_text(encoding="utf-8")
                )
                if defect == "nodes":
                    checkpoint["nodes"] = []
                elif defect == "edges":
                    checkpoint["edges"] = "not-a-list"
                elif defect == "integrity":
                    checkpoint["integrity"]["nodes"] += 1
                else:
                    checkpoint["metadata"]["input_digest"] = "0" * 64
                checkpoint_path.write_text(
                    json.dumps(checkpoint), encoding="utf-8"
                )

                validation = module.validate_checkpoint(
                    root, checkpoint_path, commit
                )

                self.assertFalse(validation["valid"])
                self.assertIn(
                    validation["reason"], {"invalid_schema", "overlay_mismatch"}
                )
                self.assertFalse(module.check_merge_readiness(root)["ready"])

    def test_executed_argv_is_allowlisted_across_graph_paths(self):
        module = self.module()
        root = self.governed_repo("argv-local")
        (root / "src").mkdir()
        (root / "src" / "value.py").write_text(
            "def value():\n    return 1\n", encoding="utf-8"
        )
        self.commit_all(root, "argv baseline")
        remote_root = self.governed_repo("argv-remote")
        remote = Path(self.temporary_directory.name) / "argv.git"
        self.git(remote_root, "init", "--bare", str(remote))
        self.git(remote_root, "remote", "add", "origin", str(remote))
        self.git(remote_root, "push", "-u", "origin", "main")
        fake = self.write_fake_graphify()
        record = Path(self.temporary_directory.name) / "argv-graphify.jsonl"
        child_audit = Path(self.temporary_directory.name) / "argv-child.jsonl"
        (self.fake_graphify_control.parent.parent / "sitecustomize.py").write_text(
            "import json,pathlib,subprocess,sys\n"
            "controls=pathlib.Path(__file__).with_name('graphify').joinpath('fixture-controls.json')\n"
            "sink=pathlib.Path(json.loads(controls.read_text(encoding='utf-8'))['ENGINEERING_ARGV_AUDIT'])\n"
            "def emit(argv):\n"
            "    sink.open('a',encoding='utf-8').write(json.dumps(list(map(str,argv)))+'\\n')\n"
            "emit([sys.executable,*sys.argv])\n"
            "real_run=subprocess.run\n"
            "real_popen=subprocess.Popen\n"
            "def run(argv,*args,**kwargs):\n"
            "    emit(argv); return real_run(argv,*args,**kwargs)\n"
            "def popen(argv,*args,**kwargs):\n"
            "    emit(argv); return real_popen(argv,*args,**kwargs)\n"
            "subprocess.run=run\n"
            "subprocess.Popen=popen\n",
            encoding="utf-8",
        )
        self.set_fake_graphify_controls(
            FAKE_GRAPHIFY_RECORD=str(record),
            ENGINEERING_ARGV_AUDIT=str(child_audit),
        )
        real_run = subprocess.run
        real_start_worker = module._start_worker
        real_start_cleanup = module._start_cleanup
        executed = []

        def recording_run(command, *args, **kwargs):
            executed.append(list(command))
            return real_run(command, *args, **kwargs)

        def recording_worker(command):
            executed.append(list(command))
            return real_start_worker(command)

        def recording_cleanup(command):
            executed.append(list(command))
            return real_start_cleanup(command)

        with (
            patch.object(module.subprocess, "run", side_effect=recording_run),
            patch.object(module, "_start_worker", side_effect=recording_worker),
            patch.object(module, "_start_cleanup", side_effect=recording_cleanup),
        ):
            module.rebuild(root, sys.executable)
            self.commit_file(root, "src/value.py", "def value():\n    return 2\n")
            module.rebuild(root, sys.executable)
            module.rebuild(root, sys.executable)
            module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=0,
            )
            module.reconcile_canonical(
                remote_root,
                refresh_remote=True,
                graphify_python=sys.executable,
            )

        executed.extend(
            json.loads(line)
            for line in child_audit.read_text(encoding="utf-8").splitlines()
        )

        allowed = re.compile(r"(?:git|python(?:\d+(?:\.\d+)*)?)(?:\.exe)?$")
        self.assertTrue(executed)
        self.assertTrue(
            all(allowed.fullmatch(Path(command[0]).name.lower()) for command in executed),
            executed,
        )
        self.assertTrue(
            any(
                "fetch" in command
                and any(
                    "refs/heads/main:refs/remotes/origin/main" in argument
                    for argument in command
                )
                for command in executed
            )
        )
        self.assertTrue(
            any("_graph-worker" in command for command in executed), executed
        )
        self.assertTrue(
            any(
                "worktree" in command and "add" in command
                for command in executed
            ),
            executed,
        )
        self.assertTrue(
            any(
                "-m" in command and "graphify" in command
                for command in executed
            ),
            executed,
        )
        cleanup_commands = [
            command
            for command in executed
            if len(command) > 2
            and command[1] == "-c"
            and "shutil.rmtree" in command[2]
        ]
        self.assertTrue(
            all(
                Path(path).name == "staging"
                for command in cleanup_commands
                for path in command[3:]
            ),
            cleanup_commands,
        )
        graphify_calls = [
            json.loads(line)
            for line in record.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            {"update", "private_rebuild_code"},
            {call[0] for call in graphify_calls},
        )
        forbidden = (
            "enterprise_endpoint",
            "enterprise_client",
            "enterprise_upload",
            "enterprise_autodetect",
            "enterprise_switch",
        )
        audit_text = json.dumps({"argv": executed, "graphify": graphify_calls}).lower()
        self.assertFalse(any(item in audit_text for item in forbidden))

    def test_timed_out_worker_is_killed_and_exact_resources_are_cleaned(self):
        module = self.module()
        root = self.governed_repo("slow-worker")
        (root / "src").mkdir()
        (root / "src" / "slow.py").write_text(
            "def slow():\n    return 1\n", encoding="utf-8"
        )
        self.commit_all(root, "slow baseline")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/slow.py", "def slow():\n    return 2\n")
        before = self.git(root, "worktree", "list", "--porcelain")
        def remove_fixture(_root, worktree, _deadline):
            shutil.rmtree(worktree)
            self.git(_root, "worktree", "prune")
            return True, "clean", None

        def remove_staging_fixture(paths, _deadline):
            for path in paths:
                shutil.rmtree(path)
            return True, "clean", None

        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                module,
                "_start_worker",
                side_effect=self.timed_out_registered_worker(module),
            ),
            patch.object(
                module,
                "_terminate_process_tree",
                side_effect=lambda process, _pgid, **_kwargs: (
                    process.kill(),
                    setattr(process, "_engineering_tree_proven", True),
                    True,
                )[-1],
            ),
            patch.object(
                module,
                "_bounded_worktree_remove",
                side_effect=remove_fixture,
            ),
            patch.object(
                module,
                "_bounded_rmtree_many",
                side_effect=remove_staging_fixture,
            ),
            patch.object(module.os, "killpg", return_value=None, create=True),
        ):
            result = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=10,
                cleanup_timeout_seconds=5,
                identity_clock=lambda: 0.0,
            )
        self.assertEqual("hook_budget_exceeded", result["reason"])
        self.assertTrue(result["worker_process_tree_terminated"])
        self.assertTrue(result["cleanup"]["completed"])
        self.assertGreater(self.worker_timeout_seconds, 0)
        self.assertLessEqual(self.worker_timeout_seconds, 10)
        self.assertEqual(before, self.git(root, "worktree", "list", "--porcelain"))
        self.assertFalse(Path(result["operation"]["worktree_path"]).exists())
        self.assertFalse(Path(result["operation"]["staging_path"]).exists())
        self.assertFalse(
            (module.common_graph_dir(root) / "state" / "lock").exists()
        )

    def test_posix_timeout_escalates_saved_process_group_after_leader_exit(self):
        module = self.module()
        process = Mock()
        process.pid = 4242
        process.poll.return_value = 0
        group = {"alive": True}
        sigkill = getattr(signal, "SIGKILL", 9)

        def kill_group(pgid, selected_signal):
            self.assertEqual(4242, pgid)
            if selected_signal == sigkill:
                group["alive"] = False
            elif selected_signal == 0 and not group["alive"]:
                raise ProcessLookupError

        with (
            patch.object(module.os, "name", "posix"),
            patch.object(
                module.os, "killpg", side_effect=kill_group, create=True
            ) as killpg,
            patch.object(module.time, "sleep", return_value=None),
            patch.object(
                module.time, "monotonic", side_effect=[0.0, 3.0, 3.0, 3.0]
            ),
        ):
            try:
                terminated = module._terminate_process_tree(process, 4242)
            except TypeError as error:
                self.fail(f"saved process group was not accepted: {error}")

        self.assertFalse(group["alive"])
        self.assertTrue(terminated)
        calls = [call.args for call in killpg.call_args_list]
        self.assertIn((4242, signal.SIGTERM), calls)
        self.assertIn((4242, sigkill), calls)

    def test_worker_tree_dead_requires_termination_confirmation(self):
        module = self.module()
        root = self.governed_repo("unconfirmed-process-tree")
        (root / "src").mkdir()
        (root / "src" / "slow.py").write_text(
            "def slow():\n    return 1\n", encoding="utf-8"
        )
        self.commit_all(root, "unconfirmed baseline")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/slow.py", "def slow():\n    return 2\n")

        def unconfirmed(process, *_saved_group):
            process.kill()
            return False

        def remove_fixture(_root, worktree, _deadline):
            shutil.rmtree(worktree)
            self.git(_root, "worktree", "prune")
            return True, "clean", None

        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                module,
                "_start_worker",
                side_effect=self.timed_out_registered_worker(module),
            ),
            patch.object(
                module, "_terminate_process_tree", side_effect=unconfirmed
            ),
            patch.object(
                module,
                "_bounded_worktree_remove",
                side_effect=remove_fixture,
            ),
            patch.object(module, "_recover_worker_tree_state", return_value=None),
        ):
            result = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=10,
                cleanup_timeout_seconds=5,
                identity_clock=lambda: 0.0,
            )

        self.assertFalse(result["worker_process_tree_terminated"])
        self.assertFalse(result["operation"]["worker_process_tree_dead"])
        self.assertEqual(2_147_000_000, result["operation"].get("worker_pid"))
        if os.name == "nt":
            self.assertNotIn("worker_pgid", result["operation"])
        else:
            self.assertEqual(2_147_000_000, result["operation"].get("worker_pgid"))
        self.assertFalse(result["cleanup"]["completed"])
        self.assertEqual("live_worker_process_tree", result["cleanup"]["reason"])

    @unittest.skipUnless(os.name == "posix", "real POSIX process-group proof")
    def test_real_posix_timeout_kills_descendant_that_ignores_sigterm(self):
        module = self.module()
        child_pid_path = Path(self.temporary_directory.name) / "posix-child.pid"
        worker = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,signal,subprocess,sys,time;"
                    "child=subprocess.Popen([sys.executable,'-c',"
                    "'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)']);"
                    "pathlib.Path(sys.argv[1]).write_text(str(child.pid));"
                    "time.sleep(120)"
                ),
                str(child_pid_path),
            ],
            start_new_session=True,
        )
        deadline = time.monotonic() + 10
        while not child_pid_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(child_pid_path.is_file())
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))

        terminated = module._terminate_process_tree(worker, worker.pid)

        self.assertTrue(terminated)
        self.assertFalse(module._process_alive(child_pid))

    def test_real_process_tree_termination_closes_inherited_pipe_handles(self):
        module = self.module()
        child_pid_path = Path(self.temporary_directory.name) / "pipe-child.pid"
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,subprocess,sys,time;"
                    "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],"
                    "stdout=sys.stdout,stderr=sys.stderr);"
                    "pathlib.Path(sys.argv[1]).write_text(str(child.pid));"
                    "time.sleep(120)"
                ),
                str(child_pid_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=(os.name != "nt"),
        )
        deadline = time.monotonic() + 10
        while not child_pid_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(child_pid_path.is_file())
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        expected_tree = (
            module._capture_process_tree(process.pid) if os.name == "nt" else None
        )
        if os.name == "nt":
            self.assertTrue(expected_tree)

        terminated = module._terminate_process_tree(
            process,
            process.pid if os.name != "nt" else None,
            expected_tree=expected_tree,
        )
        process.communicate(timeout=5)

        self.assertTrue(terminated)
        self.assertFalse(module._process_alive(child_pid))

    def test_windows_timeout_uses_taskkill_process_tree(self):
        module = self.module()
        process = Mock()
        process.pid = 4242
        process.poll.side_effect = [None, 0]
        process.wait.return_value = 0

        with (
            patch.object(module.os, "name", "nt"),
            patch.object(module.subprocess, "run") as run,
            patch.object(
                module,
                "_saved_process_tree_absent",
                return_value=(True, "saved_process_tree_absent"),
            ) as saved_tree_absent,
        ):
            terminated = module._terminate_process_tree(
                process,
                expected_tree=[{"pid": 4242, "start_time": "saved-start"}],
            )

        self.assertTrue(terminated)
        saved_tree_absent.assert_called_once_with(
            [{"pid": 4242, "start_time": "saved-start"}],
        )
        run.assert_called_once_with(
            ["taskkill", "/PID", "4242", "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=2,
        )

    def test_windows_timeout_waits_for_saved_tree_exit_after_taskkill(self):
        """Taskkill leader exit is not proof until the captured descendants exit."""
        module = self.module()
        process = Mock()
        process.pid = 4242
        process.poll.side_effect = [None, 0]
        process.wait.return_value = 0
        expected_tree = [{"pid": 4242, "start_time": "saved-start"}]

        with (
            patch.object(module.os, "name", "nt"),
            patch.object(module.subprocess, "run"),
            patch.object(
                module,
                "_saved_process_tree_absent",
                side_effect=[
                    (False, "saved_process_alive"),
                    (True, "saved_process_tree_absent"),
                ],
            ) as saved_tree_absent,
        ):
            terminated = module._terminate_process_tree(
                process,
                expected_tree=expected_tree,
            )

        self.assertTrue(terminated)
        self.assertEqual(2, saved_tree_absent.call_count)
        saved_tree_absent.assert_called_with(expected_tree)

    def test_windows_timeout_without_saved_tree_stays_unconfirmed(self):
        module = self.module()
        process = Mock()
        process.pid = 4242
        process.poll.side_effect = [None, 0]
        process.wait.return_value = 0

        with (
            patch.object(module.os, "name", "nt"),
            patch.object(module.subprocess, "run"),
        ):
            terminated = module._terminate_process_tree(process)

        self.assertFalse(terminated)

    def test_windows_first_poll_exited_keeps_process_tree_unconfirmed(self):
        module = self.module()
        process = Mock()
        process.pid = 4242
        process.poll.return_value = 0

        with (
            patch.object(module.os, "name", "nt"),
            patch.object(module.subprocess, "run"),
        ):
            terminated = module._terminate_process_tree(process)

        self.assertFalse(terminated)

    def test_crash_after_spawn_before_identity_write_blocks_recovery(self):
        module = self.module()
        root = self.governed_repo("crash-before-worker-identity")

        class SimulatedParentCrash(RuntimeError):
            pass

        class SpawnedProcess:
            @property
            def pid(self):
                raise SimulatedParentCrash("after Popen before identity write")

        with (
            patch.object(module, "_start_worker", return_value=SpawnedProcess()),
            self.assertRaisesRegex(
                SimulatedParentCrash, "after Popen before identity write"
            ),
        ):
            module._run_graph_operation(
                root,
                graphify_python=sys.executable,
                commit=self.git(root, "rev-parse", "HEAD"),
                branch="main",
                kind="feature",
                manifest_name="engineering-traceability.json",
                hook=True,
                timeout_seconds=30,
                cleanup_timeout_seconds=30,
            )

        operations = module.common_graph_dir(root) / "state" / "operations"
        operation_root = next(operations.iterdir())
        record_path = operation_root / "resources.json"
        retained = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertTrue(retained.get("worker_start_pending"))
        self.assertFalse(retained.get("worker_process_tree_dead"))
        self.assertNotIn("worker_pid", retained)

        with patch.object(module, "_process_alive", return_value=False):
            recovery = module.reconcile_orphaned_operations(
                root, timeout_seconds=30
            )

        self.assertEqual([operation_root.name], recovery["unresolved"])
        self.assertTrue(record_path.is_file())

    def test_popen_failure_clears_pending_state_without_false_blocker(self):
        module = self.module()
        root = self.governed_repo("popen-failure-clears-pending")
        observed = {}

        def fail_start(command):
            operation_id = command[-1]
            record = module._read_operation(root, operation_id)
            observed.update(record)
            raise OSError("round-seven Popen failure")

        with (
            patch.object(module, "_start_worker", side_effect=fail_start),
            self.assertRaisesRegex(OSError, "round-seven Popen failure"),
        ):
            module._run_graph_operation(
                root,
                graphify_python=sys.executable,
                commit=self.git(root, "rev-parse", "HEAD"),
                branch="main",
                kind="feature",
                manifest_name="engineering-traceability.json",
                hook=True,
                timeout_seconds=30,
                cleanup_timeout_seconds=30,
            )

        self.assertTrue(observed.get("worker_start_pending"))
        self.assertFalse(observed.get("worker_process_tree_dead"))
        self.assertEqual(
            {"reconciled": [], "unresolved": [], "live": []},
            module.reconcile_orphaned_operations(root, timeout_seconds=30),
        )

    def test_real_graph_worker_timeout_kills_descendant_and_cleans_git_registry(self):
        module = self.module()
        root = self.governed_repo("real-process-tree")
        (root / "src").mkdir()
        (root / "src" / "value.py").write_text(
            "def value():\n    return 1\n", encoding="utf-8"
        )
        self.commit_all(root, "process baseline")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/value.py", "def value():\n    return 2\n")
        child_pid_path = Path(self.temporary_directory.name) / "descendant.pid"
        before = self.git(root, "worktree", "list", "--porcelain")
        self.set_fake_graphify_controls(
            FAKE_GRAPHIFY_SLOW="120",
            FAKE_GRAPHIFY_CHILD_PID=str(child_pid_path),
        )

        with patch.dict(os.environ, environment, clear=False):
            result = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=30,
                cleanup_timeout_seconds=10,
            )

        self.assertEqual("hook_budget_exceeded", result["reason"])
        self.assertTrue(child_pid_path.is_file())
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        self.assertFalse(module._process_alive(child_pid))
        self.assertTrue(result["cleanup"]["completed"])
        registry = self.git(root, "worktree", "list", "--porcelain")
        self.assertNotIn("engineering-graphs/state/operations", registry.replace("\\", "/"))

    def test_orphan_blocks_next_worker_then_exact_recovery_allows_rebuild(self):
        module = self.module()
        root = self.governed_repo("orphan-recovery")
        (root / "src").mkdir()
        (root / "src" / "orphan.py").write_text(
            "def value():\n    return 1\n", encoding="utf-8"
        )
        self.commit_all(root, "orphan baseline")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/orphan.py", "def value():\n    return 2\n")
        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                module,
                "_start_worker",
                side_effect=self.timed_out_registered_worker(module),
            ),
            patch.object(
                module,
                "_terminate_process_tree",
                side_effect=lambda process, _pgid: (process.kill(), True)[1],
            ),
            patch.object(
                module,
                "_bounded_worktree_remove",
                return_value=(False, "registered_worktree_remove_failed", None),
            ),
        ):
            first = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=120,
                cleanup_timeout_seconds=5,
            )
        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                module,
                "_bounded_worktree_remove",
                return_value=(False, "registered_worktree_remove_failed", None),
            ),
        ):
            blocked = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=120,
                cleanup_timeout_seconds=5,
            )
        operation_record = Path(first["operation"]["record_path"])
        orphan = json.loads(operation_record.read_text(encoding="utf-8"))
        orphan["created_at"] = (
            time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1
        )
        operation_record.write_text(
            json.dumps(orphan, indent=2) + "\n", encoding="utf-8"
        )
        owner_path = Path(orphan["repository_lock_path"]) / "owner.json"
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        owner["created_at"] = time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1
        owner_path.write_text(
            json.dumps(owner, indent=2) + "\n", encoding="utf-8"
        )
        real_remove = module._bounded_worktree_remove

        def recover_fixture(root, worktree, deadline):
            if not (worktree / ".git").exists():
                shutil.rmtree(worktree)
                return True, "clean", None
            return real_remove(root, worktree, deadline)

        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                module,
                "_bounded_worktree_remove",
                side_effect=recover_fixture,
            ),
        ):
            recovered = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=120,
                cleanup_timeout_seconds=5,
            )

        record = Path(first["operation"]["record_path"])
        self.assertEqual("unresolved_hook_worker_orphan", first["reason"])
        self.assertEqual("blocked", blocked["readiness"])
        self.assertEqual("unresolved_hook_worker_orphan", blocked["reason"])
        if os.name == "nt":
            # A synthetic PID with no Windows identity/tree evidence must stay
            # durable and blocked; only a supported identity-attested reap may
            # remove the operation.
            self.assertEqual("blocked", recovered.get("readiness"))
            self.assertEqual("unresolved_hook_worker_orphan", recovered.get("reason"))
            self.assertTrue(record.exists())
            return
        self.assertTrue(recovered["orphan_reconciled_before_worker"])
        self.assertEqual("current", recovered["freshness"])
        self.assertFalse(record.exists())

    def test_enterprise_absence_is_proved_from_imports_config_and_argv(self):
        source = ENGINEERING_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        forbidden = ("enterprise_endpoint", "enterprise_client", "enterprise_upload")

        self.assertFalse(any("enterprise" in name.lower() for name in imports))
        self.assertFalse(any(key in json.dumps(manifest).lower() for key in forbidden))
        self.assertFalse(any(key in source.lower() for key in forbidden))


class Task5ContractTests(unittest.TestCase):
    init_repo = Task2ContractTests.init_repo
    governed_repo = Task3ContractTests.governed_repo
    git = Task2ContractTests.git
    commit_all = Task2ContractTests.commit_all
    run_cli = Task2ContractTests.run_cli
    require_cli_private_acl = Task2ContractTests.require_cli_private_acl
    write_controls = Task2ContractTests.write_controls
    write_fake_graphify = Task2ContractTests.write_fake_graphify
    write_canonical_checkpoint = Task2ContractTests.write_canonical_checkpoint
    recover_fixture_checkpoint = Task2ContractTests.recover_fixture_checkpoint
    prepared_repo = Task2ContractTests.prepared_repo
    start_fake_graphify_interpreter = Task2ContractTests.start_fake_graphify_interpreter
    set_fake_graphify_controls = Task2ContractTests.set_fake_graphify_controls

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.start_fake_graphify_interpreter()
        self.private_files = patch.object(
            engineering, "_enforce_owner_private", side_effect=synthetic_owner_private
        )
        self.private_files.start()
        self.addCleanup(self.private_files.stop)
        self.private_verifier = patch.object(
            engineering, "_verify_owner_private", return_value=None
        )
        self.private_verifier.start()
        self.addCleanup(self.private_verifier.stop)

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def prepared_run(
        self,
        name: str,
        *,
        scope: list[str],
        source_body: str | None = None,
    ) -> tuple[Path, dict]:
        root, _ = self.prepared_repo(name, source_body=source_body)
        self.module().approve_checks(root)
        prepared = self.module().prepare(
            root,
            "change REQ-1",
            {"scope": scope, "forbidden": ["publish", "deploy"]},
        )
        self.assertNotEqual("blocked", prepared["readiness"])
        return root, prepared

    def test_material_replacement_rejects_candidate_local_success_without_equivalence(self):
        handoff = {
            "seed_evidence": ["REQ-COOPERATIVE-ORCHESTRATION"],
            "reconstructed_scope": [
                "REQ-COOPERATIVE-ORCHESTRATION",
                "CAP-STATELESS-VALIDATOR",
                "TEST-VALIDATOR-PASSES",
            ],
            "architect_scope": [
                "REQ-COOPERATIVE-ORCHESTRATION",
                "CAP-STATELESS-VALIDATOR",
                "TEST-VALIDATOR-PASSES",
            ],
            "result_scope": [
                "REQ-COOPERATIVE-ORCHESTRATION",
                "CAP-STATELESS-VALIDATOR",
                "TEST-VALIDATOR-PASSES",
            ],
            "result_artifacts": ["validator.py", "tests/test_validator.py"],
            "outcome_survival": {
                "baseline_ids": ["REQ-COOPERATIVE-ORCHESTRATION"],
                "mappings": [
                    {
                        "baseline_id": "REQ-COOPERATIVE-ORCHESTRATION",
                        "disposition": "REPLACED",
                        "reason": "Candidate-local validator checks pass.",
                        "verification_ids": ["TEST-VALIDATOR-PASSES"],
                        "replacement_ids": ["CAP-STATELESS-VALIDATOR"],
                        "equivalence_decision_id": None,
                    }
                ],
            },
        }

        with self.assertRaisesRegex(
            self.module().EngineeringError, "outcome-equivalence"
        ):
            self.module()._scope_handoff(handoff, require_approval=False)

    def test_outcome_survival_lists_each_missing_baseline_mapping(self):
        handoff = {
            "seed_evidence": ["REQ-COOPERATIVE-ORCHESTRATION"],
            "reconstructed_scope": [
                "REQ-COOPERATIVE-ORCHESTRATION",
                "REQ-HUMAN-COORDINATION",
                "TEST-ORCHESTRATION",
            ],
            "architect_scope": [
                "REQ-COOPERATIVE-ORCHESTRATION",
                "REQ-HUMAN-COORDINATION",
                "TEST-ORCHESTRATION",
            ],
            "result_scope": [
                "REQ-COOPERATIVE-ORCHESTRATION",
                "REQ-HUMAN-COORDINATION",
                "TEST-ORCHESTRATION",
            ],
            "result_artifacts": ["orchestrator.py"],
            "outcome_survival": {
                "baseline_ids": [
                    "REQ-COOPERATIVE-ORCHESTRATION",
                    "REQ-HUMAN-COORDINATION",
                ],
                "mappings": [
                    {
                        "baseline_id": "REQ-COOPERATIVE-ORCHESTRATION",
                        "disposition": "INCLUDED",
                        "reason": "Cooperative orchestration remains present.",
                        "verification_ids": ["TEST-ORCHESTRATION"],
                        "replacement_ids": [],
                        "equivalence_decision_id": None,
                    }
                ],
            },
        }

        with self.assertRaisesRegex(
            self.module().EngineeringError, "REQ-HUMAN-COORDINATION"
        ):
            self.module()._scope_handoff(handoff, require_approval=False)

    def test_unmanaged_material_redesign_is_advisory_and_never_accepted(self):
        root = self.init_repo("unmanaged-outcome-survival")

        prepared = self.module().prepare(
            root,
            "replace cooperative orchestration with a stateless validator",
            {
                "scope": ["validator.py"],
                "forbidden": [],
                "change_class": "replacement",
            },
        )

        self.assertEqual("advisory", prepared["readiness"])
        self.assertFalse(prepared["completion_available"])
        self.assertEqual("unknown", prepared["outcome_survival"]["state"])
        self.assertEqual(
            "unmanaged_project", prepared["outcome_survival"]["boundary"]
        )
        self.assertFalse(prepared["outcome_survival"]["accepted"])
        self.assertFalse(prepared["outcome_survival"]["implementation_ready"])

    def test_managed_material_redesign_without_owner_intent_blocks_with_external_boundary(self):
        root, _ = self.prepared_repo("managed-outcome-survival")
        self.module().approve_checks(root)

        prepared = self.module().prepare(
            root,
            "simplify cooperative orchestration",
            {
                "scope": ["README.md"],
                "forbidden": [],
                "change_class": "simplification",
            },
        )

        self.assertEqual("blocked", prepared["readiness"])
        self.assertEqual([], prepared["outcome_survival"]["missing_baseline_mappings"])
        self.assertEqual(
            "external_owner_intent_required",
            prepared["outcome_survival"]["approval_boundary"],
        )
        self.assertEqual("owner_intent_unknown", prepared["owner_intent"]["state"])

    def test_prepare_detects_intent_impact_from_authorized_artifact(self):
        """A capability-linked authorized path cannot be hidden by query underselection."""
        module = self.module()
        root, _ = self.prepared_repo("authorized-artifact-intent-impact")
        (root / "src").mkdir()
        (root / "src" / "capability_runtime.py").write_text(
            "def run():\n    return 'native'\n", encoding="utf-8"
        )
        links_path = root / "docs" / "engineering-traceability" / "links.json"
        links = json.loads(links_path.read_text(encoding="utf-8"))
        links["nodes"].extend(
            [
                {
                    "id": "CAP-NATIVE-RUNTIME",
                    "type": "capability",
                    "title": "Native runtime capability",
                    "source": {"path": "design.md", "line": 1},
                },
                {
                    "id": "CODE-NATIVE-RUNTIME",
                    "type": "code_symbol",
                    "title": "Native runtime",
                    "source": {"path": "src/capability_runtime.py", "line": 1},
                },
            ]
        )
        links["edges"].append(
            {
                "id": "EDGE-CAP-NATIVE-RUNTIME",
                "from": "CAP-NATIVE-RUNTIME",
                "to": "CODE-NATIVE-RUNTIME",
                "type": "implements",
                "provenance": "direct",
                "source": {"path": "design.md", "line": 1},
            }
        )
        links_path.write_text(json.dumps(links, indent=2) + "\n", encoding="utf-8")
        commit = self.commit_all(root, "add capability runtime fixture")
        self.write_canonical_checkpoint(root, commit)
        module.approve_checks(root)

        prepared = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["src/capability_runtime.py"], "forbidden": []},
        )

        self.assertEqual("blocked", prepared["readiness"])
        self.assertIn(
            "intent-impacting work lacks a matching external owner-intent binding",
            prepared["blockers"],
        )
        self.assertEqual("owner_intent_unknown", prepared["owner_intent"]["state"])

    def test_complete_detects_capability_impact_from_actual_changed_artifact(self):
        """Completion rechecks touched artifacts so a stale selection cannot bypass survival."""
        module = self.module()
        root, prepared = self.prepared_run(
            "actual-artifact-intent-impact", scope=["README.md"]
        )
        checkpoint = module._load_checkpoint(root, prepared["project"]["commit"])
        checkpoint["nodes"].append(
            {
                "id": "CAP-LATE-BOUND",
                "type": "capability",
                "title": "Late-bound capability",
                "source": {"path": "design.md", "line": 1},
            }
        )
        checkpoint["edges"].append(
            {
                "id": "EDGE-LATE-BOUND",
                "from": "CAP-LATE-BOUND",
                "to": "CODE-1",
                "type": "implements",
                "provenance": "direct",
            }
        )
        (root / "README.md").write_text("# Changed capability artifact\n", encoding="utf-8")

        with patch.object(module, "_load_checkpoint", return_value=checkpoint), self.assertRaisesRegex(
            module.EngineeringError,
            "completion detected unbound intent impact from actual artifacts",
        ):
            module.complete(root, prepared["run_id"], [])

    def test_complete_fails_closed_for_new_capability_path_absent_from_base_checkpoint(self):
        """A newly mapped capability must be assessed from the refreshed exact checkpoint."""
        module = self.module()
        links_name = "docs/engineering-traceability/links.json"
        root, prepared = self.prepared_run(
            "new-capability-path-intent-impact",
            scope=["src/native_dispatch.py", links_name],
        )
        (root / "src").mkdir()
        (root / "src" / "native_dispatch.py").write_text(
            "def dispatch():\n    return 'native'\n", encoding="utf-8"
        )
        links_path = root / links_name
        links = json.loads(links_path.read_text(encoding="utf-8"))
        links["nodes"].extend(
            (
                {
                    "id": "CAP-NEW-NATIVE-DISPATCH",
                    "type": "capability",
                    "title": "New native dispatch capability",
                    "source": {"path": "design.md", "line": 1},
                },
                {
                    "id": "CODE-NEW-NATIVE-DISPATCH",
                    "type": "code_symbol",
                    "title": "New native dispatch implementation",
                    "source": {"path": "src/native_dispatch.py", "line": 1},
                },
            )
        )
        links["edges"].append(
            {
                "id": "EDGE-NEW-NATIVE-DISPATCH",
                "from": "CAP-NEW-NATIVE-DISPATCH",
                "to": "CODE-NEW-NATIVE-DISPATCH",
                "type": "implements",
                "provenance": "direct",
                "source": {"path": "design.md", "line": 1},
            }
        )
        links_path.write_text(json.dumps(links, indent=2) + "\n", encoding="utf-8")
        refreshed_commit = self.commit_all(root, "add new native dispatch capability")
        self.write_canonical_checkpoint(root, refreshed_commit)

        with self.assertRaisesRegex(
            module.EngineeringError,
            "completion detected unbound intent impact from actual artifacts",
        ):
            module.complete(root, prepared["run_id"], [])

    def test_complete_requires_result_checkpoint_for_new_owner_commitment_paths(self):
        """New README, prose, and test commitments cannot bypass result assessment."""
        module = self.module()
        paths = (
            ("README-owner-commitment.md", "# Owner commitment\n"),
            ("docs/owner-commitment.md", "# Owner commitment\n"),
            ("tests/test_owner_commitment.py", "def test_commitment():\n    pass\n"),
        )
        for index, (relative, content) in enumerate(paths, start=1):
            with self.subTest(path=relative):
                root, prepared = self.prepared_run(
                    f"new-owner-commitment-{index}", scope=[relative]
                )
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                head = self.commit_all(root, f"add {relative}")
                self.write_canonical_checkpoint(root, head)
                with (
                    patch.object(
                        module,
                        "check_merge_readiness",
                        return_value={"ready": False, "commit": head},
                    ),
                    patch.object(module, "rebuild", return_value={"freshness": "stale"}),
                    self.assertRaisesRegex(
                        module.EngineeringError,
                        "feature checkpoint refresh failed",
                    ),
                ):
                    module.complete(root, prepared["run_id"], [])

    def test_complete_fails_closed_for_modified_unrepresented_owner_commitment_paths(self):
        """Existing README/docs/tests omitted from base evidence still require refresh and intent."""
        module = self.module()
        paths = (
            ("README-owner-commitment.md", "# Initial owner commitment\n"),
            ("docs/specs/owner-intent.md", "# Initial owner commitment\n"),
            ("tests/test_owner_intent.py", "def test_initial_commitment():\n    pass\n"),
        )
        for index, (relative, initial) in enumerate(paths, start=1):
            with self.subTest(path=relative):
                root, _ = self.prepared_repo(f"modified-owner-commitment-{index}")
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(initial, encoding="utf-8")
                preparation_commit = self.commit_all(root, f"add {relative}")
                self.write_canonical_checkpoint(root, preparation_commit)
                module.approve_checks(root)
                prepared = module.prepare(
                    root,
                    "change REQ-1",
                    {"scope": [relative], "forbidden": ["publish", "deploy"]},
                )
                self.assertNotEqual("blocked", prepared["readiness"])
                base = module._load_checkpoint(root, preparation_commit)
                self.assertNotIn(relative, module._checkpoint_source_paths(base))

                path.write_text(initial + "Updated owner commitment.\n", encoding="utf-8")
                head = self.commit_all(root, f"modify {relative}")
                self.write_canonical_checkpoint(root, head)
                self.assertTrue(
                    module._requires_refreshed_intent_checkpoint(
                        root, preparation_commit, base, [relative]
                    )
                )
                self.assertTrue(
                    module._completion_intent_impact(
                        root,
                        preparation_commit,
                        head,
                        False,
                        [relative],
                        prepared["authorization"],
                        prepared["authorization"].get("scope_handoff"),
                        {"ready": True, "commit": head},
                    )
                )
                with (
                    patch.object(
                        module,
                        "check_merge_readiness",
                        return_value={"ready": True, "commit": head},
                    ),
                    self.assertRaisesRegex(
                        module.EngineeringError,
                        "completion detected unbound intent impact from actual artifacts",
                    ),
                ):
                    module.complete(root, prepared["run_id"], [])

    def test_existing_unrepresented_governance_and_unknown_paths_require_refresh(self):
        """Existing policy, release, automation, and unknown paths cannot bypass intent refresh."""
        module = self.module()
        paths = (
            "SECURITY.md",
            "AGENTS.md",
            "CLAUDE.md",
            "CONTRIBUTING.md",
            ".github/workflows/security.yml",
            "release/public-export.json",
            "unclassified/material-owner-impact.txt",
        )
        for index, relative in enumerate(paths, start=1):
            with self.subTest(path=relative):
                root, _ = self.prepared_repo(f"unrepresented-governance-{index}")
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("initial governed artifact\n", encoding="utf-8")
                preparation_commit = self.commit_all(root, f"add {relative}")
                self.write_canonical_checkpoint(root, preparation_commit)
                base = module._load_checkpoint(root, preparation_commit)
                self.assertNotIn(relative, module._checkpoint_source_paths(base))

                path.write_text("changed governed artifact\n", encoding="utf-8")
                head = self.commit_all(root, f"modify {relative}")

                self.assertTrue(
                    module._requires_refreshed_intent_checkpoint(
                        root, preparation_commit, base, [relative]
                    )
                )
                with self.assertRaisesRegex(
                    module.EngineeringError, "feature checkpoint refresh failed"
                ):
                    module._completion_intent_impact(
                        root,
                        preparation_commit,
                        head,
                        False,
                        [relative],
                        {},
                        None,
                        {"ready": False, "commit": head},
                    )

    def test_complete_detects_capability_impact_across_authorized_rename(self):
        """Both rename endpoints are assessed before an approved scope can complete."""
        module = self.module()
        root, prepared = self.prepared_run(
            "renamed-artifact-intent-impact",
            scope=["README.md", "README-renamed.md"],
        )
        checkpoint = module._load_checkpoint(root, prepared["project"]["commit"])
        checkpoint["nodes"].append(
            {
                "id": "CAP-RENAMED",
                "type": "capability",
                "title": "Renamed capability",
                "source": {"path": "design.md", "line": 1},
            }
        )
        checkpoint["edges"].append(
            {
                "id": "EDGE-RENAMED",
                "from": "CAP-RENAMED",
                "to": "CODE-1",
                "type": "implements",
                "provenance": "direct",
            }
        )
        (root / "README.md").rename(root / "README-renamed.md")

        with patch.object(module, "_load_checkpoint", return_value=checkpoint), self.assertRaisesRegex(
            module.EngineeringError,
            "completion detected unbound intent impact from actual artifacts",
        ):
            module.complete(root, prepared["run_id"], [])


    def test_legacy_material_scope_handoff_remains_readable_but_owner_intent_unknown(self):
        module = self.module()
        root, _ = self.prepared_repo("scope-handoff")
        ledger = root / "docs" / "engineering-traceability" / "decision-ledger.md"
        ledger.write_text(
            "# Engineering Traceability Decision Ledger\n"
            "## PROJ-DEC-1 - Approved reconstructed scope\n",
            encoding="utf-8",
        )
        links_path = root / "docs" / "engineering-traceability" / "links.json"
        links = json.loads(links_path.read_text(encoding="utf-8"))
        links["nodes"].append(
            {
                "id": "PROJ-DEC-1",
                "type": "decision",
                "title": "Approved reconstructed scope",
                "source": {
                    "path": "docs/engineering-traceability/decision-ledger.md",
                    "line": 2,
                },
            }
        )
        links_path.write_text(json.dumps(links, indent=2) + "\n", encoding="utf-8")
        commit = self.commit_all(root, "record approved scope decision")
        self.write_canonical_checkpoint(root, commit)
        module.approve_checks(root)
        raw_handoff = {
            "seed_evidence": ["REQ-1"],
            "reconstructed_scope": ["REQ-1", "DEC-1"],
            "architect_scope": ["REQ-1", "DEC-1"],
            "result_scope": ["REQ-1", "DEC-1"],
            "result_artifacts": ["README.md", "requirements.md"],
            "outcome_survival": {
                "baseline_ids": ["REQ-1"],
                "mappings": [
                    {
                        "baseline_id": "REQ-1",
                        "disposition": "EXCLUDED",
                        "reason": "Owner approved the exact exclusion for this redesign.",
                        "verification_ids": ["DEC-1"],
                        "replacement_ids": [],
                        "equivalence_decision_id": None,
                    }
                ],
            },
        }
        approval = module.approve_scope_handoff(root, "PROJ-DEC-1", raw_handoff)
        handoff = approval["scope_handoff"]
        with self.assertRaisesRegex(module.EngineeringError, "attestation"):
            module.prepare(
                root,
                "change REQ-1",
                {
                    "scope": ["README.md", "requirements.md"],
                    "forbidden": [],
                    "change_class": "capability_deletion",
                    "scope_handoff": {
                        **handoff,
                        "approval_id": "attestation-" + "0" * 32,
                    },
                },
            )
        prepared = module.prepare(
            root,
            "change REQ-1",
            {
                "scope": ["README.md", "requirements.md"],
                "forbidden": [],
                "change_class": "capability_deletion",
                "scope_handoff": handoff,
            },
        )
        self.assertEqual("blocked", prepared["readiness"])
        self.assertEqual("owner_intent_unknown", prepared["owner_intent"]["state"])
        self.assertEqual(
            "owner_intent_unknown", prepared["outcome_survival"]["boundary"]
        )
        self.assertEqual(
            handoff["outcome_survival"],
            prepared["authorization"]["scope_handoff"]["outcome_survival"],
        )
        with self.assertRaisesRegex(module.EngineeringError, "not completion-ready"):
            module.complete(root, prepared["run_id"], receipts=[])

    def green_receipts(self, prepared: dict) -> list[dict]:
        module = self.module()
        return [
            {
                "schema": "engineering.check.v1",
                "command_id": module._check_identity(argv),
                "exit_code": 0,
                "duration_seconds": 0.01,
                "output_digest": "sha256:" + "0" * 64,
            }
            for argv in prepared["required_checks"]
        ]

    def test_complete_rejects_scope_expansion(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-scope", scope=["src/auth.py"]
        )
        (root / "src").mkdir()
        (root / "src" / "payments.py").write_text(
            "changed = True\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(module.EngineeringError, "scope"):
            module.complete(root, prepared["run_id"], receipts=[])

    def test_complete_is_idempotent_for_same_run_and_tree(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-replay", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        first = module.complete(root, prepared["run_id"], receipts=[])
        second = module.complete(root, prepared["run_id"], receipts=[])

        self.assertEqual(first, second)
        self.assertEqual("engineering.complete.v1", first["schema"])

    def test_complete_rejects_replay_after_the_tree_changes(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-replay-conflict", scope=["README.md"]
        )
        (root / "README.md").write_text("# First\n", encoding="utf-8")
        module.complete(root, prepared["run_id"], receipts=[])
        (root / "README.md").write_text("# Second\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "replay"):
            module.complete(root, prepared["run_id"], receipts=[])

    def test_complete_rejects_a_corrupt_retained_manifest(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-corrupt-replay", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        result = module.complete(root, prepared["run_id"], receipts=[])
        manifest = Path(result["manifest"])
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["schema"] = "corrupt"
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "manifest"):
            module.complete(root, prepared["run_id"], receipts=[])

    def test_complete_rejects_tampered_replay_owned_fields_and_schema(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-tampered-replay", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        result = module.complete(root, prepared["run_id"], receipts=[])
        manifest = Path(result["manifest"])
        original = json.loads(manifest.read_text(encoding="utf-8"))

        def authorization(payload):
            payload["authorization"]["scope"].append("outside.txt")

        def context(payload):
            payload["context"] = []

        def impact(payload):
            payload["actual_impact"] = []

        def check(payload):
            payload["checks"][0]["exit_code"] = 1

        def checkpoint(payload):
            payload["checkpoint"]["status"] = "current"

        def advisory(payload):
            payload["advisories"] = [{"code": "invented"}]

        def extra(payload):
            payload["unexpected"] = True

        def missing(payload):
            payload.pop("maintenance")

        for label, tamper in (
            ("authorization", authorization),
            ("context", context),
            ("impact", impact),
            ("check", check),
            ("checkpoint", checkpoint),
            ("advisory", advisory),
            ("extra", extra),
            ("missing", missing),
        ):
            with self.subTest(label=label):
                payload = json.loads(json.dumps(original))
                tamper(payload)
                manifest.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(module.EngineeringError, "manifest"):
                    module.complete(root, prepared["run_id"], receipts=[])
        manifest.write_text(json.dumps(original), encoding="utf-8")

    def test_dirty_identity_rejects_reparse_artifacts(self):
        module = self.module()
        root = self.init_repo("complete-reparse")
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        with patch.object(module, "_is_reparse_point", return_value=True):
            with self.assertRaisesRegex(module.EngineeringError, "reparse"):
                module._working_state_identity(root)

    def test_context_bodies_never_enter_manifest(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-private",
            scope=["README.md"],
            source_body="PRIVATE SYNTHETIC BODY",
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        result = module.complete(root, prepared["run_id"], receipts=[])
        text = Path(result["manifest"]).read_text(encoding="utf-8")

        self.assertNotIn("PRIVATE SYNTHETIC BODY", text)
        self.assertNotIn(str(root), text)

    def test_complete_executes_only_prepared_argv_without_shell(self):
        module = self.module()
        argv = [sys.executable, "-c", "print('synthetic')"]

        with patch.object(
            module.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(argv, 0, "ok\n", ""),
        ) as runner:
            receipt = module._execute_check(argv, timeout_seconds=5)

        self.assertEqual(0, receipt["exit_code"])
        self.assertRegex(receipt["output_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(argv, runner.call_args.args[0])
        self.assertIs(False, runner.call_args.kwargs["shell"])
        self.assertNotIn("ok", json.dumps(receipt))

    def test_complete_rejects_forged_green_receipt_for_prepared_command(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-forged-receipt", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "caller.*receipt"):
            module.complete(
                root,
                prepared["run_id"],
                receipts=self.green_receipts(prepared),
            )

    def test_changed_paths_include_both_rename_ends_and_block_old_path(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-rename-scope", scope=["renamed.md"]
        )
        (root / "README.md").rename(root / "renamed.md")
        self.git(root, "add", "-A")

        self.assertEqual(
            ["README.md", "renamed.md"],
            module._changed_paths_since(root, prepared["project"]["commit"]),
        )
        with self.assertRaisesRegex(module.EngineeringError, "scope"):
            module.complete(root, prepared["run_id"], receipts=[])

    def test_changed_paths_include_both_copy_ends(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-copy-paths", scope=["README.md", "copied.md"]
        )
        shutil.copyfile(root / "README.md", root / "copied.md")
        self.git(root, "add", "copied.md")

        self.assertEqual(
            ["README.md", "copied.md"],
            module._changed_paths_since(root, prepared["project"]["commit"]),
        )

    def test_changed_paths_include_unstaged_exact_copy_source(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-unstaged-copy", scope=["README.md", "copied.md"]
        )
        shutil.copyfile(root / "README.md", root / "copied.md")

        self.assertEqual(
            ["README.md", "copied.md"],
            module._changed_paths_since(root, prepared["project"]["commit"]),
        )

    def test_untracked_copy_provenance_fails_closed_on_unmerged_index(self):
        module = self.module()
        root = self.init_repo("complete-ambiguous-copy")
        shutil.copyfile(root / "README.md", root / "copied.md")
        original = module._git_bytes

        def ambiguous_index(project_root, *arguments):
            if arguments == ("ls-files", "--stage", "-z"):
                return b"100644 " + b"0" * 40 + b" 2\tREADME.md\0"
            return original(project_root, *arguments)

        with patch.object(module, "_git_bytes", side_effect=ambiguous_index):
            with self.assertRaisesRegex(module.EngineeringError, "ambiguous"):
                module._changed_paths_since(
                    root, self.git(root, "rev-parse", "HEAD")
                )

    def test_changed_paths_include_committed_exact_copy_source(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-committed-copy", scope=["README.md", "copied.md"]
        )
        shutil.copyfile(root / "README.md", root / "copied.md")
        self.commit_all(root, "copy README")

        self.assertEqual(
            ["README.md", "copied.md"],
            module._changed_paths_since(root, prepared["project"]["commit"]),
        )

    def test_complete_blocks_new_public_contract_in_dirty_overlay(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-dirty-contract",
            scope=["api.md", "docs/engineering-traceability/links.json"],
        )
        links_path = root / "docs" / "engineering-traceability" / "links.json"
        links = json.loads(links_path.read_text(encoding="utf-8"))
        links["nodes"].append(
            {
                "id": "CONTRACT-DIRTY",
                "type": "contract",
                "title": "Dirty synthetic contract",
                "source": {"path": "api.md", "line": 1},
            }
        )
        links_path.write_text(json.dumps(links), encoding="utf-8")
        (root / "api.md").write_text("# New contract\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "contract"):
            module.complete(root, prepared["run_id"], receipts=[])

    def test_dirty_identity_includes_index_only_changes(self):
        module = self.module()
        root = self.init_repo("complete-index-identity")
        clean = module._working_state_identity(root)
        (root / "README.md").write_text("# Staged\n", encoding="utf-8")
        self.git(root, "add", "README.md")
        self.git(root, "restore", "--worktree", "README.md")

        staged = module._working_state_identity(root)

        self.assertNotEqual(clean, staged)
        self.assertEqual(self.git(root, "rev-parse", "HEAD"), staged["head"])

    def test_dirty_identity_includes_staged_executable_mode(self):
        module = self.module()
        root = self.init_repo("complete-index-mode")
        before = module._working_state_identity(root)
        self.git(root, "update-index", "--chmod=+x", "README.md")

        self.assertNotEqual(before, module._working_state_identity(root))

    def test_dirty_identity_includes_submodule_head(self):
        module = self.module()
        root = self.init_repo("complete-submodule-parent")
        source = self.init_repo("complete-submodule-source")
        self.git(
            root,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(source),
            "vendor/sub",
        )
        self.commit_all(root, "add submodule")
        before = module._working_state_identity(root)
        checkout = root / "vendor" / "sub"
        self.git(checkout, "config", "user.email", "synthetic")
        self.git(checkout, "config", "user.name", "Synthetic Test")
        (checkout / "README.md").write_text("# New submodule head\n", encoding="utf-8")
        self.commit_all(checkout, "advance submodule")

        self.assertNotEqual(before, module._working_state_identity(root))

    @unittest.skipIf(os.name == "nt", "Git executable-mode changes are not portable on Windows")
    def test_dirty_identity_includes_unstaged_executable_mode(self):
        module = self.module()
        root = self.init_repo("complete-mode-identity")
        before = module._working_state_identity(root)
        os.chmod(root / "README.md", 0o755)

        self.assertNotEqual(before, module._working_state_identity(root))

    @unittest.skipIf(os.name == "nt", "POSIX executable mode is not portable on Windows")
    def test_dirty_identity_includes_untracked_executable_mode(self):
        module = self.module()
        root = self.init_repo("complete-untracked-mode-identity")
        artifact = root / "tool.sh"
        artifact.write_text("#!/bin/sh\n", encoding="utf-8")
        os.chmod(artifact, 0o644)
        before = module._working_state_identity(root)
        os.chmod(artifact, 0o755)

        self.assertNotEqual(before, module._working_state_identity(root))

    def test_complete_rechecks_state_after_checks_before_publication(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-check-race", scope=["README.md"]
        )
        (root / "README.md").write_text("# Before check\n", encoding="utf-8")

        def mutate(argv, *, timeout_seconds, cwd=None):
            (root / "README.md").write_text("# During check\n", encoding="utf-8")
            return {
                "schema": "engineering.check.v1",
                "command_id": module._check_identity(argv),
                "exit_code": 0,
                "duration_seconds": 0.01,
                "output_digest": "sha256:" + "0" * 64,
            }

        with patch.object(module, "_execute_check", side_effect=mutate):
            with self.assertRaisesRegex(module.EngineeringError, "changed during checks"):
                module.complete(root, prepared["run_id"], receipts=[])

    def test_complete_rejects_mutation_between_path_capture_and_initial_state(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-initial-snapshot-race", scope=["README.md"]
        )
        (root / "README.md").write_text("# Authorized dirty change\n", encoding="utf-8")
        original = module._changed_paths_since
        calls = 0

        def mutate_after_capture(project_root, commit):
            nonlocal calls
            calls += 1
            paths = original(project_root, commit)
            if calls == 1:
                (root / "outside.txt").write_text(
                    "unauthorized second write\n", encoding="utf-8"
                )
            return paths

        with patch.object(
            module, "_changed_paths_since", side_effect=mutate_after_capture
        ):
            with self.assertRaisesRegex(
                module.EngineeringError, "initial working state changed"
            ):
                module.complete(root, prepared["run_id"], receipts=[])

    def test_complete_rechecks_state_immediately_before_publication(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-publish-race", scope=["README.md"]
        )
        (root / "README.md").write_text("# Initial state\n", encoding="utf-8")
        original = module._working_state_identity
        calls = 0

        def mutate_before_publish(project_root):
            nonlocal calls
            calls += 1
            if calls == 4:
                (root / "README.md").write_text("# Publish race\n", encoding="utf-8")
            return original(project_root)

        def green_check(argv, *, timeout_seconds, cwd=None):
            return {
                "schema": "engineering.check.v1",
                "command_id": module._check_identity(argv),
                "exit_code": 0,
                "duration_seconds": 0.01,
                "output_digest": "sha256:" + "0" * 64,
            }

        with (
            patch.object(
                module, "_working_state_identity", side_effect=mutate_before_publish
            ),
            patch.object(module, "_execute_check", side_effect=green_check),
        ):
            with self.assertRaisesRegex(module.EngineeringError, "before publication"):
                module.complete(root, prepared["run_id"], receipts=[])

    def test_just_created_dead_owner_is_not_reclaimed(self):
        module = self.module()
        root = self.init_repo("complete-young-orphan")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        self.assertTrue(module._acquire_repository_lock(record))

        with patch.object(module, "_process_state", return_value="dead"):
            result = module.reconcile_orphaned_operations(root, timeout_seconds=5)

        self.assertEqual([operation["operation_id"]], result["unresolved"])
        self.assertTrue(Path(record["repository_lock_path"]).exists())
        current = module._read_operation(root, operation["operation_id"])
        current.update(phase="orphaned", worker_process_tree_dead=True)
        module._write_operation(current)
        self.addCleanup(
            module.cleanup_hook_operation,
            root,
            operation["operation_id"],
            timeout_seconds=5,
        )

    def test_invalid_or_future_orphan_timestamps_are_not_reclaimed(self):
        module = self.module()
        for label, timestamp in (("invalid", float("-inf")), ("future", time.time() + 60)):
            with self.subTest(label=label):
                root = self.init_repo(f"complete-{label}-orphan")
                operation = module.register_hook_operation(root)
                record = module._read_operation(root, operation["operation_id"])
                self.assertTrue(module._acquire_repository_lock(record))
                record["created_at"] = timestamp
                module._write_operation(record)
                owner_path = Path(record["repository_lock_path"]) / "owner.json"
                owner = json.loads(owner_path.read_text(encoding="utf-8"))
                owner["created_at"] = timestamp
                owner_path.write_text(json.dumps(owner), encoding="utf-8")

                with patch.object(module, "_process_state", return_value="dead"):
                    result = module.reconcile_orphaned_operations(
                        root, timeout_seconds=5
                    )

                self.assertEqual([operation["operation_id"]], result["unresolved"])
                current = module._read_operation(root, operation["operation_id"])
                current.update(
                    phase="orphaned",
                    worker_process_tree_dead=True,
                    created_at=time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1,
                )
                module._write_operation(current)
                owner["created_at"] = current["created_at"]
                owner_path.write_text(json.dumps(owner), encoding="utf-8")
                self.addCleanup(
                    module.cleanup_hook_operation,
                    root,
                    operation["operation_id"],
                    timeout_seconds=5,
                )

    def test_complete_blocks_unpredicted_public_contract_change(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-contract",
            scope=["api.md", "docs/engineering-traceability/links.json"],
        )
        links_path = root / "docs" / "engineering-traceability" / "links.json"
        links = json.loads(links_path.read_text(encoding="utf-8"))
        links["nodes"].append(
            {
                "id": "CONTRACT-UNPREDICTED",
                "type": "contract",
                "title": "Synthetic public contract",
                "source": {"path": "api.md", "line": 1},
            }
        )
        links_path.write_text(json.dumps(links), encoding="utf-8")
        (root / "api.md").write_text("# Changed contract\n", encoding="utf-8")
        (root / "docs" / "extra.md").write_text("# Unrelated follow-up\n", encoding="utf-8")
        self.commit_all(root, "unpredicted public contract")
        fake_graphify = self.write_fake_graphify()
        maintenance = module.common_graph_dir(root) / "state" / "maintenance.json"

        with patch.dict(os.environ, {"PYTHONPATH": str(fake_graphify)}, clear=False):
            with self.assertRaisesRegex(module.EngineeringError, "contract"):
                module.complete(
                    root,
                    prepared["run_id"],
                    receipts=[],
                )
        self.assertFalse(maintenance.exists())

    def test_complete_uses_the_single_repository_lock_and_cleans_it(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-lock", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        result = module.complete(root, prepared["run_id"], receipts=[])

        common = module.common_graph_dir(root)
        self.assertEqual(
            str(common / "runs" / prepared["run_id"] / "completion.json"),
            result["manifest"],
        )
        self.assertFalse((common / "state" / "lock").exists())
        self.assertEqual([], list((common / "state" / "operations").glob("*")))

    def test_completion_lock_records_exact_owner_identity(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-lock-owner", scope=["README.md"]
        )
        record = module._begin_completion(root, prepared["run_id"])
        self.addCleanup(module._end_completion, root, record)
        owner = module._lock_owner(record)

        self.assertEqual(prepared["run_id"], owner["run_id"])
        self.assertEqual(record["operation_id"], owner["operation_id"])
        self.assertEqual(record["lock_token"], owner["lock_token"])
        self.assertEqual(os.getpid(), owner["owner_pid"])
        self.assertIsInstance(owner["created_at"], float)

    def test_controller_completion_cleanup_preserves_replacement_lock(self):
        module = self.module()
        root = self.governed_repo("completion-replaced-lock")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            kind="completion",
            phase="orphaned",
            worker_process_tree_dead=True,
            controller_owned_completion=True,
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        replacement_owner = {
            "operation_id": "newer-operation",
            "lock_token": "newer-token",
            "owner_pid": os.getpid(),
            "owner_identity": module._process_identity(os.getpid()),
            "created_at": time.time(),
        }
        owner_path = Path(record["repository_lock_path"]) / "owner.json"
        owner_path.write_text(json.dumps(replacement_owner), encoding="utf-8")

        with patch.object(
            module,
            "_process_tree_status",
            return_value={"state": "dead", "evidence": "saved_identity_absent"},
        ):
            result = module.cleanup_hook_operation(
                root,
                operation["operation_id"],
                timeout_seconds=5,
                allow_replaced_completion_lock=True,
            )

        self.assertTrue(result["completed"], result)
        self.assertFalse(Path(record["record_path"]).exists())
        self.assertEqual(
            replacement_owner,
            json.loads(owner_path.read_text(encoding="utf-8")),
        )

    def test_replaced_lock_bypass_requires_controller_completion_marker(self):
        module = self.module()
        root = self.governed_repo("completion-replaced-lock-marker")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(kind="completion", phase="orphaned", worker_process_tree_dead=True)
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        owner_path = Path(record["repository_lock_path"]) / "owner.json"
        replacement_owner = {
            "operation_id": "newer-operation",
            "lock_token": "newer-token",
            "owner_pid": os.getpid(),
            "owner_identity": module._process_identity(os.getpid()),
            "created_at": time.time(),
        }
        owner_path.write_text(json.dumps(replacement_owner), encoding="utf-8")

        with patch.object(
            module,
            "_process_tree_status",
            return_value={"state": "dead", "evidence": "saved_identity_absent"},
        ):
            result = module.cleanup_hook_operation(
                root,
                operation["operation_id"],
                timeout_seconds=5,
                allow_replaced_completion_lock=True,
            )

        self.assertFalse(result["completed"])
        self.assertEqual("repository_lock_owner_mismatch", result["reason"])
        self.assertTrue(Path(record["record_path"]).exists())
        self.assertEqual(
            replacement_owner,
            json.loads(owner_path.read_text(encoding="utf-8")),
        )

    def test_replaced_lock_bypass_rejects_worker_operation(self):
        module = self.module()
        root = self.governed_repo("worker-replaced-lock")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            kind="hook",
            phase="orphaned",
            worker_pid=4242,
            worker_process_tree_dead=True,
            controller_owned_completion=True,
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        owner_path = Path(record["repository_lock_path"]) / "owner.json"
        replacement_owner = {
            "operation_id": "newer-operation",
            "lock_token": "newer-token",
            "owner_pid": os.getpid(),
            "owner_identity": module._process_identity(os.getpid()),
            "created_at": time.time(),
        }
        owner_path.write_text(json.dumps(replacement_owner), encoding="utf-8")

        with patch.object(
            module,
            "_process_tree_status",
            return_value={"state": "dead", "evidence": "saved_identity_absent"},
        ):
            result = module.cleanup_hook_operation(
                root,
                operation["operation_id"],
                timeout_seconds=5,
                allow_replaced_completion_lock=True,
            )

        self.assertFalse(result["completed"])
        self.assertEqual("repository_lock_owner_mismatch", result["reason"])
        self.assertTrue(Path(record["record_path"]).exists())
        self.assertEqual(
            replacement_owner,
            json.loads(owner_path.read_text(encoding="utf-8")),
        )

    def test_concurrent_live_repository_lock_blocks_without_replacing_owner(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-concurrent", scope=["README.md"]
        )
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        self.assertTrue(module._acquire_repository_lock(record))
        owner_before = module._lock_owner(record)
        self.addCleanup(
            lambda: (
                module._write_operation(
                    {
                        **module._read_operation(root, operation["operation_id"]),
                        "phase": "orphaned",
                        "worker_process_tree_dead": True,
                    }
                ),
                module.cleanup_hook_operation(
                    root, operation["operation_id"], timeout_seconds=5
                ),
            )
        )

        with self.assertRaisesRegex(module.EngineeringError, "lock"):
            module.complete(
                root,
                prepared["run_id"],
                receipts=[],
            )

        self.assertEqual(owner_before, module._lock_owner(record))

    def test_complete_refreshes_the_exact_clean_feature_checkpoint(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-checkpoint", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        commit = self.commit_all(root, "authorized change")
        fake_graphify = self.write_fake_graphify()

        with patch.dict(os.environ, {"PYTHONPATH": str(fake_graphify)}, clear=False):
            result = module.complete(
                root,
                prepared["run_id"],
                receipts=[],
            )

        self.assertEqual({"commit": commit, "status": "current"}, result["checkpoint"])

    def test_complete_cli_emits_the_bounded_manifest(self):
        root, prepared = self.prepared_run(
            "complete-cli", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        self.require_cli_private_acl(root)

        result = self.run_cli(
            "complete",
            root,
            prepared["run_id"],
        )

        if (
            os.name == "nt"
            and "owner-private ACL verification failed" in result.stderr
        ):
            self.skipTest("Windows host cannot verify new controller ACLs in a child process")

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("engineering.complete.v1", payload["schema"])
        self.assertEqual(
            {
                "schema",
                "run_id",
                "project",
                "intent",
                "authorization",
                "autonomy",
                "context",
                "changed_artifacts",
                "predicted_impact",
                "actual_impact",
                "traceability",
                "checks",
                "advisories",
                "maintenance",
                "checkpoint",
                "result_identity",
                "manifest",
            },
            set(payload),
        )

    def test_skill_requires_automatic_completion_before_readiness(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())

        self.assertIn("Engineering completion runs automatically", text)
        self.assertIn("before claiming non-trivial work is ready", text)
        self.assertIn("diagnostics and CI", text)


class Task6ContractTests(unittest.TestCase):
    init_repo = Task2ContractTests.init_repo
    git = Task2ContractTests.git
    commit_all = Task2ContractTests.commit_all
    run_cli = Task2ContractTests.run_cli
    write_controls = Task2ContractTests.write_controls
    write_fake_graphify = Task2ContractTests.write_fake_graphify
    write_canonical_checkpoint = Task2ContractTests.write_canonical_checkpoint
    recover_fixture_checkpoint = Task2ContractTests.recover_fixture_checkpoint
    prepared_repo = Task2ContractTests.prepared_repo
    prepared_run = Task5ContractTests.prepared_run
    governed_repo = Task3ContractTests.governed_repo
    cold_checkpoint = Task3ContractTests.cold_checkpoint
    commit_file = Task3ContractTests.commit_file
    graphify_environment = Task3ContractTests.graphify_environment
    start_fake_graphify_interpreter = Task2ContractTests.start_fake_graphify_interpreter
    set_fake_graphify_controls = Task2ContractTests.set_fake_graphify_controls

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.start_fake_graphify_interpreter()
        self.private_files = patch.object(
            engineering, "_enforce_owner_private", side_effect=synthetic_owner_private
        )
        self.private_files.start()
        self.addCleanup(self.private_files.stop)
        self.private_verifier = patch.object(
            engineering, "_verify_owner_private", return_value=None
        )
        self.private_verifier.start()
        self.addCleanup(self.private_verifier.stop)

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def queue(self, root: Path, **item) -> dict:
        return self.module().queue_maintenance(
            root,
            {
                "area": "docs",
                "artifact": "checkpoint",
                "kind": "checkpoint_stale",
                "impact": "routine",
                **item,
            },
        )

    def test_collaborative_is_default_and_explained_once(self):
        module = self.module()
        root = self.init_repo("autonomy-default")
        self.write_controls(root, generation="v2")

        first = module._ensure_autonomy(root)
        second = module._ensure_autonomy(root)

        self.assertEqual("collaborative", first["autonomy"])
        self.assertTrue(first["explain_autonomy"])
        self.assertFalse(second["explain_autonomy"])
        config = json.loads((root / "engineering.json").read_text(encoding="utf-8"))
        self.assertEqual("collaborative", config["autonomy"])
        self.assertTrue(config["autonomy_explained"])

    def test_saved_autonomy_and_task_override_are_separate(self):
        module = self.module()
        root, _ = self.prepared_repo("autonomy-override")

        changed = module.set_autonomy(root, "guided")
        prepared = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": ["publish"]},
            "steward",
        )

        self.assertEqual("guided", changed["autonomy"])
        self.assertEqual("guided", module.get_autonomy(root))
        self.assertEqual("steward", prepared["autonomy"])
        retained = json.loads(
            (
                module.common_graph_dir(root)
                / "runs"
                / prepared["run_id"]
                / "preparation.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("steward", retained["autonomy"])
        self.assertEqual("guided", module.get_autonomy(root))
        with self.assertRaisesRegex(module.EngineeringError, "autonomy"):
            module.set_autonomy(root, "automatic")

    def test_autonomy_change_records_bounded_replay_safe_project_history(self):
        module = self.module()
        root, _ = self.prepared_repo("autonomy-history")

        confirmed = module.set_autonomy(root, "collaborative")
        confirmed_replay = module.set_autonomy(root, "collaborative")
        first = module.set_autonomy(root, "guided")
        retained = module.set_autonomy(root, "guided")
        config = json.loads(
            (root / "engineering-traceability.json").read_text(encoding="utf-8")
        )

        self.assertEqual(confirmed, confirmed_replay)
        self.assertEqual(first, retained)
        self.assertEqual(
            [
                {
                    "kind": "autonomy_change",
                    "previous": "collaborative",
                    "new": "collaborative",
                    "changed_at": confirmed["changed_at"],
                    "origin": "engineering",
                    "reason": "saved autonomy changed",
                },
                {
                    "kind": "autonomy_change",
                    "previous": "collaborative",
                    "new": "guided",
                    "changed_at": first["changed_at"],
                    "origin": "engineering",
                    "reason": "saved autonomy changed",
                }
            ],
            config["autonomy_history"],
        )
        self.assertNotIn(str(root), json.dumps(config["autonomy_history"]))

    def test_autonomy_history_migrates_and_preserves_unrelated_history(self):
        module = self.module()
        root, _ = self.prepared_repo("autonomy-history-migration")
        path = root / "engineering-traceability.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        unrelated = [{"kind": "decision", "id": index} for index in range(60)]
        legacy = {
            "kind": "autonomy_change",
            "previous": "collaborative",
            "new": "guided",
            "changed_at": "2026-01-01T00:00:00Z",
            "origin": "engineering",
            "reason": "saved autonomy changed",
        }
        config.update(autonomy="guided", history=[*unrelated, legacy])
        config["autonomy_history"] = [
            {
                **legacy,
                "previous": "guided" if index else "collaborative",
                "new": "guided",
                "changed_at": f"2026-01-01T00:00:{index:02d}Z",
            }
            for index in range(55)
        ]
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        first = module.set_autonomy(root, "guided")
        bytes_after_first = path.read_bytes()
        second = module.set_autonomy(root, "guided")
        retained = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(first, second)
        self.assertEqual(bytes_after_first, path.read_bytes())
        self.assertEqual(unrelated, retained["history"])
        self.assertEqual(50, len(retained["autonomy_history"]))
        self.assertEqual("guided", retained["autonomy_history"][-1]["new"])

    def test_steward_preserves_publication_and_deployment_gates(self):
        module = self.module()
        root, _ = self.prepared_repo("autonomy-gates")
        module.set_autonomy(root, "steward")

        result = module.prepare(
            root,
            "publish and deploy the synthetic package",
            {
                "scope": ["README.md"],
                "forbidden": ["publish", "deploy"],
            },
            None,
        )

        self.assertEqual("blocked", result["readiness"])
        self.assertEqual(["publish", "deploy"], result["authorization"]["forbidden"])

    def test_autonomy_change_respects_the_single_live_repository_lock(self):
        module = self.module()
        root, _ = self.prepared_repo("autonomy-lock")
        path = root / "engineering-traceability.json"
        before = path.read_bytes()
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        self.assertTrue(module._acquire_repository_lock(record))
        self.addCleanup(
            lambda: (
                module._write_operation(
                    {
                        **module._read_operation(root, operation["operation_id"]),
                        "phase": "orphaned",
                        "worker_process_tree_dead": True,
                    }
                ),
                module.cleanup_hook_operation(
                    root, operation["operation_id"], timeout_seconds=5
                ),
            )
        )

        with self.assertRaisesRegex(module.EngineeringError, "lock"):
            module.set_autonomy(root, "steward")

        self.assertEqual(before, path.read_bytes())
        self.assertEqual(record["lock_token"], module._lock_owner(record)["lock_token"])

    def test_maintenance_deduplicates_and_escalates_impact_durably(self):
        module = self.module()
        root = self.init_repo("maintenance-dedupe")
        first = self.queue(root)
        second = self.queue(root, impact="blocking")

        self.assertEqual(first["id"], second["id"])
        status = module.maintenance_status(root)
        self.assertEqual(1, status["counts"]["pending"])
        self.assertEqual(1, status["counts"]["blocked"])
        self.assertEqual(0, status["counts"]["safe"])
        self.assertEqual("blocking", status["groups"][0]["highest_impact"])
        self.assertTrue(
            (
                module.common_graph_dir(root) / "state" / "maintenance.json"
            ).is_file()
        )

    def test_maintenance_reports_age_once_and_compact_grouped_counts(self):
        module = self.module()
        root = self.init_repo("maintenance-aging")
        self.queue(root, area="docs", artifact="checkpoint")
        self.queue(root, area="tests", artifact="checkpoint")
        path = module.common_graph_dir(root) / "state" / "maintenance.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        old = "2026-01-01T00:00:00Z"
        payload["items"][0]["created_at"] = old
        path.write_text(json.dumps(payload), encoding="utf-8")

        first = module.maintenance_status(root)
        second = module.maintenance_status(root)

        self.assertEqual(2, first["counts"]["pending"])
        self.assertEqual(1, first["counts"]["aged"])
        self.assertEqual(1, first["newly_escalated"])
        self.assertEqual(0, second["newly_escalated"])
        self.assertEqual(["docs", "tests"], [item["area"] for item in first["groups"]])
        self.assertNotIn(str(root), json.dumps(first))

    def test_one_off_maintenance_processes_only_safe_selected_area(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-area")
        self.queue(root, area="docs", artifact="checkpoint")
        self.queue(root, area="tests", artifact="checkpoint")
        self.queue(
            root,
            area="docs",
            artifact="docs/contract.md",
            kind="stale_artifact",
            impact="consequential",
        )

        result = module.run_maintenance(root, "docs")
        status = module.maintenance_status(root)

        self.assertEqual(1, result["processed"])
        self.assertEqual(1, result["blocked"])
        self.assertEqual(2, status["counts"]["pending"])
        self.assertEqual({"docs", "tests"}, {item["area"] for item in status["groups"]})
        self.assertEqual("collaborative", module.get_autonomy(root))

    def test_ambiguous_and_consequential_items_never_process(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-unsafe")
        self.queue(root, artifact="docs/ambiguous.md", kind="stale_artifact", impact="ambiguous")
        self.queue(root, artifact="docs/consequential.md", kind="stale_artifact", impact="consequential")

        result = module.run_maintenance(root, None)

        self.assertEqual(0, result["processed"])
        self.assertEqual(2, result["blocked"])
        self.assertEqual(2, module.maintenance_status(root)["counts"]["pending"])

    def test_failed_safe_repair_escalates_once_and_is_not_retried(self):
        module = self.module()
        root = self.init_repo("maintenance-failed-safe")
        self.queue(root, artifact="checkpoint")

        first = module.run_maintenance(root, None)
        status = module.maintenance_status(root)
        second = module.run_maintenance(root, None)

        self.assertEqual(1, first["blocked"])
        self.assertEqual(1, status["counts"]["blocked"])
        self.assertEqual("blocking", status["items"][0]["impact"])
        self.assertEqual(1, second["blocked"])
        self.assertEqual(0, second["processed"])

    def test_relevant_blocked_maintenance_blocks_preparation(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-relevant-blocker")
        self.queue(
            root,
            artifact="README.md",
            kind="stale_artifact",
            impact="blocking",
        )

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("dirty work exists outside the authorized scope", result["blockers"])

    def test_unrelated_blocked_maintenance_is_advisory_even_when_in_scope(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-unrelated-blocker")
        self.queue(
            root,
            artifact="docs/guide.md",
            kind="stale_artifact",
            impact="blocking",
        )
        module.approve_checks(root)

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["docs/guide.md"], "forbidden": []},
            None,
        )

        self.assertNotEqual("blocked", result["readiness"])
        self.assertIn(
            "Engineering maintenance: 1 queued artifact(s). Run `engineering maintain` "
            "once to repair safe items; blocked items still require review. The command "
            "does not change autonomy.",
            result["advisories"],
        )

    def test_required_current_contract_maintenance_blocks_preparation(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-required-contract")
        artifact = "docs/engineering-traceability/decision-ledger.md"
        self.queue(root, artifact=artifact, kind="stale_artifact", impact="blocking")

        result = module.prepare(
            root,
            "change REQ-1",
            {
                "scope": ["README.md"],
                "required_sources": [artifact],
                "forbidden": [],
            },
            None,
        )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("dirty work exists outside the authorized scope", result["blockers"])

    def test_unsafe_checkpoint_maintenance_blocks_preparation(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-checkpoint-blocker")
        self.queue(
            root,
            artifact="checkpoint",
            kind="checkpoint_stale",
            impact="blocking",
        )
        module.approve_checks(root)

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["docs/guide.md"], "forbidden": []},
            None,
        )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("dirty work exists outside the authorized scope", result["blockers"])

    def test_queued_maintenance_serializes_shared_state_without_broad_authority(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-serialization-advisory")
        first = self.queue(root, artifact="docs/guide.md", kind="stale_artifact")
        second = self.queue(root, artifact="docs/other.md", kind="stale_artifact")

        status = module.maintenance_status(root)
        self.assertEqual(2, status["counts"]["pending"])
        self.assertEqual(
            sorted([first["id"], second["id"]]),
            [item["id"] for item in status["items"]],
        )
        module.approve_checks(root)
        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["docs/guide.md", "docs/other.md"], "forbidden": []},
            None,
        )
        self.assertNotEqual("blocked", result["readiness"])

    def test_traceability_debt_scenario_executes_controller_blocking_matrix(self):
        module = self.module()
        payload = json.loads(SCENARIOS.read_text(encoding="utf-8"))
        scenario = next(
            item for item in payload["scenarios"]
            if item.get("id") == "traceability-debt-maintenance"
        )
        self.assertIn("block_only_checkpoint_contract_or_dependent_acceptance", scenario["must"])
        unrelated = {
            "safe": False,
            "kind": "stale_artifact",
            "artifact": "docs/guide.md",
        }
        checkpoint = {
            "safe": False,
            "kind": "checkpoint_stale",
            "artifact": "checkpoint",
        }
        required = {
            "safe": False,
            "kind": "stale_artifact",
            "artifact": "docs/engineering/decision-ledger.md",
        }
        dependent = {
            "safe": False,
            "kind": "stale_artifact",
            "artifact": "src/app.py",
        }
        self.assertFalse(
            module._maintenance_blocks_preparation(
                unrelated, required_sources=set(), impact=[]
            )
        )
        self.assertTrue(
            module._maintenance_blocks_preparation(
                checkpoint, required_sources=set(), impact=[]
            )
        )
        self.assertTrue(
            module._maintenance_blocks_preparation(
                required,
                required_sources={"docs/engineering/decision-ledger.md"},
                impact=[],
            )
        )
        self.assertTrue(
            module._maintenance_blocks_preparation(
                dependent,
                required_sources=set(),
                impact=[{"id": "src/app.py"}],
            )
        )
        source = ENGINEERING_SCRIPT.read_text(encoding="utf-8")
        imports = {
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertNotIn("sched", imports)
        self.assertNotIn("threading", imports)
        self.assertIn("_acquire_repository_lock", source)

    def test_collaborative_explains_one_off_maintenance_command(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-collaborative")
        self.queue(root)

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )

        self.assertTrue(any("engineering maintain" in item for item in result["advisories"]))
        self.assertEqual(1, module.maintenance_status(root)["counts"]["pending"])

    def test_steward_runs_safe_maintenance_only_during_prepare(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-steward")
        module.set_autonomy(root, "steward")
        self.queue(root, artifact="checkpoint")
        self.queue(root, artifact="docs/review.md", kind="stale_artifact", impact="ambiguous")

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )

        self.assertEqual("steward", result["autonomy"])
        status = module.maintenance_status(root)
        self.assertEqual(1, status["counts"]["pending"])
        self.assertEqual(1, status["counts"]["blocked"])

    def test_maintain_cli_supports_status_all_and_area(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-cli")
        self.queue(root, area="docs", artifact="checkpoint")
        self.queue(root, area="tests", artifact="checkpoint")

        status = self.run_cli("maintain", "status", root)
        area = self.run_cli("maintain", root, "--area", "docs")

        self.assertEqual(0, status.returncode, status.stderr)
        self.assertEqual(2, json.loads(status.stdout)["counts"]["pending"])
        self.assertEqual(0, area.returncode, area.stderr)
        self.assertEqual(1, json.loads(area.stdout)["processed"])
        self.assertEqual(1, module.maintenance_status(root)["counts"]["pending"])

    def test_maintenance_has_no_background_or_service_execution(self):
        module = self.module()
        source = ENGINEERING_SCRIPT.read_text(encoding="utf-8")
        imports = {
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }

        self.assertFalse({"sched", "threading"} & imports)
        self.assertFalse(module.maintenance_status(self.init_repo("foreground"))["background"])

    def test_maintenance_rejects_credential_shaped_or_unbounded_identity(self):
        module = self.module()
        root = self.init_repo("maintenance-private")

        with self.assertRaisesRegex(module.EngineeringError, "maintenance item"):
            self.queue(root, artifact="docs/password=synthetic-secret")
        with self.assertRaisesRegex(module.EngineeringError, "maintenance item"):
            self.queue(root, area="x" * 129)

        path = module.common_graph_dir(root) / "state" / "maintenance.json"
        self.assertFalse(path.exists())

    def test_maintenance_fails_closed_for_malformed_existing_state(self):
        module = self.module()
        root = self.init_repo("maintenance-malformed-state")
        path = module.common_graph_dir(root) / "state" / "maintenance.json"
        path.parent.mkdir(parents=True)

        tampered_item = {
            "id": "maintenance-3f7a1f8ad181",
            "area": "docs",
            "artifact": "docs/review.md",
            "kind": "stale_artifact",
            "impact": "routine",
            "safe": True,
            "created_at": "2026-01-01T00:00:00Z",
            "last_seen_at": "2026-01-01T00:00:00Z",
            "escalated_at": None,
        }
        for payload in (
            {"items": []},
            {"schema": "engineering.maintenance.v1"},
            {
                "schema": "engineering.maintenance.v1",
                "items": [tampered_item],
                "history": [],
            },
        ):
            with self.subTest(payload=payload):
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(module.EngineeringError, "state"):
                    module._maintenance_pending(root)

    def test_maintenance_rejects_nonlocal_or_control_shaped_artifacts(self):
        module = self.module()
        root = self.init_repo("maintenance-artifact-boundary")

        for artifact in (
            "https://example.invalid/file",
            "docs/file.md?download=1",
            "docs/file.md#fragment",
            "docs/control\nvalue.md",
            "../outside.md",
            "C:/outside.md",
            "token=synthetic-value",
        ):
            with self.subTest(artifact=artifact):
                with self.assertRaisesRegex(module.EngineeringError, "maintenance item"):
                    self.queue(root, artifact=artifact)

    def test_maintenance_rejects_inconsistent_or_future_timestamps(self):
        module = self.module()
        root = self.init_repo("maintenance-time-boundary")
        future = "2999-01-01T00:00:00Z"

        with self.assertRaisesRegex(module.EngineeringError, "timestamp"):
            self.queue(root, created_at=future, last_seen_at=future)
        with self.assertRaisesRegex(module.EngineeringError, "timestamp"):
            self.queue(
                root,
                created_at="2026-01-02T00:00:00Z",
                last_seen_at="2026-01-01T00:00:00Z",
            )

    def test_completion_batches_maintenance_once_and_retains_opaque_ids(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-completion-producer")
        # This test exercises maintenance queuing for an already-known,
        # non-owner-facing follow-up artifact.  It deliberately avoids README,
        # docs, tests, and every unrepresented path: those must refresh and
        # bind owner intent under the completion fail-closed regressions.
        (root / "notes").mkdir(exist_ok=True)
        (root / "notes" / "follow-up.txt").write_text(
            "Follow up\n", encoding="utf-8"
        )
        links_path = root / "docs" / "engineering-traceability" / "links.json"
        links = json.loads(links_path.read_text(encoding="utf-8"))
        links["nodes"].append(
            {
                "id": "NOTE-FOLLOW-UP",
                "type": "code_symbol",
                "title": "Follow-up maintenance note",
                "source": {"path": "notes/follow-up.txt", "line": 1},
            }
        )
        links_path.write_text(json.dumps(links, indent=2) + "\n", encoding="utf-8")
        base = self.commit_all(root, "add known maintenance follow-up")
        self.write_canonical_checkpoint(root, base)
        module.approve_checks(root)
        prepared = module.prepare(
            root,
            "change REQ-1",
            {
                "scope": ["notes/follow-up.txt"],
                "forbidden": ["publish", "deploy"],
            },
        )
        self.assertNotEqual("blocked", prepared["readiness"])
        (root / "notes" / "follow-up.txt").write_text(
            "Updated follow up\n", encoding="utf-8"
        )

        changed, _ = module._stable_completion_snapshot(
            root, prepared["project"]["commit"]
        )
        self.assertEqual(["notes/follow-up.txt"], changed)
        base_checkpoint = module._load_checkpoint(root, prepared["project"]["commit"])
        self.assertIn("notes/follow-up.txt", module._checkpoint_source_paths(base_checkpoint))
        self.assertFalse(
            module._unrepresented_owner_commitment_paths(base_checkpoint, changed)
        )
        self.assertFalse(
            module._requires_refreshed_intent_checkpoint(
                root, prepared["project"]["commit"], base_checkpoint, changed
            )
        )
        self.assertFalse(
            module._intent_impacting(
                base_checkpoint,
                [],
                prepared["authorization"].get("change_class"),
                prepared["authorization"].get("scope_handoff"),
                artifact_paths=changed,
            )
        )
        self.assertFalse(
            module._completion_intent_impact(
                root,
                prepared["project"]["commit"],
                module.git(root, "rev-parse", "HEAD"),
                True,
                changed,
                prepared["authorization"],
                prepared["authorization"].get("scope_handoff"),
                module.check_merge_readiness(root),
            )
        )

        first = module.complete(root, prepared["run_id"], receipts=[])

        state_before = (
            module.common_graph_dir(root) / "state" / "maintenance.json"
        ).read_bytes()
        second = module.complete(root, prepared["run_id"], receipts=[])

        self.assertEqual(1, len(first["maintenance"]))
        self.assertTrue(
            all(re.fullmatch(r"maintenance-[0-9a-f]{12}", item) for item in first["maintenance"])
        )
        self.assertEqual(first, second)
        self.assertEqual(
            state_before,
            (module.common_graph_dir(root) / "state" / "maintenance.json").read_bytes(),
        )

    def test_completion_replay_does_not_readd_consumed_maintenance(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "maintenance-consumed-replay", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        first = module.complete(root, prepared["run_id"], receipts=[])
        state_path = module.common_graph_dir(root) / "state" / "maintenance.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["history"].append(
            {"id": state["items"][0]["id"], "completed_at": module._utc_now()}
        )
        state["items"] = []
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        consumed = state_path.read_bytes()

        replay = module.complete(root, prepared["run_id"], receipts=[])

        self.assertEqual(first, replay)
        self.assertEqual(consumed, state_path.read_bytes())

    def test_failed_check_does_not_publish_maintenance(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "maintenance-failed-check", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        state_path = module.common_graph_dir(root) / "state" / "maintenance.json"
        failed = {
            "schema": "engineering.check.v1",
            "command_id": module._check_identity(prepared["required_checks"][0]),
            "exit_code": 1,
            "duration_seconds": 0.01,
            "output_digest": "sha256:" + "0" * 64,
        }

        with (
            patch.object(module, "_execute_check", return_value=failed),
            self.assertRaisesRegex(module.EngineeringError, "check failed"),
        ):
            module.complete(root, prepared["run_id"], receipts=[])

        self.assertFalse(state_path.exists())

    def test_manifest_failure_restores_exact_prior_maintenance(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "maintenance-manifest-rollback", scope=["README.md"]
        )
        self.queue(
            root,
            artifact="docs/prior.md",
            kind="stale_artifact",
            impact="ambiguous",
        )
        state_path = module.common_graph_dir(root) / "state" / "maintenance.json"
        before = state_path.read_bytes()
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        real_private_atomic = module._private_atomic_bytes

        def fail_manifest(path, content):
            if Path(path).name.startswith(".completion.json.stage-"):
                raise OSError("synthetic manifest publication failure")
            return real_private_atomic(path, content)

        with (
            patch.object(module, "_private_atomic_bytes", side_effect=fail_manifest),
            self.assertRaisesRegex(OSError, "manifest publication"),
        ):
            module.complete(root, prepared["run_id"], receipts=[])

        self.assertEqual(before, state_path.read_bytes())

    def test_failed_checkpoint_repair_resolves_after_exact_publication_once(self):
        module = self.module()
        root = self.governed_repo("maintenance-checkpoint-resolution")
        self.queue(root, artifact="checkpoint")
        failed = module.run_maintenance(root, None)

        _, environment = self.cold_checkpoint(root)
        first = module.maintenance_status(root)
        history_path = module.common_graph_dir(root) / "state" / "maintenance.json"
        history_once = history_path.read_bytes()
        with patch.dict(os.environ, environment, clear=False):
            module.rebuild(root, sys.executable)
        second = module.maintenance_status(root)

        self.assertEqual(1, failed["blocked"])
        self.assertEqual(0, first["counts"]["pending"])
        self.assertEqual(history_once, history_path.read_bytes())
        self.assertEqual(0, second["counts"]["pending"])
        history = json.loads(history_path.read_text(encoding="utf-8"))["history"]
        self.assertEqual(1, len(history))

    def test_checkpoint_maintenance_is_scoped_to_worktree_lineage(self):
        module = self.module()
        root = self.governed_repo("maintenance-lineage-a")
        other = Path(self.temporary_directory.name) / "maintenance-lineage-b"
        self.git(root, "worktree", "add", "-b", "feature/lineage-b", str(other))
        stale_a = self.queue(root, artifact="checkpoint")
        stale_b = self.queue(other, artifact="checkpoint")
        unrelated = self.queue(
            root,
            artifact="docs/unrelated.md",
            kind="stale_artifact",
            impact="ambiguous",
        )
        state_path = module.common_graph_dir(root) / "state" / "maintenance.json"
        initial = json.loads(state_path.read_text(encoding="utf-8"))
        checkpoint_items = [
            item for item in initial["items"] if item["kind"] == "checkpoint_stale"
        ]

        self.assertNotEqual(stale_a["id"], stale_b["id"])
        self.assertEqual(2, len(checkpoint_items))
        self.assertEqual(2, len({item["target"]["lineage"] for item in checkpoint_items}))
        self.assertNotIn(str(root), json.dumps(checkpoint_items))
        self.assertNotIn(str(other), json.dumps(checkpoint_items))

        _, environment = self.cold_checkpoint(other)
        after_b = module.maintenance_status(root)
        remaining_checkpoint = [
            item for item in after_b["items"] if item["kind"] == "checkpoint_stale"
        ]
        self.assertEqual([stale_a["id"]], [item["id"] for item in remaining_checkpoint])
        self.assertIn(unrelated["id"], {item["id"] for item in after_b["items"]})

        wrong_worktree = module.run_maintenance(other, None)
        after_wrong_worktree = module.maintenance_status(root)
        self.assertEqual(0, wrong_worktree["processed"])
        self.assertEqual(
            [stale_a["id"]],
            [
                item["id"]
                for item in after_wrong_worktree["items"]
                if item["kind"] == "checkpoint_stale"
            ],
        )

        self.commit_file(root, "src/successor.py", "VALUE = 1\n")
        with patch.dict(os.environ, environment, clear=False):
            published_a = module.rebuild(root, sys.executable)
        self.assertEqual("current", published_a["freshness"])
        after_a = module.maintenance_status(root)
        self.assertEqual([unrelated["id"]], [item["id"] for item in after_a["items"]])
        history = json.loads(state_path.read_text(encoding="utf-8"))["history"]
        self.assertEqual(2, len(history))

    def test_batch_mutation_reuses_one_existing_lock_and_writes_once(self):
        module = self.module()
        root = self.init_repo("maintenance-single-lock-batch")
        operation = module._begin_completion(root, "maintenance-batch-test")
        try:
            with (
                patch.object(module, "_begin_completion", wraps=module._begin_completion) as begin,
                patch.object(module, "_write_maintenance", wraps=module._write_maintenance) as write,
            ):
                queued = module._queue_maintenance_locked(
                    root,
                    [
                        {
                            "area": "docs",
                            "artifact": "docs/one.md",
                            "kind": "stale_artifact",
                            "impact": "routine",
                        },
                        {
                            "area": "tests",
                            "artifact": "tests/test_one.py",
                            "kind": "stale_artifact",
                            "impact": "ambiguous",
                        },
                    ],
                    operation,
                )
            self.assertEqual(0, begin.call_count)
            self.assertEqual(1, write.call_count)
            self.assertEqual(2, len(queued))
        finally:
            module._end_completion(root, operation)

    def test_semantic_hook_and_legacy_reconciliation_persist_maintenance(self):
        module = self.module()
        root = self.governed_repo("maintenance-producers")
        manifest_path = root / "engineering.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["graphify"]["hook_budget_seconds"] = 60
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.commit_all(root, "configure hook")
        _, environment = self.cold_checkpoint(root)
        self.commit_file(root, "docs/design.md", "# Changed meaning\n")

        with patch.dict(os.environ, environment, clear=False):
            hook = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                cleanup_timeout_seconds=30,
            )

        legacy = root / "graphify-out"
        legacy.mkdir()
        (legacy / "graph.json").write_text("{}\n", encoding="utf-8")
        (legacy / "notes.txt").write_text("keep\n", encoding="utf-8")
        reconciled = module.reconcile_legacy_outputs(root)
        status = module.maintenance_status(root)

        self.assertEqual("semantic_update_deferred", hook["reason"])
        self.assertEqual(2, status["counts"]["pending"])
        self.assertEqual(
            {"checkpoint_stale", "legacy_graph_ambiguous"},
            {item["kind"] for item in status["items"]},
        )
        self.assertEqual(1, len(reconciled["maintenance"]))

    def test_skill_explains_maintain_and_level_two_vs_three(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())

        self.assertIn("Collaborative", text)
        self.assertIn("Steward", text)
        self.assertIn("does not run in the background", text)
        self.assertIn("process safe queued work once", text)
        self.assertIn("does not change the saved autonomy level", text)
        self.assertIn("references/controller-contract.md", text)
        self.assertNotIn("engineering maintain <area>", text)


class Task7ContractTests(unittest.TestCase):
    init_repo = Task2ContractTests.init_repo
    git = Task2ContractTests.git
    commit_all = Task2ContractTests.commit_all
    run_cli = Task2ContractTests.run_cli
    write_controls = Task2ContractTests.write_controls
    write_fake_graphify = Task2ContractTests.write_fake_graphify
    write_canonical_checkpoint = Task2ContractTests.write_canonical_checkpoint
    recover_fixture_checkpoint = Task2ContractTests.recover_fixture_checkpoint
    prepared_repo = Task2ContractTests.prepared_repo
    prepared_run = Task5ContractTests.prepared_run
    start_fake_graphify_interpreter = Task2ContractTests.start_fake_graphify_interpreter

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.home = Path(self.temporary_directory.name) / "home"
        self.home.mkdir()
        self.start_fake_graphify_interpreter()
        self.environment = patch.dict(
            os.environ,
            {"ENGINEERING_USER_HOME": str(self.home)},
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.real_owner_private = engineering._enforce_owner_private
        self.private_files = patch.object(
            engineering,
            "_enforce_owner_private",
            side_effect=lambda path: os.chmod(path, 0o700 if Path(path).is_dir() else 0o600),
        )
        self.private_files.start()
        self.addCleanup(self.private_files.stop)
        self.private_verifier = patch.object(
            engineering, "_verify_owner_private", return_value=None
        )
        self.private_verifier.start()
        self.addCleanup(self.private_verifier.stop)
        self.governed_installer_guard = patch.object(
            engineering,
            "_run_governed_graphify_install",
            side_effect=AssertionError(
                "Unit tests must mock the governed installer boundary; "
                "real installation is temp-venv-only."
            ),
        )
        self.governed_installer_guard.start()
        self.addCleanup(self.governed_installer_guard.stop)

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def terminal_completion(self, name="learning-source"):
        module = self.module()
        root, prepared = self.prepared_run(name, scope=["README.md"])
        return root, module.complete(root, prepared["run_id"], receipts=[])

    def forged_promoted_item(self, module, candidate, project_digest=None):
        project_digest = project_digest or candidate["project_digest"]
        identifier = "candidate-" + hashlib.sha256(
            f"{project_digest}\0{candidate['source_digest']}\0{candidate['kind']}".encode()
        ).hexdigest()[:12]
        evaluation_project = "sha256:" + "4" * 64
        if evaluation_project == project_digest:
            evaluation_project = "sha256:" + "5" * 64
        evaluation_digest = "sha256:" + "6" * 64
        evaluation = {
            "id": "evaluation-" + hashlib.sha256(
                f"{identifier}\0{evaluation_project}\0{evaluation_digest}".encode()
            ).hexdigest()[:12],
            "project_digest": evaluation_project,
            "source_reference": "completion:run-a1b2c3",
            "source_digest": evaluation_digest,
            "result": "passed",
        }
        return {
            **candidate,
            "id": identifier,
            "project_digest": project_digest,
            "state": "promoted",
            "evidence": [evaluation],
            "review": {
                "approval": {
                    "id": "approval-" + hashlib.sha256(
                        f"{identifier}\0approved".encode()
                    ).hexdigest()[:12],
                    "decision": "approved",
                }
            },
            "history": [
                module._lifecycle_record(identifier, state)
                for state in (
                    "proposed",
                    "evaluating",
                    "approved_for_promotion",
                    "promoted",
                )
            ],
        }

    def bundle_repo(self, name="bundle", *, version="2.2.5"):
        root = Path(self.temporary_directory.name) / name
        source = root / ".agents" / "skills" / "engineering"
        shutil.copytree(SKILL_DIR, source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        manifest_path = source / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = version
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        self.git(root, "init", "-b", "main")
        self.git(root, "config", "user.email", "synthetic")
        self.git(root, "config", "user.name", "Engineering Tests")
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", "bundle")
        return source

    def update_bundle(self, source, version="2.1.1"):
        skill = source / "SKILL.md"
        skill.write_bytes(skill.read_bytes() + f"\n<!-- version {version} -->\n".encode())
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        manifest["version"] = version
        (source / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        root_text = self.git(source, "rev-parse", "--show-toplevel")
        root = Path(root_text) if sys.platform == "win32" else PosixPath(root_text)
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", f"bundle {version}")

    def managed_snapshot(self, module, home):
        paths = module._install_paths(home)
        snapshot = {}
        for key in ("canonical", "previous", "claude", "shim", "command", "receipt", "previous_receipt"):
            path = paths[key]
            snapshot[key] = (
                ("tree", module._tree_digest(path))
                if path.is_dir()
                else (("file", hashlib.sha256(path.read_bytes()).hexdigest()) if path.is_file() else None)
            )
        return snapshot

    def byte_snapshot(self, *paths):
        return {
            str(path): path.read_bytes() if path.is_file() else None
            for path in paths
        }

    def fail_once_on_target(self, module, target):
        real_replace = module._replace_install_path
        failed = False

        def replace(
            source,
            destination,
            expected_pre_state=None,
            *,
            preimage_path=None,
            expected_source_state=None,
            expected_target_state=None,
        ):
            nonlocal failed
            if not failed and Path(destination).resolve() == Path(target).resolve():
                failed = True
                raise OSError("synthetic transactional publication failure")
            return real_replace(
                source,
                destination,
                expected_pre_state,
                preimage_path=preimage_path,
                expected_source_state=expected_source_state,
                expected_target_state=expected_target_state,
            )

        return replace

    def test_candidate_requires_terminal_verified_completion(self):
        module = self.module()
        root = self.init_repo("incomplete-learning")

        with self.assertRaisesRegex(module.EngineeringError, "terminal"):
            module.propose_learning(root, "run-a1b2c3", "failure_lesson")

    def test_candidate_rejects_fabricated_shallow_completion(self):
        module = self.module()
        root, completion = self.terminal_completion("fabricated-completion")
        path = Path(completion["manifest"])
        path.write_text(
            json.dumps(
                {
                    "schema": "engineering.complete.v1",
                    "run_id": completion["run_id"],
                    "checks": [{"schema": "engineering.check.v1", "exit_code": 0}],
                    "checkpoint": completion["checkpoint"],
                    "result_identity": completion["result_identity"],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(module.EngineeringError, "terminal"):
            module.propose_learning(root, completion["run_id"], "reusable_test")

    def test_candidate_rejects_full_shape_completion_without_controller_attestation(self):
        module = self.module()
        root, prepared = self.prepared_run("forged-full-completion", scope=["README.md"])
        preparation = module._load_preparation(root, prepared["run_id"])
        head = self.git(root, "rev-parse", "HEAD")
        checks = [
            {
                "schema": "engineering.check.v1",
                "command_id": module._check_identity(argv),
                "exit_code": 0,
                "duration_seconds": 0.01,
                "output_digest": "sha256:" + "7" * 64,
            }
            for argv in preparation["required_checks"]
        ]
        payload = module._completion_payload(
            preparation,
            [],
            {"commit": head, "dirty_tree_digest": None},
            {"commit": head, "ready": True},
            False,
            checks,
            [],
        )
        manifest = module._common_graph_dir(root) / "runs" / prepared["run_id"] / "completion.json"
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "attestation|terminal"):
            module.propose_learning(root, prepared["run_id"], "reusable_test")

    def test_repository_identity_is_immutable_git_lineage_across_clones_and_worktrees(self):
        module = self.module()
        root, completion = self.terminal_completion("repository-identity")
        first = module._project_contribution_digest(root)
        self.git(root, "remote", "add", "origin", "https://example.invalid/first.git")
        self.git(root, "remote", "set-url", "origin", "https://example.invalid/changed.git")
        self.assertEqual(first, module._project_contribution_digest(root))

        linked = Path(self.temporary_directory.name) / "repository-identity-linked"
        self.git(root, "worktree", "add", "--detach", str(linked), "HEAD")
        try:
            self.assertEqual(first, module._project_contribution_digest(linked))
        finally:
            self.git(root, "worktree", "remove", "--force", str(linked))

        clone = Path(self.temporary_directory.name) / "repository-identity-clone"
        subprocess.run(
            ["git", "clone", "--quiet", str(root), str(clone)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(first, module._project_contribution_digest(clone))

        independent = Path(self.temporary_directory.name) / "repository-identity-independent"
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(independent)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.git(independent, "config", "user.email", "synthetic")
        self.git(independent, "config", "user.name", "Independent Test")
        (independent / "README.md").write_text("# Different lineage\n", encoding="utf-8")
        self.git(independent, "add", "README.md")
        self.git(independent, "commit", "-m", "independent root")
        self.assertNotEqual(first, module._project_contribution_digest(independent))

        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        with self.assertRaisesRegex(module.EngineeringError, "second project"):
            module.evaluate_learning(candidate["id"], root, completion["run_id"])

    def test_proposal_transaction_never_partially_publishes_queue_local_or_index(self):
        module = self.module()
        root, completion = self.terminal_completion("proposal-transaction")
        _, source_digest = module._terminal_completion(root, completion["run_id"])
        project_digest = module._project_contribution_digest(root)
        identifier = "candidate-" + hashlib.sha256(
            f"{project_digest}\0{source_digest}\0reusable_test".encode()
        ).hexdigest()[:12]
        paths = (
            module._contribution_queue_path(),
            module.common_graph_dir(root) / "contributions" / f"{identifier}.json",
            module._contribution_index_path(),
            module._controller_key_path(module._promotion_controller_dir()),
        )
        for target in paths:
            with self.subTest(target=target.name):
                with (
                    patch.object(
                        module,
                        "_replace_install_path",
                        side_effect=self.fail_once_on_target(module, target),
                    ),
                    self.assertRaisesRegex(OSError, "transactional publication"),
                ):
                    module.propose_learning(root, completion["run_id"], "reusable_test")
                self.assertEqual({str(path): None for path in paths}, self.byte_snapshot(*paths))

    def test_lifecycle_transactions_restore_queue_local_registry_and_key(self):
        module = self.module()
        root, completion = self.terminal_completion("lifecycle-transaction-source")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        second_root, second_completion = self.terminal_completion("lifecycle-transaction-second")
        queue = module._contribution_queue_path()
        local = module.common_graph_dir(root) / "contributions" / f"{candidate['id']}.json"

        for operation in ("evaluate", "approve"):
            for target in (queue, local):
                with self.subTest(operation=operation, target=target.name):
                    before = self.byte_snapshot(queue, local)
                    with (
                        patch.object(
                            module,
                            "_replace_install_path",
                            side_effect=self.fail_once_on_target(module, target),
                        ),
                        self.assertRaisesRegex(OSError, "transactional publication"),
                    ):
                        if operation == "evaluate":
                            module.evaluate_learning(
                                candidate["id"], second_root, second_completion["run_id"]
                            )
                        else:
                            module.record_learning_approval(candidate["id"], approved=True)
                    self.assertEqual(before, self.byte_snapshot(queue, local))
            if operation == "evaluate":
                evaluation = module.evaluate_learning(
                    candidate["id"], second_root, second_completion["run_id"]
                )
            else:
                module.record_learning_approval(candidate["id"], approved=True)

        controller = module._promotion_controller_dir()
        registry = module._promotion_attestation_path()
        key = module._controller_key_path(controller)
        for target in (queue, local, registry):
            with self.subTest(operation="promote", target=target.name):
                before = self.byte_snapshot(queue, local, registry, key)
                with (
                    patch.object(
                        module,
                        "_replace_install_path",
                        side_effect=self.fail_once_on_target(module, target),
                    ),
                    self.assertRaisesRegex(OSError, "transactional publication"),
                ):
                    module.promote_learning(
                        candidate["id"], [{"evaluation_id": evaluation["id"]}], approved=True
                    )
                self.assertEqual(before, self.byte_snapshot(queue, local, registry, key))

    def test_contribution_index_cannot_redirect_to_another_project(self):
        module = self.module()
        root, completion = self.terminal_completion("index-source")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        second_root, second_completion = self.terminal_completion("index-second")
        redirect = (
            module.common_graph_dir(second_root)
            / "contributions"
            / f"{candidate['id']}.json"
        )
        redirect.parent.mkdir(parents=True, exist_ok=True)
        local = module.common_graph_dir(root) / "contributions" / f"{candidate['id']}.json"
        redirect.write_bytes(local.read_bytes())
        index_path = module._contribution_index_path()
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["items"][0]["local_record"] = str(redirect)
        index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "index|pointer|signature"):
            module.evaluate_learning(candidate["id"], second_root, second_completion["run_id"])

    def test_windows_private_acl_is_applied_and_verified_or_fails_closed(self):
        module = self.module()
        target = self.home / "controller.json"
        target.write_text("{}", encoding="utf-8")
        executable = Path(
            "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
            if os.name == "nt"
            else "/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        native_environment = {
            "PSModulePath": str(executable.parent / "Modules")
        }
        private = {
            "protected": True,
            "owner_sid": "S-1-5-21-1",
            "current_sid": "S-1-5-21-1",
            "access": [
                {
                    "sid": "S-1-5-21-1",
                    "type": "Allow",
                    "inherited": False,
                    "inheritance": "None",
                    "propagation": "None",
                }
            ],
        }
        completed = subprocess.CompletedProcess(
            [], 0, stdout="warning\nENGINEERING_ACL_RESULT:" + json.dumps(private), stderr="notice"
        )
        with (
            patch.object(module.os, "name", "nt"),
            patch.object(
                module, "_shared_native_powershell", return_value=executable
            ),
            patch.object(
                module,
                "_shared_native_powershell_environment",
                return_value=native_environment,
            ),
            patch.object(module.subprocess, "run", return_value=completed) as run,
        ):
            self.real_owner_private(target)
        self.assertEqual(1, run.call_count)
        invoked = Path(run.call_args.args[0][0])
        self.assertTrue(invoked.is_absolute())
        self.assertEqual("powershell.exe", invoked.name.casefold())
        self.assertEqual(
            str(invoked.parent / "Modules"),
            run.call_args.kwargs["env"]["PSModulePath"],
        )
        self.assertNotIn("PATH", {
            key.upper(): value for key, value in run.call_args.kwargs["env"].items()
        })
        self.assertEqual(str(target), run.call_args.args[0][-3])
        self.assertEqual("1", run.call_args.args[0][-2])
        self.assertEqual("0", run.call_args.args[0][-1])

        system_private = {
            **private,
            "access": [
                *private["access"],
                {
                    "sid": "S-1-5-18",
                    "type": "Allow",
                    "inherited": False,
                    "inheritance": "None",
                    "propagation": "None",
                },
            ],
        }
        result = subprocess.CompletedProcess(
            [], 0, stdout="ENGINEERING_ACL_RESULT:" + json.dumps(system_private), stderr=""
        )
        with (
            patch.object(module.os, "name", "nt"),
            patch.object(
                module, "_shared_native_powershell", return_value=executable
            ),
            patch.object(
                module,
                "_shared_native_powershell_environment",
                return_value=native_environment,
            ),
            patch.object(module.subprocess, "run", return_value=result),
        ):
            self.real_owner_private(target)

        for change in (
            {"protected": False},
            {
                "access": [
                    *private["access"],
                    {
                        "sid": "S-1-1-0",
                        "type": "Allow",
                        "inherited": False,
                        "inheritance": "None",
                        "propagation": "None",
                    },
                ]
            },
            {
                "access": [
                    {
                        "sid": "S-1-5-21-1",
                        "type": "Allow",
                        "inherited": True,
                        "inheritance": "None",
                        "propagation": "None",
                    }
                ]
            },
        ):
            permissive = {**private, **change}
            result = subprocess.CompletedProcess(
                [], 0, stdout="ENGINEERING_ACL_RESULT:" + json.dumps(permissive), stderr=""
            )
            with (
                patch.object(module.os, "name", "nt"),
                patch.object(
                    module, "_shared_native_powershell", return_value=executable
                ),
                patch.object(
                    module,
                    "_shared_native_powershell_environment",
                    return_value=native_environment,
                ),
                patch.object(module.subprocess, "run", return_value=result),
                self.assertRaisesRegex(module.EngineeringError, "owner-private"),
            ):
                self.real_owner_private(target)

        for result in (
            subprocess.CompletedProcess([], 0, stdout="warning only\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="ENGINEERING_ACL_RESULT:{bad", stderr=""),
            subprocess.CompletedProcess([], 7, stdout="ENGINEERING_ACL_RESULT:" + json.dumps(private), stderr="failure"),
        ):
            with self.subTest(result=result):
                with (
                    patch.object(module.os, "name", "nt"),
                    patch.object(
                        module, "_shared_native_powershell", return_value=executable
                    ),
                    patch.object(
                        module,
                        "_shared_native_powershell_environment",
                        return_value=native_environment,
                    ),
                    patch.object(module.subprocess, "run", return_value=result),
                    self.assertRaisesRegex(module.EngineeringError, "owner-private"),
                ):
                    self.real_owner_private(target)

    def test_private_atomic_publication_keeps_existing_private_sibling_readable(self):
        module = self.module()
        parent = self.home / "private-transaction"
        parent.mkdir()
        retained = parent / "preparation.json"
        retained.write_text('{"schema":"engineering.prepare.v1"}\n', encoding="utf-8")

        module._private_atomic_bytes(parent / "completion.json", b"{}\n")

        self.assertEqual(
            '{"schema":"engineering.prepare.v1"}\n',
            retained.read_text(encoding="utf-8"),
        )
        nested = parent / "nested" / "future.json"
        nested.parent.mkdir()
        nested.write_text("first\n", encoding="utf-8")
        self.assertEqual("first\n", nested.read_text(encoding="utf-8"))
        nested.write_text("second\n", encoding="utf-8")
        self.assertEqual("second\n", nested.read_text(encoding="utf-8"))

    def test_windows_private_directory_acl_is_inheritable_and_owner_only(self):
        module = self.module()
        target = self.home / "controller"
        target.mkdir()
        executable = Path(
            "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
            if os.name == "nt"
            else "/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        native_environment = {
            "PSModulePath": str(executable.parent / "Modules")
        }
        private = {
            "protected": True,
            "owner_sid": "S-1-5-21-1",
            "current_sid": "S-1-5-21-1",
            "access": [
                {
                    "sid": "S-1-5-21-1",
                    "type": "Allow",
                    "inherited": False,
                    "inheritance": "ContainerInherit, ObjectInherit",
                    "propagation": "None",
                }
            ],
        }
        completed = subprocess.CompletedProcess(
            [], 0, stdout="ENGINEERING_ACL_RESULT:" + json.dumps(private), stderr=""
        )
        with (
            patch.object(module.os, "name", "nt"),
            patch.object(
                module, "_shared_native_powershell", return_value=executable
            ),
            patch.object(
                module,
                "_shared_native_powershell_environment",
                return_value=native_environment,
            ),
            patch.object(module.subprocess, "run", return_value=completed) as run,
        ):
            self.real_owner_private(target)

        self.assertEqual(str(target), run.call_args.args[0][-3])
        self.assertEqual("1", run.call_args.args[0][-2])
        self.assertEqual("1", run.call_args.args[0][-1])

    def test_proposed_candidate_is_project_local_and_not_discoverable(self):
        module = self.module()
        root, completion = self.terminal_completion()

        candidate = module.propose_learning(
            root, completion["run_id"], "reusable_test"
        )

        self.assertEqual("proposed", candidate["state"])
        self.assertNotIn(candidate["id"], module.discover_shared_skills())
        local = module.common_graph_dir(root) / "contributions" / f"{candidate['id']}.json"
        self.assertTrue(local.is_file())
        queue = (self.home / ".agents" / "engineering" / "contribution-queue.json")
        queue_text = queue.read_text(encoding="utf-8")
        self.assertNotIn(str(root), queue_text)
        self.assertNotIn("PRIVATE", queue_text)

    def test_promotion_requires_distinct_second_project_and_explicit_approval(self):
        module = self.module()
        root, completion = self.terminal_completion("promotion-source")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        local = module.common_graph_dir(root) / "contributions" / f"{candidate['id']}.json"
        self.assertEqual("proposed", json.loads(local.read_text(encoding="utf-8"))["state"])

        with self.assertRaisesRegex(module.EngineeringError, "evaluation"):
            module.promote_learning(candidate["id"], [], approved=True)
        with self.assertRaisesRegex(module.EngineeringError, "evaluation"):
            module.promote_learning(
                candidate["id"],
                [{"project_digest": candidate["project_digest"], "result": "passed"}],
                approved=True,
            )
        with self.assertRaisesRegex(module.EngineeringError, "second project"):
            module.evaluate_learning(candidate["id"], root, completion["run_id"])

        second_root, second_completion = self.terminal_completion("promotion-second")
        evaluation = module.evaluate_learning(
            candidate["id"], second_root, second_completion["run_id"]
        )
        self.assertEqual("evaluating", json.loads(local.read_text(encoding="utf-8"))["state"])
        with self.assertRaisesRegex(module.EngineeringError, "approval"):
            module.promote_learning(
                candidate["id"],
                [{"evaluation_id": evaluation["id"]}],
                approved=False,
            )
        module.record_learning_approval(candidate["id"], approved=True)
        self.assertEqual(
            "approved_for_promotion", json.loads(local.read_text(encoding="utf-8"))["state"]
        )

        promoted = module.promote_learning(
            candidate["id"],
            [{"evaluation_id": evaluation["id"]}],
            approved=True,
        )
        self.assertEqual("promoted", promoted["state"])
        self.assertEqual(
            ["proposed", "evaluating", "approved_for_promotion", "promoted"],
            [item["state"] for item in promoted["history"]],
        )
        self.assertIn(candidate["id"], module.discover_shared_skills())
        self.assertEqual("promoted", json.loads(local.read_text(encoding="utf-8"))["state"])

    def test_well_formed_forged_promotion_without_attestation_never_discovers(self):
        module = self.module()
        root, completion = self.terminal_completion("forged-shaped-promotion")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        queue_path = module._contribution_queue_path()
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        queue["items"] = [self.forged_promoted_item(module, candidate)]
        queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "attestation|promotion"):
            module.discover_shared_skills()

    def test_tampered_attestation_and_cross_project_replay_fail_closed(self):
        module = self.module()
        root, completion = self.terminal_completion("attested-source")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        second_root, second_completion = self.terminal_completion("attested-second")
        evaluation = module.evaluate_learning(candidate["id"], second_root, second_completion["run_id"])
        module.record_learning_approval(candidate["id"], approved=True)
        module.promote_learning(
            candidate["id"], [{"evaluation_id": evaluation["id"]}], approved=True
        )
        registry_path = module._promotion_attestation_path()
        original_registry = registry_path.read_text(encoding="utf-8")
        registry = json.loads(original_registry)
        registry["items"][0]["signature"] = "hmac-sha256:" + "0" * 64
        registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(module.EngineeringError, "attestation"):
            module.discover_shared_skills()

        registry_path.write_text(original_registry, encoding="utf-8")
        queue_path = module._contribution_queue_path()
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        queue["items"] = [
            self.forged_promoted_item(
                module, candidate, project_digest="sha256:" + "9" * 64
            )
        ]
        queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(module.EngineeringError, "attestation|promotion"):
            module.discover_shared_skills()

    def test_contribution_home_reparse_parent_fails_before_resolution(self):
        module = self.module()
        root, completion = self.terminal_completion("contribution-reparse")
        managed = self.home / ".agents"
        managed.mkdir()
        real = module._is_reparse_point

        with (
            patch.object(
                module,
                "_is_reparse_point",
                side_effect=lambda path: Path(path).name == managed.name or real(path),
            ),
            self.assertRaisesRegex(module.EngineeringError, "reparse|boundary"),
        ):
            module.propose_learning(root, completion["run_id"], "reusable_test")

    def test_forged_promoted_state_and_missing_lifecycle_never_discover(self):
        module = self.module()
        root, completion = self.terminal_completion("forged-promotion")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        path = self.home / ".agents" / "engineering" / "contribution-queue.json"
        queue = json.loads(path.read_text(encoding="utf-8"))
        queue["items"][0].update(
            state="promoted",
            history=["proposed", "evaluating", "approved_for_promotion", "promoted"],
            evidence=[{"project_digest": "sha256:" + "4" * 64, "result": "passed"}],
            review={"explicit_approval": True},
        )
        path.write_text(json.dumps(queue), encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "queue"):
            module.discover_shared_skills()
        self.assertNotIn(candidate["id"], [])

    def test_install_creates_one_canonical_skill_and_thin_agent_forwarders(self):
        module = self.module()
        source = self.bundle_repo()

        receipt = module.install_bundle(source, self.home)

        canonical = self.home / ".agents" / "skills" / "engineering" / "SKILL.md"
        claude = self.home / ".claude" / "skills" / "engineering" / "SKILL.md"
        shim = self.home / ".agents" / "skills" / "engineering-traceability" / "SKILL.md"
        expected_skill = subprocess.run(
            [
                "git",
                "-C",
                str(source.parents[2]),
                "show",
                "HEAD:.agents/skills/engineering/SKILL.md",
            ],
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(expected_skill, canonical.read_bytes())
        self.assertIn("engineering.py", (canonical.parent / "scripts" / "engineering.cmd").read_text(encoding="utf-8"))
        self.assertIn("engineering.py", (canonical.parent / "scripts" / "engineering").read_text(encoding="utf-8"))
        self.assertIn("~/.agents/skills/engineering/SKILL.md", claude.read_text(encoding="utf-8"))
        self.assertIn("~/.agents/skills/engineering/SKILL.md", shim.read_text(encoding="utf-8"))
        self.assertNotIn(str(source), claude.read_text(encoding="utf-8"))
        self.assertEqual(
            json.loads((source / "manifest.json").read_text(encoding="utf-8"))["version"],
            receipt["skill_version"],
        )
        self.assertRegex(receipt["source_git_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            "d89ec68af95e0cad801b56d88df383991e659823",
            receipt["graphify_commit"],
        )
        self.assertEqual(receipt["codex_parity_hash"], receipt["claude_parity_hash"])
        receipt_text = (
            self.home / ".agents" / "engineering" / "install-receipt.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn(str(source), receipt_text)

    def test_bundle_identity_and_install_bytes_are_stable_across_checkout_eol(self):
        """One Git artifact has one bundle identity on LF and CRLF hosts."""
        module = self.module()
        origin_source = self.bundle_repo("bundle-object-eol")
        origin = origin_source.parents[2]
        lf_root = Path(self.temporary_directory.name) / "bundle-object-eol-lf"
        crlf_root = Path(self.temporary_directory.name) / "bundle-object-eol-crlf"
        isolated_git_config = Path(self.temporary_directory.name) / "empty.gitconfig"
        isolated_git_config.write_text("", encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "GIT_CONFIG_GLOBAL": str(isolated_git_config),
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        ):
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--config",
                    "core.autocrlf=false",
                    str(origin),
                    str(lf_root),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--config",
                    "core.autocrlf=true",
                    str(origin),
                    str(crlf_root),
                ],
                check=True,
                capture_output=True,
            )
        lf_source = lf_root / ".agents" / "skills" / "engineering"
        crlf_source = crlf_root / ".agents" / "skills" / "engineering"
        self.assertNotEqual(
            (lf_source / "SKILL.md").read_bytes(),
            (crlf_source / "SKILL.md").read_bytes(),
            "fixture must exercise distinct checkout bytes",
        )

        _, _, lf_commit, lf_digest = module._bundle_files(lf_source)
        _, _, crlf_commit, crlf_digest = module._bundle_files(crlf_source)
        self.assertEqual(lf_commit, crlf_commit)
        self.assertEqual(lf_digest, crlf_digest)
        expected_tree = self.git(origin, "rev-parse", f"{lf_commit}^{{tree}}")
        lf_receipt = module.install_bundle(lf_source, self.home)
        installed_skill = self.home / ".agents" / "skills" / "engineering" / "SKILL.md"
        committed_skill = subprocess.run(
            [
                "git",
                "-C",
                str(origin),
                "show",
                f"{lf_commit}:.agents/skills/engineering/SKILL.md",
            ],
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(committed_skill, installed_skill.read_bytes())
        self.assertEqual(expected_tree, lf_receipt["source_git_tree"])
        retained = module._load_install_receipt(
            self.home / ".agents" / "engineering" / "install-receipt.json",
            module._install_key(self.home),
        )
        self.assertEqual(expected_tree, retained["source_git_tree"])

    def test_install_release_gate_preflight_requires_exact_token_pair(self):
        """Installation may consume a verified token but never self-authorizes it."""
        module = self.module()
        source = self.bundle_repo("install-release-gate", version="2.2.6")
        _, source_manifest, source_commit, source_digest = module._bundle_files(source)
        source_tree = module._bundle_git_tree(source, source_commit)
        with self.assertRaisesRegex(module.EngineeringError, "requires an exact release token"):
            module.install_bundle(source, self.home)
        self.assertFalse((self.home / ".agents" / "skills" / "engineering").exists())
        with self.assertRaisesRegex(module.EngineeringError, "both token"):
            module.install_bundle(
                source,
                self.home,
                release_token={"root": str(self.home), "token_id": "release-token-" + "1" * 32},
            )
        with patch.object(
            module,
            "verify_release_token",
            return_value={
                "schema": "engineering.release-token.v2",
                "token_id": "release-token-" + "1" * 32,
                "token_digest": "sha256:" + "3" * 64,
                "artifact_digest": "sha256:" + "1" * 64,
                "action": "install",
                "acceptance_id": "acceptance-a",
                "native_approval_required": True,
                "source_bundle": {
                    "source_git_commit": source_commit,
                    "source_git_tree": source_tree,
                    "source_digest": source_digest,
                    "skill_version": source_manifest["version"],
                },
            },
        ) as verify:
            receipt = module.install_bundle(
                source,
                self.home,
                release_token={
                    "root": str(source.parents[3]),
                    "token_id": "release-token-" + "1" * 32,
                },
                release_artifact_digest="sha256:" + "1" * 64,
            )
        verify.assert_called_once_with(
            source.parents[3],
            "release-token-" + "1" * 32,
            "sha256:" + "1" * 64,
            "install",
        )
        self.assertTrue(receipt["release_gate"]["native_approval_required"])

    def test_install_rejects_release_token_for_different_source_bundle(self):
        """Replacing the copied bundle after acceptance must invalidate the install token."""
        module = self.module()
        source_a = self.bundle_repo("install-token-bundle-a", version="2.2.6")
        source_b = self.bundle_repo("install-token-bundle-b", version="2.2.6")
        (source_b / "SKILL.md").write_bytes(
            (source_b / "SKILL.md").read_bytes() + b"\n# synthetic bundle B\n"
        )
        source_b_root = source_b.parents[2]
        self.git(source_b_root, "add", ".")
        self.git(source_b_root, "commit", "-m", "different bundle")
        _, manifest_a, commit_a, digest_a = module._bundle_files(source_a)
        tree_a = module._bundle_git_tree(source_a, commit_a)

        with patch.object(
            module,
            "verify_release_token",
            return_value={
                "schema": "engineering.release-token.v2",
                "token_id": "release-token-" + "1" * 32,
                "artifact_digest": "sha256:" + "2" * 64,
                "action": "install",
                "acceptance_id": "acceptance-a",
                "native_approval_required": True,
                "source_bundle": {
                    "source_git_commit": commit_a,
                    "source_git_tree": tree_a,
                    "source_digest": digest_a,
                    "skill_version": manifest_a["version"],
                },
            },
        ):
            with self.assertRaisesRegex(module.EngineeringError, "source bundle"):
                module.install_bundle(
                    source_b,
                    self.home,
                    release_token={
                        "root": str(source_b_root),
                        "token_id": "release-token-" + "1" * 32,
                    },
                    release_artifact_digest="sha256:" + "2" * 64,
                )

        self.assertFalse((self.home / ".agents" / "skills" / "engineering").exists())

    def test_install_receipt_reconciles_release_source_facts(self):
        """The signed receipt must retain the exact gate and bundle that were installed."""
        module = self.module()
        source = self.bundle_repo("install-receipt-source-facts", version="2.2.6")
        _, manifest, commit, source_digest = module._bundle_files(source)
        source_tree = module._bundle_git_tree(source, commit)
        authorization = {
            "schema": "engineering.install-release-authorization.v1",
            "token_id": "release-token-" + "1" * 32,
            "token_digest": "sha256:" + "3" * 64,
            "artifact_digest": "sha256:" + "2" * 64,
            "acceptance_id": "acceptance-a",
            "source_bundle": {
                "source_git_commit": commit,
                "source_git_tree": source_tree,
                "source_digest": source_digest,
                "skill_version": manifest["version"],
            },
        }
        with patch.object(
            module,
            "verify_release_token",
            return_value={
                "schema": "engineering.release-token.v2",
                "token_id": authorization["token_id"],
                "token_digest": authorization["token_digest"],
                "artifact_digest": authorization["artifact_digest"],
                "action": "install",
                "acceptance_id": authorization["acceptance_id"],
                "native_approval_required": True,
                "source_bundle": authorization["source_bundle"],
            },
        ):
            receipt = module.install_bundle(
                source,
                self.home,
                release_token={
                    "root": str(source.parents[2]),
                    "token_id": authorization["token_id"],
                },
                release_artifact_digest=authorization["artifact_digest"],
            )

        self.assertEqual("engineering.install.v5", receipt["schema"])
        self.assertEqual(authorization, receipt.get("release_authorization"))
        self.assertEqual(source_digest, receipt["source_digest"])
        persisted = {key: value for key, value in receipt.items() if key != "release_gate"}
        self.assertEqual(
            persisted,
            module._load_install_receipt(
                module._install_paths(self.home)["receipt"], module._install_key(self.home)
            ),
        )

    def test_install_publishes_a_discoverable_windows_command_launcher(self):
        module = self.module()
        source = self.bundle_repo("command-launcher")
        module.install_bundle(source, self.home)

        launcher = self.home / ".agents" / "bin" / "engineering.cmd"
        self.assertTrue(launcher.is_file())
        self.assertIn("..\\skills\\engineering\\scripts\\engineering.cmd", launcher.read_text(encoding="utf-8"))
        self.assertTrue(module._valid_command_launchers(launcher.parent))

    def _run_windows_skill_launcher(self, available: tuple[str, ...]) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(SKILL_DIR / "scripts" / "engineering.cmd", scripts / "engineering.cmd")
            (scripts / "engineering.py").write_text("raise SystemExit(99)\n", encoding="utf-8")
            capture = root / "capture.txt"
            for command in available:
                (root / f"{command}.cmd").write_text(
                    '@echo off\r\n>"%CAPTURE_FILE%" echo %~n0 %*\r\nexit /b 0\r\n',
                    encoding="utf-8",
                    newline="",
                )
            environment = {
                **os.environ,
                "PATH": str(root),
                "PATHEXT": ".COM;.EXE;.BAT;.CMD",
                "CAPTURE_FILE": str(capture),
            }
            result = subprocess.run(
                [
                    os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
                    "/d",
                    "/c",
                    str(scripts / "engineering.cmd"),
                    "--help",
                ],
                capture_output=True,
                text=True,
                env=environment,
                timeout=10,
            )
            result.capture = capture.read_text(encoding="utf-8").strip() if capture.is_file() else ""
            return result

    @unittest.skipUnless(os.name == "nt", "Windows launcher contract")
    def test_windows_skill_launcher_preserves_py3_preference(self):
        result = self._run_windows_skill_launcher(("py", "python"))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertRegex(result.capture, r'^py -3 ".+engineering\.py" --help$')

    @unittest.skipUnless(os.name == "nt", "Windows launcher contract")
    def test_windows_skill_launcher_falls_back_to_python_when_py_is_unavailable(self):
        result = self._run_windows_skill_launcher(("python",))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertRegex(result.capture, r'^python ".+engineering\.py" --help$')

    @unittest.skipUnless(os.name == "nt", "Windows launcher contract")
    def test_windows_skill_launcher_invokes_resolved_python_without_pathext(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(SKILL_DIR / "scripts" / "engineering.cmd", scripts / "engineering.cmd")
            # The class normally patches sys.executable to the isolated fake
            # Graphify venv.  A copied venv launcher is invalid without its
            # sibling pyvenv.cfg, while this launcher-resolution test needs a
            # standalone base interpreter only.
            launcher_python = Path(getattr(sys, "_base_executable", sys.executable))
            shutil.copy2(launcher_python, root / "python.exe")
            runtime_dll = launcher_python.with_name(
                f"python{sys.version_info.major}{sys.version_info.minor}.dll"
            )
            if runtime_dll.is_file():
                shutil.copy2(runtime_dll, root / runtime_dll.name)
            capture = root / "capture.txt"
            (scripts / "engineering.py").write_text(
                "from pathlib import Path\n"
                "import os, sys\n"
                "Path(os.environ['CAPTURE_FILE']).write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n",
                encoding="utf-8",
            )
            environment = {
                **os.environ,
                "PATH": str(root),
                "PATHEXT": "",
                "CAPTURE_FILE": str(capture),
            }

            result = subprocess.run(
                [
                    os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
                    "/d",
                    "/c",
                    str(scripts / "engineering.cmd"),
                    "--help",
                ],
                capture_output=True,
                text=True,
                env=environment,
                timeout=10,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("--help", capture.read_text(encoding="utf-8"))

    def test_windows_skill_launcher_executes_the_resolved_interpreter_path(self):
        launcher = (SKILL_DIR / "scripts" / "engineering.cmd").read_text(
            encoding="utf-8"
        )

        self.assertIn('set "ENGINEERING_PYTHON=%%~$PATH:I"', launcher)
        self.assertIn('"%ENGINEERING_PYTHON%"', launcher)
        self.assertNotRegex(launcher, r"(?m)^py -3 ")
        self.assertNotRegex(launcher, r"(?m)^python ")

    def test_semantic_matrix_blocks_only_impacted_declared_rows(self):
        module = self.module()
        nodes = [
            {"id": "code-orbit", "type": "code_symbol", "source": {"path": "src/orbit.py"}},
            {"id": "test-positive", "type": "test", "source": {"path": "tests/test_orbit.py"}},
            {"id": "test-negative", "type": "test", "source": {"path": "tests/test_orbit.py"}},
        ]
        manifest = {"semantic_matrices": [{"source": "docs/routes.md", "items": [{
            "id": "orbit-route", "owner": "operations", "implementation": "code-orbit",
            "positive": "test-positive", "negative": "missing-negative",
        }]}]}

        self.assertEqual(["orbit-route"], module._semantic_matrix_issues(manifest, nodes, {"src/orbit.py"}))
        self.assertEqual([], module._semantic_matrix_issues(manifest, nodes, {"README.md"}))

    def test_install_validation_allows_only_generated_controller_bytecode(self):
        module = self.module()
        source = self.bundle_repo("bytecode-cache")
        receipt = module.install_bundle(source, self.home)
        canonical = self.home / ".agents" / "skills" / "engineering"
        cache = canonical / "scripts" / "__pycache__"
        cache.mkdir()
        (cache / "engineering.cpython-312.pyc").write_bytes(b"generated")
        (cache / "engineering_host_boundary.cpython-312.pyc").write_bytes(
            b"generated host boundary"
        )

        self.assertEqual(
            receipt["codex_parity_hash"],
            module._validated_installed_bundle(canonical, receipt),
        )

        (cache / "untrusted.cpython-312.pyc").write_bytes(b"unexpected")
        with self.assertRaisesRegex(module.EngineeringError, "unexpected bytecode"):
            module._validated_installed_bundle(canonical, receipt)

    def test_install_replay_is_exact_and_known_good_rollback_restores_prior(self):
        module = self.module()
        source = self.bundle_repo()
        first = module.install_bundle(source, self.home)
        canonical = self.home / ".agents" / "skills" / "engineering" / "SKILL.md"
        prior_bytes = canonical.read_bytes()
        self.update_bundle(source)

        second = module.install_bundle(source, self.home)
        replay = module.install_bundle(source, self.home)
        rolled_back = module.rollback_install(self.home)

        self.assertEqual(second, replay)
        self.assertEqual(prior_bytes, canonical.read_bytes())
        self.assertEqual("rolled_back", rolled_back["status"])
        self.assertEqual(first["skill_version"], rolled_back["skill_version"])

    def test_temporary_home_install_replay_and_rollback_do_not_mutate_windows_path(self):
        """A custom installation must not register its launcher in the active user profile."""
        module = self.module()
        source = self.bundle_repo("custom-home-path")
        active_home = Path(self.temporary_directory.name) / "active-home"
        active_home.mkdir()
        registry = Mock()
        registry.HKEY_CURRENT_USER = object()
        registry.KEY_QUERY_VALUE = 1
        registry.KEY_SET_VALUE = 2
        registry.REG_SZ = 1
        registry.REG_EXPAND_SZ = 2
        registry.QueryValueEx.return_value = ("", registry.REG_EXPAND_SZ)
        registry.OpenKey.return_value = contextlib.nullcontext(Mock())
        path_before = os.environ.get("PATH", "")

        with (
            patch.object(module.os, "name", "nt"),
            patch.object(Path, "home", return_value=active_home),
            patch.dict(sys.modules, {"winreg": registry}),
        ):
            module.install_bundle(source, self.home)
            module.install_bundle(source, self.home)
            self.update_bundle(source, "2.1.1")
            module.install_bundle(source, self.home)
            module.rollback_install(self.home)

        self.assertEqual(path_before, os.environ.get("PATH", ""))
        self.assertEqual(0, registry.OpenKey.call_count)
        self.assertEqual(0, registry.SetValueEx.call_count)

    def test_active_home_replay_upgrade_and_rollback_do_not_restore_windows_path(self):
        """Only the first active-home install may register a launcher directory."""
        module = self.module()
        source = self.bundle_repo("active-home-path")
        first_bundle = module._bundle_files(source)
        first_tree = module._bundle_git_tree(source, first_bundle[2])
        baseline = r"C:\\baseline"
        registry_state = {"path": baseline}
        registry = Mock()
        registry.HKEY_CURRENT_USER = object()
        registry.KEY_QUERY_VALUE = 1
        registry.KEY_SET_VALUE = 2
        registry.REG_SZ = 1
        registry.REG_EXPAND_SZ = 2
        registry.OpenKey.return_value = contextlib.nullcontext(Mock())
        registry.QueryValueEx.side_effect = lambda _key, _name: (
            registry_state["path"], registry.REG_EXPAND_SZ
        )
        registry.SetValueEx.side_effect = lambda _key, _name, _reserved, _kind, value: (
            registry_state.__setitem__("path", value)
        )

        with (
            patch.object(module.os, "name", "nt"),
            patch.object(Path, "home", return_value=self.home),
            patch.dict(sys.modules, {"winreg": registry}),
            patch.dict(os.environ, {"PATH": baseline}, clear=False),
            patch.object(module, "_bundle_files", return_value=first_bundle),
            patch.object(module, "_bundle_git_tree", return_value=first_tree),
        ):
            module.install_bundle(source, self.home)
            self.assertNotEqual(baseline, registry_state["path"])
            self.assertNotEqual(baseline, os.environ["PATH"])

            def assert_not_restored():
                self.assertEqual(baseline, registry_state["path"])
                self.assertEqual(baseline, os.environ["PATH"])
                self.assertEqual(0, registry.OpenKey.call_count)
                self.assertEqual(0, registry.SetValueEx.call_count)

            registry_state["path"] = baseline
            os.environ["PATH"] = baseline
            registry.reset_mock()
            module.install_bundle(source, self.home)
            assert_not_restored()

        self.update_bundle(source, "2.1.1")
        updated_bundle = module._bundle_files(source)
        updated_tree = module._bundle_git_tree(source, updated_bundle[2])
        with (
            patch.object(module.os, "name", "nt"),
            patch.object(Path, "home", return_value=self.home),
            patch.dict(sys.modules, {"winreg": registry}),
            patch.dict(os.environ, {"PATH": baseline}, clear=False),
            patch.object(module, "_bundle_files", return_value=updated_bundle),
            patch.object(module, "_bundle_git_tree", return_value=updated_tree),
        ):
            registry_state["path"] = baseline
            registry.reset_mock()
            module.install_bundle(source, self.home)
            assert_not_restored()

            registry.reset_mock()
            module.rollback_install(self.home)
            assert_not_restored()

    def test_active_home_windows_launcher_registration_is_idempotent(self):
        module = self.module()
        command = self.home / ".agents" / "bin"
        registry = Mock()
        registry.HKEY_CURRENT_USER = object()
        registry.KEY_QUERY_VALUE = 1
        registry.KEY_SET_VALUE = 2
        registry.REG_SZ = 1
        registry.REG_EXPAND_SZ = 2
        registry.QueryValueEx.return_value = (str(command), registry.REG_EXPAND_SZ)
        registry.OpenKey.return_value = contextlib.nullcontext(Mock())

        with (
            patch.object(module.os, "name", "nt"),
            patch.object(Path, "home", return_value=self.home),
            patch.dict(sys.modules, {"winreg": registry}),
            patch.dict(os.environ, {"PATH": str(command)}, clear=False),
        ):
            module._register_windows_command_directory(self.home.resolve(), command)
            module._register_windows_command_directory(self.home.resolve(), command)

        self.assertEqual(2, registry.OpenKey.call_count)
        self.assertEqual(0, registry.SetValueEx.call_count)

    def test_tampered_installed_script_or_prior_bundle_is_never_known_good(self):
        module = self.module()
        source = self.bundle_repo()
        module.install_bundle(source, self.home)
        paths = module._install_paths(self.home)
        (paths["canonical"] / "scripts" / "engineering.py").write_text(
            "tampered = True\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(module.EngineeringError, "receipt"):
            module.install_bundle(source, self.home)

        second_home = Path(self.temporary_directory.name) / "second-home"
        second_home.mkdir()
        self.update_bundle(source)
        with patch.dict(
            os.environ, {"ENGINEERING_USER_HOME": str(second_home)}, clear=False
        ):
            module.install_bundle(source, second_home)
            self.update_bundle(source, "2.0.2")
            module.install_bundle(source, second_home)
            paths = module._install_paths(second_home)
            (paths["previous"] / "references" / "controller-contract.md").write_text(
                "tampered\n", encoding="utf-8"
            )
            current = module._tree_digest(paths["canonical"])
            with self.assertRaisesRegex(module.EngineeringError, "known-good"):
                module.rollback_install(second_home)
            self.assertEqual(current, module._tree_digest(paths["canonical"]))

    def test_install_rejects_source_symlink_and_preserves_existing_install(self):
        module = self.module()
        source = self.bundle_repo()
        module.install_bundle(source, self.home)
        canonical = self.home / ".agents" / "skills" / "engineering" / "SKILL.md"
        before = canonical.read_bytes()
        unsafe = Path(self.temporary_directory.name) / "unsafe-bundle"
        shutil.copytree(source, unsafe)
        outside = Path(self.temporary_directory.name) / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        try:
            (unsafe / "escape.txt").symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation is unavailable")

        with self.assertRaisesRegex(module.EngineeringError, "link|reparse"):
            module.install_bundle(unsafe, self.home)

        self.assertEqual(before, canonical.read_bytes())

    def test_install_lock_fails_closed_without_mutating_target(self):
        module = self.module()
        source = self.bundle_repo()
        module.install_bundle(source, self.home)
        canonical = self.home / ".agents" / "skills" / "engineering" / "SKILL.md"
        before = canonical.read_bytes()
        lock = self.home / ".agents" / "engineering" / "install.lock"
        lock.mkdir()
        (lock / "owner.json").write_text(
            json.dumps(
                {
                    "schema": "engineering.directory-lock.v1",
                    "owner_pid": os.getpid(),
                    "created_at": "2000-01-01T00:00:00Z",
                    "operation_id": "operation-" + "1" * 32,
                    "token": "2" * 32,
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(module.EngineeringError, "install.*progress"):
            module.install_bundle(source, self.home)

        self.assertEqual(before, canonical.read_bytes())

    def test_dead_install_lock_is_recovered_but_live_or_mismatched_is_preserved(self):
        module = self.module()
        source = self.bundle_repo()
        lock = self.home / ".agents" / "engineering" / "install.lock"
        lock.mkdir(parents=True)
        owner = {
            "schema": "engineering.directory-lock.v1",
            "owner_pid": 2_147_000_000,
            "created_at": "2000-01-01T00:00:00Z",
            "operation_id": "operation-" + "1" * 32,
            "token": "2" * 32,
        }
        (lock / "owner.json").write_text(json.dumps(owner), encoding="utf-8")

        with patch.object(module, "_process_alive", return_value=False):
            receipt = module.install_bundle(source, self.home)

        self.assertEqual("installed", receipt["status"])
        self.assertFalse(lock.exists())

    def test_project_lineage_rejects_shallow_replace_and_graft_state(self):
        module = self.module()
        source = self.bundle_repo("lineage-source")
        repository = Path(self.git(source, "rev-parse", "--show-toplevel"))
        shallow = Path(self.temporary_directory.name) / "shallow"
        subprocess.run(
            ["git", "clone", "--depth", "1", repository.as_uri(), str(shallow)],
            check=True,
            capture_output=True,
            text=True,
        )
        with self.assertRaisesRegex(module.EngineeringError, "lineage|shallow"):
            module._project_contribution_digest(shallow)

        (repository / "second.txt").write_text("second\n", encoding="utf-8")
        self.git(repository, "add", "second.txt")
        self.git(repository, "commit", "-m", "second")
        root_commit = self.git(repository, "rev-list", "--max-parents=0", "HEAD")
        self.git(repository, "replace", "HEAD", root_commit)
        with self.assertRaisesRegex(module.EngineeringError, "lineage|replace"):
            module._project_contribution_digest(repository)
        self.git(repository, "replace", "-d", "HEAD")

        graft = Path(self.git(repository, "rev-parse", "--git-path", "info/grafts"))
        if not graft.is_absolute():
            graft = repository / graft
        graft.parent.mkdir(parents=True, exist_ok=True)
        graft.write_text(self.git(repository, "rev-parse", "HEAD") + "\n", encoding="ascii")
        with self.assertRaisesRegex(module.EngineeringError, "lineage|graft"):
            module._project_contribution_digest(repository)

    def test_project_lineage_ignores_dangerous_git_environment_injection(self):
        module = self.module()
        source = self.bundle_repo("identity-source")
        repository = Path(self.git(source, "rev-parse", "--show-toplevel"))
        other = self.bundle_repo("identity-other")
        other_repository = Path(self.git(other, "rev-parse", "--show-toplevel"))
        expected = module._project_contribution_digest(repository)
        injected = {
            "GIT_DIR": str(other_repository / ".git"),
            "GIT_WORK_TREE": str(other_repository),
            "GIT_OBJECT_DIRECTORY": str(other_repository / ".git" / "objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(other_repository / ".git" / "objects"),
            "GIT_REPLACE_REF_BASE": "refs/heads",
            "GIT_CONFIG_GLOBAL": str(other_repository / "hostile.gitconfig"),
        }
        with patch.dict(os.environ, injected, clear=False):
            self.assertEqual(expected, module._project_contribution_digest(repository))

    def test_controller_key_permissions_are_verified_on_every_read(self):
        module = self.module()
        controller = self.home / ".agents" / "engineering" / "controller"
        controller.mkdir(parents=True)
        key = controller / "attestation.key"
        key.write_text("1" * 64 + "\n", encoding="ascii")

        with patch.object(module, "_verify_owner_private") as verify:
            self.assertEqual(bytes.fromhex("1" * 64), module._controller_key(controller, required=True))

        self.assertEqual([((controller,), {"directory": True}), ((key,), {"directory": False})], verify.call_args_list)

    def test_forged_previous_install_receipt_cannot_drive_rollback(self):
        module = self.module()
        source = self.bundle_repo("signed-receipts")
        module.install_bundle(source, self.home)
        self.update_bundle(source, "2.1.1")
        module.install_bundle(source, self.home)
        previous = self.home / ".agents" / "engineering" / "previous-install-receipt.json"
        payload = json.loads(previous.read_text(encoding="utf-8"))
        payload["status"] = "rolled_back"
        previous.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "receipt|signature"):
            module.rollback_install(self.home)

    def test_first_install_holds_lock_before_initializing_signing_key(self):
        module = self.module()
        source = self.bundle_repo("first-install-lock")
        entered = threading.Event()
        release = threading.Event()
        real_key = module._install_key
        outcomes = []

        def delayed_key(home):
            if threading.current_thread().name == "winning-install":
                entered.set()
                self.assertTrue(release.wait(10))
            return real_key(home)

        def install():
            try:
                outcomes.append(module.install_bundle(source, self.home))
            except Exception as error:
                outcomes.append(error)

        with patch.object(module, "_install_key", side_effect=delayed_key):
            winner = threading.Thread(target=install, name="winning-install")
            winner.start()
            self.assertTrue(entered.wait(10))
            with self.assertRaisesRegex(module.EngineeringError, "install.*progress"):
                module.install_bundle(source, self.home)
            release.set()
            winner.join(30)

        self.assertFalse(winner.is_alive())
        self.assertEqual(1, len(outcomes))
        self.assertIsInstance(outcomes[0], dict)
        key = module._install_key(self.home)
        receipt = module._load_install_receipt(module._install_paths(self.home)["receipt"], key)
        self.assertEqual(outcomes[0], receipt)

    def test_lock_owner_publication_failure_never_leaves_unowned_lock(self):
        module = self.module()
        lock = self.home / ".agents" / "engineering" / "install.lock"
        with (
            patch.object(module, "_atomic_text", side_effect=OSError("synthetic crash")),
            self.assertRaises(OSError),
        ):
            module._acquire_directory_lock(lock, "locked")
        self.assertFalse(lock.exists())

    def test_lock_reclaim_rejects_reparse_leaf_before_read_or_delete(self):
        module = self.module()
        lock = self.home / ".agents" / "engineering" / "install.lock"
        lock.mkdir(parents=True)
        (lock / "owner.json").write_text("{}", encoding="utf-8")
        real = module._is_reparse_point

        def mark_lock(path):
            return Path(path) == lock or real(path)

        with (
            patch.object(module, "_is_reparse_point", side_effect=mark_lock),
            self.assertRaisesRegex(module.EngineeringError, "reparse|boundary|locked"),
        ):
            module._acquire_directory_lock(lock, "locked")
        self.assertTrue(lock.exists())

    def test_managed_parent_reparse_point_is_rejected_before_resolution(self):
        module = self.module()
        source = self.bundle_repo()
        agents = self.home / ".agents"
        agents.mkdir()

        real = module._is_reparse_point

        def mark_agents(path):
            return Path(path) == agents or real(path)

        with (
            patch.object(module, "_is_reparse_point", side_effect=mark_agents),
            self.assertRaisesRegex(module.EngineeringError, "boundary|reparse"),
        ):
            module.install_bundle(source, self.home)

        self.assertFalse((agents / "skills" / "engineering").exists())

    def test_install_rejects_dirty_source_closure(self):
        module = self.module()
        source = self.bundle_repo()
        (source / "SKILL.md").write_text("changed after commit\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "exact Git source"):
            module.install_bundle(source, self.home)

        self.assertFalse((self.home / ".agents" / "skills" / "engineering").exists())

    def test_partial_loader_publication_restores_every_prior_surface(self):
        module = self.module()
        source = self.bundle_repo()
        module.install_bundle(source, self.home)
        paths = module._install_paths(self.home)
        before = {key: module._tree_digest(paths[key]) for key in ("canonical", "claude", "shim")}
        receipt_before = paths["receipt"].read_bytes()
        self.update_bundle(source)
        with (
            patch.object(
                module,
                "_replace_install_path",
                side_effect=self.fail_once_on_target(module, paths["receipt"]),
            ),
            self.assertRaisesRegex(OSError, "transactional publication"),
        ):
            module.install_bundle(source, self.home)

        self.assertEqual(
            before,
            {key: module._tree_digest(paths[key]) for key in ("canonical", "claude", "shim")},
        )
        self.assertEqual(receipt_before, paths["receipt"].read_bytes())

    def test_windows_atomic_publish_retries_transient_access_denied(self):
        """A short Windows sharing race cannot invalidate an exact install."""
        module = self.module()
        source = Path(self.temporary_directory.name) / "atomic-source"
        target = Path(self.temporary_directory.name) / "atomic-target"
        source.mkdir()
        (source / "payload.txt").write_text("exact\n", encoding="utf-8")
        real_replace = module.os.replace
        attempts = []
        denied = PermissionError(13, "synthetic transient access denied")
        denied.winerror = 5

        def transient_once(observed_source, observed_target):
            attempts.append((Path(observed_source), Path(observed_target)))
            if len(attempts) == 1:
                raise denied
            return real_replace(observed_source, observed_target)

        with (
            patch.object(module, "_install_replace_retry_delays", return_value=(0.0,)),
            patch.object(module.os, "replace", side_effect=transient_once),
            patch.object(module.time, "sleep") as sleep,
        ):
            module._replace_install_path(
                source,
                target,
                {
                    "exists": False,
                    "kind": "absent",
                    "bytes_hex": None,
                    "sha256": None,
                    "mode": None,
                },
            )

        self.assertEqual(2, len(attempts))
        sleep.assert_called_once()
        self.assertEqual("exact\n", (target / "payload.txt").read_text(encoding="utf-8"))

    def test_atomic_publish_retry_policy_is_injected_without_path_flavour_mutation(self):
        """Windows retry coverage must not replace the host pathlib flavour."""
        module = self.module()
        source = Path(self.temporary_directory.name) / "portable-retry-source"
        target = Path(self.temporary_directory.name) / "portable-retry-target"
        source.mkdir()
        (source / "payload.txt").write_text("exact\n", encoding="utf-8")
        real_replace = module.os.replace
        attempts = 0
        denied = PermissionError(13, "synthetic transient access denied")
        denied.winerror = 5

        def transient_once(observed_source, observed_target):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise denied
            return real_replace(observed_source, observed_target)

        try:
            with (
                patch.object(module.os, "name", "posix"),
                patch.object(
                    module,
                    "_install_replace_retry_delays",
                    return_value=(0.0,),
                ),
                patch.object(module.os, "replace", side_effect=transient_once),
                patch.object(module.time, "sleep"),
            ):
                module._replace_install_path(
                    source,
                    target,
                    {
                        "exists": False,
                        "kind": "absent",
                        "bytes_hex": None,
                        "sha256": None,
                        "mode": None,
                    },
                )
        except PermissionError:
            self.fail("retry policy must be injectable without changing pathlib semantics")

        self.assertEqual(2, attempts)
        self.assertEqual("exact\n", (target / "payload.txt").read_text(encoding="utf-8"))

    def test_windows_atomic_publish_retry_revalidates_the_preimage(self):
        """A changed target during retry remains a hard publication failure."""
        module = self.module()
        source = Path(self.temporary_directory.name) / "retry-source"
        target = Path(self.temporary_directory.name) / "retry-target"
        source.mkdir()
        denied = PermissionError(13, "synthetic transient access denied")
        denied.winerror = 5
        attempts = 0

        def substitute_target(observed_source, observed_target):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                Path(observed_target).mkdir()
                raise denied
            self.fail("changed publication target must be rejected before retry")

        with (
            patch.object(module, "_install_replace_retry_delays", return_value=(0.0,)),
            patch.object(module.os, "replace", side_effect=substitute_target),
            patch.object(module.time, "sleep"),
            self.assertRaisesRegex(module.EngineeringError, "target changed"),
        ):
            module._replace_install_path(
                source,
                target,
                {
                    "exists": False,
                    "kind": "absent",
                    "bytes_hex": None,
                    "sha256": None,
                    "mode": None,
                },
            )

        self.assertEqual(1, attempts)

    def test_existing_install_backup_retry_rejects_source_substitution(self):
        """The real upgrade path cannot back up bytes changed during a retry."""
        module = self.module()
        source = self.bundle_repo("upgrade-backup-retry-race")
        module.install_bundle(source, self.home)
        self.update_bundle(source)
        paths = module._install_paths(self.home)
        real_replace = module.os.replace
        denied = PermissionError(13, "synthetic transient access denied")
        denied.winerror = 5
        injected = False

        def substitute_existing_install(observed_source, observed_target):
            nonlocal injected
            observed_source = Path(observed_source)
            observed_target = Path(observed_target)
            if (
                not injected
                and os.path.normcase(str(observed_source.resolve()))
                == os.path.normcase(str(paths["canonical"].resolve()))
                and observed_target.name.startswith(".engineering.backup-")
            ):
                injected = True
                (observed_source / "SKILL.md").write_text(
                    "# concurrently substituted install\n", encoding="utf-8"
                )
                raise denied
            return real_replace(observed_source, observed_target)

        with (
            patch.object(module, "_install_replace_retry_delays", return_value=(0.0,)),
            patch.object(module.os, "replace", side_effect=substitute_existing_install),
            patch.object(module.time, "sleep"),
            self.assertRaisesRegex(module.EngineeringError, "target changed"),
        ):
            module.install_bundle(source, self.home)

        self.assertTrue(injected)

    def test_rollback_restoration_retry_rejects_target_substitution(self):
        """The real rollback exception path cannot replace a raced restore target."""
        module = self.module()
        source = self.bundle_repo("rollback-restore-retry-race")
        module.install_bundle(source, self.home)
        self.update_bundle(source)
        module.install_bundle(source, self.home)
        paths = module._install_paths(self.home)
        real_replace = module.os.replace
        denied = PermissionError(13, "synthetic transient access denied")
        denied.winerror = 5
        forced_late_failure = False
        restore_attempts = 0

        def substitute_restoration_target(observed_source, observed_target):
            nonlocal forced_late_failure, restore_attempts
            observed_source = Path(observed_source)
            observed_target = Path(observed_target)
            if (
                not forced_late_failure
                and os.path.normcase(str(observed_target.resolve()))
                == os.path.normcase(str(paths["previous"].resolve()))
                and observed_source.name.startswith("..engineering.previous.stage-")
            ):
                forced_late_failure = True
                raise OSError("synthetic later rollback publication failure")
            if (
                forced_late_failure
                and os.path.normcase(str(observed_target.resolve()))
                == os.path.normcase(str(paths["canonical"].resolve()))
                and observed_source.name.startswith(".engineering.backup-")
            ):
                restore_attempts += 1
                if restore_attempts == 1:
                    observed_target.mkdir(parents=True)
                    (observed_target / "substitute.txt").write_text(
                        "concurrent\n", encoding="utf-8"
                    )
                    raise denied
                shutil.rmtree(observed_target)
            return real_replace(observed_source, observed_target)

        with (
            patch.object(module, "_install_replace_retry_delays", return_value=(0.0,)),
            patch.object(module.os, "replace", side_effect=substitute_restoration_target),
            patch.object(module.time, "sleep"),
            self.assertRaisesRegex(module.EngineeringError, "target changed"),
        ):
            module.rollback_install(self.home)

        self.assertTrue(forced_late_failure)
        self.assertEqual(1, restore_attempts)

    def test_transaction_cleanup_preserves_a_substituted_published_target(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "cas-published-target"
        stage = root / "stage"
        target = root / "target"
        stage.mkdir(parents=True)
        (stage / "payload.txt").write_text("authorized\n", encoding="utf-8")

        def substitute_then_fail():
            shutil.rmtree(target)
            target.mkdir()
            (target / "substitute.txt").write_text("must survive\n", encoding="utf-8")
            raise OSError("synthetic later publication failure")

        with self.assertRaisesRegex(module.EngineeringError, "target changed"):
            module._transactional_replace(
                [(stage, target)],
                "1" * 32,
                after_publication=substitute_then_fail,
            )

        self.assertEqual(
            "must survive\n",
            (target / "substitute.txt").read_text(encoding="utf-8"),
        )

    def test_transaction_rejects_a_preexisting_backup_without_deleting_it(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "cas-backup-target"
        stage = root / "stage"
        target = root / "target"
        backup = root / (".target.backup-" + "2" * 32)
        stage.mkdir(parents=True)
        target.mkdir()
        backup.mkdir()
        (stage / "payload.txt").write_text("new\n", encoding="utf-8")
        (target / "payload.txt").write_text("old\n", encoding="utf-8")
        (backup / "substitute.txt").write_text("must survive\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "target changed"):
            module._transactional_replace([(stage, target)], "2" * 32)

        self.assertEqual(
            "must survive\n",
            (backup / "substitute.txt").read_text(encoding="utf-8"),
        )

    def test_transaction_cleanup_preserves_a_substituted_stage(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "cas-stage-target"
        stage = root / "stage"
        target = root / "target"
        stage.mkdir(parents=True)
        (stage / "payload.txt").write_text("authorized\n", encoding="utf-8")

        def substitute_stage_after_publication():
            stage.mkdir()
            (stage / "substitute.txt").write_text("must survive\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "target changed"):
            module._transactional_replace(
                [(stage, target)],
                "3" * 32,
                after_publication=substitute_stage_after_publication,
            )

        self.assertEqual(
            "must survive\n",
            (stage / "substitute.txt").read_text(encoding="utf-8"),
        )

    def test_install_removal_revalidates_lexical_reparse_ancestors(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "cas-reparse"
        target = root / "target"
        target.mkdir(parents=True)
        (target / "payload.txt").write_text("must survive\n", encoding="utf-8")
        expected = module._install_path_state(target)

        with (
            patch.object(
                module,
                "_reject_reparse_ancestors",
                side_effect=module.EngineeringError("synthetic reparse ancestor"),
            ) as reject,
            self.assertRaisesRegex(module.EngineeringError, "reparse ancestor"),
        ):
            module._remove_install_path(target, expected)

        reject.assert_called()
        self.assertTrue(target.exists())

    def test_every_late_install_publication_failure_restores_exact_state(self):
        module = self.module()
        for index, key in enumerate(("claude", "shim", "command", "receipt", "previous", "previous_receipt")):
            with self.subTest(key=key):
                source = self.bundle_repo(f"install-fault-{index}")
                home = Path(self.temporary_directory.name) / f"install-home-{index}"
                home.mkdir()
                with patch.dict(
                    os.environ, {"ENGINEERING_USER_HOME": str(home)}, clear=False
                ):
                    module.install_bundle(source, home)
                    self.update_bundle(source)
                    before = self.managed_snapshot(module, home)
                    target = module._install_paths(home)[key]
                    with (
                        patch.object(module, "_replace_install_path", side_effect=self.fail_once_on_target(module, target)),
                        self.assertRaisesRegex(OSError, "transactional publication"),
                    ):
                        module.install_bundle(source, home)
                    self.assertEqual(before, self.managed_snapshot(module, home))

    def test_every_late_rollback_publication_failure_restores_exact_state(self):
        module = self.module()
        for index, key in enumerate(("claude", "shim", "command", "receipt", "previous", "previous_receipt")):
            with self.subTest(key=key):
                source = self.bundle_repo(f"rollback-fault-{index}")
                home = Path(self.temporary_directory.name) / f"rollback-home-{index}"
                home.mkdir()
                with patch.dict(
                    os.environ, {"ENGINEERING_USER_HOME": str(home)}, clear=False
                ):
                    module.install_bundle(source, home)
                    self.update_bundle(source)
                    module.install_bundle(source, home)
                    before = self.managed_snapshot(module, home)
                    target = module._install_paths(home)[key]
                    with (
                        patch.object(module, "_replace_install_path", side_effect=self.fail_once_on_target(module, target)),
                        self.assertRaisesRegex(OSError, "transactional publication"),
                    ):
                        module.rollback_install(home)
                    self.assertEqual(before, self.managed_snapshot(module, home))

    def test_setup_preview_is_read_only_and_names_both_missing_approvals(self):
        module = self.module()
        root = self.init_repo("setup-preview")
        before = module._working_state_identity(root)
        missing = module.EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        )

        with patch.object(module, "verify_graphify", side_effect=missing):
            result = module.setup(root, sys.executable)

        self.assertEqual("proposal", result["readiness"])
        self.assertEqual(
            ["graphify_install", "project_controls"],
            result["approvals_required"],
        )
        self.assertEqual("<selected-python>", result["graphify"]["install_command"][0])
        self.assertTrue(result["graphify"]["interpreter_sha256"].startswith("sha256:"))
        self.assertIn("missing", result["graphify"]["reason"].lower())
        self.assertIn(
            "hook installation as one bundle",
            result["project_plan"]["approval_scope"],
        )
        self.assertFalse(result["writes_applied"])
        self.assertEqual(before, module._working_state_identity(root))
        self.assertFalse((root / "engineering.json").exists())

    def test_setup_preview_is_compact_but_its_digest_still_binds_the_full_plan(self):
        module = self.module()
        root = self.init_repo("compact-setup-preview")
        with patch.object(module, "verify_graphify", side_effect=module.EngineeringError("missing")):
            result = module.setup(root, sys.executable)
            _, claims = module._setup_preview(root, sys.executable)
        rendered = json.dumps(result)
        self.assertNotIn("bytes_hex", rendered)
        self.assertNotIn('"content"', rendered)
        self.assertNotIn(str(root), rendered)
        self.assertNotIn(sys.executable, rendered)
        self.assertIn("documents", result["project_plan"])
        self.assertTrue(result["project_plan_digest"].startswith("sha256:"))
        self.assertEqual(result["project_plan_digest"], claims["project_plan_digest"])

    def test_setup_requires_all_current_approvals_before_any_write(self):
        module = self.module()
        missing = module.EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        )
        for index, scopes in enumerate(
            (("project_controls",), ("graphify_install",))
        ):
            with self.subTest(scopes=scopes):
                root = self.init_repo(f"setup-partial-{index}")
                before = module._working_state_identity(root)
                with patch.object(module, "verify_graphify", side_effect=missing):
                    preview = module.setup(root, sys.executable)
                with (
                    patch.object(module, "verify_graphify", side_effect=missing),
                    patch.object(module, "_run_governed_graphify_install") as runner,
                    patch.object(module, "_install_hooks_authorized") as hooks,
                ):
                    module.approve_setup(
                        root,
                        sys.executable,
                        preview["project_plan_digest"],
                        scopes=list(scopes),
                        graphify_plan_digest=(
                            preview["graphify_plan_digest"]
                            if "graphify_install" in scopes
                            else None
                        ),
                    )
                    result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
                self.assertFalse(result["writes_applied"])
                runner.assert_not_called()
                hooks.assert_not_called()
                self.assertEqual(before, module._working_state_identity(root))

    def test_setup_applies_exact_graphify_command_and_project_contract(self):
        module = self.module()
        root = self.init_repo("setup-approved")
        identity = module.GraphifyIdentity(
            executable=Path(sys.executable),
            repository=module.GRAPHIFY_REPOSITORY,
            version=module.GRAPHIFY_VERSION,
            commit=module.GRAPHIFY_COMMIT,
            required_commands=module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        missing = module.EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        )
        installed = {"value": False}

        def verify(_python):
            if not installed["value"]:
                raise missing
            return identity

        def install(_argv, _interpreter):
            installed["value"] = True

        with (
            patch.object(module, "verify_graphify", side_effect=verify),
            patch.object(module, "_run_governed_graphify_install", side_effect=install) as runner,
        ):
            preview = module.setup(root, sys.executable)
            internal, _ = module._setup_preview(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls", "graphify_install"],
                graphify_plan_digest=preview["graphify_plan_digest"],
            )
            result = module.setup(root, sys.executable)

        self.assertEqual("controls_written_pending_commit", result["readiness"])
        self.assertTrue(result["writes_applied"])
        runner.assert_called_once_with(
            internal["graphify"]["install_argv"],
            internal["graphify"]["interpreter"],
        )
        self.assertTrue((root / "engineering.json").is_file())
        self.assertIn("engineering-managed-start", (root / "AGENTS.md").read_text())
        self.assertIn("engineering-managed-start", (root / "CLAUDE.md").read_text())
        self.assertEqual("/graphify-out/\n", (root / ".gitignore").read_text())
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        self.assertIn("engineering-traceability-hook", (hooks / "pre-commit").read_text())

    def test_setup_preserves_midflight_instructions_ignores_and_custom_hook(self):
        module = self.module()
        root = self.init_repo("setup-midflight")
        (root / "AGENTS.md").write_text("# Team rules\n\nKeep this.\n", encoding="utf-8")
        (root / "CLAUDE.md").write_text("# Claude rules\n\nKeep this too.\n", encoding="utf-8")
        (root / ".gitignore").write_text("private.local\n", encoding="utf-8")
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\nprintf 'custom\\n' >> \"$PWD/custom-hook.log\"\n",
            encoding="utf-8",
        )
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )

        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            result = module.setup(root, sys.executable)

        self.assertEqual("controls_written_pending_commit", result["readiness"])
        self.assertIn("Keep this.", (root / "AGENTS.md").read_text())
        self.assertIn("Keep this too.", (root / "CLAUDE.md").read_text())
        self.assertEqual(
            "private.local\n/graphify-out/\n", (root / ".gitignore").read_text()
        )
        preserved = hooks / "engineering-traceability-preserved" / "pre-commit"
        self.assertIn("custom-hook.log", preserved.read_text())

    def test_setup_is_idempotent_after_success(self):
        module = self.module()
        root = self.init_repo("setup-idempotent")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            module.setup(root, sys.executable)
            first = module._working_state_identity(root)
            result = module.setup(root, sys.executable)
            second = module._working_state_identity(root)

        self.assertEqual(first, second)
        self.assertEqual("controls_written_pending_commit", result["readiness"])
        self.assertFalse(result["writes_applied"])
        self.assertEqual(1, (root / "AGENTS.md").read_text().count("engineering-managed-start"))

    def test_failed_graphify_install_leaves_no_project_or_hook_setup(self):
        module = self.module()
        root = self.init_repo("setup-install-failure")
        missing = module.EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        )
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        before = module._working_state_identity(root)
        with patch.object(module, "verify_graphify", side_effect=missing):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls", "graphify_install"],
                graphify_plan_digest=preview["graphify_plan_digest"],
            )
        with (
            patch.object(module, "verify_graphify", side_effect=missing),
            patch.object(
                module,
                "_run_governed_graphify_install",
                side_effect=module.EngineeringError("install failed"),
            ),
            self.assertRaisesRegex(
                module.EngineeringError,
                "recovery: project files, baseline, and hooks were not written",
            ),
        ):
            module.setup(root, sys.executable)
        self.assertEqual(before, module._working_state_identity(root))
        self.assertFalse((root / "engineering.json").exists())
        self.assertFalse((hooks / "engineering-traceability-dispatcher").exists())

    def test_late_setup_failure_restores_custom_files_and_hooks(self):
        module = self.module()
        root = self.init_repo("setup-rollback")
        (root / "AGENTS.md").write_text("original agent\n", encoding="utf-8")
        (root / ".gitignore").write_text("original.ignore\n", encoding="utf-8")
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        before_hook = (hooks / "pre-commit").read_bytes()
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
        with (
            patch.object(module, "verify_graphify", return_value=identity),
            patch.object(
                module,
                "_transactional_project_documents",
                side_effect=OSError("late setup publication"),
            ),
            self.assertRaisesRegex(OSError, "late setup publication"),
        ):
            module.setup(root, sys.executable)

        self.assertEqual("original agent\n", (root / "AGENTS.md").read_text())
        self.assertEqual("original.ignore\n", (root / ".gitignore").read_text())
        self.assertFalse((root / "CLAUDE.md").exists())
        self.assertFalse((root / "engineering.json").exists())
        self.assertEqual(before_hook, (hooks / "pre-commit").read_bytes())
        self.assertFalse((hooks / "engineering-traceability-dispatcher").exists())

    def test_existing_invalid_controls_fail_closed_before_setup(self):
        module = self.module()
        root = self.init_repo("setup-invalid")
        (root / "engineering.json").write_text("{}\n", encoding="utf-8")
        self.git(root, "add", "engineering.json")
        self.commit_all(root, "invalid controls")
        before = module._working_state_identity(root)

        with self.assertRaises(module.EngineeringError):
            module.setup(root, sys.executable)

        self.assertEqual(before, module._working_state_identity(root))

    def test_setup_rejects_mismatched_preview_digest_without_writes(self):
        module = self.module()
        root = self.init_repo("setup-mismatched-digest")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        before = module._working_state_identity(root)
        with patch.object(module, "verify_graphify", return_value=identity):
            with self.assertRaisesRegex(
                module.EngineeringError, "plan changed before approval"
            ):
                module.approve_setup(
                    root,
                    sys.executable,
                    "sha256:" + "0" * 64,
                    scopes=["project_controls"],
                )
        self.assertEqual(before, module._working_state_identity(root))

    def test_setup_rejects_malformed_managed_block_without_writes(self):
        module = self.module()
        root = self.init_repo("setup-malformed-block")
        (root / "AGENTS.md").write_text(
            "custom\n<!-- engineering-managed-start -->\nunterminated\n",
            encoding="utf-8",
        )
        before = module._working_state_identity(root)
        with self.assertRaisesRegex(module.EngineeringError, "block is malformed"):
            module.setup(root, sys.executable)
        self.assertEqual(before, module._working_state_identity(root))

    def test_setup_cli_exposes_digest_bound_approval_flags(self):
        result = self.run_cli("approve-setup", "--help")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--project-plan-digest", result.stdout)
        self.assertIn("--graphify-plan-digest", result.stdout)
        self.assertIn("--scope", result.stdout)
        setup = self.run_cli("setup", "--help")
        self.assertNotIn("--approve-project-controls", setup.stdout)
        self.assertNotIn("--approve-graphify-install", setup.stdout)

    def test_skill_explains_setup_preview_and_separate_approvals(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())

        self.assertIn("controller-contract.md", text)
        self.assertIn("preview", text.lower())
        self.assertIn("explicit setup authority", text)
        self.assertIn("Graphify is a separate approval", text)

    def test_verified_graphify_is_retained_when_late_project_setup_fails(self):
        module = self.module()
        root = self.init_repo("setup-graphify-retained")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        missing = module.EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        )
        installed = {"value": False}

        def verify(_python):
            if not installed["value"]:
                raise missing
            return identity

        def install(_argv, _interpreter):
            installed["value"] = True

        with (
            patch.object(module, "verify_graphify", side_effect=verify),
            patch.object(module, "_run_governed_graphify_install", side_effect=install),
            patch.object(
                module,
                "_transactional_project_documents",
                side_effect=OSError("project publication failed"),
            ),
            self.assertRaisesRegex(
                module.EngineeringError,
                "graphify_installed_project_setup_failed.*retained",
            ),
        ):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls", "graphify_install"],
                graphify_plan_digest=preview["graphify_plan_digest"],
            )
            module.setup(root, sys.executable)
        self.assertFalse((root / "engineering.json").exists())

    def test_setup_digest_echo_cannot_apply_without_controller_attestation(self):
        module = self.module()
        root = self.init_repo("setup-echo-bypass")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            with self.assertRaises(TypeError):
                module.setup(
                    root,
                    sys.executable,
                    approve_project_controls=preview["project_plan_digest"],
                )
        self.assertFalse((root / "engineering.json").exists())

    def test_approve_setup_creates_hmac_attestation_and_setup_consumes_once(self):
        module = self.module()
        root = self.init_repo("setup-attested")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            approval = module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            result = module.setup(root, sys.executable)
        self.assertRegex(approval["approval_id"], r"^attestation-")
        self.assertEqual("controls_written_pending_commit", result["readiness"])
        with self.assertRaisesRegex(module.EngineeringError, "missing or mismatched"):
            module._require_attestation(
                module._project_controller_dir(root),
                "setup",
                approval["claims"],
            )

    def test_setup_approval_becomes_stale_when_project_or_hook_changes(self):
        module = self.module()
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        for index, change in enumerate(("project", "hook")):
            with self.subTest(change=change):
                root = self.init_repo(f"setup-stale-{index}")
                hooks = module._hooks_dir(root)
                hooks.mkdir(parents=True, exist_ok=True)
                (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                with patch.object(module, "verify_graphify", return_value=identity):
                    preview = module.setup(root, sys.executable)
                    module.approve_setup(
                        root,
                        sys.executable,
                        preview["project_plan_digest"],
                        scopes=["project_controls"],
                    )
                    if change == "project":
                        (root / "AGENTS.md").write_text("changed\n", encoding="utf-8")
                    else:
                        (hooks / "pre-commit").write_text(
                            "#!/bin/sh\nprintf changed\n", encoding="utf-8"
                        )
                    result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
                self.assertFalse((root / "engineering.json").exists())

    def test_setup_scope_mismatch_and_failed_attempt_consume_no_authority(self):
        module = self.module()
        root = self.init_repo("setup-scope-replay")
        missing = module.EngineeringError("Graphify is missing")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", side_effect=missing):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            result = module.setup(root, sys.executable)
        self.assertEqual("proposal", result["readiness"])
        with patch.object(module, "verify_graphify", return_value=identity):
            fresh = module.setup(root, sys.executable)
        self.assertEqual("proposal", fresh["readiness"])

    def test_hook_destination_rejects_external_core_hooks_path(self):
        module = self.module()
        root = self.init_repo("setup-external-hooks")
        external = Path(self.temporary_directory.name) / "external-hooks"
        external.mkdir()
        self.git(root, "config", "core.hooksPath", str(external))

        with self.assertRaisesRegex(module.EngineeringError, "unsupported core.hooksPath"):
            module.setup(root, sys.executable)
        self.assertEqual([], list(external.iterdir()))

    def test_hook_destination_rejects_reparse_common_hooks_directory(self):
        module = self.module()
        root = self.init_repo("setup-reparse-hooks")
        common = Path(self.git(root, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = root / common
        hooks = common.resolve() / "hooks"
        real = module._is_reparse_point

        def mark_hooks(path):
            return Path(path).absolute() == hooks.absolute() or real(path)

        with (
            patch.object(module, "_is_reparse_point", side_effect=mark_hooks),
            self.assertRaisesRegex(module.EngineeringError, "reparse|boundary"),
        ):
            module.setup(root, sys.executable)

    def test_direct_hook_installer_cannot_bypass_setup_attestation(self):
        module = self.module()
        root = self.init_repo("setup-direct-hook-bypass")
        before = module._working_state_identity(root)

        with self.assertRaisesRegex(module.EngineeringError, "Direct hook mutation"):
            module.install_hooks(root, sys.executable, ENGINEERING_SCRIPT)

        self.assertEqual(before, module._working_state_identity(root))

    def test_tampered_setup_attestation_fails_closed_without_project_writes(self):
        module = self.module()
        root = self.init_repo("setup-tampered-attestation")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
        registry_path = module._attestation_path(
            module._project_controller_dir(root)
        )
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["items"][0]["claims"]["scopes"] = ["graphify_install"]
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch.object(module, "verify_graphify", return_value=identity),
            self.assertRaisesRegex(module.EngineeringError, "HMAC|attestation"),
        ):
            module.setup(root, sys.executable)
        self.assertFalse((root / "engineering.json").exists())

    def test_forged_managed_hook_markers_are_not_treated_as_installed(self):
        module = self.module()
        root = self.init_repo("setup-forged-hook")
        hooks = module._hooks_dir(root)
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "engineering-traceability-dispatcher").write_text(
            "#!/bin/sh\n# engineering-traceability-dispatcher\nexit 0\n",
            encoding="utf-8",
        )
        for event in module.HOOK_EVENTS:
            (hooks / event).write_text(
                "#!/bin/sh\n# engineering-traceability-hook\nexit 0\n",
                encoding="utf-8",
            )
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
        self.assertTrue(preview["project_plan"]["hook_installation"]["required"])
        self.assertTrue(preview["project_plan"]["hook_installation"]["existing"])

    def test_preserved_hook_mutation_after_approval_stales_setup(self):
        module = self.module()
        root = self.init_repo("setup-preserved-stale")
        hooks = module._hooks_dir(root)
        preserved = hooks / "engineering-traceability-preserved"
        preserved.mkdir(parents=True)
        hook = preserved / "pre-commit"
        hook.write_text("#!/bin/sh\nprintf first\n", encoding="utf-8")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            hook.write_text("#!/bin/sh\nprintf changed\n", encoding="utf-8")
            result = module.setup(root, sys.executable)
        self.assertEqual("proposal", result["readiness"])
        self.assertFalse((root / "engineering.json").exists())

    def assert_legacy_preserved_stales_setup(self, change):
        module = self.module()
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        root = self.init_repo(f"setup-legacy-preserved-{change}")
        legacy = module._hooks_dir(root) / "engineering-preserved"
        legacy.mkdir(parents=True)
        hook = legacy / "pre-commit"
        hook.write_text("#!/bin/sh\nprintf first\n", encoding="utf-8")
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            if change == "change":
                hook.write_text("#!/bin/sh\nprintf changed\n", encoding="utf-8")
                result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
            elif change == "add":
                (legacy / "post-merge").write_text(
                    "#!/bin/sh\nprintf added\n", encoding="utf-8"
                )
                result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
            elif change == "remove":
                hook.unlink()
                result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
            else:
                real = module._is_reparse_point

                def mark_hook(path):
                    return Path(path).absolute() == hook.absolute() or real(path)

                with (
                    patch.object(module, "_is_reparse_point", side_effect=mark_hook),
                    self.assertRaisesRegex(
                        module.EngineeringError, "link|reparse|boundary"
                    ),
                ):
                    module.setup(root, sys.executable)
        self.assertFalse((root / "engineering.json").exists())

    def test_legacy_preserved_change_stales_setup(self):
        self.assert_legacy_preserved_stales_setup("change")

    def test_legacy_preserved_addition_stales_setup(self):
        self.assert_legacy_preserved_stales_setup("add")

    def test_legacy_preserved_removal_stales_setup(self):
        self.assert_legacy_preserved_stales_setup("remove")

    def test_legacy_preserved_reparse_stales_setup(self):
        self.assert_legacy_preserved_stales_setup("reparse")

    def test_installer_rechecks_exact_hook_state_at_mutation_seam(self):
        module = self.module()
        root = self.init_repo("setup-hook-seam-race")
        hooks = module._hooks_dir(root)
        legacy = hooks / "engineering-preserved"
        legacy.mkdir(parents=True)
        preserved = legacy / "pre-commit"
        original = b"#!/bin/sh\nprintf original\n"
        preserved.write_bytes(original)
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\n# engineering-hook\n"
            'exec "$(dirname -- "$0")/engineering-dispatcher" pre-commit "$@"\n',
            encoding="utf-8",
        )
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        original_installer = module._install_hooks_authorized

        def inject_drift(project, graphify_python, script_path, approved_state):
            preserved.write_bytes(b"#!/bin/sh\nprintf raced\n")
            return original_installer(
                project, graphify_python, script_path, approved_state
            )

        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            with (
                patch.object(
                    module,
                    "_install_hooks_authorized",
                    side_effect=inject_drift,
                ),
                self.assertRaisesRegex(
                    module.EngineeringError, "hook state changed before mutation"
                ),
            ):
                module.setup(root, sys.executable)
        self.assertEqual(original, preserved.read_bytes())
        self.assertFalse((root / "engineering.json").exists())

    def test_hook_final_replace_cas_rejects_concurrent_target_change(self):
        module = self.module()
        root = self.init_repo("setup-hook-final-cas")
        hooks = module._hooks_dir(root)
        hooks.mkdir(parents=True, exist_ok=True)
        hook = hooks / "pre-commit"
        hook.write_bytes(b"#!/bin/sh\nprintf original\n")
        approved = module._hook_plan_state(root)
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        original_replace = module._replace_install_path
        injected = False

        def inject_change(
            source, target, expected_pre_state=None, *, preimage_path=None,
            expected_source_state=None, expected_target_state=None,
        ):
            nonlocal injected
            if target == hook and not injected:
                injected = True
                hook.write_bytes(b"#!/bin/sh\nprintf concurrent\n")
            return original_replace(
                source,
                target,
                expected_pre_state,
                preimage_path=preimage_path,
                expected_source_state=expected_source_state,
                expected_target_state=expected_target_state,
            )

        with (
            patch.object(module, "verify_graphify", return_value=identity),
            patch.object(module, "_replace_install_path", side_effect=inject_change),
            self.assertRaisesRegex(module.EngineeringError, "changed before publication"),
        ):
            module._install_hooks_authorized(
                root, sys.executable, ENGINEERING_SCRIPT, approved
            )
        self.assertEqual(b"#!/bin/sh\nprintf concurrent\n", hook.read_bytes())

    def test_hook_migration_uses_approved_bytes_after_source_race(self):
        module = self.module()
        root = self.init_repo("setup-hook-approved-bytes")
        hooks = module._hooks_dir(root)
        legacy = hooks / "engineering-preserved"
        legacy.mkdir(parents=True)
        source = legacy / "pre-commit"
        approved_bytes = b"#!/bin/sh\nprintf approved\n"
        source.write_bytes(approved_bytes)
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\n# engineering-hook\n"
            'exec "$(dirname -- "$0")/engineering-dispatcher" pre-commit "$@"\n',
            encoding="utf-8",
            newline="\n",
        )
        approved = module._hook_plan_state(root)
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        original_replace = module._replace_install_path
        injected = False

        def inject_change(
            stage, target, expected_pre_state=None, *, preimage_path=None,
            expected_source_state=None, expected_target_state=None,
        ):
            nonlocal injected
            if not injected:
                injected = True
                source.write_bytes(b"#!/bin/sh\nprintf raced\n")
            return original_replace(
                stage,
                target,
                expected_pre_state,
                preimage_path=preimage_path,
                expected_source_state=expected_source_state,
                expected_target_state=expected_target_state,
            )

        with (
            patch.object(module, "verify_graphify", return_value=identity),
            patch.object(module, "_replace_install_path", side_effect=inject_change),
        ):
            module._install_hooks_authorized(
                root, sys.executable, ENGINEERING_SCRIPT, approved
            )
        self.assertEqual(
            approved_bytes,
            (hooks / module.PRESERVED_HOOK_DIRECTORY / "pre-commit").read_bytes(),
        )

    def test_project_document_final_replace_cas_rejects_concurrent_change(self):
        module = self.module()
        root = self.init_repo("setup-document-final-cas")
        target = root / "AGENTS.md"
        target.write_text("original\n", encoding="utf-8")
        expected = module._project_document_state(root, target)
        original_replace = module._replace_install_path
        injected = False

        def inject_change(
            source, destination, expected_pre_state=None, *, preimage_path=None,
            expected_source_state=None, expected_target_state=None,
        ):
            nonlocal injected
            if destination == target and not injected:
                injected = True
                target.write_text("concurrent\n", encoding="utf-8")
            return original_replace(
                source,
                destination,
                expected_pre_state,
                preimage_path=preimage_path,
                expected_source_state=expected_source_state,
                expected_target_state=expected_target_state,
            )

        with (
            patch.object(module, "_replace_install_path", side_effect=inject_change),
            self.assertRaisesRegex(module.EngineeringError, "changed before publication"),
        ):
            module._transactional_project_documents(
                root, [(target, b"managed\n")], {"AGENTS.md": expected}
            )
        self.assertEqual("concurrent\n", target.read_text(encoding="utf-8"))

    def test_post_publication_verification_failure_preserves_concurrent_substitution(self):
        module = self.module()
        root = self.init_repo("setup-post-publication-rollback")
        target = root / "managed-hook"
        original = b"#!/bin/sh\nprintf original\n"
        target.write_bytes(original)
        expected = module._project_document_state(root, target)
        stage = root / "managed-hook.stage"
        stage.write_bytes(b"#!/bin/sh\nprintf managed\n")

        def fail_verification():
            target.write_bytes(b"#!/bin/sh\nprintf tampered\n")
            raise module.EngineeringError("synthetic post-publication mismatch")

        with self.assertRaisesRegex(module.EngineeringError, "target changed"):
            module._transactional_replace(
                [(stage, target)],
                "post-publication-test",
                {target: expected},
                after_publication=fail_verification,
            )
        self.assertEqual(b"#!/bin/sh\nprintf tampered\n", target.read_bytes())
        backup = target.with_name(".managed-hook.backup-post-publication-test")
        self.assertEqual(original, backup.read_bytes())

    def test_project_document_cas_preserves_concurrent_instruction_change(self):
        module = self.module()
        root = self.init_repo("setup-project-document-race")
        instruction = root / "AGENTS.md"
        instruction.write_text("original instruction\n", encoding="utf-8")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        original_publication = module._transactional_project_documents

        def inject_change(project, documents, expected_pre_states):
            instruction.write_text("concurrent instruction\n", encoding="utf-8")
            return original_publication(project, documents, expected_pre_states)

        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            hook_state = module._hook_plan_state(root)
            with (
                patch.object(
                    module,
                    "_transactional_project_documents",
                    side_effect=inject_change,
                ),
                self.assertRaisesRegex(
                    module.EngineeringError,
                    "project document changed before staging",
                ),
            ):
                module.setup(root, sys.executable)
        self.assertEqual("concurrent instruction\n", instruction.read_text())
        self.assertEqual(hook_state, module._hook_plan_state(root))
        self.assertFalse((root / "engineering.json").exists())
        self.assertFalse((root / "CLAUDE.md").exists())
        self.assertFalse((root / ".gitignore").exists())

    def test_preserved_hook_change_removal_and_addition_break_readiness(self):
        module = self.module()
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        for index, change in enumerate(("change", "remove", "add")):
            with self.subTest(change=change):
                root = self.init_repo(f"setup-preserved-readiness-{index}")
                hooks = module._hooks_dir(root)
                hooks.mkdir(parents=True, exist_ok=True)
                (hooks / "pre-commit").write_text(
                    "#!/bin/sh\nprintf original\n", encoding="utf-8"
                )
                with patch.object(module, "verify_graphify", return_value=identity):
                    preview = module.setup(root, sys.executable)
                    module.approve_setup(
                        root,
                        sys.executable,
                        preview["project_plan_digest"],
                        scopes=["project_controls"],
                    )
                    module.setup(root, sys.executable)
                    self.assertEqual(
                        "controls_written_pending_commit", module.setup(root, sys.executable)["readiness"]
                    )
                    preserved = (
                        hooks / "engineering-traceability-preserved" / "pre-commit"
                    )
                    if change == "change":
                        preserved.write_text(
                            "#!/bin/sh\nprintf changed\n", encoding="utf-8"
                        )
                    elif change == "remove":
                        preserved.unlink()
                    else:
                        (preserved.parent / "post-merge").write_text(
                            "#!/bin/sh\nprintf added\n", encoding="utf-8"
                        )
                    result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
                self.assertIn("project_controls", result["approvals_required"])

    def test_preserved_hook_symlink_poison_fails_closed(self):
        module = self.module()
        root = self.init_repo("setup-preserved-symlink")
        preserved = module._hooks_dir(root) / "engineering-traceability-preserved"
        preserved.mkdir(parents=True)
        outside = Path(self.temporary_directory.name) / "outside-hook"
        outside.write_text("#!/bin/sh\n", encoding="utf-8")
        poisoned = preserved / "pre-commit"
        try:
            poisoned.symlink_to(outside)
        except OSError:
            poisoned.write_text("#!/bin/sh\n", encoding="utf-8")
            real = module._is_reparse_point

            def mark_poison(path):
                return Path(path).absolute() == poisoned.absolute() or real(path)

            with (
                patch.object(module, "_is_reparse_point", side_effect=mark_poison),
                self.assertRaisesRegex(
                    module.EngineeringError, "link|reparse|boundary"
                ),
            ):
                module.setup(root, sys.executable)
        else:
            with self.assertRaisesRegex(
                module.EngineeringError, "link|reparse|boundary"
            ):
                module.setup(root, sys.executable)

    def test_setup_rejects_reparse_instruction_before_reading_external_content(self):
        module = self.module()
        root = self.init_repo("setup-instruction-reparse")
        instruction = root / "AGENTS.md"
        secret = "external-content-must-not-be-read"
        instruction.write_text(secret, encoding="utf-8")
        before = module._working_state_identity(root)
        real_reparse = module._is_reparse_point
        real_managed_instruction = module._managed_instruction_text

        def mark_instruction(path):
            return Path(path).name == "AGENTS.md" or real_reparse(path)

        def reject_instruction_read(path):
            if Path(path).absolute() == instruction.absolute():
                raise AssertionError("unsafe instruction content was read")
            return real_managed_instruction(path)

        with (
            patch.object(module, "_is_reparse_point", side_effect=mark_instruction),
            patch.object(
                module,
                "_managed_instruction_text",
                side_effect=reject_instruction_read,
            ),
            self.assertRaisesRegex(module.EngineeringError, "reparse|boundary") as error,
        ):
            module.setup(root, sys.executable)
        self.assertNotIn(secret, str(error.exception))
        self.assertEqual(before, module._working_state_identity(root))

    def test_setup_rejects_every_noncanonical_managed_marker_shape(self):
        module = self.module()
        shapes = (
            "<!-- engineering-managed-end -->\n<!-- engineering-managed-start -->\n",
            "<!-- engineering-managed-start -->\nx\n<!-- engineering-managed-end -->\n<!-- engineering-managed-start -->\n",
            "stray <!-- engineering-managed-end -->\n",
        )
        for index, content in enumerate(shapes):
            with self.subTest(index=index):
                root = self.init_repo(f"setup-marker-shape-{index}")
                (root / "AGENTS.md").write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(module.EngineeringError, "block is malformed"):
                    module.setup(root, sys.executable)

    def test_governed_graphify_plan_binds_exact_external_interpreter(self):
        module = self.module()
        root = self.init_repo("setup-interpreter-plan")
        missing = module.EngineeringError("Graphify is missing")
        with patch.object(module, "verify_graphify", side_effect=missing):
            preview = module.setup(root, sys.executable)
            internal, _ = module._setup_preview(root, sys.executable)
        interpreter = internal["graphify"]["interpreter"]
        self.assertEqual(str(Path(sys.executable).resolve()), interpreter["path"])
        self.assertRegex(interpreter["sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            [
                str(Path(sys.executable).resolve()),
                "-m",
                "pip",
                "install",
                "git+https://github.com/safishamsi/graphify.git"
                "@d89ec68af95e0cad801b56d88df383991e659823",
            ],
            internal["graphify"]["install_argv"],
        )
        self.assertNotIn("interpreter", preview["graphify"])
        self.assertEqual(interpreter["sha256"], preview["graphify"]["interpreter_sha256"])

    def test_legacy_mutation_commands_are_read_only_setup_forwarders(self):
        module = self.module()
        root = self.init_repo("setup-legacy-forwarders")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        before = module._working_state_identity(root)
        with patch.object(module, "verify_graphify", return_value=identity):
            for command in ("bootstrap", "reconstruct", "install-hooks"):
                result = module.legacy_setup_forwarder(root, sys.executable, command)
                self.assertEqual("proposal", result["readiness"])
        self.assertEqual(before, module._working_state_identity(root))

    def test_successful_installer_with_failed_verification_reports_external_change(self):
        module = self.module()
        root = self.init_repo("setup-external-unverified")
        missing = module.EngineeringError("Graphify is missing")
        with patch.object(module, "verify_graphify", side_effect=missing):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                graphify_plan_digest=preview["graphify_plan_digest"],
                scopes=["project_controls", "graphify_install"],
            )
        with (
            patch.object(module, "verify_graphify", side_effect=missing),
            patch.object(module, "_run_governed_graphify_install"),
            self.assertRaisesRegex(
                module.EngineeringError,
                "external_change_unverified.*no project setup",
            ),
        ):
            module.setup(root, sys.executable)
        self.assertFalse((root / "engineering.json").exists())

    def test_skill_explains_quarantine_promotion_and_dual_agent_install(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())

        self.assertIn("project-local", text)
        self.assertIn("second project", text)
        self.assertIn("explicit approval", text)
        self.assertIn("~/.agents/skills/engineering/", text)
        self.assertIn("Codex and Claude", text)
        self.assertIn("known-good rollback", text)
        self.assertIn("Promote means apply", text)
        self.assertIn("never rewrites itself", text)

    def test_learning_practice_contract(self):
        module = self.module()
        practice = {
            "schema": "engineering.practice.v1",
            "title": "Verify generated output before replacing a canonical checkpoint",
            "instruction": "Publish generated output only after identity and integrity checks pass.",
            "applies_to": ["completion", "maintenance"],
            "verification": "A failed rebuild retains the prior valid checkpoint.",
            "sanitized": True,
        }

        normalized = module._validate_practice(practice)
        self.assertEqual(practice, normalized)
        self.assertEqual(module._practice_digest(practice), module._practice_digest(dict(practice)))

        invalid = [
            {**practice, "extra": True},
            {**practice, "sanitized": False},
            {**practice, "applies_to": ["unknown"]},
            {**practice, "instruction": "Run curl https://example.invalid/install"},
            {**practice, "instruction": "Use C:\\Users\\someone\\private.txt"},
            {**practice, "title": "x" * 121},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(module.EngineeringError):
                module._validate_practice(payload)

    def test_learning_candidate_projection_is_bounded_and_private(self):
        module = self.module()
        practice = module._validate_practice(
            {
                "schema": "engineering.practice.v1",
                "title": "Retain the prior checkpoint when rebuilding fails",
                "instruction": "Publish a replacement only after integrity checks pass.",
                "applies_to": ["completion", "maintenance"],
                "verification": "A failed rebuild leaves the prior checkpoint readable.",
                "sanitized": True,
            }
        )
        candidate = {
            "id": "candidate-" + "a" * 12,
            "kind": "reusable_pattern",
            "state": "proposed",
            "practice": practice,
            "project_digest": "sha256:" + "1" * 64,
            "source_reference": "completion:run-a1b2c3",
            "source_digest": "sha256:" + "2" * 64,
        }

        projection = module._learning_candidate_projection(candidate)

        self.assertEqual(
            {
                "candidate_id": candidate["id"],
                "title": practice["title"],
                "kind": "reusable_pattern",
                "modules": ["completion", "maintenance"],
                "state": "proposed",
                "actions": ["keep", "inspect", "dismiss"],
            },
            projection,
        )
        self.assertNotIn("project_digest", projection)
        self.assertNotIn("source_reference", projection)

    def test_practice_candidate_is_retained_and_duplicate_suppressed(self):
        module = self.module()
        root, completion = self.terminal_completion("practice-candidate")
        practice = {
            "schema": "engineering.practice.v1",
            "title": "Retain a prior checkpoint after failed generation",
            "instruction": "Publish a replacement only after integrity checks pass.",
            "applies_to": ["completion", "maintenance"],
            "verification": "A failed rebuild leaves the prior checkpoint readable.",
            "sanitized": True,
        }

        first = module.propose_learning(
            root, completion["run_id"], "reusable_pattern", practice
        )
        second = module.propose_learning(
            root, completion["run_id"], "reusable_pattern", dict(practice)
        )

        self.assertEqual(first, second)
        self.assertEqual(module._practice_digest(practice), first["practice_digest"])
        self.assertEqual(practice, first["practice"])

    def test_promote_means_apply_and_disable_preserves_history(self):
        module = self.module()
        self.assertTrue(hasattr(module, "promote_and_apply"))
        self.assertTrue(hasattr(module, "disable_applied_practice"))
        source_root, source_completion = self.terminal_completion("applied-source")
        practice = {
            "schema": "engineering.practice.v1",
            "title": "Retain a prior checkpoint after failed generation",
            "instruction": "Publish a replacement only after integrity checks pass.",
            "applies_to": ["completion", "maintenance"],
            "verification": "A failed rebuild leaves the prior checkpoint readable.",
            "sanitized": True,
        }
        candidate = module.propose_learning(
            source_root,
            source_completion["run_id"],
            "reusable_pattern",
            practice,
        )
        second_root, second_completion = self.terminal_completion("applied-second")
        evaluation = module.evaluate_learning(
            candidate["id"], second_root, second_completion["run_id"]
        )

        local = module.common_graph_dir(source_root) / "contributions" / f"{candidate['id']}.json"
        transaction_paths = (
            module._contribution_queue_path(),
            local,
            module._promotion_attestation_path(),
            module._applied_practices_path(),
        )
        before = self.byte_snapshot(*transaction_paths)
        with (
            patch.object(
                module,
                "_replace_install_path",
                side_effect=self.fail_once_on_target(
                    module, module._applied_practices_path()
                ),
            ),
            self.assertRaisesRegex(OSError, "transactional publication"),
        ):
            module.promote_and_apply(
                candidate["id"], [evaluation["id"]], approved=True
            )
        self.assertEqual(before, self.byte_snapshot(*transaction_paths))

        applied = module.promote_and_apply(
            candidate["id"], [evaluation["id"]], approved=True
        )

        self.assertEqual("promoted_applied", applied["state"])
        ledger = module._load_applied_practices()
        self.assertEqual(1, len(ledger["items"]))
        self.assertEqual("active", ledger["items"][0]["state"])
        self.assertEqual(candidate["id"], ledger["items"][0]["candidate_id"])

        disabled = module.disable_applied_practice(candidate["id"], approved=True)
        self.assertEqual("disabled", disabled["state"])
        self.assertEqual("promoted_applied", module._candidate(module._load_contribution_queue(), candidate["id"])["state"])

    def test_applied_ledger_rejects_tamper_and_bounds(self):
        module = self.module()
        controller = module._promotion_controller_dir()
        controller.mkdir(parents=True)
        key = b"k" * 32
        module._controller_key_path(controller).write_text(key.hex() + "\n", encoding="ascii")
        practice = module._validate_practice(
            {
                "schema": "engineering.practice.v1",
                "title": "Retain a prior checkpoint after failed generation",
                "instruction": "Publish a replacement only after integrity checks pass.",
                "applies_to": ["completion", "maintenance"],
                "verification": "A failed rebuild leaves the prior checkpoint readable.",
                "sanitized": True,
            }
        )

        def entry(number):
            item = {
                "candidate_id": f"candidate-{number:012x}",
                "practice_digest": module._practice_digest(practice),
                "practice": practice,
                "state": "active",
                "skill_version": module._skill_version(),
                "disabled_reason": None,
            }
            item["signature"] = module._applied_practice_signature(key, item)
            return item

        ledger = {"schema": "engineering.applied-practices.v1", "items": [entry(1)]}
        module._applied_practices_path().write_text(
            json.dumps(ledger, indent=2) + "\n", encoding="utf-8"
        )
        self.assertEqual(ledger, module._load_applied_practices())

        ledger["items"][0]["practice"]["title"] = "Tampered"
        module._applied_practices_path().write_text(
            json.dumps(ledger, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(module.EngineeringError, "ledger"):
            module._load_applied_practices()

        too_many = {
            "schema": "engineering.applied-practices.v1",
            "items": [entry(number) for number in range(1, 130)],
        }
        with self.assertRaisesRegex(module.EngineeringError, "active limit"):
            module._validate_applied_ledger(too_many, key)
        with (
            patch.object(module, "MAX_APPLIED_LEDGER_BYTES", 64),
            self.assertRaisesRegex(module.EngineeringError, "size limit"),
        ):
            module._validate_applied_ledger(
                {"schema": "engineering.applied-practices.v1", "items": [entry(2)]},
                key,
            )

    def test_applied_practice_relevance_and_skill_immutability(self):
        module = self.module()
        controller = module._promotion_controller_dir()
        controller.mkdir(parents=True)
        key = b"p" * 32
        module._controller_key_path(controller).write_text(key.hex() + "\n", encoding="ascii")
        practice = module._validate_practice(
            {
                "schema": "engineering.practice.v1",
                "title": "Retain a prior checkpoint after failed generation",
                "instruction": "Publish a replacement only after integrity checks pass.",
                "applies_to": ["completion", "maintenance"],
                "verification": "A failed rebuild leaves the prior checkpoint readable.",
                "sanitized": True,
            }
        )
        item = {
            "candidate_id": "candidate-" + "b" * 12,
            "practice_digest": module._practice_digest(practice),
            "practice": practice,
            "state": "active",
            "skill_version": module._skill_version(),
            "disabled_reason": None,
        }
        item["signature"] = module._applied_practice_signature(key, item)
        module._applied_practices_path().write_text(
            json.dumps(
                {"schema": "engineering.applied-practices.v1", "items": [item]},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        before = module._tree_digest(SKILL_DIR)

        selected = module.applicable_practices(
            "completion", manifest_version=module._skill_version()
        )

        self.assertEqual(1, len(selected))
        self.assertEqual(practice["instruction"], selected[0]["instruction"])
        self.assertEqual([], module.applicable_practices("setup", manifest_version=module._skill_version()))
        self.assertEqual(before, module._tree_digest(SKILL_DIR))
        preparation = {
            "run_id": "run-a1b2c3",
            "project": {"root_digest": "sha256:" + "1" * 64},
            "intent": "verify",
            "authorization": {"scope": []},
            "autonomy": "collaborative",
            "context": [],
            "impact": [],
            "completion_applied_practices": selected,
            "completion_practice_status": {"status": "active", "count": 1},
        }
        completion = module._completion_payload(
            preparation,
            [],
            {"commit": "a" * 40, "dirty_tree_digest": None},
            {"commit": "a" * 40, "ready": True},
            False,
            [],
            [],
        )
        self.assertEqual(selected, completion["applied_practices"])
        self.assertEqual({"status": "active", "count": 1}, completion["practice_status"])
        with self.assertRaisesRegex(module.EngineeringError, "version"):
            module.applicable_practices("completion", manifest_version="3.0.0")

    def test_learning_cli_binds_exact_combined_confirmation(self):
        module = self.module()
        candidate_id = "candidate-" + "c" * 12
        evaluation_id = "evaluation-" + "d" * 12
        output = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "engineering",
                    "learning-promote-apply",
                    candidate_id,
                    "--evaluation-id",
                    evaluation_id,
                    "--confirm",
                    f"Promote and apply {candidate_id}",
                ],
            ),
            patch.object(
                module,
                "promote_and_apply",
                return_value={"state": "promoted_applied"},
            ) as promote,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())

        promote.assert_called_once_with(candidate_id, [evaluation_id], True)
        self.assertEqual({"state": "promoted_applied"}, json.loads(output.getvalue()))

    def test_source_improvement_is_proposal_only(self):
        module = self.module()
        practice = module._validate_practice(
            {
                "schema": "engineering.practice.v1",
                "title": "Retain a prior checkpoint after failed generation",
                "instruction": "Publish a replacement only after integrity checks pass.",
                "applies_to": ["completion", "maintenance"],
                "verification": "A failed rebuild leaves the prior checkpoint readable.",
                "sanitized": True,
            }
        )
        candidate = {
            "id": "candidate-" + "e" * 12,
            "state": "promoted_applied",
            "practice": practice,
            "practice_digest": module._practice_digest(practice),
            "source_digest": "sha256:" + "1" * 64,
            "evidence": [{"source_digest": "sha256:" + "2" * 64}],
        }
        with (
            patch.object(
                module,
                "_load_contribution_queue",
                return_value={"schema": "engineering.contribution-queue.v1", "items": [candidate]},
            ),
            patch.object(module, "_require_promotion_attestation"),
        ):
            proposal = module.source_improvement_proposal(candidate["id"])

        self.assertEqual("engineering.source-improvement-proposal.v1", proposal["schema"])
        self.assertEqual(candidate["practice_digest"], proposal["practice_digest"])
        self.assertEqual(2, len(proposal["evidence_digests"]))
        self.assertNotIn("diff", proposal)
        self.assertNotIn("patch", proposal)
        self.assertNotIn("command", proposal)


    def test_retrospective_is_read_only_and_returns_declared_evidence_findings(self):
        module = self.module()
        root, _ = self.prepared_repo("retrospective")
        before = module._working_state_identity(root)
        preview = module.retrospective_preview(root)
        self.assertTrue(preview["finite_universe"])
        self.assertEqual(0, preview["llm"]["controller_calls"])
        self.assertFalse(preview["permissions"]["project_writes"])
        with self.assertRaisesRegex(module.EngineeringError, "preview"):
            module.retrospective(root)
        result = module.retrospective(root, preview_digest=preview["preview_digest"])
        self.assertEqual("engineering.retrospective.v1", result["schema"])
        self.assertTrue(result["read_only"])
        self.assertTrue(result["finite_universe"])
        for remediation in result["remediation"]:
            self.assertIn("finding_id", remediation)
            self.assertIn("classification", remediation)
            self.assertIsInstance(remediation["evidence_refs"], list)
        self.assertEqual(before, module._working_state_identity(root))

    def test_retrospective_scope_excludes_unrelated_requirement_findings(self):
        module = self.module()
        root, _ = self.prepared_repo("retrospective-scope")
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        requirements = [node for node in checkpoint["nodes"] if node["type"] == "requirement"]
        self.assertTrue(requirements)
        selected = requirements[0]["source"]["path"]
        unrelated = {
            item["requirement"]
            for item in module.coverage(checkpoint)
            if item["requirement"] != requirements[0]["id"]
        }
        preview = module.retrospective_preview(root, scope=[selected])
        result = module.retrospective(
            root, scope=[selected], preview_digest=preview["preview_digest"]
        )
        reported = {
            item.get("requirement")
            for item in result["findings"]
            if item.get("requirement")
        }
        self.assertTrue(reported.isdisjoint(unrelated))

    def test_retrospective_scope_excludes_unrelated_decision_drift(self):
        module = self.module()
        root, _ = self.prepared_repo("retrospective-decision-scope")
        config = module.load_project_config(root)
        links_path = root / module._project_paths(root)[1]
        scope = [config["inputs"][0]]
        with patch.object(module, "_ledger_decisions", return_value={"OTHER-DEC-1": 1}):
            preview = module.retrospective_preview(root, scope=scope)
            result = module.retrospective(
                root, scope=scope, preview_digest=preview["preview_digest"]
            )
        self.assertFalse(
            any("decision" in item for item in result["findings"]),
            (links_path, result),
        )

    def test_retrospective_scope_includes_declared_node_source(self):
        module = self.module()
        root, _ = self.prepared_repo("retrospective-declared-source")
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        selected = next(
            node["source"]["path"]
            for node in checkpoint["nodes"]
            if node["type"] == "requirement"
        )
        preview = module.retrospective_preview(root, scope=[selected])
        result = module.retrospective(
            root, scope=[selected], preview_digest=preview["preview_digest"]
        )
        self.assertEqual([selected], result["finite_universe"])
        self.assertTrue(any(item["type"] == "requirement" for item in result["inventory"]))

    def test_retrospective_preview_includes_matrix_impacted_through_node_source(self):
        module = self.module()
        root, _ = self.prepared_repo("retrospective-matrix-preview")
        manifest = module.load_project_config(root)
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        referenced = next(
            node for node in checkpoint["nodes"] if node["type"] == "code_symbol"
        )
        test_id = next(node["id"] for node in checkpoint["nodes"] if node["type"] == "test")
        matrix = {
            "source": manifest["inputs"][0],
            "items": [{
                "id": "matrix-item",
                "owner": "owner",
                "implementation": referenced["id"],
                "positive": test_id,
                "negative": test_id,
            }],
        }
        manifest["semantic_matrices"] = [matrix]
        with patch.object(
            module, "_json_at", side_effect=[manifest, {"nodes": checkpoint["nodes"]}]
        ):
            preview = module.retrospective_preview(
                root, scope=[referenced["source"]["path"]]
            )
        self.assertEqual(matrix["source"], preview["semantic_matrices"][0]["source"])

    def test_retrospective_inventory_classifies_only_declared_evidence(self):
        module = self.module()
        nodes = [
            {
                "id": "CONTRACT-1",
                "type": "contract",
                "source": {"path": "design.md", "line": 1},
                "retrospective_state": "contradictory",
            },
            {
                "id": "REQ-1",
                "type": "requirement",
                "source": {"path": "design.md", "line": 2},
            },
            {
                "id": "CODE-1",
                "type": "code_symbol",
                "source": {"path": "src/app.py", "line": 1},
            },
            {
                "id": "OUTSIDE",
                "type": "contract",
                "source": {"path": "other.md", "line": 1},
            },
            {
                "id": "ROUTE-1",
                "type": "route",
                "source": {"path": "routes.md", "line": 1},
                "retrospective_state": "stale",
            },
            {
                "id": "SCHEMA-1",
                "type": "schema",
                "source": {"path": "schemas.md", "line": 1},
            },
        ]
        checkpoint = {
            "nodes": nodes,
            "edges": [
                {
                    "id": "EDGE-1",
                    "from": "REQ-1",
                    "to": "CODE-1",
                    "provenance": "missing",
                }
            ],
        }
        inventory = module._retrospective_inventory(
            {"baseline": {"accepted": True}},
            checkpoint,
            {"design.md", "src/app.py", "routes.md", "schemas.md"},
        )
        self.assertEqual(
            {
                "CONTRACT-1": "contradictory",
                "REQ-1": "missing",
                "CODE-1": "missing",
                "ROUTE-1": "stale",
                "SCHEMA-1": "orphaned",
            },
            {item["id"]: item["classification"] for item in inventory},
        )

    def test_retrospective_unmanaged_project_is_advisory_without_writes(self):
        module = self.module()
        root = self.init_repo("retrospective-unmanaged")
        before = module._working_state_identity(root)
        preview = module.retrospective_preview(root)
        result = module.retrospective(root, preview_digest=preview.get("preview_digest"))
        self.assertEqual("advisory", result["state"])
        self.assertEqual("manifest_not_tracked", result["findings"][0]["reason"])
        self.assertEqual(before, module._working_state_identity(root))


class DeliveryEvaluationContractTests(unittest.TestCase):
    init_repo = Task2ContractTests.init_repo

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.home = Path(self.temporary_directory.name) / "home"
        self.home.mkdir()
        self.environment = patch.dict(
            os.environ, {"ENGINEERING_USER_HOME": str(self.home)}, clear=False
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.private_files = patch.object(
            engineering, "_enforce_owner_private", side_effect=synthetic_owner_private
        )
        self.private_files.start()
        self.addCleanup(self.private_files.stop)
        self.private_verifier = patch.object(
            engineering, "_verify_owner_private", return_value=None
        )
        self.verify_private = self.private_verifier.start()
        self.addCleanup(self.private_verifier.stop)

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def evaluation_input(self, **changes):
        value = {
            "task_id": "task-controller",
            "dod_id": "dod-controller",
            "artifact_digest": "sha256:ddb48e5b1d320ff88ac89675b60f8b5f61fb64881c7e8b247efbaff3c87bf075",
            "verdict": "accepted_exact_artifact",
            "trigger": "completion",
            "model": {"requested": "requested-model", "actual": "actual-model", "fallback": None},
            "routing": {
                "reasoning": {"state": "unknown"},
                "owner_override": {"state": "unknown"},
                "execution_target": {"state": "unknown"},
                "scope": {"state": "unknown"},
            },
            "lanes": {"dependencies": 2, "parallelism": 3},
            "terminal": {
                "artifact_identity": "sha256:ddb48e5b1d320ff88ac89675b60f8b5f61fb64881c7e8b247efbaff3c87bf075",
                "acceptance_state": "accepted_exact_artifact",
                "current_gate": "release_gate",
                "next_action": "awaiting_approval",
                "reconciliation_digest": "sha256:" + "1" * 64,
            },
            "acceptance": {
                "technical": "passed",
                "domain": "passed",
                "outcome": "passed",
                "operating_interface": "cli",
                "operating_environment": "local",
                "representative_data": "verified",
                "outcome_evidence_digest": "sha256:" + "c" * 64,
                "representative_data_evidence_digest": "sha256:" + "d" * 64,
                "gate": "accepted",
            },
            "proxy_pass_outcome_fail": 0,
            "audit_false_positive": 0,
            "unconsumed_terminal_event": 0,
            "duration_seconds": 30,
            "critical_path_seconds": 20,
            "coordination_cost_seconds": 5,
            "terminal_to_reconciliation_seconds": 2,
            "feedback_iterations": 1,
            "invalidated_evidence": 0,
            "auditor_coverage": {"planned": 2, "completed": 2},
            "rework": 1,
            "escaped_defects": 0,
            "false_blockers": 0,
            "missed_escalations": 0,
            "unnecessary_orchestrator_intervention": 0,
            "non_applicable": {"model.fallback": "no_fallback_used"},
        }
        value.update(changes)
        return value

    def record(
        self,
        root,
        completion_id,
        value,
        *,
        digest="sha256:" + "1" * 64,
        bind_terminal=True,
    ):
        module = self.module()
        completion = {
            "changed_artifacts": ["README.md"],
            "result_identity": {"commit": "1" * 40, "dirty_tree_digest": None},
            "checks": [
                {"output_digest": "sha256:" + "c" * 64},
                {"output_digest": "sha256:" + "d" * 64},
            ],
        }
        if bind_terminal:
            value = {
                **value,
                "terminal": {
                    **value["terminal"],
                    "reconciliation_digest": digest,
                },
            }
        with (
            patch.object(module, "_terminal_completion", return_value=(completion, digest)),
            patch.object(module, "_project_contribution_digest", return_value="sha256:" + "2" * 64),
        ):
            return module.record_delivery_evaluation(root, completion_id, value)

    def test_delivery_evaluation_rejects_unbounded_or_private_input(self):
        root = self.init_repo("delivery-validation")
        cases = (
            self.evaluation_input(raw_source="private source body"),
            self.evaluation_input(trigger="x" * 65),
            self.evaluation_input(task_id="x" * 65),
            self.evaluation_input(model={"actual": "password=secret", "fallback": None}),
            self.evaluation_input(terminal={"artifact_identity": "sha256:" + "0" * 64}),
            self.evaluation_input(artifact_digest="sha256:" + "0" * 64),
            self.evaluation_input(duration_seconds=None, non_applicable={"model.fallback": "no_fallback_used"}),
        )

        for value in cases:
            with self.subTest(value=value):
                with self.assertRaisesRegex(self.module().EngineeringError, "delivery evaluation"):
                    self.record(root, "run-a1b2c3", value)

    def test_delivery_evaluation_requires_typed_provider_neutral_routing_disclosure(self):
        """New records disclose routing facts or typed Unknown without provider guessing."""
        module = self.module()
        root = self.init_repo("delivery-routing")
        missing = self.evaluation_input()
        missing.pop("routing", None)
        with self.assertRaisesRegex(module.EngineeringError, "routing"):
            self.record(root, "run-a1b2c3", missing)

        unknown = self.evaluation_input(
            routing={
                "reasoning": {"state": "unknown"},
                "owner_override": {"state": "unknown"},
                "execution_target": {"state": "unknown"},
                "scope": {"state": "unknown"},
            }
        )
        recorded = self.record(root, "run-b2c3d4", unknown, digest="sha256:" + "2" * 64)
        self.assertEqual("unknown", recorded["input"]["routing"]["reasoning"]["state"])

        private = self.evaluation_input(
            routing={
                "reasoning": {"state": "recorded", "value": "password=secret"},
                "owner_override": {"state": "unknown"},
                "execution_target": {"state": "unknown"},
                "scope": {"state": "unknown"},
            }
        )
        with self.assertRaisesRegex(module.EngineeringError, "routing"):
            self.record(root, "run-c3d4e5", private, digest="sha256:" + "3" * 64)

        legacy = self.evaluation_input()
        legacy.pop("routing", None)
        self.assertEqual(
            legacy,
            module._validate_delivery_evaluation(
                legacy,
                allow_legacy_terminal=True,
                allow_legacy_routing=True,
            ),
        )

    def test_delivery_evaluation_tracks_reconciled_terminal_event(self):
        root = self.init_repo("delivery-terminal")
        record = self.record(root, "run-a1b2c3", self.evaluation_input())

        self.assertEqual("requested-model", record["input"]["model"]["requested"])
        self.assertEqual(record["input"]["artifact_digest"], record["input"]["terminal"]["artifact_identity"])
        self.assertEqual("accepted_exact_artifact", record["input"]["terminal"]["acceptance_state"])
        self.assertEqual("release_gate", record["input"]["terminal"]["current_gate"])
        self.assertEqual("awaiting_approval", record["input"]["terminal"]["next_action"])
        self.assertEqual(0, record["input"]["unconsumed_terminal_event"])
        self.assertEqual(2, record["input"]["terminal_to_reconciliation_seconds"])

    def test_delivery_evaluation_rejects_unbound_terminal_or_outcome_evidence(self):
        module = self.module()
        root = self.init_repo("delivery-bound-evidence")

        with self.assertRaisesRegex(module.EngineeringError, "terminal evidence"):
            self.record(
                root,
                "run-a1b2c3",
                self.evaluation_input(),
                digest="sha256:" + "2" * 64,
                bind_terminal=False,
            )

        value = self.evaluation_input()
        value["acceptance"] = {
            **value["acceptance"],
            "outcome_evidence_digest": "sha256:" + "a" * 64,
        }
        with self.assertRaisesRegex(module.EngineeringError, "acceptance evidence"):
            self.record(root, "run-b2c3d4", value, digest="sha256:" + "2" * 64)

        for field in ("outcome_evidence_digest", "representative_data_evidence_digest"):
            with self.subTest(field=field):
                value = self.evaluation_input()
                value["acceptance"] = {
                    **value["acceptance"],
                    field: "sha256:" + "1" * 64,
                }
                with self.assertRaisesRegex(module.EngineeringError, "acceptance evidence"):
                    self.record(
                        root,
                        "run-c3d4e5" if field.startswith("outcome") else "run-d4e5f6",
                        value,
                        digest="sha256:" + "1" * 64,
                    )

    def test_delivery_evaluation_keeps_outcome_acceptance_distinct_from_proxy_checks(self):
        module = self.module()
        root = self.init_repo("delivery-outcome")
        failed_outcome = self.record(
            root,
            "run-a1b2c3",
            self.evaluation_input(
                acceptance={
                    "technical": "passed",
                    "domain": "passed",
                    "outcome": "failed",
                    "operating_interface": "cli",
                    "operating_environment": "local",
                    "representative_data": "verified",
                    "outcome_evidence_digest": "sha256:" + "c" * 64,
                    "representative_data_evidence_digest": "sha256:" + "d" * 64,
                    "gate": "failed",
                },
                proxy_pass_outcome_fail=1,
                audit_false_positive=1,
            ),
        )
        unknown_outcome = self.record(
            root,
            "run-b2c3d4",
            self.evaluation_input(
                acceptance={
                    "technical": "passed",
                    "domain": "passed",
                    "outcome": "unknown",
                    "operating_interface": "cli",
                    "operating_environment": "local",
                    "representative_data": "missing",
                    "outcome_evidence_digest": None,
                    "representative_data_evidence_digest": None,
                    "gate": "failed",
                },
                proxy_pass_outcome_fail=0,
                audit_false_positive=0,
            ),
            digest="sha256:" + "3" * 64,
        )

        self.assertEqual("failed", failed_outcome["input"]["acceptance"]["gate"])
        self.assertEqual("unknown", unknown_outcome["input"]["acceptance"]["outcome"])
        trends = module.delivery_trends(window=2)
        self.assertEqual(1, trends["metrics"]["proxy_pass_outcome_fail"]["sum"])
        self.assertEqual(0.5, trends["rates"]["audit_false_positive"])
        with self.assertRaisesRegex(module.EngineeringError, "proxy signal"):
            self.record(
                root,
                "run-c3d4e5",
                self.evaluation_input(
                    acceptance=failed_outcome["input"]["acceptance"],
                    auditor_coverage={"planned": 0, "completed": 0},
                    proxy_pass_outcome_fail=1,
                    audit_false_positive=1,
                ),
                digest="sha256:" + "4" * 64,
            )
        with self.assertRaisesRegex(module.EngineeringError, "acceptance"):
            self.record(
                root,
                "run-d4e5f6",
                self.evaluation_input(
                    acceptance={
                        **failed_outcome["input"]["acceptance"],
                        "operating_interface": "mock",
                    },
                    proxy_pass_outcome_fail=1,
                    audit_false_positive=1,
                ),
                digest="sha256:" + "5" * 64,
            )

    def test_delivery_evaluation_is_signed_replay_safe_owner_private_and_trendable(self):
        module = self.module()
        root = self.init_repo("delivery-replay")
        before = module._working_state_identity(root)
        first = self.record(root, "run-a1b2c3", self.evaluation_input())
        replay = self.record(root, "run-a1b2c3", self.evaluation_input())
        second = self.record(
            root,
            "run-d4e5f6",
            self.evaluation_input(duration_seconds=10, critical_path_seconds=8),
            digest="sha256:" + "3" * 64,
        )

        self.assertEqual(first, replay)
        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(first["signature"].startswith("hmac-sha256:"))
        self.assertEqual("accepted_exact_artifact", first["input"]["verdict"])
        self.assertEqual(before, module._working_state_identity(root))
        ledger = module._delivery_evaluation_path()
        self.assertTrue(ledger.is_file())
        self.assertNotIn(str(root), ledger.read_text(encoding="utf-8"))

        trends = module.delivery_trends(window=2)
        self.assertEqual("engineering.delivery-trends.v1", trends["schema"])
        self.assertEqual(2, trends["record_count"])
        self.assertEqual(40, trends["metrics"]["duration_seconds"]["sum"])
        self.assertEqual(1, module.delivery_trends(window=1)["record_count"])
        self.assertGreater(self.verify_private.call_count, 0)
        self.assertIn(((ledger,), {"directory": False}), self.verify_private.call_args_list)

    def test_delivery_evaluations_are_bounded_and_trends_use_latest_comparable_cohort(self):
        module = self.module()
        root = self.init_repo("delivery-cohorts")
        self.record(root, "run-a1b2c3", self.evaluation_input(duration_seconds=30))
        self.record(root, "run-b2c3d4", self.evaluation_input(duration_seconds=10, critical_path_seconds=8), digest="sha256:" + "3" * 64)
        self.record(
            root,
            "run-c3d4e5",
            self.evaluation_input(task_id="task-other", dod_id="dod-other", duration_seconds=15, critical_path_seconds=10),
            digest="sha256:" + "4" * 64,
        )

        insufficient = module.delivery_trends(window=30)
        self.assertEqual("insufficient_sample", insufficient["status"])
        self.assertEqual({"task_id": "task-other", "dod_id": "dod-other"}, insufficient["cohort"])
        self.assertEqual(1, insufficient["record_count"])

        self.record(
            root,
            "run-d4e5f6",
            self.evaluation_input(task_id="task-other", dod_id="dod-other", duration_seconds=20, critical_path_seconds=15),
            digest="sha256:" + "5" * 64,
        )
        trends = module.delivery_trends(window=30)
        self.assertEqual("ready", trends["status"])
        self.assertEqual(2, trends["record_count"])
        self.assertEqual(35, trends["metrics"]["duration_seconds"]["sum"])

        bounded_root = self.init_repo("delivery-bounds")
        bounded_home = self.home / "bounded-home"
        bounded_home.mkdir()
        with (
            patch.dict(os.environ, {"ENGINEERING_USER_HOME": str(bounded_home)}, clear=False),
            patch.object(module, "_DELIVERY_EVALUATION_MAX_ITEMS", 1),
        ):
            first = self.record(bounded_root, "run-e5f6a7", self.evaluation_input())
            second = self.record(bounded_root, "run-f6a7b8", self.evaluation_input(), digest="sha256:" + "6" * 64)
            ledger = module._load_delivery_evaluations()
        self.assertEqual([second["id"]], [item["id"] for item in ledger["items"]])
        self.assertNotEqual(first["id"], second["id"])

        sized_home = self.home / "sized-home"
        sized_home.mkdir()
        with (
            patch.dict(os.environ, {"ENGINEERING_USER_HOME": str(sized_home)}, clear=False),
            patch.object(module, "_DELIVERY_EVALUATION_MAX_BYTES", 1),
            self.assertRaisesRegex(module.EngineeringError, "bounded size"),
        ):
            self.record(self.init_repo("delivery-size"), "run-a7b8c9", self.evaluation_input())

    def test_delivery_evaluation_retention_persists_sequence_and_evicts_for_size(self):
        module = self.module()
        sequence_home = self.home / "sequence-home"
        sequence_home.mkdir()
        with patch.dict(os.environ, {"ENGINEERING_USER_HOME": str(sequence_home)}, clear=False):
            root = self.init_repo("delivery-sequence")
            first = self.record(root, "run-a1b2c3", self.evaluation_input())
            second = self.record(root, "run-b2c3d4", self.evaluation_input(), digest="sha256:" + "3" * 64)
            persisted = module._load_delivery_evaluations()
        self.assertEqual([first["id"], second["id"]], [item["id"] for item in persisted["items"]])
        self.assertEqual(1, persisted["sequences"][first["id"]])
        self.assertEqual(2, persisted["sequences"][second["id"]])

        sized_home = self.home / "size-retention-home"
        sized_home.mkdir()
        with patch.dict(os.environ, {"ENGINEERING_USER_HOME": str(sized_home)}, clear=False):
            root = self.init_repo("delivery-size-retention")
            first = self.record(root, "run-c3d4e5", self.evaluation_input())
            maximum = module._delivery_evaluation_bytes(module._load_delivery_evaluations())
            with patch.object(module, "_DELIVERY_EVALUATION_MAX_BYTES", maximum):
                second = self.record(root, "run-d4e5f6", self.evaluation_input(), digest="sha256:" + "4" * 64)
                retained = module._load_delivery_evaluations()
        self.assertEqual([second["id"]], [item["id"] for item in retained["items"]])
        self.assertNotEqual(first["id"], second["id"])
        self.assertLessEqual(module._delivery_evaluation_bytes(retained), maximum)

    def test_delivery_trends_exclude_legacy_unbound_records_from_current_cohort(self):
        module = self.module()
        legacy = self.evaluation_input()
        legacy["terminal"].pop("reconciliation_digest")
        current = self.evaluation_input(duration_seconds=10, critical_path_seconds=8)
        payload = {
            "items": [
                {"id": "delivery-eval-" + "a" * 12, "input": legacy},
                {"id": "delivery-eval-" + "b" * 12, "input": current},
            ],
            "sequences": {
                "delivery-eval-" + "a" * 12: 1,
                "delivery-eval-" + "b" * 12: 2,
            },
        }
        with patch.object(module, "_load_delivery_evaluations", return_value=payload):
            trends = module.delivery_trends(window=30)

        self.assertEqual(1, trends["legacy_record_count"])
        self.assertEqual(1, trends["record_count"])
        self.assertEqual("insufficient_sample", trends["status"])

    def test_delivery_eval_cli_accepts_only_bounded_input_file(self):
        module = self.module()
        root = self.init_repo("delivery-cli")
        output = io.StringIO()
        with (
            patch.object(module, "_terminal_completion", return_value=({
                "changed_artifacts": ["README.md"],
                "result_identity": {"commit": "1" * 40, "dirty_tree_digest": None},
                "checks": [
                    {"output_digest": "sha256:" + "c" * 64},
                    {"output_digest": "sha256:" + "d" * 64},
                ],
            }, "sha256:" + "1" * 64)),
            patch.object(module, "_project_contribution_digest", return_value="sha256:" + "2" * 64),
            patch.object(sys, "argv", [
                "engineering", "delivery-eval", str(root), "run-a1b2c3", "--input-file", "-"
            ]),
            patch.object(sys, "stdin", io.StringIO(json.dumps(self.evaluation_input()))),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())

        self.assertEqual(
            "engineering.delivery-evaluation.v1", json.loads(output.getvalue())["schema"]
        )


class CapabilityAssuranceContractTests(unittest.TestCase):
    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def test_authoritative_decision_ledger_requires_a_resolvable_overlay_node(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "docs" / "engineering"
            docs.mkdir(parents=True)
            ledger = docs / "decision-ledger.md"
            ledger.write_text("# Decisions\n\n## ENG-DEC-0001 - Adopt contract\n", encoding="utf-8")
            manifest = {"version": 2, "inputs": []}
            (root / "engineering.json").write_text(json.dumps(manifest), encoding="utf-8")
            links = {"version": 1, "nodes": [{"id": "ENG-DEC-0001", "type": "decision", "title": "Adopt contract", "source": {"path": "docs/engineering/decision-ledger.md", "line": 3}}], "edges": []}
            (docs / "links.json").write_text(json.dumps(links), encoding="utf-8")
            module._validate_overlay(root, "WORKTREE", manifest, links, "engineering.json")
            links["nodes"] = []
            with self.assertRaisesRegex(module.TraceabilityError, "decision ledger"):
                module._validate_overlay(root, "WORKTREE", manifest, links, "engineering.json")

    def test_setup_adopts_one_existing_standard_decision_ledger(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "--initial-branch=main", str(root)], check=True, capture_output=True)
            ledger = root / "docs" / "engineering" / "decision-ledger.md"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("# Existing decisions\n", encoding="utf-8")
            with patch.object(module, "default_branch", return_value="main"):
                documents = dict(module._setup_documents(root, module.GRAPHIFY_VERSION))
            config = json.loads(documents[root / "engineering.json"])
            self.assertEqual("docs/engineering/decision-ledger.md", config["decision_ledger"])
            self.assertNotIn(ledger, documents)

    def test_pre_repository_prepare_and_map_are_read_only_advisories(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "plain-folder"
            root.mkdir()
            (root / "app.py").write_text("print('local')\n", encoding="utf-8")
            for argv, expected, code in (
                (["engineering", "prepare", str(root), "change", "--scope-json", '{"scope": []}'], "advisory", 0),
                (["engineering", "map", str(root), "--no-open"], "unavailable", 0),
                (["engineering", "setup", str(root)], "proposal", 1),
            ):
                output = io.StringIO()
                with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
                    self.assertEqual(code, module.main())
                result = json.loads(output.getvalue())
                self.assertEqual(expected, result.get("readiness", result.get("status")))
            self.assertFalse((root / ".git").exists())
            self.assertFalse((root / "engineering.json").exists())

    def test_graphify_environment_excludes_provider_credentials(self):
        module = self.module()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "not-forwarded", "GRAPHIFY_OUT": "old"}, clear=False):
            environment = module._graphify_environment(output=Path("safe-output"))
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertEqual("safe-output", environment["GRAPHIFY_OUT"])

    def test_map_cache_hit_renders_without_graphify_or_browser(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            checkpoint = {
                "metadata": {"graph_digest": "g", "input_digest": "o"},
                "nodes": [{"id": "REQ-1", "type": "requirement"}],
                "edges": [],
            }
            state = Path(temporary) / "state"
            with (
                patch.object(module, "resolve_project_root", return_value=root),
                patch.object(module, "git", return_value="a" * 40),
                patch.object(module, "_load_checkpoint", return_value=checkpoint),
                patch.object(module, "_load_assurance_overlay", return_value=[]),
                patch.object(module, "_common_graph_dir", return_value=state),
                patch.object(module.subprocess, "run") as process,
            ):
                first = module.render_map(root, open_output=False)
                second = module.render_map(root, open_output=False)
            self.assertFalse(first["cached"])
            self.assertFalse(second["cached"])
            self.assertTrue(Path(second["output"]).is_file())
            process.assert_not_called()

    def assurance_manifest(self):
        return {
            "schema": "engineering.capability-assurance.v1",
            "capabilities": [
                {
                    "id": "cap-order-api",
                    "criticality": "material",
                    "required_cells": ["prod-eu"],
                    "required_interfaces": ["orders-api"],
                    "required_roles": ["service_owner"],
                }
            ],
            "cells": [{"id": "prod-eu", "production": True}],
            "obligations": [
                {
                    "id": "orders-route-observability",
                    "capability_id": "cap-order-api",
                    "kind": "route_observability",
                }
            ],
        }

    def test_assurance_reducer_keeps_unknown_and_contradiction_distinct(self):
        module = self.module()
        manifest = module.validate_assurance_manifest(self.assurance_manifest())
        unknown = module.reduce_assurance_status(
            manifest, "cap-order-api", "prod-eu", [], "2026-08-02T12:00:00Z"
        )
        self.assertEqual("unknown", unknown["summary"])
        self.assertEqual("unknown", unknown["deployment"])

        contradictory = module.reduce_assurance_status(
            manifest,
            "cap-order-api",
            "prod-eu",
            [
                {
                    "kind": "deployment",
                    "result": "passed",
                    "release": "release-1",
                    "interface": "orders-api",
                    "observed_at": "2026-08-02T11:00:00Z",
                    "valid_until": "2026-08-03T11:00:00Z",
                },
                {
                    "kind": "synthetic",
                    "result": "passed",
                    "release": "release-1",
                    "interface": "orders-api",
                    "observed_at": "2026-08-02T11:05:00Z",
                    "valid_until": "2026-08-03T11:05:00Z",
                },
                {
                    "kind": "incident",
                    "result": "failed",
                    "severity": "severe",
                    "release": "release-1",
                    "interface": "orders-api",
                    "observed_at": "2026-08-02T11:10:00Z",
                    "valid_until": "2026-08-03T11:10:00Z",
                },
            ],
            "2026-08-02T12:00:00Z",
        )
        self.assertEqual("conflicting", contradictory["confidence"])
        self.assertEqual("not_live", contradictory["summary"])

    def test_recommendations_need_declared_gap_and_neutral_remediation(self):
        module = self.module()
        manifest = module.validate_assurance_manifest(self.assurance_manifest())
        recommendation = module.assurance_recommendations(
            manifest,
            [{"kind": "missing", "obligation_id": "orders-route-observability"}],
        )
        self.assertEqual("recommendation", recommendation["status"])
        self.assertEqual("observability", recommendation["items"][0]["remediation_class"])
        self.assertEqual(
            {"status": "unknown", "items": []},
            module.assurance_recommendations(manifest, []),
        )

    def test_assurance_reaction_and_feedback_are_route_neutral_and_evidence_bound(self):
        module = self.module()
        manifest = self.assurance_manifest()
        observations = [
            {
                "kind": "deployment", "result": "passed", "release": "release-1",
                "interface": "orders-api", "observed_at": "2026-08-02T11:00:00Z",
                "valid_until": "2026-08-03T11:00:00Z",
            },
            {
                "kind": "synthetic", "result": "passed", "release": "release-1",
                "interface": "orders-api", "observed_at": "2026-08-02T11:01:00Z",
                "valid_until": "2026-08-03T11:01:00Z",
            },
        ]
        feedback = module.assurance_feedback_request(
            manifest, "cap-order-api", "prod-eu", observations, "2026-08-02T12:00:00Z"
        )
        self.assertEqual("requested", feedback["status"])
        self.assertEqual(["service_owner"], feedback["roles"])
        self.assertNotIn("recipient", feedback)
        reaction = module.assurance_reaction(feedback["capability_status"])
        self.assertEqual("await_feedback", reaction["action"])
        self.assertTrue(reaction["dedupe_key"].startswith("sha256:"))

    def test_execution_context_is_bounded_redacted_and_digest_bound(self):
        module = self.module()
        preparation = {
            "schema": "engineering.prepare.v1",
            "run_id": "run-a1b2c3",
            "project": {"root_digest": "sha256:" + "1" * 64, "commit": "a" * 40},
            "authorization": {"scope": ["src/order.py"], "forbidden": ["secrets.env"]},
            "context": [
                {"id": "REQ-1", "provenance": "direct"},
                {"id": "DEC-1", "provenance": "derived"},
                {"id": "CODE-IRRELEVANT", "provenance": "inferred"},
            ],
        }
        bundle = module.build_execution_context(
            preparation,
            assertions=[{"id": "REQ-1", "text": "Do not expose api_key=abc"}],
            forbidden_ids={"CODE-IRRELEVANT"},
        )
        self.assertEqual("engineering.execution-context.v1", bundle["schema"])
        self.assertEqual(["REQ-1", "DEC-1"], [item["id"] for item in bundle["context"]])
        self.assertNotIn("api_key=abc", json.dumps(bundle))
        self.assertEqual(
            "enforced",
            module.validate_execution_context(bundle, preparation, runner_enforces_boundary=True)["mode"],
        )
        tampered = {**bundle, "scope": ["src/order.py", "secrets.env"]}
        with self.assertRaisesRegex(module.EngineeringError, "digest|scope"):
            module.validate_execution_context(tampered, preparation, runner_enforces_boundary=True)
        self.assertEqual(
            "advisory",
            module.validate_execution_context(bundle, preparation, runner_enforces_boundary=False)["mode"],
        )

    def test_task_authority_allows_only_exact_safe_declared_checks(self):
        module = self.module()
        # This contract covers command/effect authority, not the checkout
        # hosting the test runner.  CI uses a deliberately shallow checkout.
        def claims_for(checks):
            with patch.object(
                module,
                "_project_contribution_digest",
                return_value="sha256:" + "1" * 64,
            ):
                return module._check_capability_claims(Path("."), checks)

        checks = [[sys.executable, "-m", "unittest", "--help"]]
        claims = claims_for(checks)
        authority = {
            "schema": "engineering.task-authority.v2",
            "task_id": "task-local-checks",
            "repository_id": claims["repository_id"],
            "commit": "a" * 40,
            "commands_digest": claims["commands_digest"],
            "effects": {
                "network": False,
                "connector": False,
                "publication": False,
                "deployment": False,
                "live_environment": False,
                "destructive": False,
            },
            "issued_at": "2026-08-04T10:00:00+00:00",
            "valid_until": "2026-08-04T11:00:00+00:00",
        }
        key = b"1" * 32
        authority["signature"] = module._task_authority_signature(key, authority)
        project = Mock(root=Path("."), commit="a" * 40)
        clock = Mock(wraps=module.datetime)
        clock.now.return_value = module.datetime.fromisoformat("2026-08-04T10:30:00+00:00")
        with patch.object(module, "_controller_key", return_value=key), patch.object(
            module, "resolve_project", return_value=project
        ), patch.object(module, "datetime", clock):
            accepted = module.validate_task_check_authority(Path("."), authority, claims)
        self.assertEqual("task-local-checks", accepted["task_id"])
        self.assertEqual(claims["commands_digest"], accepted["commands_digest"])
        for changed in (
            {**authority, "commands_digest": "sha256:" + "2" * 64},
            {**authority, "effects": {**authority["effects"], "network": True}},
        ):
            with self.subTest(changed=changed), patch.object(module, "_controller_key", return_value=key), patch.object(
                module, "resolve_project", return_value=project
            ), patch.object(module, "datetime", clock), self.assertRaisesRegex(
                module.EngineeringError, "authority"
            ):
                module.validate_task_check_authority(Path("."), changed, claims)
        inline = claims_for([[sys.executable, "-c", "print(1)"]])
        with patch.object(module, "resolve_project", return_value=project), patch.object(
            module, "datetime", clock
        ), self.assertRaisesRegex(module.EngineeringError, "authority"):
            module.validate_task_check_authority(
                Path("."), {**authority, "commands_digest": inline["commands_digest"]}, inline
            )
        shell = claims_for([["bash", "check.sh"]])
        with patch.object(module, "resolve_project", return_value=project), patch.object(
            module, "datetime", clock
        ), self.assertRaisesRegex(module.EngineeringError, "authority"):
            module.validate_task_check_authority(
                Path("."), {**authority, "commands_digest": shell["commands_digest"]}, shell
            )
        expired = {**authority, "valid_until": "2026-08-04T10:20:00+00:00"}
        expired["signature"] = module._task_authority_signature(key, expired)
        with patch.object(module, "resolve_project", return_value=project), patch.object(
            module, "datetime", clock
        ), self.assertRaisesRegex(module.EngineeringError, "authority"):
            module.validate_task_check_authority(Path("."), expired, claims)
        with patch.object(
            module, "resolve_project", return_value=Mock(root=Path("."), commit="b" * 40)
        ), patch.object(module, "datetime", clock), self.assertRaisesRegex(
            module.EngineeringError, "authority"
        ):
            module.validate_task_check_authority(Path("."), authority, claims)

    def test_prepare_cli_accepts_scope_file_and_stdin_without_shell_quoting(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            scope_file = Path(temporary) / "scope.json"
            scope_file.write_text('{"scope":["README.md"]}', encoding="utf-8")
            for source, input_text in ((str(scope_file), None), ("-", '{"scope":["README.md"]}')):
                with self.subTest(source=source):
                    output = io.StringIO()
                    with (
                        patch.object(sys, "argv", ["engineering", "prepare", ".", "change", "--scope-file", source]),
                        patch.object(module, "resolve_project_root", return_value=Path(".")),
                        patch.object(module, "prepare", return_value={"readiness": "ready"}) as prepare,
                        patch.object(sys, "stdin", io.StringIO(input_text or "")),
                        contextlib.redirect_stdout(output),
                    ):
                        self.assertEqual(0, module.main())
                    self.assertEqual({"scope": ["README.md"]}, prepare.call_args.args[2])
                    self.assertEqual({"readiness": "ready"}, json.loads(output.getvalue()))

    def test_expected_cli_blocker_is_stable_json_not_raw_error(self):
        module = self.module()
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", ["engineering", "status", "."]),
            patch.object(module, "resolve_project_root", side_effect=module.EngineeringError("manifest_not_tracked")),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            self.assertEqual(2, module.main())
        self.assertEqual("", errors.getvalue())
        self.assertEqual(
            {"schema": "engineering.error.v1", "status": "blocked", "reason": "manifest_not_tracked", "remediation": "authorize_engineering_setup"},
            json.loads(output.getvalue()),
        )

    def test_checkpoint_unavailable_cli_is_structured_not_a_raw_error(self):
        module = self.module()
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", ["engineering", "map", ".", "--no-open"]),
            patch.object(module, "resolve_project_root", return_value=Path(".")),
            patch.object(
                module,
                "render_map",
                side_effect=module.EngineeringError("Expected one commit-bound checkpoint for abc."),
            ),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            self.assertEqual(2, module.main())
        self.assertEqual("", errors.getvalue())
        self.assertEqual(
            "canonical_checkpoint_unavailable", json.loads(output.getvalue())["reason"]
        )

    def test_default_branch_uses_local_remote_metadata_after_direct_head(self):
        module = self.module()

        def direct_head(root, *arguments):
            if arguments[:1] == ("symbolic-ref",):
                raise module.TraceabilityError("direct ref")
            if arguments == ("remote", "show", "-n", "origin"):
                return "* remote origin\n  HEAD branch: main\n"
            if arguments == ("rev-parse", "--verify", "refs/remotes/origin/main"):
                return "a" * 40
            raise AssertionError(arguments)

        with patch.object(module, "git", side_effect=direct_head):
            self.assertEqual("main", module.default_branch(Path(".")))
        with patch.object(module, "git", side_effect=[module.TraceabilityError("direct"), "  HEAD branch: unknown\n"]):
            with self.assertRaisesRegex(module.TraceabilityError, "ambiguous"):
                module.default_branch(Path("."))

    def test_unmanaged_project_returns_no_write_advisory(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "midflight"
            subprocess.run(["git", "init", "--initial-branch=main", str(root)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "synthetic" + "@" + "example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Synthetic"], check=True)
            (root / "README.md").write_text("# Mid-flight\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "initial"], check=True, capture_output=True)

            result = module.prepare(root, "change an existing module", {"scope": ["README.md"]})

            self.assertEqual("advisory", result["readiness"])
            self.assertIsNone(result["run_id"])
            self.assertEqual("unknown", result["project"]["traceability"])
            self.assertFalse(result["completion_available"])
            self.assertFalse((root / "engineering-traceability.json").exists())
            self.assertFalse((Path(module.common_graph_dir(root)) / "runs").exists())

    def test_hook_cli_is_quiet_when_current_and_actionable_when_stale(self):
        module = self.module()
        for result, expected_stderr in (
            ({"freshness": "current"}, ""),
            ({"freshness": "stale", "reason": "checkpoint_pending"}, "checkpoint pending"),
        ):
            with self.subTest(result=result):
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    patch.object(sys, "argv", ["engineering", "hook", "post-commit", "."]),
                    patch.object(module, "resolve_project_root", return_value=Path(".")),
                    patch.object(module, "handle_hook", return_value=result),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    self.assertEqual(0, module.main())
                self.assertEqual("", stdout.getvalue())
                self.assertIn(expected_stderr, stderr.getvalue())

    def test_controller_resolver_uses_the_installed_portable_launcher(self):
        module = self.module()
        argv = module.controller_argv()
        self.assertEqual(1, len(argv))
        self.assertEqual(
            ENGINEERING_SCRIPT.with_name("engineering.cmd" if os.name == "nt" else "engineering").resolve(),
            Path(argv[0]),
        )

    def test_initial_checkpoint_recovery_is_bounded_and_non_project_mutating(self):
        module = self.module()
        project = module.ProjectIdentity(Path("."), Path("."), "main", "a" * 40, "main")
        with patch.object(module, "bootstrap_graph", return_value={
            "state": "current", "checkpoint": "local-checkpoint"
        }) as bootstrap:
            recovered = module._recover_initial_checkpoint(project)
        self.assertEqual({"recovered": True, "checkpoint": "local-checkpoint"}, recovered)
        self.assertEqual(project.root, bootstrap.call_args.args[0])
        self.assertTrue(bootstrap.call_args.kwargs["setup_authorized"])
        self.assertEqual(
            module.DEFAULT_INITIAL_CHECKPOINT_RECOVERY_SECONDS,
            bootstrap.call_args.kwargs["recovery_timeout_seconds"],
        )

    def test_feature_recovery_builds_canonical_before_an_isolated_feature_delta(self):
        module = self.module()
        project = module.ProjectIdentity(Path("."), Path("."), "feature/one", "a" * 40, "main")
        with patch.object(module, "bootstrap_graph", return_value={
            "state": "current", "checkpoint": "main-checkpoint"
        }) as canonical, patch.object(
            module, "rebuild", return_value={"freshness": "current", "checkpoint": "feature-checkpoint"}
        ) as feature:
            recovered = module._recover_initial_checkpoint(project)
        self.assertEqual({"recovered": True, "checkpoint": "feature-checkpoint"}, recovered)
        canonical.assert_called_once()
        self.assertEqual(project.commit, feature.call_args.kwargs["target_commit"])

    def test_bootstrap_requires_supported_graphify_only_when_construction_is_needed(self):
        module = self.module()
        project = module.ProjectIdentity(Path("."), Path("."), "main", "a" * 40, "main")
        with patch.object(module, "resolve_project", return_value=project), patch.object(
            module, "_tracked_manifest_name", return_value="engineering-traceability.json"
        ), patch.object(module, "graph_checkpoint_catalogue", return_value={"state": "managed", "canonical": None, "features": []}
        ), patch.object(module, "reconcile_canonical", side_effect=[
            {"freshness": "cached", "canonical_published": False, "reason": "canonical_checkpoint_missing"},
            {
            "freshness": "cached", "checkpoint": "canonical-checkpoint", "canonical_published": True
            },
        ]), patch.object(module, "verify_graphify") as verify:
            result = module.bootstrap_graph(project.root, setup_authorized=True)
        self.assertEqual("current", result["state"])
        self.assertEqual("canonical-checkpoint", result["checkpoint"])
        verify.assert_called_once_with(sys.executable)

        with patch.object(module, "resolve_project", return_value=project), patch.object(
            module, "_tracked_manifest_name", return_value="engineering-traceability.json"
        ), patch.object(module, "graph_checkpoint_catalogue", return_value={"state": "managed", "canonical": {}, "features": []}
        ), patch.object(module, "reconcile_canonical", return_value={
            "freshness": "cached", "checkpoint": "canonical-checkpoint", "canonical_published": True
        }), patch.object(module, "verify_graphify") as verify:
            exact = module.bootstrap_graph(project.root, setup_authorized=False)
        self.assertEqual("current", exact["state"])
        verify.assert_not_called()

    def test_bootstrap_keeps_unmanaged_and_missing_graphify_fail_closed(self):
        module = self.module()
        with patch.object(module, "_tracked_manifest_name", return_value=None):
            unmanaged = module.bootstrap_graph(Path("."), setup_authorized=False)
        self.assertEqual("advisory", unmanaged["state"])
        self.assertEqual("adopt_engineering", unmanaged["next_action"])

        with patch.object(module, "resolve_project_root", return_value=Path(".")), patch.object(
            module, "_tracked_manifest_name", return_value="engineering-traceability.json"
        ), patch.object(module, "graph_checkpoint_catalogue", return_value={"state": "managed", "canonical": None, "features": []}
        ), patch.object(
            module, "reconcile_canonical", return_value={"freshness": "cached", "canonical_published": False}
        ), patch.object(module, "verify_graphify", side_effect=module.EngineeringError("Graphify is missing")):
            blocked = module.bootstrap_graph(Path("."), setup_authorized=True)
        self.assertEqual("blocked", blocked["state"])
        self.assertEqual("graphify_unavailable_or_incompatible", blocked["reason"])

    def test_checkpoint_catalogue_never_promotes_feature_records(self):
        module = self.module()
        manifest = {"project": {"default_branch": "main"}}
        validations = iter((
            {"valid": True, "reason": "exact_current"},
            {"valid": True, "reason": "exact_current"},
            {"valid": False, "reason": "overlay_mismatch"},
        ))
        checkpoints = [
            Path("graphs/main/" + "a" * 40 + "/checkpoint.json"),
            Path("graphs/features/feature-one/" + "b" * 40 + "/checkpoint.json"),
            Path("graphs/features/orphan/" + "c" * 40 + "/checkpoint.json"),
        ]
        with patch.object(module, "resolve_project_root", return_value=Path(".")), patch.object(
            module, "_tracked_manifest_name", return_value="engineering-traceability.json"
        ), patch.object(
            module, "_json_at", return_value=manifest
        ), patch.object(module, "git", side_effect=lambda root, *argv: (
            "a" * 40 if "origin/main" in argv[-1] else "b" * 40
            if "feature-one" in argv[-1] else (_ for _ in ()).throw(module.EngineeringError("missing")))
        ), patch.object(module, "_common_graph_dir", return_value=Path("graphs")), patch.object(
            Path, "glob", side_effect=[checkpoints[:1], checkpoints[1:]]
        ), patch.object(module, "validate_checkpoint", side_effect=lambda *args: next(validations)), patch.object(
            module, "_is_ancestor_or_equal", side_effect=lambda root, ancestor, descendant: ancestor == descendant
        ):
            catalogue = module.graph_checkpoint_catalogue(Path("."))
        self.assertEqual("current", catalogue["canonical"]["state"])
        self.assertEqual(["active", "quarantined"], [item["state"] for item in catalogue["features"]])

    def test_setup_lifecycle_is_truthful_about_commit_and_checkpoint(self):
        module = self.module()
        with patch.object(module, "_tracked_manifest_name", return_value=None):
            pending_commit = module._setup_readiness(Path("."), sys.executable)
        self.assertEqual("controls_written_pending_commit", pending_commit["readiness"])

        with patch.object(module, "_tracked_manifest_name", return_value="engineering-traceability.json"), patch.object(
            module, "check_merge_readiness", return_value={"ready": True, "checkpoint": "exact-checkpoint"}
        ):
            operational = module._setup_readiness(Path("."), sys.executable)
        self.assertEqual("operational", operational["readiness"])

        with patch.object(module, "_tracked_manifest_name", return_value="engineering-traceability.json"), patch.object(
            module, "check_merge_readiness", return_value={"ready": False, "reason": "cold_rebuild_deferred"}
        ):
            pending_checkpoint = module._setup_readiness(Path("."), sys.executable)
        self.assertEqual("checkpoint_pending", pending_checkpoint["readiness"])


class Task10ContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.home = Path(self.temporary_directory.name) / "host-owned-home"
        self.home.mkdir()
        self.engineering_home = patch.dict(
            os.environ, {"ENGINEERING_USER_HOME": str(self.home)}, clear=False
        )
        self.engineering_home.start()
        self.addCleanup(self.engineering_home.stop)
        self.root = Path(self.temporary_directory.name) / "authority-project"
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(self.root)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "synthetic"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.name", "Synthetic Test"],
            check=True,
        )
        self.host_key = Path(self.temporary_directory.name) / "synthetic-host-key"
        subprocess.run(
            [
                "ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(self.host_key),
            ],
            check=True,
            capture_output=True,
        )
        self.auditor_key = Path(self.temporary_directory.name) / "auditor-1-key"
        self.reviewer_key = Path(self.temporary_directory.name) / "reviewer-1-key"
        for key in (self.auditor_key, self.reviewer_key):
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                check=True,
                capture_output=True,
            )
        public_key = self.host_key.with_suffix(".pub").read_text(encoding="ascii").strip()
        auditor_public_key = self.auditor_key.with_suffix(".pub").read_text(
            encoding="ascii"
        ).strip()
        reviewer_public_key = self.reviewer_key.with_suffix(".pub").read_text(
            encoding="ascii"
        ).strip()
        self.host_allowed_signers = (
            "\n".join(
                (
                    f"synthetic-host {public_key}",
                    f"writer-1 {public_key}",
                    f"auditor-1 {auditor_public_key}",
                    f"reviewer-1 {reviewer_public_key}",
                )
            )
            + "\n"
        ).encode("ascii")
        self.host_authority_dir = (
            self.home / ".agents" / "engineering" / "host-authority"
        )
        self.host_authority_dir.mkdir(parents=True)
        self.host_anchor_path = self.host_authority_dir / "host-trust-anchor.json"
        self.host_signers_path = self.host_authority_dir / "allowed-signers"
        self.host_signers_path.write_bytes(self.host_allowed_signers)
        self.host_anchor_path.write_text(
            json.dumps(
                {
                    "schema": "engineering.host-trust-anchor.v2",
                    "anchor_id": "host-anchor-synthetic",
                    "format_version": 1,
                    "signers_digest": "sha256:"
                    + hashlib.sha256(self.host_allowed_signers).hexdigest(),
                    "identity": {"state": "unknown"},
                }
            ),
            encoding="utf-8",
        )
        self.bootstrap_authority_dir = (
            self.home / ".agents" / "engineering" / "bootstrap-authority"
        )
        self.bootstrap_authority_dir.mkdir(parents=True)
        self.bootstrap_signers_path = self.bootstrap_authority_dir / "allowed-signers"
        self.bootstrap_anchor_path = (
            self.bootstrap_authority_dir / "bootstrap-trust-anchor.json"
        )
        self.bootstrap_allowed_signers = (
            "\n".join(
                (
                    f"bootstrap-owner {public_key}",
                    f"bootstrap-semantic {auditor_public_key}",
                    f"bootstrap-technical {reviewer_public_key}",
                )
            )
            + "\n"
        ).encode("ascii")
        self.bootstrap_signers_path.write_bytes(self.bootstrap_allowed_signers)
        self.bootstrap_anchor_path.write_text(
            json.dumps(
                {
                    "schema": "engineering.v2.2.6-bootstrap-trust-anchor.v1",
                    "anchor_id": "bootstrap-anchor-synthetic",
                    "format_version": 1,
                    "signers_digest": "sha256:"
                    + hashlib.sha256(self.bootstrap_allowed_signers).hexdigest(),
                    "identity": {"state": "unknown"},
                }
            ),
            encoding="utf-8",
        )
        (self.root / ".engineering-host-approvers").write_text(
            self.host_allowed_signers.decode("ascii"),
            encoding="ascii",
        )
        (self.root / "README.md").write_text("# Authority fixture\n", encoding="utf-8")
        (self.root / "docs").mkdir()
        (self.root / "docs" / "spec.md").write_text(
            "# Outcome design\n\nThe downstream lane remains blocked until exact evidence is current.\n",
            encoding="utf-8",
        )
        (self.root / "schema").mkdir()
        (self.root / "schema" / "outcome.json").write_text(
            json.dumps({"interfaces": [{"id": "native outcome interface"}]}),
            encoding="utf-8",
        )
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_outcome.py").write_text(
            "def test_missing_evidence_blocks():\n    pass\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "initial"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.authority_remote = Path(self.temporary_directory.name) / "authority-origin.git"
        subprocess.run(
            ["git", "init", "--bare", "--initial-branch=main", str(self.authority_remote)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "remote", "add", "origin", str(self.authority_remote)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "push", "-u", "origin", "main"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "remote", "set-head", "origin", "-a"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.repository_id = engineering._project_contribution_digest(self.root)
        self.repository_identity_original = engineering._project_contribution_digest
        self.repository_identity = patch.object(
            engineering,
            "_project_contribution_digest",
            side_effect=lambda root: (
                self.repository_id
                if Path(root).resolve() == self.root.resolve()
                else self.repository_identity_original(Path(root))
            ),
        )
        self.repository_identity.start()
        self.addCleanup(self.repository_identity.stop)
        self.private_writer = patch.object(
            engineering, "_enforce_owner_private", side_effect=synthetic_owner_private
        )
        self.private_writer.start()
        self.addCleanup(self.private_writer.stop)
        self.private_reader = patch.object(
            engineering, "_verify_owner_private", return_value=None
        )
        self.private_reader.start()
        self.addCleanup(self.private_reader.stop)
        self.canonical_host_home = patch.object(
            engineering, "_canonical_host_home", return_value=self.home
        )
        self.canonical_host_home.start()
        self.addCleanup(self.canonical_host_home.stop)

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def host_receipt_for(
        self,
        *,
        contract,
        authority_epoch="epoch-local-1",
        repository_id=None,
        anchor=None,
    ):
        anchor = anchor or json.loads(self.host_anchor_path.read_text(encoding="utf-8"))
        return {
            "schema": "engineering.host-receipt.v1",
            "receipt_id": "host-receipt-synthetic",
            "repository_id": repository_id or self.repository_id,
            "authority_epoch": authority_epoch,
            "contract": contract,
            "identity": {"state": "unknown"},
            "trust_anchor": anchor,
        }

    def sign_host_approval(
        self,
        *,
        schema,
        claims_schema,
        claims,
        namespace,
        contract,
        authority_epoch,
        signer=None,
        approver="synthetic-host",
        receipt=None,
    ):
        module = self.module()
        receipt = receipt or self.host_receipt_for(
            contract=contract, authority_epoch=authority_epoch
        )
        material = module._canonical_json(
            {"schema": claims_schema, "claims": claims, "host_receipt": receipt}
        )
        claims_path = Path(self.temporary_directory.name) / f"host-approval-{time.time_ns()}.json"
        claims_path.write_bytes(material)
        subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(signer or self.host_key),
                "-n",
                namespace,
                str(claims_path),
            ],
            check=True,
            capture_output=True,
        )
        return {
            "schema": schema,
            "approver": approver,
            "claims": claims,
            "host_receipt": receipt,
            "signature": claims_path.with_suffix(".json.sig").read_text(encoding="ascii"),
        }

    def binding(self, **changes):
        module = self.module()
        issued = module.datetime.now(module.timezone.utc)
        value = {
            "authority_epoch": "epoch-local-1",
            "target": "candidate-v2-2-4",
            "action_class": "local_implementation",
            "scope": ["src/authority.py", "tests/test_authority.py"],
            "safeguards": ["no_install", "no_network", "one_writer"],
            "native_requirements": [],
            "issued_at": issued.isoformat(),
            "expires_at": (issued + module.timedelta(hours=2)).isoformat(),
        }
        value.update(changes)
        return value

    def approval(self, value):
        module = self.module()
        normalized = module._scoped_authority_binding(self.root, value)
        return self.sign_host_approval(
            schema=module.HOST_AUTHORITY_APPROVAL_SCHEMA,
            claims_schema="engineering.host-authority-claims.v3",
            claims=normalized,
            namespace="engineering-authority",
            contract=module.SCOPED_AUTHORITY_SCHEMA,
            authority_epoch=normalized["authority_epoch"],
        )

    def persist(self, binding=None, **changes):
        module = self.module()
        value = dict(binding or self.binding(**changes))
        approval = self.approval(value)
        return module.persist_scoped_authority(self.root, value, approval)

    def request(self, authority_id, **changes):
        value = {
            "authority_id": authority_id,
            "authority_epoch": "epoch-local-1",
            "target": "candidate-v2-2-4",
            "action_class": "local_implementation",
            "scope": ["src/authority.py", "tests/test_authority.py"],
            "safeguards": ["no_install", "no_network", "one_writer"],
            "permission_mode": "sandboxed",
            "native_requirements": [],
            "continuation": {"turn": "turn-1", "retry": 0, "callback": False},
        }
        value.update(changes)
        return value

    def test_exact_authority_persists_across_unchanged_continuations(self):
        module = self.module()
        authority = self.persist()
        first = module.resolve_scoped_authority(
            self.root, self.request(authority["authority_id"])
        )
        retry = module.resolve_scoped_authority(
            self.root,
            self.request(
                authority["authority_id"],
                continuation={"turn": "turn-2", "retry": 3, "callback": True},
            ),
        )
        self.assertEqual("authorized", first["decision"])
        self.assertTrue(first["business_authority_present"])
        self.assertFalse(first["request_business_approval"])
        self.assertEqual(authority["authority_id"], retry["authority_id"])
        self.assertEqual(first["binding_digest"], retry["binding_digest"])

    def test_missing_authority_and_full_access_still_require_business_approval(self):
        module = self.module()
        result = module.resolve_scoped_authority(
            self.root,
            self.request(None, permission_mode="full_access"),
        )
        self.assertEqual("request_required", result["decision"])
        self.assertFalse(result["business_authority_present"])
        self.assertTrue(result["request_business_approval"])
        self.assertEqual("missing_authority", result["reason"])
        self.assertEqual("full_access", result["permission_mode"])

    def test_changed_binding_requires_new_authority(self):
        module = self.module()
        authority = self.persist()
        changes = {
            "authority_epoch": "epoch-local-2",
            "target": "another-candidate",
            "action_class": "installation",
            "scope": ["src/authority.py"],
            "safeguards": ["no_network"],
        }
        for field, changed in changes.items():
            with self.subTest(field=field):
                result = module.resolve_scoped_authority(
                    self.root,
                    self.request(authority["authority_id"], **{field: changed}),
                )
                self.assertEqual("request_required", result["decision"])
                self.assertEqual(f"changed_{field}", result["reason"])
                self.assertTrue(result["request_business_approval"])

        with patch.object(
            module, "_project_contribution_digest", return_value="sha256:" + "f" * 64
        ):
            changed_project = module.resolve_scoped_authority(
                self.root, self.request(authority["authority_id"])
            )
        self.assertEqual("changed_repository_id", changed_project["reason"])
        self.assertTrue(changed_project["request_business_approval"])

    def test_revocation_consumption_and_expiry_fail_closed(self):
        module = self.module()
        for transition in ("revoked", "consumed"):
            with self.subTest(transition=transition):
                authority = self.persist(authority_epoch=f"epoch-{transition}")
                at = module.datetime.now(module.timezone.utc).isoformat()
                terminal = module.transition_scoped_authority(
                    self.root, authority["authority_id"], transition, at
                )
                replay = module.transition_scoped_authority(
                    self.root, authority["authority_id"], transition, at
                )
                self.assertEqual(terminal, replay)
                result = module.resolve_scoped_authority(
                    self.root, self.request(authority["authority_id"])
                )
                self.assertEqual(transition, result["reason"])
                with self.assertRaisesRegex(module.EngineeringError, "terminal"):
                    module.transition_scoped_authority(
                        self.root,
                        authority["authority_id"],
                        "consumed" if transition == "revoked" else "revoked",
                        at,
                    )

        past = module.datetime.now(module.timezone.utc) - module.timedelta(minutes=1)
        expired = self.persist(
            issued_at=(past - module.timedelta(hours=1)).isoformat(),
            expires_at=past.isoformat(),
        )
        result = module.resolve_scoped_authority(
            self.root, self.request(expired["authority_id"])
        )
        self.assertEqual("expired", result["reason"])
        self.assertTrue(result["request_business_approval"])

    def test_native_destructive_and_connector_approvals_remain_pending(self):
        module = self.module()
        authority = self.persist(native_requirements=["connector", "destructive"])
        result = module.resolve_scoped_authority(
            self.root,
            self.request(
                authority["authority_id"],
                permission_mode="full_access",
                native_requirements=["connector", "destructive"],
            ),
        )
        self.assertEqual("pending_native_approval", result["decision"])
        self.assertTrue(result["business_authority_present"])
        self.assertFalse(result["request_business_approval"])
        self.assertEqual(["connector", "destructive"], result["native_approval_required"])

    def test_delegation_preserves_provenance_and_can_only_narrow(self):
        module = self.module()
        parent = self.persist()
        child = module.delegate_scoped_authority(
            self.root,
            parent["authority_id"],
            self.binding(
                scope=["src/authority.py"],
                issued_at=parent["issued_at"],
                expires_at=parent["expires_at"],
            ),
        )
        self.assertEqual(parent["authority_id"], child["parent_authority_id"])
        self.assertEqual(["src/authority.py"], child["scope"])
        replay = module.delegate_scoped_authority(
            self.root,
            parent["authority_id"],
            self.binding(
                scope=["src/authority.py"],
                issued_at=parent["issued_at"],
                expires_at=parent["expires_at"],
            ),
        )
        self.assertEqual(child["authority_id"], replay["authority_id"])
        with self.assertRaisesRegex(module.EngineeringError, "broaden"):
            module.delegate_scoped_authority(
                self.root,
                parent["authority_id"],
                self.binding(
                    scope=["src/authority.py", "tests/test_authority.py", "release/publish.py"],
                    issued_at=parent["issued_at"],
                    expires_at=parent["expires_at"],
                ),
            )

    def test_delegated_authority_follows_parent_revocation_and_consumption(self):
        module = self.module()
        for transition in ("revoked", "consumed"):
            with self.subTest(transition=transition):
                parent = self.persist(authority_epoch=f"epoch-parent-{transition}")
                child = module.delegate_scoped_authority(
                    self.root,
                    parent["authority_id"],
                    self.binding(
                        authority_epoch=f"epoch-parent-{transition}",
                        scope=["src/authority.py"],
                        issued_at=parent["issued_at"],
                        expires_at=parent["expires_at"],
                    ),
                )
                module.transition_scoped_authority(
                    self.root,
                    parent["authority_id"],
                    transition,
                    module.datetime.now(module.timezone.utc).isoformat(),
                )
                result = module.resolve_scoped_authority(
                    self.root,
                    self.request(child["authority_id"], scope=["src/authority.py"]),
                )
                self.assertEqual("request_required", result["decision"])
                self.assertEqual(f"ancestor_{transition}", result["reason"])
                self.assertTrue(result["request_business_approval"])

    def test_exact_artifact_audit_history_is_signed_and_replay_safe(self):
        module = self.module()
        authority = self.persist()
        observed = module.datetime.now(module.timezone.utc).isoformat()
        digest = "sha256:" + "a" * 64
        event = module.record_authority_audit(
            self.root,
            authority["authority_id"],
            digest,
            "auditor-independent-1",
            "accepted",
            observed,
        )
        replay = module.record_authority_audit(
            self.root,
            authority["authority_id"],
            digest,
            "auditor-independent-1",
            "accepted",
            observed,
        )
        self.assertEqual(event, replay)
        self.assertEqual(digest, event["artifact_digest"])
        with self.assertRaisesRegex(module.EngineeringError, "conflict"):
            module.record_authority_audit(
                self.root,
                authority["authority_id"],
                digest,
                "auditor-independent-1",
                "rejected",
                (module.datetime.now(module.timezone.utc) + module.timedelta(seconds=1)).isoformat(),
            )

    def test_authority_requires_retained_host_approval_attestation(self):
        module = self.module()
        with self.assertRaisesRegex(module.EngineeringError, "host approval"):
            module.persist_scoped_authority(
                self.root, self.binding(), {"fabricated": True}
            )
        binding = self.binding()
        approval = self.approval(binding)
        signature_lines = approval["signature"].splitlines()
        signature_lines[1] = (
            ("A" if signature_lines[1][0] != "A" else "B") + signature_lines[1][1:]
        )
        approval["signature"] = "\n".join(signature_lines) + "\n"
        with self.assertRaisesRegex(module.EngineeringError, "signature"):
            module.persist_scoped_authority(self.root, binding, approval)

    def test_destructive_binding_cannot_suppress_native_approval(self):
        module = self.module()
        authority = self.persist(action_class="destructive")
        result = module.resolve_scoped_authority(
            self.root,
            self.request(
                authority["authority_id"],
                action_class="destructive",
                native_requirements=[],
            ),
        )
        self.assertEqual("pending_native_approval", result["decision"])
        self.assertEqual(["destructive"], result["native_approval_required"])

    def test_publish_rejects_cardinality_before_writing(self):
        module = self.module()
        ledger = {
            "schema": module.AUTHORITY_LEDGER_SCHEMA,
            "authorities": [{}] * (module.MAX_SCOPED_AUTHORITIES + 1),
            "audits": [],
        }
        with self.assertRaisesRegex(module.EngineeringError, "bounded size"):
            module._publish_scoped_authorities(self.root, ledger, b"x" * 32)
        self.assertFalse(module._scoped_authority_path(self.root).exists())

    def test_conflicting_concurrent_transitions_are_serialized(self):
        module = self.module()
        authority = self.persist()
        barrier = threading.Barrier(3)
        outcomes = []

        def transition(status):
            barrier.wait()
            try:
                outcomes.append(
                    module.transition_scoped_authority(
                        self.root,
                        authority["authority_id"],
                        status,
                        module.datetime.now(module.timezone.utc).isoformat(),
                    )["status"]
                )
            except module.EngineeringError as error:
                outcomes.append(str(error))

        workers = [
            threading.Thread(target=transition, args=(status,))
            for status in ("revoked", "consumed")
        ]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            # Authority mutations use the shared completion cleanup boundary,
            # whose bounded recovery budget is 30 seconds.  Keep this test
            # fail-closed for a real liveness fault without declaring a busy
            # Windows host deadlocked halfway through that documented budget.
            worker.join(timeout=35)
            self.assertFalse(worker.is_alive())
        self.assertEqual(1, sum(item in {"revoked", "consumed"} for item in outcomes))
        self.assertEqual(
            1,
            sum("terminal" in item or "lock timed out" in item for item in outcomes),
        )
        retained = module._load_scoped_authorities(self.root)["authorities"][0]
        self.assertIn(retained["status"], {"revoked", "consumed"})

    def test_tampered_authority_state_fails_closed(self):
        module = self.module()
        self.persist()
        path = module._scoped_authority_path(self.root)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["authorities"][0]["target"] = "tampered-target"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(module.EngineeringError, "ledger"):
            module.resolve_scoped_authority(self.root, self.request(payload["authorities"][0]["authority_id"]))

    def test_policy_preserves_native_hosts_and_pauses_exhausted_workers(self):
        skill = " ".join(SKILL.read_text(encoding="utf-8").split())
        contract = " ".join(
            (SKILL_DIR / "references" / "controller-contract.md")
            .read_text(encoding="utf-8")
            .split()
        )
        for required in (
            "approval presence",
            "request approval again",
            "Full Access",
            "PAUSED_AWAITING_CENTRAL_ADJUDICATION",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill)
        for required in (
            "native destructive",
            "native connector",
            "Codex and Claude",
            "exact artifact",
        ):
            with self.subTest(required=required):
                self.assertIn(required, contract)

class Task11OwnerIntentContractTests(Task10ContractTests):
    """Owner-private intent bindings prevent candidate-local scope narrowing."""

    def owner_intent_binding(self, **changes):
        value = {
            "schema": "engineering.owner-intent.v1",
            "intent_id": "intent-native-graph",
            "repository_id": self.repository_id,
            "authority_epoch": "epoch-local-1",
            "source_evidence": [
                {
                    "identity": "source-owner-approval",
                    "digest": "sha256:" + "1" * 64,
                }
            ],
            "outcomes": [
                {
                    "id": "OUTCOME-NATIVE-GRAPH",
                    "criticality": "core",
                    "statement_digest": "sha256:" + "2" * 64,
                    "required_evidence": [
                        {
                            "class": "real_outcome",
                            "interface": "native_harness",
                            "environment": "candidate",
                        }
                    ],
                }
            ],
            "predecessor": {
                "schema": "engineering.owner-intent-predecessor.v1",
                "state": "none",
            },
        }
        value.update(changes)
        return value

    def owner_intent_approval(
        self, binding, *, receipt_changes=None, signer=None, approver="synthetic-host"
    ):
        return self.host_owner_intent_approval(
            binding,
            receipt_changes=receipt_changes,
            signer=signer,
            approver=approver,
        )

    def bound_native_owner_intent(self):
        module = self.module()
        binding = self.owner_intent_binding()
        return module.bind_owner_intent(
            self.root, binding, self.owner_intent_approval(binding)
        )

    def owner_exception(
        self,
        intent,
        outcome_id,
        disposition,
        *,
        exception_id="exception-native-graph",
        receipt_changes=None,
        signer=None,
        approver="synthetic-host",
    ):
        module = self.module()
        claims = {
            "exception_id": exception_id,
            "owner_intent_id": intent["intent_id"],
            "owner_intent_digest": intent["owner_intent_digest"],
            "outcome_id": outcome_id,
            "disposition": disposition,
        }
        receipt = self.host_receipt(
            contract=module.OWNER_EXCEPTION_SCHEMA,
            authority_epoch=intent["authority_epoch"],
        )
        receipt.update(receipt_changes or {})
        return self.sign_host_approval(
            schema=module.OWNER_EXCEPTION_SCHEMA,
            claims_schema="engineering.host-owner-exception-claims.v3",
            claims=claims,
            namespace="engineering-owner-exception",
            contract=module.OWNER_EXCEPTION_SCHEMA,
            authority_epoch=intent["authority_epoch"],
            signer=signer,
            approver=approver,
            receipt=receipt,
        )

    def outcome_equivalence(self, owner_intent=None, **changes):
        module = self.module()
        value = {
            "schema": "engineering.outcome-equivalence.v2",
            "reviewer_id": "reviewer-1",
            "architect_id": "architect-1",
            "implementer_id": "implementer-1",
            "writer_id": "writer-1",
            "evidence_id": "evidence-equivalence",
            "evidence_digest": "sha256:" + "6" * 64,
        }
        signer = changes.pop("signer", self.reviewer_key)
        approver = changes.pop("approver", value["reviewer_id"])
        value.update(changes)
        claims = {
            name: value[name]
            for name in (
                "reviewer_id",
                "architect_id",
                "implementer_id",
                "writer_id",
                "evidence_id",
                "evidence_digest",
            )
        }
        owner_intent = owner_intent or module._active_owner_intent(self.root)
        return {
            **value,
            "equivalence_attestation": self.sign_host_approval(
                schema=module.OUTCOME_EQUIVALENCE_ATTESTATION_SCHEMA,
                claims_schema="engineering.outcome-equivalence-claims.v2",
                claims=claims,
                namespace="engineering-outcome-equivalence",
                contract=module.OUTCOME_EQUIVALENCE_SCHEMA,
                authority_epoch=owner_intent["authority_epoch"],
                signer=signer,
                approver=approver,
            ),
        }

    def outcome_survival_v2(self, intent, **changes):
        outcome_id = intent["outcomes"][0]["id"]
        value = {
            "schema": "engineering.outcome-survival.v2",
            "owner_intent_id": intent["intent_id"],
            "owner_intent_digest": intent["owner_intent_digest"],
            "mappings": [
                {
                    "outcome_id": outcome_id,
                    "disposition": "INCLUDED",
                    "reason": "Retain executable native graph outcome.",
                    "verification_ids": ["evidence-native-graph"],
                    "replacement_ids": [],
                    "equivalence": None,
                    "owner_exception": None,
                }
            ],
        }
        value.update(changes)
        return value

    def installable_bundle_source(self):
        module = self.module()
        source = self.root / ".agents" / "skills" / "engineering"
        (source / "scripts").mkdir(parents=True)
        (source / "references").mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: engineering\ndescription: synthetic release bundle\n---\n",
            encoding="utf-8",
        )
        (source / "manifest.json").write_text(
            json.dumps(
                {
                    "name": "engineering",
                    "version": "2.2.6",
                    "graphify": {"commit": module.GRAPHIFY_COMMIT},
                }
            ),
            encoding="utf-8",
        )
        (source / "scripts" / "engineering.py").write_text(
            "# synthetic release bundle\n", encoding="utf-8"
        )
        (source / "references" / "controller-contract.md").write_text(
            "# Synthetic controller contract\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(self.root), "add", ".agents"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "add release bundle"],
            check=True,
            capture_output=True,
            text=True,
        )
        return source

    def bootstrap_anchor(self):
        return json.loads(self.bootstrap_anchor_path.read_text(encoding="utf-8"))

    def bootstrap_host_receipt(self, *, contract, authority_epoch="epoch-local-1"):
        return {
            "schema": "engineering.v2.2.6-bootstrap-host-receipt.v1",
            "receipt_id": "bootstrap-host-receipt-synthetic",
            "repository_id": self.repository_id,
            "authority_epoch": authority_epoch,
            "contract": contract,
            "identity": {"state": "unknown"},
            "trust_anchor": self.bootstrap_anchor(),
        }

    def sign_bootstrap_evidence(
        self,
        *,
        schema,
        claims_schema,
        claims,
        namespace,
        contract,
        signer,
        approver,
        authority_epoch="epoch-local-1",
    ):
        module = self.module()
        receipt = self.bootstrap_host_receipt(
            contract=contract, authority_epoch=authority_epoch
        )
        material = module._canonical_json(
            {"schema": claims_schema, "claims": claims, "host_receipt": receipt}
        )
        claims_path = Path(
            self.temporary_directory.name
        ) / f"bootstrap-evidence-{time.time_ns()}.json"
        claims_path.write_bytes(material)
        subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(signer),
                "-n",
                namespace,
                str(claims_path),
            ],
            check=True,
            capture_output=True,
        )
        return {
            "schema": schema,
            "approver": approver,
            "claims": claims,
            "host_receipt": receipt,
            "signature": claims_path.with_suffix(".json.sig").read_text(encoding="ascii"),
        }

    def installed_v225_receipt(self):
        if hasattr(self, "_installed_v225_receipt"):
            return self._installed_v225_receipt
        module = self.module()
        source_root = Path(self.temporary_directory.name) / "installed-v225-source"
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(source_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(source_root), "config", "user.email", "synthetic"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(source_root), "config", "user.name", "Synthetic Test"],
            check=True,
        )
        source = source_root / ".agents" / "skills" / "engineering"
        (source / "scripts").mkdir(parents=True)
        (source / "references").mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: engineering\ndescription: synthetic v2.2.5 bundle\n---\n",
            encoding="utf-8",
        )
        (source / "manifest.json").write_text(
            json.dumps(
                {
                    "name": "engineering",
                    "version": "2.2.5",
                    "graphify": {"commit": module.GRAPHIFY_COMMIT},
                }
            ),
            encoding="utf-8",
        )
        (source / "scripts" / "engineering.py").write_text(
            "# synthetic v2.2.5 release bundle\n", encoding="utf-8"
        )
        (source / "references" / "controller-contract.md").write_text(
            "# Synthetic v2.2.5 controller contract\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(source_root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(source_root), "commit", "-m", "add v2.2.5 bundle"],
            check=True,
            capture_output=True,
            text=True,
        )
        module.install_bundle(source, self.home)
        receipt_path = module._install_paths(self.home)["receipt"]
        key = module._controller_key(
            self.home / ".agents" / "engineering" / "controller", required=True
        )
        self._installed_v225_receipt = module._load_install_receipt(receipt_path, key)
        return self._installed_v225_receipt

    def public_bundle_source(self, source):
        public_root = Path(self.temporary_directory.name) / f"public-v226-{time.time_ns()}"
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(public_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(public_root), "config", "user.email", "synthetic"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(public_root), "config", "user.name", "Synthetic Test"],
            check=True,
        )
        (public_root / "README.md").write_text("# Public bootstrap base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(public_root), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(public_root), "commit", "-m", "public bootstrap base"],
            check=True,
            capture_output=True,
            text=True,
        )
        destination = public_root / ".agents" / "skills" / "engineering"
        shutil.copytree(source, destination)
        subprocess.run(["git", "-C", str(public_root), "add", ".agents"], check=True)
        subprocess.run(
            ["git", "-C", str(public_root), "commit", "-m", "add public v2.2.6 bundle"],
            check=True,
            capture_output=True,
            text=True,
        )
        return destination

    def bootstrap_candidate(self, source, role):
        module = self.module()
        _, manifest, source_commit, source_digest = module._bundle_files(source)
        repository = Path(
            subprocess.run(
                ["git", "-C", str(source), "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ).resolve()
        source_tree = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD^{tree}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        base_commit = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD^"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        candidate = {
            "role": role,
            "repository_id": module._project_contribution_digest(repository),
            "source_git_commit": source_commit,
            "source_git_tree": source_tree,
            "source_digest": source_digest,
            "skill_version": manifest["version"],
            "base_commit": base_commit,
        }
        candidate["artifact_digest"] = "sha256:" + hashlib.sha256(
            module._canonical_json(candidate)
        ).hexdigest()
        return candidate

    def bootstrap_pair_digest(self, candidates):
        module = self.module()
        return "sha256:" + hashlib.sha256(
            module._canonical_json(sorted(candidates, key=lambda item: item["role"]))
        ).hexdigest()

    def bootstrap_ancestry_digest(self, candidates):
        module = self.module()
        return "sha256:" + hashlib.sha256(
            module._canonical_json(
                [
                    {
                        "role": item["role"],
                        "base_commit": item["base_commit"],
                        "source_git_commit": item["source_git_commit"],
                    }
                    for item in sorted(candidates, key=lambda item: item["role"])
                ]
            )
        ).hexdigest()

    def bootstrap_authorization(self, source, *, issued_at=None, audit_specs=None):
        module = self.module()
        public_source = self.public_bundle_source(source)
        candidates = [
            self.bootstrap_candidate(source, "internal"),
            self.bootstrap_candidate(public_source, "public"),
        ]
        pair_digest = self.bootstrap_pair_digest(candidates)
        ancestry_digest = self.bootstrap_ancestry_digest(candidates)
        receipt = self.installed_v225_receipt()
        issued_at = issued_at or module._utc_now()
        installed_v225 = {
            "receipt_digest": module._json_digest(receipt),
            "skill_version": receipt["skill_version"],
            "source_git_commit": receipt["source_git_commit"],
            "source_digest": receipt["source_digest"],
        }
        owner_claims = {
            "approval_id": "bootstrap-owner-approval",
            "repository_id": self.repository_id,
            "authority_epoch": "epoch-local-1",
            "candidate_pair_digest": pair_digest,
            "installed_v225_receipt_digest": installed_v225["receipt_digest"],
            "decision": "owner_approved",
            "issued_at": issued_at,
            "replay_nonce": "bootstrap-owner-nonce",
        }
        owner_approval = self.sign_bootstrap_evidence(
            schema="engineering.v2.2.6-bootstrap-owner-approval.v1",
            claims_schema="engineering.v2.2.6-bootstrap-owner-claims.v1",
            claims=owner_claims,
            namespace="engineering-v226-bootstrap-owner",
            contract="engineering.v2.2.6-bootstrap-owner-approval.v1",
            signer=self.host_key,
            approver="bootstrap-owner",
        )
        audits = []
        audit_specs = audit_specs or (
            ("bootstrap-audit-semantic", "semantic", self.auditor_key, "bootstrap-semantic", "bootstrap-semantic-nonce"),
            ("bootstrap-audit-technical", "technical", self.reviewer_key, "bootstrap-technical", "bootstrap-technical-nonce"),
        )
        for audit_id, auditor_role, signer, approver, nonce in audit_specs:
            claims = {
                "audit_id": audit_id,
                "auditor_role": auditor_role,
                "repository_id": self.repository_id,
                "authority_epoch": "epoch-local-1",
                "candidate_pair_digest": pair_digest,
                "candidate_ancestry_digest": ancestry_digest,
                "decision": "accepted",
                "issued_at": issued_at,
                "replay_nonce": nonce,
            }
            audits.append(
                self.sign_bootstrap_evidence(
                    schema="engineering.v2.2.6-bootstrap-audit.v1",
                    claims_schema="engineering.v2.2.6-bootstrap-audit-claims.v1",
                    claims=claims,
                    namespace="engineering-v226-bootstrap-audit",
                    contract="engineering.v2.2.6-bootstrap-audit.v1",
                    signer=signer,
                    approver=approver,
                )
            )
        record = {
            "schema": "engineering.v2.2.6-bootstrap-host-record.v1",
            "record_id": "bootstrap-record-v226",
            "repository_id": self.repository_id,
            "authority_epoch": "epoch-local-1",
            "candidate_pair": sorted(candidates, key=lambda item: item["role"]),
            "candidate_pair_digest": pair_digest,
            "installed_v225": installed_v225,
            "owner_approval": owner_approval,
            "independent_audits": audits,
            "issued_at": issued_at,
            "replay_nonce": "bootstrap-record-nonce",
            "public_source": str(public_source),
            "identity": {"state": "unknown"},
        }
        _, manifest, source_commit, source_digest = module._bundle_files(source)
        source_tree = module._bundle_git_tree(source, source_commit)
        return {
            "record": record,
            "authorization": {
                "schema": "engineering.v2.2.6-bootstrap-authorization.v2",
                "record_id": record["record_id"],
                "record_digest": module._json_digest(record),
                "source_bundle": {
                    "source_git_commit": source_commit,
                    "source_git_tree": source_tree,
                    "source_digest": source_digest,
                    "skill_version": manifest["version"],
                },
            },
        }

    def publish_bootstrap_authorization(self, material):
        path = self.bootstrap_authority_dir / "v2.2.6-authorization.json"
        path.write_text(json.dumps(material["record"]), encoding="utf-8")
        return material["authorization"]

    def host_anchor(self, **changes):
        value = json.loads(self.host_anchor_path.read_text(encoding="utf-8"))
        value.update(changes)
        return value

    def host_receipt(
        self,
        *,
        contract,
        authority_epoch="epoch-local-1",
        repository_id=None,
        anchor=None,
    ):
        return {
            "schema": "engineering.host-receipt.v1",
            "receipt_id": "host-receipt-synthetic",
            "repository_id": repository_id or self.repository_id,
            "authority_epoch": authority_epoch,
            "contract": contract,
            "identity": {"state": "unknown"},
            "trust_anchor": anchor or self.host_anchor(),
        }

    def host_owner_intent_approval(
        self, binding, *, receipt_changes=None, signer=None, approver="synthetic-host"
    ):
        module = self.module()
        normalized = module._owner_intent_binding(self.root, binding)
        receipt = self.host_receipt(
            contract="engineering.owner-intent.v1",
            authority_epoch=normalized["authority_epoch"],
        )
        receipt.update(receipt_changes or {})
        return self.sign_host_approval(
            schema=module.HOST_OWNER_INTENT_APPROVAL_SCHEMA,
            claims_schema="engineering.host-owner-intent-claims.v3",
            claims=normalized,
            namespace="engineering-owner-intent",
            contract=module.OWNER_INTENT_SCHEMA,
            authority_epoch=normalized["authority_epoch"],
            signer=signer,
            approver=approver,
            receipt=receipt,
        )

    def owner_intent_import(self, intent):
        module = self.module()
        artifact = {
            "repository_id": intent["repository_id"],
            "commit": subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "tree": subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "HEAD^{tree}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
        }
        artifact["digest"] = module._json_digest(artifact)
        mappings = [
            {
                "outcome_id": item["id"],
                "outcome_statement_digest": item["statement_digest"],
                "lifecycle_state": "DESIGN_MAPPED",
                "design": {"path": "docs/spec.md", "section": "Outcome design"},
                "contract": {
                    "path": "schema/outcome.json",
                    "interface": "native outcome interface",
                },
                "runtime_behavior": "The later lane remains blocked until its exact acceptance evidence is current.",
                "negative_test": {
                    "path": "tests/test_outcome.py",
                    "selector": "test_missing_evidence_blocks",
                },
                "required_evidence": item["required_evidence"][0],
                "exact_artifact": artifact,
            }
            for item in intent["outcomes"]
        ]
        return {
            "schema": "engineering.owner-intent-import.v2",
            "import_id": "intent-import-native-graph",
            "repository_id": intent["repository_id"],
            "authority_epoch": intent["authority_epoch"],
            "owner_intent_id": intent["intent_id"],
            "owner_intent_digest": intent["owner_intent_digest"],
            "outcome_ids": sorted(item["id"] for item in intent["outcomes"]),
            "coverage_scopes": ["accepted_owner_outcomes", "product_releases"],
            "outcome_mappings": mappings,
            "outcome_mapping_digest": module._json_digest(mappings),
        }

    def owner_intent_import_approval(self, imported):
        module = self.module()
        receipt = self.host_receipt(
            contract="engineering.owner-intent-import.v2",
            authority_epoch=imported["authority_epoch"],
        )
        material = module._canonical_json(
            {
                "schema": "engineering.host-owner-intent-import-claims.v2",
                "claims": imported,
                "host_receipt": receipt,
            }
        )
        claims_path = Path(self.temporary_directory.name) / f"owner-intent-import-{time.time_ns()}.json"
        claims_path.write_bytes(material)
        subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(self.host_key),
                "-n",
                "engineering-owner-intent-import",
                str(claims_path),
            ],
            check=True,
            capture_output=True,
        )
        return {
            "schema": "engineering.host-owner-intent-import-approval.v2",
            "approver": "synthetic-host",
            "claims": imported,
            "host_receipt": receipt,
            "signature": claims_path.with_suffix(".json.sig").read_text(encoding="ascii"),
        }

    def terminal_completion(self, survival):
        return {
            "schema": "engineering.complete.v1",
            "run_id": "run-a1b2c3",
            "authorization": {"scope_handoff": {"outcome_survival": survival}},
            "owner_intent": {
                "intent_id": survival["owner_intent_id"],
                "owner_intent_digest": survival["owner_intent_digest"],
                "authority_epoch": "epoch-local-1",
            },
            "result_identity": {
                "commit": "a" * 40,
                "dirty_tree_digest": None,
            },
            "changed_artifacts": ["src/native_graph.py"],
            "scope_result_artifacts": ["src/native_graph.py"],
        }

    def outcome_acceptance(
        self, intent, survival, evidence_class="real_outcome", evidence=None
    ):
        module = self.module()
        completion = self.terminal_completion(survival)
        completion_digest = "sha256:" + "3" * 64
        artifact_digest = module._completion_artifact_digest(
            completion, completion_digest
        )
        value = {
            "schema": "engineering.outcome-acceptance.v1",
            "acceptance_id": "acceptance-native-graph",
            "completion_digest": completion_digest,
            "artifact_digest": artifact_digest,
            "owner_intent_id": intent["intent_id"],
            "owner_intent_digest": intent["owner_intent_digest"],
            "mapping_digest": survival["mapping_digest"],
            "evidence_digest": None,
            "roles": {
                "architect_id": "architect-1",
                "implementer_id": "implementer-1",
                "writer_id": "writer-1",
                "auditor_id": "auditor-1",
            },
            "audit_attestation": None,
            "outcomes": [
                {
                    "outcome_id": intent["outcomes"][0]["id"],
                    "state": "accepted",
                    "evidence": evidence if evidence is not None else [
                        {
                            "evidence_id": "evidence-native-graph",
                            "evidence_digest": "sha256:" + "4" * 64,
                            "class": evidence_class,
                            "interface": "native_harness",
                            "environment": "candidate",
                            "producer_role": "codex_native",
                        }
                    ],
                }
            ],
        }
        value["evidence_digest"] = module._outcome_evidence_matrix_digest(
            value["outcomes"]
        )
        value["audit_attestation"] = self.audit_attestation(value)
        return completion, completion_digest, value

    def audit_attestation(
        self, acceptance, *, receipt_changes=None, signer=None, approver=None
    ):
        module = self.module()
        claims = module._outcome_audit_claims(acceptance)
        intent = module._active_owner_intent(
            self.root, acceptance["owner_intent_id"], acceptance["owner_intent_digest"]
        )
        receipt = self.host_receipt(
            contract=module.OUTCOME_ACCEPTANCE_SCHEMA,
            authority_epoch=intent["authority_epoch"],
        )
        receipt.update(receipt_changes or {})
        return self.sign_host_approval(
            schema=module.INDEPENDENT_OUTCOME_AUDIT_SCHEMA,
            claims_schema="engineering.independent-outcome-audit-claims.v3",
            claims=claims,
            namespace="engineering-independent-audit",
            contract=module.OUTCOME_ACCEPTANCE_SCHEMA,
            authority_epoch=intent["authority_epoch"],
            signer=signer or self.auditor_key,
            approver=approver or acceptance["roles"]["auditor_id"],
            receipt=receipt,
        )

    def traceability_host_attestation(
        self, receipt, *, host_receipt=None, signer=None, approver="synthetic-host"
    ):
        module = self.module()
        claims = module._traceability_host_claims(receipt)
        return self.sign_host_approval(
            schema=module.TRACEABILITY_HOST_ATTESTATION_SCHEMA,
            claims_schema="engineering.traceability-host-claims.v3",
            claims=claims,
            namespace="engineering-traceability",
            contract="engineering.traceability-host-attestation.v2",
            authority_epoch="epoch-local-1",
            signer=signer,
            approver=approver,
            receipt=host_receipt,
        )

    def test_owner_intent_requires_external_host_signature(self):
        """Accepting a forged owner baseline would reintroduce self-approval."""
        module = self.module()
        with self.assertRaisesRegex(module.EngineeringError, "owner intent host approval"):
            module.bind_owner_intent(
                self.root,
                self.owner_intent_binding(),
                {"fabricated": True},
            )

    def test_owner_intent_successor_requires_explicit_complete_predecessor_dispositions(self):
        """An active approved baseline cannot disappear behind a new binding."""
        module = self.module()
        missing = self.owner_intent_binding()
        missing.pop("predecessor", None)
        with self.assertRaisesRegex(module.EngineeringError, "predecessor"):
            module.bind_owner_intent(
                self.root, missing, self.owner_intent_approval(missing)
            )

        initial_binding = self.owner_intent_binding(
            predecessor={"schema": "engineering.owner-intent-predecessor.v1", "state": "none"}
        )
        initial = module.bind_owner_intent(
            self.root,
            initial_binding,
            self.owner_intent_approval(initial_binding),
        )
        partial = self.owner_intent_binding(
            intent_id="intent-successor",
            predecessor={"schema": "engineering.owner-intent-predecessor.v1", "state": "none"},
        )
        with self.assertRaisesRegex(module.EngineeringError, "predecessor"):
            module.bind_owner_intent(
                self.root, partial, self.owner_intent_approval(partial)
            )

        transition = {
            "schema": "engineering.owner-intent-predecessor.v1",
            "state": "successor",
            "intent_id": initial["intent_id"],
            "owner_intent_digest": initial["owner_intent_digest"],
            "dispositions": [
                {
                    "outcome_id": "OUTCOME-NATIVE-GRAPH",
                    "disposition": "CARRIED_FORWARD",
                    "successor_outcome_id": "OUTCOME-NATIVE-GRAPH",
                }
            ],
        }
        successor_binding = self.owner_intent_binding(
            intent_id="intent-successor", predecessor=transition
        )
        approval = self.owner_intent_approval(successor_binding)
        successor = module.bind_owner_intent(self.root, successor_binding, approval)
        replay = module.bind_owner_intent(self.root, successor_binding, approval)
        self.assertEqual(successor, replay)
        self.assertEqual(transition, successor["predecessor"])
        ledger = module._load_owner_intents(self.root)
        prior = next(item for item in ledger["intents"] if item["intent_id"] == initial["intent_id"])
        self.assertEqual("superseded", prior["status"])

    def test_v226_bootstrap_acceptance_does_not_call_postactivation_trust(self):
        """The first v2.2.6 delivery cannot depend on its uninstalled host gate."""
        module = self.module()
        source = self.installable_bundle_source()
        authorization = self.publish_bootstrap_authorization(self.bootstrap_authorization(source))
        with patch.object(
            module,
            "_host_owned_trust_anchor",
            create=True,
            side_effect=AssertionError("post-activation trust must not run"),
        ):
            receipt = module.install_bundle(
                source,
                self.home,
                bootstrap_authorization=authorization,
            )
        self.assertEqual("installed", receipt["status"])
        self.assertEqual(
            authorization["source_bundle"], receipt["bootstrap_authorization"]["source_bundle"]
        )

    def test_v226_bootstrap_needs_no_github_policy_collaborator_or_personal_key(self):
        """Bootstrap facts are sufficient without repository administration or a human key."""
        module = self.module()
        source = self.installable_bundle_source()
        material = self.bootstrap_authorization(source)
        self.publish_bootstrap_authorization(material)
        with patch.object(
            module,
            "_host_owned_trust_anchor",
            create=True,
            side_effect=AssertionError("post-activation trust must not run"),
        ):
            status = module.v226_bootstrap_handoff_status(source, self.home)
        self.assertEqual("post_audit_authorization_available", status["state"])
        self.assertEqual(material["authorization"], status["bootstrap_authorization"])

    def test_v226_bootstrap_requires_semantic_and_technical_audit_categories(self):
        """Distinct arbitrary labels cannot stand in for the required two audit categories."""
        module = self.module()
        source = self.installable_bundle_source()
        material = self.bootstrap_authorization(
            source,
            audit_specs=(
                ("bootstrap-audit-semantic", "architecture", self.auditor_key, "bootstrap-semantic", "bootstrap-architecture-nonce"),
                ("bootstrap-audit-technical", "verification", self.reviewer_key, "bootstrap-technical", "bootstrap-verification-nonce"),
            ),
        )
        self.publish_bootstrap_authorization(material)

        with self.assertRaisesRegex(module.EngineeringError, "semantic.*technical|required audit"):
            module.v226_bootstrap_handoff_status(source, self.home)

    def test_v226_bootstrap_rejects_an_authorization_for_a_different_source_bundle(self):
        """Bootstrap audit facts for A cannot authorize copying clean bundle B."""
        module = self.module()
        source_a = self.installable_bundle_source()
        authorization = self.publish_bootstrap_authorization(self.bootstrap_authorization(source_a))
        other_root = Path(self.temporary_directory.name) / "bootstrap-bundle-b"
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(other_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(other_root), "config", "user.email", "synthetic"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(other_root), "config", "user.name", "Synthetic Test"],
            check=True,
        )
        source_b = other_root / ".agents" / "skills" / "engineering"
        shutil.copytree(source_a, source_b)
        (source_b / "scripts" / "engineering.py").write_text(
            "# distinct clean bootstrap bundle B\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(other_root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(other_root), "commit", "-m", "bootstrap bundle B"],
            check=True,
            capture_output=True,
            text=True,
        )

        with self.assertRaisesRegex(module.EngineeringError, "bootstrap authorization|source bundle"):
            module.install_bundle(
                source_b,
                self.home,
                bootstrap_authorization=authorization,
            )

    def test_v226_bootstrap_rejects_candidate_supplied_authorization_absent_from_host_boundary(self):
        """A candidate cannot invent the durable root package-approval record."""
        module = self.module()
        source = self.installable_bundle_source()
        authorization = self.bootstrap_authorization(source)["authorization"]

        with self.assertRaisesRegex(module.EngineeringError, "host.*bootstrap"):
            module.install_bundle(
                source,
                self.home,
                bootstrap_authorization=authorization,
            )

    def test_v226_bootstrap_reports_pre_audit_capability_without_self_authorizing(self):
        """Before audits, the supported handoff exposes evidence but never installs a candidate."""
        module = self.module()
        source = self.installable_bundle_source()
        self.installed_v225_receipt()
        with patch.object(
            module,
            "_host_owned_trust_anchor",
            create=True,
            side_effect=AssertionError("post-activation trust must not run"),
        ):
            status = module.v226_bootstrap_handoff_status(source, self.home)
        self.assertEqual("pre_audit_capability_evidence", status["state"])
        self.assertEqual("root", status["post_audit_authority"])
        self.assertEqual(
            {"installed_v225", "owner_approval", "independent_audits"},
            set(status["required_external_evidence"]),
        )
        with self.assertRaisesRegex(module.EngineeringError, "host bootstrap"):
            module.install_bundle(
                source,
                self.home,
                bootstrap_authorization={
                    "schema": "engineering.v2.2.6-bootstrap-authorization.v2",
                    "record_id": "bootstrap-record-v226",
                    "record_digest": "sha256:" + "a" * 64,
                    "source_bundle": status["source_bundle"],
                },
            )

    def test_v226_bootstrap_handoff_status_cli_is_read_only_and_exact(self):
        """The supported pre/post-audit handoff is a public read-only controller command."""
        module = self.module()
        source = Path(self.temporary_directory.name) / "candidate-skill"
        home = Path(self.temporary_directory.name) / "host-home"
        output = io.StringIO()
        expected = {
            "schema": "engineering.v2.2.6-bootstrap-handoff.v1",
            "state": "pre_audit_capability_evidence",
            "post_audit_authority": "root",
        }
        with (
            patch.object(module, "v226_bootstrap_handoff_status", return_value=expected) as status,
            patch.object(
                sys,
                "argv",
                [
                    "engineering",
                    "bootstrap-handoff-status",
                    str(source),
                    "--home",
                    str(home),
                ],
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())
        status.assert_called_once_with(source, home)
        self.assertEqual(expected, json.loads(output.getvalue()))

    def test_v226_bootstrap_fails_closed_for_invalid_external_evidence(self):
        """The host record must resolve signed, current, distinct, exact evidence."""
        module = self.module()
        source = self.installable_bundle_source()
        material = self.bootstrap_authorization(source)
        now = module.datetime.now(module.timezone.utc)
        cases = []

        forged = json.loads(json.dumps(material))
        forged["record"]["owner_approval"]["claims"]["decision"] = "owner_rejected"
        cases.append(("forged", forged))

        stale = self.bootstrap_authorization(
            source,
            issued_at=(now - module.timedelta(days=31)).isoformat().replace("+00:00", "Z"),
        )
        cases.append(("stale", stale))

        mismatched = json.loads(json.dumps(material))
        mismatched["record"]["candidate_pair"][0]["source_digest"] = "sha256:" + "f" * 64
        mismatched["authorization"]["record_digest"] = module._json_digest(
            mismatched["record"]
        )
        cases.append(("mismatched", mismatched))

        duplicate = json.loads(json.dumps(material))
        duplicate["record"]["independent_audits"] = [
            duplicate["record"]["independent_audits"][0],
            duplicate["record"]["independent_audits"][0],
        ]
        duplicate["authorization"]["record_digest"] = module._json_digest(
            duplicate["record"]
        )
        cases.append(("duplicate", duplicate))

        owner_as_auditor = json.loads(json.dumps(material))
        owner_audit_claims = owner_as_auditor["record"]["independent_audits"][1]["claims"]
        owner_audit_claims["replay_nonce"] = "bootstrap-owner-audit-nonce"
        owner_as_auditor["record"]["independent_audits"][1] = self.sign_bootstrap_evidence(
            schema="engineering.v2.2.6-bootstrap-audit.v1",
            claims_schema="engineering.v2.2.6-bootstrap-audit-claims.v1",
            claims=owner_audit_claims,
            namespace="engineering-v226-bootstrap-audit",
            contract="engineering.v2.2.6-bootstrap-audit.v1",
            signer=self.host_key,
            approver="bootstrap-owner",
        )
        owner_as_auditor["authorization"]["record_digest"] = module._json_digest(
            owner_as_auditor["record"]
        )
        cases.append(("owner_as_auditor", owner_as_auditor))

        for field, value in (
            ("repository_id", "sha256:" + "f" * 64),
            ("authority_epoch", "epoch-wrong"),
            ("contract", "engineering.wrong-bootstrap-contract.v1"),
        ):
            wrong_receipt = json.loads(json.dumps(material))
            wrong_receipt["record"]["owner_approval"]["host_receipt"][field] = value
            wrong_receipt["authorization"]["record_digest"] = module._json_digest(
                wrong_receipt["record"]
            )
            cases.append((f"wrong_{field}", wrong_receipt))

        for label, candidate in cases:
            with self.subTest(label=label):
                self.publish_bootstrap_authorization(candidate)
                with self.assertRaisesRegex(module.EngineeringError, "bootstrap"):
                    module.v226_bootstrap_handoff_status(source, self.home)

    def test_v226_bootstrap_fails_closed_when_installed_v225_receipt_is_unavailable(self):
        """A host record cannot stand in for the actual installed v2.2.5 evidence."""
        module = self.module()
        source = self.installable_bundle_source()
        material = self.bootstrap_authorization(source)
        self.publish_bootstrap_authorization(material)
        module._install_paths(self.home)["receipt"].unlink()
        with self.assertRaisesRegex(module.EngineeringError, "v2.2.5 installed receipt"):
            module.v226_bootstrap_handoff_status(source, self.home)

    def test_v226_bootstrap_replay_is_exact_and_cannot_replace_host_record(self):
        """An exact record is idempotent; a changed record cannot replace its installed receipt."""
        module = self.module()
        source = self.installable_bundle_source()
        material = self.bootstrap_authorization(source)
        authorization = self.publish_bootstrap_authorization(material)
        first = module.install_bundle(
            source, self.home, bootstrap_authorization=authorization
        )
        replay = module.install_bundle(
            source, self.home, bootstrap_authorization=authorization
        )
        self.assertEqual(first, replay)

        replacement = json.loads(json.dumps(material))
        replacement["record"]["replay_nonce"] = "bootstrap-replacement-nonce"
        replacement["authorization"]["record_digest"] = module._json_digest(
            replacement["record"]
        )
        self.publish_bootstrap_authorization(replacement)
        with self.assertRaisesRegex(module.EngineeringError, "bootstrap authorization"):
            module.install_bundle(
                source,
                self.home,
                bootstrap_authorization=replacement["authorization"],
            )

    def test_candidate_local_signer_substitution_is_rejected_after_activation(self):
        """A candidate Git signer file cannot replace the host-owned anchor."""
        module = self.module()
        binding = self.owner_intent_binding()
        trusted = self.host_owner_intent_approval(binding)
        attacker_key = Path(self.temporary_directory.name) / "attacker-host-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(attacker_key)],
            check=True,
            capture_output=True,
        )
        attacker_signers = (
            "attacker-host "
            + attacker_key.with_suffix(".pub").read_text(encoding="ascii").strip()
            + "\n"
        ).encode("ascii")
        (self.root / ".engineering-host-approvers").write_bytes(attacker_signers)
        subprocess.run(
            ["git", "-C", str(self.root), "add", ".engineering-host-approvers"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "candidate signer substitution"],
            check=True,
            capture_output=True,
        )
        trusted_record = module.bind_owner_intent(self.root, binding, trusted)
        self.assertEqual("intent-native-graph", trusted_record["intent_id"])

        attacker_anchor = self.host_anchor(
            anchor_id="host-anchor-attacker",
            signers_digest="sha256:" + hashlib.sha256(attacker_signers).hexdigest(),
        )
        attacker = self.host_owner_intent_approval(
            self.owner_intent_binding(intent_id="intent-attacker"),
            receipt_changes={"trust_anchor": attacker_anchor},
            signer=attacker_key,
        )
        with self.assertRaisesRegex(module.EngineeringError, "host.*anchor|host receipt|signature"):
            module.bind_owner_intent(
                self.root, self.owner_intent_binding(intent_id="intent-attacker"), attacker
            )

    def test_restart_preserves_host_owned_trust_and_intent_state(self):
        """A fresh controller process rereads the host anchor and retained intent ledger."""
        module = self.module()
        binding = self.owner_intent_binding()
        bound = module.bind_owner_intent(
            self.root, binding, self.host_owner_intent_approval(binding)
        )
        first_anchor, _ = module._host_owned_trust_anchor()
        restarted = load_engineering()
        with (
            patch.object(restarted, "_canonical_host_home", return_value=self.home),
            patch.object(restarted, "_verify_owner_private", return_value=None),
            patch.object(restarted, "_enforce_owner_private", side_effect=synthetic_owner_private),
        ):
            second_anchor, _ = restarted._host_owned_trust_anchor()
            status = restarted.owner_intent_status(self.root, bound["intent_id"])
        self.assertEqual(first_anchor, second_anchor)
        self.assertEqual("bound", status["state"])

    def test_host_receipt_wrong_repository_epoch_or_contract_fails_closed(self):
        """Host receipt fields are exact admission facts, not advisory metadata."""
        module = self.module()
        binding = self.owner_intent_binding()
        cases = (
            ("repository_id", "sha256:" + "f" * 64, "repository"),
            ("authority_epoch", "epoch-wrong", "epoch"),
            ("contract", "engineering.wrong-contract.v1", "contract"),
        )
        for field, value, label in cases:
            with self.subTest(field=field):
                approval = self.host_owner_intent_approval(
                    binding, receipt_changes={field: value}
                )
                with self.assertRaisesRegex(module.EngineeringError, label):
                    module.bind_owner_intent(self.root, binding, approval)

    def test_postactivation_import_is_required_before_successor_or_frontend_dispatch(self):
        """No downstream product-release or owner-outcome admission precedes import."""
        module = self.module()
        binding = self.owner_intent_binding()
        intent = module.bind_owner_intent(
            self.root, binding, self.host_owner_intent_approval(binding)
        )
        for scope in ("product_releases", "accepted_owner_outcomes"):
            with self.subTest(scope=scope), self.assertRaisesRegex(
                module.EngineeringError, "post-activation.*import"
            ):
                module.dependent_dispatch_status(self.root, scope)
        imported = self.owner_intent_import(intent)
        module.import_owner_intent(
            self.root, imported, self.owner_intent_import_approval(imported)
        )
        for scope in ("product_releases", "accepted_owner_outcomes"):
            with self.subTest(scope=scope):
                admitted = module.dependent_dispatch_status(self.root, scope)
                self.assertEqual("admitted", admitted["state"])
                self.assertEqual(imported["outcome_mapping_digest"], admitted["outcome_mapping_digest"])

    def test_postactivation_import_requires_complete_per_outcome_design_evidence_mapping(self):
        """IDs and broad scopes never substitute for row-level downstream proof."""
        module = self.module()
        binding = self.owner_intent_binding()
        intent = module.bind_owner_intent(
            self.root, binding, self.host_owner_intent_approval(binding)
        )
        complete = self.owner_intent_import(intent)
        cases = []
        missing = json.loads(json.dumps(complete))
        missing["outcome_mappings"] = []
        missing["outcome_mapping_digest"] = module._json_digest([])
        cases.append(("missing", missing))
        unknown = json.loads(json.dumps(complete))
        unknown["outcome_mappings"][0]["runtime_behavior"] = "Unknown"
        unknown["outcome_mapping_digest"] = module._json_digest(unknown["outcome_mappings"])
        cases.append(("unknown", unknown))
        proxy = json.loads(json.dumps(complete))
        proxy["outcome_mappings"][0]["required_evidence"]["class"] = "proxy"
        proxy["outcome_mapping_digest"] = module._json_digest(proxy["outcome_mappings"])
        cases.append(("proxy", proxy))
        wrong_artifact = json.loads(json.dumps(complete))
        wrong_artifact["outcome_mappings"][0]["exact_artifact"]["commit"] = "f" * 40
        wrong_artifact["outcome_mapping_digest"] = module._json_digest(
            wrong_artifact["outcome_mappings"]
        )
        cases.append(("wrong artifact", wrong_artifact))
        broad_only = {key: value for key, value in complete.items() if key not in {
            "outcome_mappings", "outcome_mapping_digest"
        }}
        broad_only["schema"] = "engineering.owner-intent-import.v1"
        cases.append(("broad scope", broad_only))
        for label, value in cases:
            with self.subTest(case=label), self.assertRaisesRegex(
                module.EngineeringError, "mapping|post-activation|import"
            ):
                module.import_owner_intent(
                    self.root, value, self.owner_intent_import_approval(value)
                )

    def test_postactivation_import_rejects_unresolvable_design_contract_and_test_references(self):
        """Plausible-looking caller strings are not exact-artifact evidence."""
        module = self.module()
        binding = self.owner_intent_binding()
        intent = module.bind_owner_intent(
            self.root, binding, self.host_owner_intent_approval(binding)
        )
        imported = self.owner_intent_import(intent)
        imported["outcome_mappings"][0]["design"] = {
            "path": "docs/invented-spec.md",
            "section": "Invented outcome design",
        }
        imported["outcome_mappings"][0]["contract"] = {
            "path": "schema/invented-outcome.json",
            "interface": "invented native interface",
        }
        imported["outcome_mappings"][0]["negative_test"] = {
            "path": "tests/test_invented_outcome.py",
            "selector": "test_invented_evidence_blocks",
        }
        imported["outcome_mapping_digest"] = module._json_digest(
            imported["outcome_mappings"]
        )
        with self.assertRaisesRegex(module.EngineeringError, "mapping.*reference|artifact"):
            module.import_owner_intent(
                self.root, imported, self.owner_intent_import_approval(imported)
            )

    def test_postactivation_import_rejects_cross_wired_outcome_evidence(self):
        """Each row must prove the evidence required by that exact owner outcome."""
        module = self.module()
        outcomes = [
            {
                "id": "OUTCOME-NATIVE-GRAPH",
                "criticality": "core",
                "statement_digest": "sha256:" + "2" * 64,
                "required_evidence": [
                    {
                        "class": "real_outcome",
                        "interface": "native_graph_harness",
                        "environment": "candidate",
                    }
                ],
            },
            {
                "id": "OUTCOME-SERVED-CONSUMER",
                "criticality": "core",
                "statement_digest": "sha256:" + "3" * 64,
                "required_evidence": [
                    {
                        "class": "end_to_end",
                        "interface": "served_consumer",
                        "environment": "served",
                    }
                ],
            },
        ]
        binding = self.owner_intent_binding(outcomes=outcomes)
        intent = module.bind_owner_intent(
            self.root, binding, self.host_owner_intent_approval(binding)
        )
        imported = self.owner_intent_import(intent)
        imported["outcome_mappings"][0]["required_evidence"] = outcomes[1][
            "required_evidence"
        ][0]
        imported["outcome_mappings"][1]["required_evidence"] = outcomes[0][
            "required_evidence"
        ][0]
        imported["outcome_mapping_digest"] = module._json_digest(
            imported["outcome_mappings"]
        )
        with self.assertRaisesRegex(module.EngineeringError, "mapping.*evidence|outcome"):
            module.import_owner_intent(
                self.root, imported, self.owner_intent_import_approval(imported)
            )

    def test_candidate_cannot_replace_host_owned_trust_anchor(self):
        """A candidate-local signer edit cannot replace the private host anchor."""
        module = self.module()
        attacker_key = Path(self.temporary_directory.name) / "attacker-host-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(attacker_key)],
            check=True,
            capture_output=True,
        )
        attacker_public = attacker_key.with_suffix(".pub").read_text(encoding="ascii").strip()
        (self.root / ".engineering-host-approvers").write_text(
            f"attacker-host {attacker_public}\n", encoding="ascii"
        )
        subprocess.run(["git", "-C", str(self.root), "add", ".engineering-host-approvers"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "candidate signer replacement"],
            check=True,
            capture_output=True,
            text=True,
        )
        binding = self.owner_intent_binding()
        trusted = module.bind_owner_intent(
            self.root, binding, self.host_owner_intent_approval(binding)
        )
        self.assertEqual(binding["intent_id"], trusted["intent_id"])
        attacker_anchor = self.host_anchor(
            anchor_id="host-anchor-attacker",
            signers_digest="sha256:" + hashlib.sha256(
                f"attacker-host {attacker_public}\n".encode("ascii")
            ).hexdigest(),
        )
        attacker_binding = self.owner_intent_binding(intent_id="intent-attacker")
        attacker_approval = self.owner_intent_approval(
            attacker_binding,
            receipt_changes={"trust_anchor": attacker_anchor},
            signer=attacker_key,
            approver="attacker-host",
        )

        with self.assertRaisesRegex(module.EngineeringError, "host.*anchor|host receipt|signature"):
            module.bind_owner_intent(
                self.root,
                attacker_binding,
                attacker_approval,
            )

    def test_caller_home_override_cannot_redirect_shared_postactivation_trust(self):
        """Caller environment cannot redirect every approval gate to attacker trust."""
        module = self.module()
        attacker_home = Path(self.temporary_directory.name) / "attacker-home"
        attacker_authority = attacker_home / ".agents" / "engineering" / "host-authority"
        attacker_authority.mkdir(parents=True)
        attacker_key = Path(self.temporary_directory.name) / "attacker-redirect-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(attacker_key)],
            check=True,
            capture_output=True,
        )
        attacker_allowed = (
            "attacker-host "
            + attacker_key.with_suffix(".pub").read_text(encoding="ascii").strip()
            + "\n"
        ).encode("ascii")
        attacker_anchor = {
            "schema": module.HOST_TRUST_ANCHOR_SCHEMA,
            "anchor_id": "host-anchor-attacker-redirect",
            "format_version": 1,
            "signers_digest": "sha256:"
            + hashlib.sha256(attacker_allowed).hexdigest(),
            "identity": {"state": "unknown"},
        }
        (attacker_authority / "allowed-signers").write_bytes(attacker_allowed)
        (attacker_authority / "host-trust-anchor.json").write_text(
            json.dumps(attacker_anchor), encoding="utf-8"
        )
        binding = self.owner_intent_binding(intent_id="intent-host-redirect")
        normalized = module._owner_intent_binding(self.root, binding)
        receipt = self.host_receipt(
            contract=module.OWNER_INTENT_SCHEMA,
            authority_epoch=normalized["authority_epoch"],
            anchor=attacker_anchor,
        )
        approval = self.sign_host_approval(
            schema=module.HOST_OWNER_INTENT_APPROVAL_SCHEMA,
            claims_schema="engineering.host-owner-intent-claims.v3",
            claims=normalized,
            namespace="engineering-owner-intent",
            contract=module.OWNER_INTENT_SCHEMA,
            authority_epoch=normalized["authority_epoch"],
            signer=attacker_key,
            approver="attacker-host",
            receipt=receipt,
        )

        with (
            patch.object(module, "_canonical_host_home", return_value=self.home, create=True),
            patch.dict(
                os.environ,
                {
                    "ENGINEERING_USER_HOME": str(attacker_home),
                    "HOME": str(attacker_home),
                    "USERPROFILE": str(attacker_home),
                },
                clear=False,
            ),
            self.assertRaisesRegex(
                module.EngineeringError, "host receipt|host.*anchor|signature"
            ),
        ):
            module.bind_owner_intent(self.root, binding, approval)

    def test_caller_home_override_cannot_mint_outcome_acceptance_or_release_token(self):
        """Outcome and release gates retain the same OS-bound external trust root."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        survival = module._outcome_survival_v2(
            self.outcome_survival_v2(intent), intent
        )
        completion, completion_digest, acceptance = self.outcome_acceptance(
            intent, survival
        )

        attacker_home = Path(self.temporary_directory.name) / "attacker-audit-home"
        attacker_authority = (
            attacker_home / ".agents" / "engineering" / "host-authority"
        )
        attacker_authority.mkdir(parents=True)
        attacker_key = Path(self.temporary_directory.name) / "attacker-audit-redirect-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(attacker_key)],
            check=True,
            capture_output=True,
        )
        attacker_allowed = (
            "attacker-auditor "
            + attacker_key.with_suffix(".pub").read_text(encoding="ascii").strip()
            + "\n"
        ).encode("ascii")
        attacker_anchor = {
            "schema": module.HOST_TRUST_ANCHOR_SCHEMA,
            "anchor_id": "host-anchor-attacker-audit-redirect",
            "format_version": 1,
            "signers_digest": "sha256:"
            + hashlib.sha256(attacker_allowed).hexdigest(),
            "identity": {"state": "unknown"},
        }
        (attacker_authority / "allowed-signers").write_bytes(attacker_allowed)
        (attacker_authority / "host-trust-anchor.json").write_text(
            json.dumps(attacker_anchor), encoding="utf-8"
        )
        acceptance["roles"]["auditor_id"] = "attacker-auditor"
        claims = module._outcome_audit_claims(acceptance)
        receipt = self.host_receipt(
            contract=module.OUTCOME_ACCEPTANCE_SCHEMA,
            authority_epoch=intent["authority_epoch"],
            anchor=attacker_anchor,
        )
        acceptance["audit_attestation"] = self.sign_host_approval(
            schema=module.INDEPENDENT_OUTCOME_AUDIT_SCHEMA,
            claims_schema="engineering.independent-outcome-audit-claims.v3",
            claims=claims,
            namespace="engineering-independent-audit",
            contract=module.OUTCOME_ACCEPTANCE_SCHEMA,
            authority_epoch=intent["authority_epoch"],
            signer=attacker_key,
            approver="attacker-auditor",
            receipt=receipt,
        )

        with (
            patch.object(module, "_terminal_completion", return_value=(completion, completion_digest)),
            patch.dict(
                os.environ,
                {
                    "ENGINEERING_USER_HOME": str(attacker_home),
                    "HOME": str(attacker_home),
                    "USERPROFILE": str(attacker_home),
                },
                clear=False,
            ),
            self.assertRaisesRegex(
                module.EngineeringError, "host receipt|host.*anchor|signature"
            ),
        ):
            module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )
        self.assertFalse(module._release_token_path(self.root).exists())

    def test_traceability_attestation_cannot_use_candidate_controlled_signers(self):
        """New traceability proof uses the same immutable external signer anchor."""
        module = self.module()
        receipt = {
            "project_id": "project-a",
            "worktree_id": "worktree-a",
            "commit": "a" * 40,
            "checkpoint": "checkpoint-a",
        }
        trusted = self.traceability_host_attestation(receipt)
        self.assertTrue(
            module._verify_traceability_host_attestation(self.root, receipt, trusted).startswith(
                "traceability-host-attestation-"
            )
        )

        attacker_key = Path(self.temporary_directory.name) / "attacker-traceability-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(attacker_key)],
            check=True,
            capture_output=True,
        )
        attacker_public = attacker_key.with_suffix(".pub").read_text(encoding="ascii").strip()
        (self.root / ".engineering-host-approvers").write_text(
            f"attacker-host {attacker_public}\n", encoding="ascii"
        )
        subprocess.run(["git", "-C", str(self.root), "add", ".engineering-host-approvers"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "candidate traceability signer replacement"],
            check=True,
            capture_output=True,
            text=True,
        )
        attacker_anchor = self.host_anchor(
            anchor_id="host-anchor-attacker",
            signers_digest="sha256:" + hashlib.sha256(
                f"attacker-host {attacker_public}\n".encode("ascii")
            ).hexdigest(),
        )
        attacker_attestation = self.traceability_host_attestation(
            receipt,
            host_receipt=self.host_receipt(
                contract="engineering.traceability-host-attestation.v2",
                anchor=attacker_anchor,
            ),
            signer=attacker_key,
            approver="attacker-host",
        )
        with self.assertRaisesRegex(module.EngineeringError, "host.*anchor|host receipt|signature"):
            module._verify_traceability_host_attestation(
                self.root, receipt, attacker_attestation
            )

    def test_intent_bind_and_status_cli_return_only_bound_owner_identity(self):
        """A valid external intent becomes queryable without exposing its source body."""
        module = self.module()
        binding = self.owner_intent_binding()
        binding_path = Path(self.temporary_directory.name) / "owner-intent.json"
        approval_path = Path(self.temporary_directory.name) / "owner-intent-approval.json"
        binding_path.write_text(json.dumps(binding), encoding="utf-8")
        approval_path.write_text(
            json.dumps(self.owner_intent_approval(binding)), encoding="utf-8"
        )
        output = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "engineering",
                    "intent-bind",
                    str(self.root),
                    "--binding-file",
                    str(binding_path),
                    "--approval-file",
                    str(approval_path),
                ],
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())
        bound = json.loads(output.getvalue())
        self.assertEqual("engineering.owner-intent.v1", bound["schema"])
        self.assertNotIn("source_body", json.dumps(bound))

        status_output = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "engineering",
                    "intent-status",
                    str(self.root),
                    "--authority-id",
                    "intent-native-graph",
                ],
            ),
            contextlib.redirect_stdout(status_output),
        ):
            self.assertEqual(0, module.main())
        status = json.loads(status_output.getvalue())
        self.assertEqual("bound", status["state"])
        self.assertEqual("intent-native-graph", status["intent_id"])

    def test_bound_owner_intent_stays_in_private_controller_state(self):
        """A binding must not materialize owner-private intent as a project artifact."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        ledger = module._owner_intent_path(self.root)
        self.assertTrue(ledger.is_file())
        common = Path(
            subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--git-common-dir"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        if not common.is_absolute():
            common = self.root / common
        self.assertTrue(ledger.is_relative_to(common.resolve()))
        status = subprocess.run(
            ["git", "-C", str(self.root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual("", status)
        self.assertNotIn("source_body", json.dumps(intent))

    def test_candidate_cannot_replace_owner_baseline_or_exclude_without_exception(self):
        """A candidate cannot supply its own baseline or self-exclude a core outcome."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        narrowed = self.outcome_survival_v2(intent)
        narrowed["baseline_ids"] = ["OUTCOME-UNIT"]
        with self.assertRaisesRegex(module.EngineeringError, "controller-injected"):
            module._outcome_survival_v2(narrowed, intent)

        omitted = self.outcome_survival_v2(intent)
        omitted["mappings"] = []
        with self.assertRaisesRegex(module.EngineeringError, "incomplete|mapping"):
            module._outcome_survival_v2(omitted, intent)

        excluded = self.outcome_survival_v2(intent)
        excluded["mappings"][0]["disposition"] = "EXCLUDED"
        with self.assertRaisesRegex(module.EngineeringError, "owner exception"):
            module._outcome_survival_v2(excluded, intent)

    def test_intent_impact_detection_follows_exact_graph_links(self):
        """Only exact links to explicit capability/assurance nodes require new intent."""
        module = self.module()
        self.assertTrue(
            {
                "capability",
                "capability_assurance",
                "assurance_obligation",
                "obligation",
            }.issubset(module.NODE_TYPES)
        )
        checkpoint = {
            "nodes": [
                {"id": "REQ-NATIVE", "type": "requirement"},
                {
                    "id": "CAP-NATIVE",
                    "type": "capability",
                    "source": {"path": "docs/native-capability.md"},
                },
                {
                    "id": "code-native",
                    "type": "code_symbol",
                    "source": {"path": "src/native_graph.py"},
                },
                {
                    "id": "code-isolated",
                    "type": "code_symbol",
                    "source": {"path": "src/capability_runtime.py"},
                },
            ],
            "edges": [
                {
                    "id": "edge-native",
                    "from": "REQ-NATIVE",
                    "to": "code-native",
                    "type": "implements",
                    "provenance": "direct",
                },
                {
                    "id": "edge-capability",
                    "from": "CAP-NATIVE",
                    "to": "code-isolated",
                    "type": "may_impact",
                    "provenance": "direct",
                },
            ],
        }
        self.assertFalse(
            module._intent_impacting(
                checkpoint, ["code-native"], None, None
            )
        )
        self.assertTrue(
            module._intent_impacting(
                checkpoint, ["code-isolated"], None, None
            )
        )
        self.assertTrue(
            module._intent_impacting(
                checkpoint,
                [],
                None,
                None,
                artifact_paths=["src/capability_runtime.py"],
            )
        )
        nodes = {item["id"]: item for item in checkpoint["nodes"]}
        selected, missing = module._explicit_context_ids(
            "change CAP-NATIVE", {}, nodes
        )
        self.assertEqual(["CAP-NATIVE"], selected)
        self.assertEqual([], missing)

    def test_controller_injects_active_owner_baseline_into_v2_handoff(self):
        """Scope approval receives mappings but never a candidate-owned baseline."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        raw = {
            "seed_evidence": ["OUTCOME-NATIVE-GRAPH"],
            "reconstructed_scope": [
                "OUTCOME-NATIVE-GRAPH",
                "evidence-native-graph",
            ],
            "architect_scope": [
                "OUTCOME-NATIVE-GRAPH",
                "evidence-native-graph",
            ],
            "result_scope": [
                "OUTCOME-NATIVE-GRAPH",
                "evidence-native-graph",
            ],
            "result_artifacts": ["src/native_graph.py"],
            "outcome_survival": self.outcome_survival_v2(intent),
        }
        bound = module._bind_owner_intent_handoff(
            self.root, module._scope_handoff(raw, require_approval=False)
        )
        survival = bound["outcome_survival"]
        self.assertEqual(["OUTCOME-NATIVE-GRAPH"], survival["baseline_ids"])
        self.assertRegex(survival["mapping_digest"], r"^sha256:[0-9a-f]{64}$")

    def test_signed_owner_exception_is_required_for_excluding_core_outcome(self):
        """Only a host-signed exception can defer or exclude an owner baseline."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        excluded = self.outcome_survival_v2(intent)
        mapping = excluded["mappings"][0]
        mapping["disposition"] = "EXCLUDED"
        mapping["owner_exception"] = self.owner_exception(
            intent, mapping["outcome_id"], "EXCLUDED"
        )
        survival = module._outcome_survival_v2(
            excluded, intent, root=self.root
        )
        self.assertEqual("EXCLUDED", survival["mappings"][0]["disposition"])

    def test_multiple_active_authorities_and_owner_exceptions_are_additive_and_idempotent(self):
        """Concurrent scopes and distinct core exceptions must not overwrite one another."""
        module = self.module()
        issued = module.datetime.now(module.timezone.utc)
        authority_a_binding = self.binding(
            target="candidate-a",
            scope=["src/a.py"],
            issued_at=issued.isoformat(),
            expires_at=(issued + module.timedelta(hours=2)).isoformat(),
        )
        authority_b_binding = self.binding(
            target="candidate-b",
            scope=["src/b.py"],
            issued_at=issued.isoformat(),
            expires_at=(issued + module.timedelta(hours=2)).isoformat(),
        )
        authority_a = self.persist(binding=authority_a_binding)
        authority_b = self.persist(binding=authority_b_binding)
        replay_a = self.persist(binding=authority_a_binding)
        self.assertEqual(authority_a["authority_id"], replay_a["authority_id"])
        self.assertNotEqual(authority_a["authority_id"], authority_b["authority_id"])
        for authority, target, scope in (
            (authority_a, "candidate-a", ["src/a.py"]),
            (authority_b, "candidate-b", ["src/b.py"]),
        ):
            with self.subTest(authority=authority["authority_id"]):
                resolved = module.resolve_scoped_authority(
                    self.root,
                    self.request(authority["authority_id"], target=target, scope=scope),
                )
                self.assertEqual("authorized", resolved["decision"])
        ledger = module._load_scoped_authorities(self.root)
        self.assertEqual(
            {authority_a["authority_id"], authority_b["authority_id"]},
            {
                item["authority_id"]
                for item in ledger["authorities"]
                if item["authority_id"] in {authority_a["authority_id"], authority_b["authority_id"]}
            },
        )

        binding = self.owner_intent_binding(
            intent_id="intent-multiple-exceptions",
            outcomes=[
                {
                    "id": "OUTCOME-NATIVE-GRAPH",
                    "criticality": "core",
                    "statement_digest": "sha256:" + "2" * 64,
                    "required_evidence": [
                        {
                            "class": "real_outcome",
                            "interface": "native_harness",
                            "environment": "candidate",
                        }
                    ],
                },
                {
                    "id": "OUTCOME-NATIVE-RECOVERY",
                    "criticality": "core",
                    "statement_digest": "sha256:" + "3" * 64,
                    "required_evidence": [
                        {
                            "class": "real_outcome",
                            "interface": "native_harness",
                            "environment": "candidate",
                        }
                    ],
                },
            ],
        )
        intent = module.bind_owner_intent(
            self.root, binding, self.owner_intent_approval(binding)
        )
        mappings = []
        for outcome_id, disposition, exception_id in (
            ("OUTCOME-NATIVE-GRAPH", "EXCLUDED", "exception-native-graph"),
            ("OUTCOME-NATIVE-RECOVERY", "DEFERRED", "exception-native-recovery"),
        ):
            mappings.append(
                {
                    "outcome_id": outcome_id,
                    "disposition": disposition,
                    "reason": "Externally authorized synthetic exception.",
                    "verification_ids": [
                        "evidence-native-graph"
                        if outcome_id == "OUTCOME-NATIVE-GRAPH"
                        else "evidence-native-recovery"
                    ],
                    "replacement_ids": [],
                    "equivalence": None,
                    "owner_exception": self.owner_exception(
                        intent,
                        outcome_id,
                        disposition,
                        exception_id=exception_id,
                    ),
                }
            )
        survival = self.outcome_survival_v2(intent, mappings=mappings)
        first = module._outcome_survival_v2(survival, intent, root=self.root)
        replay = module._outcome_survival_v2(survival, intent, root=self.root)
        self.assertEqual(first, replay)
        self.assertEqual(
            {"exception-native-graph", "exception-native-recovery"},
            {
                mapping["owner_exception"]["claims"]["exception_id"]
                for mapping in first["mappings"]
            },
        )

    def test_candidate_cannot_replace_host_owned_exception_anchor(self):
        """A candidate signer edit cannot grant itself a core-outcome exception."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        attacker_key = Path(self.temporary_directory.name) / "attacker-exception-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(attacker_key)],
            check=True,
            capture_output=True,
        )
        attacker_public = attacker_key.with_suffix(".pub").read_text(encoding="ascii").strip()
        (self.root / ".engineering-host-approvers").write_text(
            f"attacker-host {attacker_public}\n", encoding="ascii"
        )
        subprocess.run(["git", "-C", str(self.root), "add", ".engineering-host-approvers"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "candidate exception signer replacement"],
            check=True,
            capture_output=True,
            text=True,
        )
        excluded = self.outcome_survival_v2(intent)
        mapping = excluded["mappings"][0]
        mapping["disposition"] = "EXCLUDED"
        attacker_anchor = self.host_anchor(
            anchor_id="host-anchor-attacker",
            signers_digest="sha256:" + hashlib.sha256(
                f"attacker-host {attacker_public}\n".encode("ascii")
            ).hexdigest(),
        )
        mapping["owner_exception"] = self.owner_exception(
            intent,
            mapping["outcome_id"],
            "EXCLUDED",
            receipt_changes={"trust_anchor": attacker_anchor},
            signer=attacker_key,
            approver="attacker-host",
        )

        with self.assertRaisesRegex(module.EngineeringError, "host.*anchor|host receipt|signature"):
            module._outcome_survival_v2(excluded, intent, root=self.root)

    def test_replacement_requires_an_independent_equivalence_reviewer(self):
        """A candidate cannot call its own replacement equivalent to the baseline."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        replacement = self.outcome_survival_v2(intent)
        mapping = replacement["mappings"][0]
        mapping["disposition"] = "REPLACED"
        mapping["replacement_ids"] = ["replacement-native-graph"]
        mapping["equivalence"] = self.outcome_equivalence(
            reviewer_id="writer-1",
            signer=self.host_key,
            approver="writer-1",
        )
        with self.assertRaisesRegex(module.EngineeringError, "not independent"):
            module._outcome_survival_v2(replacement, intent, root=self.root)

        mapping["equivalence"] = self.outcome_equivalence()
        normalized = module._outcome_survival_v2(replacement, intent, root=self.root)
        self.assertEqual("REPLACED", normalized["mappings"][0]["disposition"])

    def test_replaced_outcome_requires_external_equivalence_attestation(self):
        """A candidate-supplied reviewer field is not independent equivalence evidence."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        replacement = self.outcome_survival_v2(intent)
        mapping = replacement["mappings"][0]
        mapping["disposition"] = "REPLACED"
        mapping["replacement_ids"] = ["replacement-native-graph"]
        mapping["equivalence"] = {
            "schema": "engineering.outcome-equivalence.v2",
            "reviewer_id": "reviewer-1",
            "architect_id": "architect-1",
            "implementer_id": "implementer-1",
            "writer_id": "writer-1",
            "evidence_id": "evidence-equivalence",
            "evidence_digest": "sha256:" + "6" * 64,
        }
        with self.assertRaisesRegex(module.EngineeringError, "external equivalence attestation"):
            module._outcome_survival_v2(replacement, intent, root=self.root)

    def test_execution_context_carries_owner_intent_digest_and_rejects_tampering(self):
        """A dispatched continuation cannot shed or replace the bound owner intent."""
        module = self.module()
        preparation = {
            "schema": "engineering.prepare.v1",
            "run_id": "run-a1b2c3",
            "project": {
                "root_digest": "sha256:" + "1" * 64,
                "commit": "a" * 40,
            },
            "authorization": {"scope": ["src/native_graph.py"]},
            "context": [{"id": "OUTCOME-NATIVE-GRAPH", "provenance": "direct"}],
            "owner_intent": {
                "schema": "engineering.owner-intent-status.v1",
                "state": "bound",
                "intent_id": "intent-native-graph",
                "owner_intent_digest": "sha256:" + "2" * 64,
                "authority_epoch": "epoch-local-1",
                "core_outcome_count": 1,
                "intent_impacting": True,
                "bound_to_scope_handoff": True,
            },
        }
        bundle = module.build_execution_context(preparation)
        self.assertEqual(
            "sha256:" + "2" * 64,
            bundle["owner_intent"]["owner_intent_digest"],
        )
        self.assertEqual(
            "enforced",
            module.validate_execution_context(
                bundle, preparation, runner_enforces_boundary=True
            )["mode"],
        )
        tampered = {**bundle, "owner_intent": {**bundle["owner_intent"], "owner_intent_digest": "sha256:" + "3" * 64}}
        with self.assertRaisesRegex(module.EngineeringError, "digest|scope|owner intent"):
            module.validate_execution_context(
                tampered, preparation, runner_enforces_boundary=True
            )

    def test_unit_evidence_cannot_satisfy_real_native_harness_requirement(self):
        """Typed evidence cannot upgrade a unit result into a native runtime proof."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        survival = module._outcome_survival_v2(
            self.outcome_survival_v2(intent), intent
        )
        completion, completion_digest, acceptance = self.outcome_acceptance(
            intent, survival, evidence_class="unit"
        )
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ), self.assertRaisesRegex(module.EngineeringError, "required evidence"):
            module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )

    def test_independent_audit_binds_role_assignments_and_outcome_states(self):
        """An attestation cannot be replayed after actor or outcome-state changes."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        survival = module._outcome_survival_v2(
            self.outcome_survival_v2(intent), intent
        )
        completion, completion_digest, acceptance = self.outcome_acceptance(
            intent, survival
        )
        acceptance["roles"]["architect_id"] = "architect-replaced"
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ), self.assertRaisesRegex(module.EngineeringError, "independent outcome audit"):
            module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )

    def test_audit_principal_must_equal_declared_auditor(self):
        """A trusted host cannot stand in for the named independent auditor."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        survival = module._outcome_survival_v2(
            self.outcome_survival_v2(intent), intent
        )
        completion, completion_digest, acceptance = self.outcome_acceptance(
            intent, survival
        )
        acceptance["audit_attestation"] = self.audit_attestation(
            acceptance,
            signer=self.host_key,
            approver="synthetic-host",
        )
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ), self.assertRaisesRegex(module.EngineeringError, "principal.*declared independent reviewer"):
            module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )

    def test_candidate_cannot_replace_host_owned_audit_anchor(self):
        """A candidate signer edit cannot manufacture an independently audited acceptance."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        survival = module._outcome_survival_v2(
            self.outcome_survival_v2(intent), intent
        )
        completion, completion_digest, acceptance = self.outcome_acceptance(
            intent, survival
        )
        attacker_key = Path(self.temporary_directory.name) / "attacker-audit-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(attacker_key)],
            check=True,
            capture_output=True,
        )
        attacker_public = attacker_key.with_suffix(".pub").read_text(encoding="ascii").strip()
        (self.root / ".engineering-host-approvers").write_text(
            f"attacker-auditor {attacker_public}\n", encoding="ascii"
        )
        subprocess.run(["git", "-C", str(self.root), "add", ".engineering-host-approvers"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "candidate audit signer replacement"],
            check=True,
            capture_output=True,
            text=True,
        )
        acceptance["roles"]["auditor_id"] = "attacker-auditor"
        attacker_anchor = self.host_anchor(
            anchor_id="host-anchor-attacker",
            signers_digest="sha256:" + hashlib.sha256(
                f"attacker-auditor {attacker_public}\n".encode("ascii")
            ).hexdigest(),
        )
        acceptance["audit_attestation"] = self.audit_attestation(
            acceptance,
            receipt_changes={"trust_anchor": attacker_anchor},
            signer=attacker_key,
            approver="attacker-auditor",
        )

        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ), self.assertRaisesRegex(module.EngineeringError, "host.*anchor|host receipt|signature"):
            module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )

    def test_accepted_evidence_must_retain_the_mapped_verification_identity(self):
        """A matching class/interface cannot swap out the approved evidence identity."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        survival = module._outcome_survival_v2(
            self.outcome_survival_v2(intent), intent
        )
        completion, completion_digest, acceptance = self.outcome_acceptance(
            intent, survival
        )
        acceptance["outcomes"][0]["evidence"][0]["evidence_id"] = "evidence-substitute"
        acceptance["evidence_digest"] = module._outcome_evidence_matrix_digest(
            acceptance["outcomes"]
        )
        acceptance["audit_attestation"] = self.audit_attestation(acceptance)
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ), self.assertRaisesRegex(module.EngineeringError, "mapped verification evidence"):
            module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )

        completion, completion_digest, acceptance = self.outcome_acceptance(
            intent, survival
        )
        acceptance["outcomes"][0]["state"] = "unknown"
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ), self.assertRaisesRegex(module.EngineeringError, "independent outcome audit"):
            module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )

    def test_v060_proxy_only_self_exclusion_cannot_receive_release_token(self):
        """v0.6.0 policy evidence cannot exclude native fan-out/fan-in runtime proof."""
        module = self.module()
        binding = self.owner_intent_binding(
            outcomes=[
                {
                    "id": "OUTCOME-EXECUTABLE-NATIVE-GRAPH",
                    "criticality": "core",
                    "statement_digest": "sha256:" + "2" * 64,
                    "required_evidence": [
                        {
                            "class": "real_outcome",
                            "interface": "executable_native_graph",
                            "environment": "candidate",
                        },
                        {
                            "class": "real_outcome",
                            "interface": "autonomous_fanout_fanin",
                            "environment": "candidate",
                        },
                        {
                            "class": "real_outcome",
                            "interface": "no_prompt_steering",
                            "environment": "candidate",
                        },
                        {
                            "class": "real_outcome",
                            "interface": "codex_native_dispatch_wake",
                            "environment": "candidate",
                        },
                        {
                            "class": "real_outcome",
                            "interface": "claude_native_dispatch_wake",
                            "environment": "candidate",
                        },
                    ],
                }
            ]
        )
        intent = module.bind_owner_intent(
            self.root, binding, self.owner_intent_approval(binding)
        )
        excluded = self.outcome_survival_v2(intent)
        excluded["mappings"][0]["disposition"] = "EXCLUDED"
        with self.assertRaisesRegex(module.EngineeringError, "owner exception"):
            module._outcome_survival_v2(excluded, intent)

        policy_kernel_unit = [
            {
                "evidence_id": "evidence-policy-kernel-unit",
                "evidence_digest": "sha256:" + "4" * 64,
                "class": "unit",
                "interface": "policy_kernel",
                "environment": "candidate",
                "producer_role": "policy_kernel",
            }
        ]
        raw_survival = self.outcome_survival_v2(intent)
        raw_survival["mappings"][0]["verification_ids"] = [
            item["evidence_id"] for item in policy_kernel_unit
        ]
        survival = module._outcome_survival_v2(raw_survival, intent)
        completion, completion_digest, acceptance = self.outcome_acceptance(
            intent, survival, evidence=policy_kernel_unit
        )
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ), self.assertRaisesRegex(module.EngineeringError, "required evidence"):
            module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )
        acceptance["outcomes"][0]["state"] = "unknown"
        acceptance["evidence_digest"] = module._outcome_evidence_matrix_digest(
            acceptance["outcomes"]
        )
        acceptance["audit_attestation"] = self.audit_attestation(acceptance)
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ):
            recorded = module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )
            with self.assertRaisesRegex(module.EngineeringError, "core outcome"):
                module.release_gate(
                    self.root, completion["run_id"], recorded["acceptance_id"]
                )

    def test_codex_and_claude_native_e2e_evidence_with_independent_auditor_receives_token(self):
        """Both native harnesses plus an independent exact-artifact audit release."""
        module = self.module()
        binding = self.owner_intent_binding(
            outcomes=[
                {
                    "id": "OUTCOME-NATIVE-GRAPH",
                    "criticality": "core",
                    "statement_digest": "sha256:" + "2" * 64,
                    "required_evidence": [
                        {
                            "class": "end_to_end",
                            "interface": "codex_native_dispatch_wake",
                            "environment": "candidate",
                        },
                        {
                            "class": "end_to_end",
                            "interface": "claude_native_dispatch_wake",
                            "environment": "candidate",
                        },
                        *[
                            {
                                "class": "real_outcome",
                                "interface": interface,
                                "environment": "candidate",
                            }
                            for interface in (
                                "capability_negotiation",
                                "authenticated_ipc",
                                "anti_replay",
                                "idempotent_effects",
                                "bounded_retry_cycle_detection",
                                "distinct_completion_states",
                            )
                        ],
                    ],
                }
            ]
        )
        intent = module.bind_owner_intent(
            self.root, binding, self.owner_intent_approval(binding)
        )
        evidence = [
            {
                "evidence_id": "evidence-codex-native",
                "evidence_digest": "sha256:" + "4" * 64,
                "class": "end_to_end",
                "interface": "codex_native_dispatch_wake",
                "environment": "candidate",
                "producer_role": "codex_native",
            },
            {
                "evidence_id": "evidence-claude-native",
                "evidence_digest": "sha256:" + "5" * 64,
                "class": "end_to_end",
                "interface": "claude_native_dispatch_wake",
                "environment": "candidate",
                "producer_role": "claude_native",
            },
            *[
                {
                    "evidence_id": f"evidence-{interface}",
                    "evidence_digest": "sha256:"
                    + hashlib.sha256(interface.encode("ascii")).hexdigest(),
                    "class": "real_outcome",
                    "interface": interface,
                    "environment": "candidate",
                    "producer_role": "independent_runtime_audit",
                }
                for interface in (
                    "capability_negotiation",
                    "authenticated_ipc",
                    "anti_replay",
                    "idempotent_effects",
                    "bounded_retry_cycle_detection",
                    "distinct_completion_states",
                )
            ],
        ]
        raw_survival = self.outcome_survival_v2(intent)
        raw_survival["mappings"][0]["verification_ids"] = [
            item["evidence_id"] for item in evidence
        ]
        survival = module._outcome_survival_v2(raw_survival, intent)
        completion, completion_digest, acceptance = self.outcome_acceptance(
            intent, survival, evidence=evidence
        )
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ):
            recorded = module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )
            token = module.release_gate(
                self.root, completion["run_id"], recorded["acceptance_id"]
            )
            verified = module.verify_release_token(
                self.root, token["token_id"], token["artifact_digest"], "activation"
            )
        self.assertEqual("engineering.release-token.v2", token["schema"])
        self.assertNotIn("install", token["actions"])
        self.assertEqual("activation", verified["action"])

    def test_install_release_token_binds_the_exact_clean_source_bundle(self):
        """An install token is issued only for the clean accepted bundle it names."""
        module = self.module()
        source = self.installable_bundle_source()
        intent = self.bound_native_owner_intent()
        survival = module._outcome_survival_v2(self.outcome_survival_v2(intent), intent)
        completion, completion_digest, acceptance = self.outcome_acceptance(intent, survival)
        completion["result_identity"]["commit"] = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        acceptance["artifact_digest"] = module._completion_artifact_digest(
            completion, completion_digest
        )
        acceptance["audit_attestation"] = self.audit_attestation(acceptance)
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ):
            recorded = module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )
            token = module.release_gate(
                self.root,
                completion["run_id"],
                recorded["acceptance_id"],
                install_source=source,
            )
            verified = module.verify_release_token(
                self.root, token["token_id"], token["artifact_digest"], "install"
            )
        _, manifest, commit, digest = module._bundle_files(source)
        tree = module._bundle_git_tree(source, commit)
        self.assertEqual(
            {
                "source_git_commit": commit,
                "source_git_tree": tree,
                "source_digest": digest,
                "skill_version": manifest["version"],
            },
            verified["source_bundle"],
        )
        self.assertRegex(verified["token_digest"], r"^sha256:[0-9a-f]{64}$")

    def test_actual_install_rejects_a_release_token_for_a_different_bundle(self):
        """A signed token for A cannot authorize copying the distinct clean bundle B."""
        module = self.module()
        source_a = self.installable_bundle_source()
        intent = self.bound_native_owner_intent()
        survival = module._outcome_survival_v2(self.outcome_survival_v2(intent), intent)
        completion, completion_digest, acceptance = self.outcome_acceptance(intent, survival)
        completion["result_identity"]["commit"] = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        acceptance["artifact_digest"] = module._completion_artifact_digest(
            completion, completion_digest
        )
        acceptance["audit_attestation"] = self.audit_attestation(acceptance)
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ):
            recorded = module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )
            token = module.release_gate(
                self.root,
                completion["run_id"],
                recorded["acceptance_id"],
                install_source=source_a,
            )

        other_root = Path(self.temporary_directory.name) / "other-bundle-project"
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(other_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(other_root), "config", "user.email", "synthetic"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(other_root), "config", "user.name", "Synthetic Test"],
            check=True,
        )
        source_b = other_root / ".agents" / "skills" / "engineering"
        shutil.copytree(source_a, source_b)
        (source_b / "scripts" / "engineering.py").write_text(
            "# distinct clean bundle B\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(other_root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(other_root), "commit", "-m", "bundle B"],
            check=True,
            capture_output=True,
            text=True,
        )

        with self.assertRaisesRegex(module.EngineeringError, "exact source bundle"):
            module.install_bundle(
                source_b,
                Path(self.temporary_directory.name) / "installed-home",
                release_token={"root": str(self.root), "token_id": token["token_id"]},
                release_artifact_digest=token["artifact_digest"],
            )

    def test_actual_install_receipt_reconciles_the_signed_source_bundle(self):
        """The installed receipt retains the signed source facts after the actual copy."""
        module = self.module()
        source = self.installable_bundle_source()
        intent = self.bound_native_owner_intent()
        survival = module._outcome_survival_v2(self.outcome_survival_v2(intent), intent)
        completion, completion_digest, acceptance = self.outcome_acceptance(intent, survival)
        completion["result_identity"]["commit"] = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        acceptance["artifact_digest"] = module._completion_artifact_digest(
            completion, completion_digest
        )
        acceptance["audit_attestation"] = self.audit_attestation(acceptance)
        with patch.object(
            module,
            "_terminal_completion",
            return_value=(completion, completion_digest),
        ):
            recorded = module.record_outcome_acceptance(
                self.root, completion["run_id"], acceptance
            )
            token = module.release_gate(
                self.root,
                completion["run_id"],
                recorded["acceptance_id"],
                install_source=source,
            )
        home = Path(self.temporary_directory.name) / "installed-home"
        with (
            patch.object(module, "_engineering_user_home", return_value=home),
            patch.object(module, "_register_windows_command_directory"),
        ):
            receipt = module.install_bundle(
                source,
                home,
                release_token={"root": str(self.root), "token_id": token["token_id"]},
                release_artifact_digest=token["artifact_digest"],
            )
        _, manifest, commit, digest = module._bundle_files(source)
        tree = module._bundle_git_tree(source, commit)
        self.assertEqual("engineering.install.v5", receipt["schema"])
        self.assertEqual(
            {
                "source_git_commit": commit,
                "source_git_tree": tree,
                "source_digest": digest,
                "skill_version": manifest["version"],
            },
            receipt["release_authorization"]["source_bundle"],
        )
        self.assertEqual(receipt["source_digest"], module._tree_digest(home / ".agents" / "skills" / "engineering"))

    def test_legacy_release_token_stays_readable_but_cannot_authorize_new_install(self):
        """Historical tokens remain inspectable but cannot acquire a v2 install privilege."""
        module = self.module()
        intent = self.bound_native_owner_intent()
        token = {
            "schema": "engineering.release-token.v1",
            "token_id": "release-token-" + "1" * 32,
            "completion_id": "run-a1b2c3",
            "completion_digest": "sha256:" + "2" * 64,
            "artifact_digest": "sha256:" + "3" * 64,
            "owner_intent_id": intent["intent_id"],
            "owner_intent_digest": intent["owner_intent_digest"],
            "mapping_digest": "sha256:" + "4" * 64,
            "evidence_digest": "sha256:" + "5" * 64,
            "acceptance_id": "acceptance-legacy",
            "acceptance_digest": "sha256:" + "6" * 64,
            "actions": ["activation", "install", "merge"],
        }
        key = module._controller_key(module._project_controller_dir(self.root), required=True)
        record = {"token": token, "issued_at": module._utc_now()}
        record["signature"] = module._release_token_signature(key, record)
        module._publish_release_tokens(
            self.root,
            {"schema": module.RELEASE_TOKEN_LEDGER_SCHEMA, "tokens": [record]},
            None,
        )

        verified = module.verify_release_token(
            self.root, token["token_id"], token["artifact_digest"], "activation"
        )
        self.assertEqual("engineering.release-token.v1", verified["schema"])
        with self.assertRaisesRegex(module.EngineeringError, "exact install source bundle"):
            module.verify_release_token(
                self.root, token["token_id"], token["artifact_digest"], "install"
            )

    def test_outcome_acceptance_and_release_gate_cli_dispatch_exact_inputs(self):
        """The public controller commands preserve exact local gate inputs."""
        module = self.module()
        source = Path(self.temporary_directory.name) / "acceptance.json"
        source.write_text("{}", encoding="utf-8")
        output = io.StringIO()
        with (
            patch.object(
                module,
                "record_outcome_acceptance",
                return_value={"schema": "engineering.outcome-acceptance.v1"},
            ) as accept,
            patch.object(
                sys,
                "argv",
                [
                    "engineering",
                    "outcome-accept",
                    str(self.root),
                    "run-a1b2c3",
                    "--input-file",
                    str(source),
                ],
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())
        accept.assert_called_once()
        self.assertEqual("run-a1b2c3", accept.call_args.args[1])
        self.assertEqual({}, accept.call_args.args[2])
        self.assertEqual("engineering.outcome-acceptance.v1", json.loads(output.getvalue())["schema"])

        with (
            patch.object(
                module,
                "release_gate",
                return_value={"schema": "engineering.release-token.v2"},
            ) as gate,
            patch.object(
                sys,
                "argv",
                [
                    "engineering",
                    "release-gate",
                    str(self.root),
                    "run-a1b2c3",
                    "--acceptance-id",
                    "acceptance-native-graph",
                ],
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(0, module.main())
        gate.assert_called_once()
        self.assertEqual(
            ("run-a1b2c3", "acceptance-native-graph"), gate.call_args.args[1:]
        )

        bundle = Path(self.temporary_directory.name) / "bundle-source"
        with (
            patch.object(
                module,
                "release_gate",
                return_value={"schema": "engineering.release-token.v2"},
            ) as gate,
            patch.object(
                sys,
                "argv",
                [
                    "engineering",
                    "release-gate",
                    str(self.root),
                    "run-a1b2c3",
                    "--acceptance-id",
                    "acceptance-native-graph",
                    "--install-source",
                    str(bundle),
                ],
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(0, module.main())
        self.assertEqual(Path(bundle), gate.call_args.kwargs["install_source"])

    def test_postactivation_import_and_dependent_status_cli_dispatch_exact_inputs(self):
        """The public controller exposes the mandatory import and read-only fence."""
        module = self.module()
        imported_path = Path(self.temporary_directory.name) / "owner-intent-import.json"
        approval_path = Path(self.temporary_directory.name) / "owner-intent-import-approval.json"
        imported_path.write_text("{}", encoding="utf-8")
        approval_path.write_text("{}", encoding="utf-8")
        output = io.StringIO()
        with (
            patch.object(
                module,
                "import_owner_intent",
                return_value={"schema": "engineering.owner-intent-import.v2"},
            ) as imported,
            patch.object(
                sys,
                "argv",
                [
                    "engineering",
                    "intent-import",
                    str(self.root),
                    "--import-file",
                    str(imported_path),
                    "--approval-file",
                    str(approval_path),
                ],
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())
        imported.assert_called_once()
        self.assertEqual({}, imported.call_args.args[1])
        self.assertEqual({}, imported.call_args.args[2])
        self.assertEqual(
            "engineering.owner-intent-import.v2", json.loads(output.getvalue())["schema"]
        )

        output = io.StringIO()
        with (
            patch.object(
                module,
                "dependent_dispatch_status",
                return_value={"state": "admitted", "dispatch_performed": False},
            ) as status,
            patch.object(
                sys,
                "argv",
                [
                    "engineering",
                    "dependent-dispatch-status",
                    str(self.root),
                    "--scope",
                    "product_releases",
                ],
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())
        status.assert_called_once()
        self.assertEqual("product_releases", status.call_args.args[1])
        self.assertEqual(False, json.loads(output.getvalue())["dispatch_performed"])


class TraceabilityViewV225ContractTests(unittest.TestCase):
    """Regression coverage for the v2.2.5 query-only traceability projection."""

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def manifest(self):
        return {
            "schema": "engineering.capability-assurance.v1",
            "capabilities": [{
                "id": "orders", "criticality": "material",
                "required_cells": ["eu", "us"],
                "required_interfaces": ["api"], "required_roles": ["owner"],
                "topology": {"artifacts_or_configurations": ["orders-image-1"], "routes": ["orders-route"], "schedules": ["on-demand"]},
            }],
            "cells": [{"id": "eu", "production": True}, {"id": "us", "production": True}],
            "obligations": [],
        }

    def receipt(self, **changes):
        value = {
            "receipt_id": "receipt-1", "project_id": "project-1", "worktree_id": "worktree-1", "commit": "a" * 40, "checkpoint": "checkpoint-1", "kind": "deployment", "result": "passed", "capability_id": "orders",
            "cell_id": "eu", "release": "r1", "interface": "api",
            "artifact": "orders-image-1", "route": "orders-route", "schedule": "on-demand",
            "observed_at": "2026-08-12T10:00:00Z", "valid_until": "2026-08-13T10:00:00Z",
            "admission": "host_attested",
        }
        value.update(changes)
        return value

    def duplicate(self, receipt, **changes):
        value = dict(receipt)
        value.update(changes)
        return value

    def live_receipts(self, **changes):
        base = self.receipt(**changes)
        kinds = ("intent", "requirement", "decision", "plan", "implementation", "code", "test", "artifact", "release", "installation", "configuration", "route", "schedule", "interface", "runtime", "deployment", "synthetic", "availability")
        receipts = [self.duplicate(base, receipt_id=f"receipt-{index + 1}", kind=kind) for index, kind in enumerate(kinds)]
        receipts.append(self.duplicate(base, receipt_id="receipt-acceptance", kind="feedback", result="accepted", role="owner"))
        return receipts

    def test_reducer_isolates_cell_release_and_scoped_incident_availability_acceptance(self):
        module = self.module()
        receipts = self.live_receipts() + [
            self.receipt(receipt_id="receipt-5", cell_id="us", release="r2", kind="incident", result="failed", severity="severe"),
            self.receipt(receipt_id="receipt-6", cell_id="us", release="r2", kind="availability", result="failed"),
            self.receipt(receipt_id="receipt-7", cell_id="us", release="r2", kind="feedback", result="rejected", role="owner"),
        ]
        eu = module.reduce_traceability_receipts(self.manifest(), "orders", "eu", receipts, "2026-08-12T12:00:00Z")
        us = module.reduce_traceability_receipts(self.manifest(), "orders", "us", receipts, "2026-08-12T12:00:00Z")
        self.assertEqual("unknown", eu["state"])
        self.assertEqual("not_live", us["state"])
        self.assertEqual("r1", eu["release"])
        self.assertEqual("r2", us["release"])

    def test_required_cell_aggregation_and_lifecycle_gaps_are_explicit(self):
        module = self.module()
        view = module.compose_traceability_view(
            self.manifest(), self.live_receipts(),
            {"project": {"identity": "sha256:" + "1" * 64}, "worktree": {"branch": "feature/v225"}, "commit": "a" * 40, "checkpoint": {"kind": "feature", "digest": "sha256:" + "2" * 64}, "graphify": {"commit": module.GRAPHIFY_COMMIT, "status": "pinned"}, "overlay": {"digest": "sha256:" + "3" * 64}, "assurance": {"digest": "sha256:" + "4" * 64}, "dirty_coverage": {"state": "unknown"}, "authority": {"state": "unknown", "reasons": ["no_live_authority"]}, "freshness": "current", "paths": ["docs/engineering/links.json"], "gaps": ["implementation"], "provenance": "synthetic"}, "2026-08-12T12:00:00Z",
        )
        capability = view["capabilities"][0]
        self.assertEqual("unknown", capability["aggregate"]["state"])
        self.assertIn("us", capability["aggregate"]["missing_required_cells"])
        self.assertIn("implementation", capability["aggregate"]["lifecycle_gaps"])

    def test_latest_receipt_replaces_stale_same_scope_evidence_and_legacy_is_not_verified_live(self):
        module = self.module()
        old = self.receipt(observed_at="2026-08-10T10:00:00Z", valid_until="2026-08-11T10:00:00Z")
        current = self.receipt(receipt_id="receipt-2", observed_at="2026-08-12T11:00:00Z", valid_until="2026-08-13T11:00:00Z")
        legacy = {key: value for key, value in current.items() if key != "admission"}
        reduced = module.reduce_traceability_receipts(self.manifest(), "orders", "eu", [old, current], "2026-08-12T12:00:00Z")
        self.assertEqual("current", reduced["freshness"])
        self.assertEqual("2026-08-12T11:00:00Z", reduced["receipts"]["deployment"]["observed_at"])
        legacy_reduced = module.reduce_traceability_receipts(self.manifest(), "orders", "eu", [legacy, self.receipt(receipt_id="receipt-3", kind="synthetic"), self.receipt(receipt_id="receipt-4", kind="availability"), self.receipt(receipt_id="receipt-5", kind="feedback", result="accepted", role="owner")], "2026-08-12T12:00:00Z")
        self.assertNotEqual("verified_live", legacy_reduced["state"])
        self.assertIn("unadmitted_evidence", legacy_reduced["gaps"])

    def test_authority_and_freshness_gaps_do_not_upgrade_claimed_live_receipts(self):
        module = self.module()
        forged = self.receipt(admission="caller_claimed", claimed_state="verified_live")
        reduced = module.reduce_traceability_receipts(self.manifest(), "orders", "eu", [forged], "2026-08-12T12:00:00Z")
        self.assertEqual("unknown", reduced["state"])
        self.assertIn("authority", reduced["gaps"])
        stale = module.reduce_traceability_receipts(self.manifest(), "orders", "eu", [self.receipt(valid_until="2026-08-12T11:00:00Z")], "2026-08-12T12:00:00Z")
        self.assertEqual("stale", stale["freshness"])

    def test_query_compatibility_and_html_use_the_identical_view_digest(self):
        module = self.module()
        view = module.compose_traceability_view(self.manifest(), [], {"commit": "b" * 40, "graphify": {"commit": module.GRAPHIFY_COMMIT}}, "2026-08-12T12:00:00Z")
        rendered = module.render_traceability_view_html(view)
        self.assertIn(view["digest"], rendered)
        self.assertIn("<main", rendered)
        self.assertIn("<table", rendered)
        self.assertEqual({"requirements": []}, module.query_result("coverage", {"nodes": [], "edges": []}))
        self.assertEqual("engineering.traceability-view.v2", view["schema"])

    def test_traceability_view_cli_is_machine_readable_and_html_receipt_repeats_the_view_digest(self):
        module = self.module()
        view = {"schema": "engineering.traceability-view.v2", "digest": "sha256:" + "a" * 64}
        for command in ("traceability", "traceability-view"):
            output = io.StringIO()
            with self.subTest(command=command):
                with (
                    patch.object(sys, "argv", ["engineering", command, ".", "--html"]),
                    patch.object(module, "resolve_project_root", return_value=Path(".")),
                    patch.object(module, "traceability_view", return_value=view),
                    patch.object(module, "write_traceability_view_html", return_value={"output": "synthetic.html", "digest": view["digest"]}),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(0, module.main())
            result = json.loads(output.getvalue())
            self.assertEqual(view["digest"], result["view"]["digest"])
            self.assertEqual(view["digest"], result["html"]["digest"])

    def test_traceability_cli_forwards_focus_commit_and_as_of_to_canonical_view(self):
        module = self.module()
        view = {"schema": "engineering.traceability-view.v2", "digest": "sha256:" + "c" * 64}
        target_commit = "d" * 40
        for command in ("traceability", "traceability-view"):
            with self.subTest(command=command):
                with (
                    patch.object(sys, "argv", [
                        "engineering", command, ".", "--focus", "code-1",
                        "--commit", target_commit, "--as-of", "2026-08-12T12:00:00Z",
                    ]),
                    patch.object(module, "resolve_project_root", return_value=Path(".")),
                    patch.object(module, "traceability_view", return_value=view) as view_mock,
                    patch("sys.stdout", new_callable=io.StringIO),
                ):
                    self.assertEqual(0, module.main())
                self.assertEqual(
                    {"as_of": "2026-08-12T12:00:00Z", "focus": "code-1", "commit": target_commit},
                    view_mock.call_args.kwargs,
                )

    def test_v2_receipt_requires_a_stable_identity_and_complete_scope(self):
        module = self.module()
        for changed in (
            {"receipt_id": None}, {"capability_id": None}, {"cell_id": None},
            {"release": None}, {"artifact": None}, {"route": None}, {"schedule": None},
        ):
            receipt = self.receipt(**changed)
            receipt = {key: value for key, value in receipt.items() if value is not None}
            with self.subTest(changed=changed), self.assertRaisesRegex(module.EngineeringError, "receipt"):
                module._traceability_receipt(receipt, module._assurance_timestamp("2026-08-12T12:00:00Z"))
        configured = self.receipt(receipt_id="receipt-config", artifact=None, configuration="config-1")
        self.assertEqual("config-1", module._traceability_receipt(configured, module._assurance_timestamp("2026-08-12T12:00:00Z"))["configuration"])

    def test_view_envelope_and_renderer_expose_governed_unknowns_without_private_paths(self):
        module = self.module()
        context = {
            "project": {"identity": "sha256:" + "1" * 64}, "worktree": {"branch": "feature/v225"},
            "commit": "c" * 40, "checkpoint": {"kind": "feature", "digest": "sha256:" + "2" * 64},
            "graphify": {"commit": module.GRAPHIFY_COMMIT, "status": "pinned"},
            "overlay": {"digest": "sha256:" + "3" * 64}, "assurance": {"digest": "sha256:" + "4" * 64},
            "dirty_coverage": {"state": "unknown"}, "authority": {"state": "unknown", "reasons": ["no_live_authority"]},
            "freshness": "stale", "paths": ["docs/engineering/links.json"], "gaps": ["checkpoint_freshness"], "provenance": "synthetic",
        }
        view = module.compose_traceability_view(self.manifest(), [], context, "2026-08-12T12:00:00Z")
        for required in ("project", "worktree", "commit", "checkpoint", "graphify", "overlay", "assurance", "dirty_coverage", "authority", "freshness", "paths", "gaps", "provenance"):
            self.assertIn(required, view["envelope"])
        document = module.render_traceability_view_html(view)
        for required in ("Authority", "Freshness", "Lifecycle matrix", "Unknown", "Relationship paths"):
            self.assertIn(required, document)
        self.assertNotIn("C:\\", document)

    def test_verified_live_requires_all_declared_lifecycle_stages_and_one_complete_scope_key(self):
        module = self.module()
        incomplete = self.live_receipts()
        incomplete = [item for item in incomplete if item["kind"] != "installation"]
        result = module.reduce_traceability_receipts(self.manifest(), "orders", "eu", incomplete, "2026-08-12T12:00:00Z")
        self.assertNotEqual("verified_live", result["state"])

    def test_plural_interface_and_role_requirements_cannot_be_satisfied_by_one_receipt_set(self):
        module = self.module()
        manifest = self.manifest()
        capability = manifest["capabilities"][0]
        capability["required_interfaces"] = ["api", "admin"]
        capability["required_roles"] = ["owner", "security"]
        capability["topology"]["artifacts_or_configurations"].append("orders-image-2")
        result = module.reduce_traceability_receipts(
            manifest, "orders", "eu", self.live_receipts(), "2026-08-12T12:00:00Z"
        )
        self.assertNotEqual("verified_live", result["state"])
        self.assertIn("interfaces", result["gaps"])
        self.assertIn("roles", result["gaps"])
        self.assertIn("intent", result["lifecycle_gaps"])

    def test_complete_trusted_lifecycle_aggregates_multiple_roles_on_one_interface(self):
        module = self.module()
        manifest = self.manifest()
        manifest["capabilities"][0]["required_roles"] = ["owner", "security"]
        receipts = self.live_receipts() + [
            self.duplicate(
                self.receipt(receipt_id="receipt-security", kind="feedback", result="accepted", role="security"),
                observed_at="2026-08-12T11:00:00Z",
            )
        ]
        trusted = [dict(item, _traceability_trust_token=module._TRACEABILITY_TRUST_TOKEN) for item in receipts]
        result = module.reduce_traceability_receipts(
            manifest, "orders", "eu", trusted, "2026-08-12T12:00:00Z",
            identity={"project_id": "project-1", "worktree_id": "worktree-1", "commit": "a" * 40, "checkpoint": "checkpoint-1"},
        )
        self.assertEqual("verified_live", result["state"])
        self.assertEqual([], result["lifecycle_gaps"])
        self.assertNotIn("roles", result["gaps"])

    def test_exact_identity_binding_rejects_a_valid_receipt_from_another_checkpoint(self):
        module = self.module()
        result = module.reduce_traceability_receipts(
            self.manifest(), "orders", "eu", self.live_receipts(), "2026-08-12T12:00:00Z",
            identity={"project_id": "project-2", "worktree_id": "worktree-1", "commit": "a" * 40, "checkpoint": "checkpoint-1"},
        )
        self.assertEqual("unknown", result["state"])
        self.assertIn("intent", result["lifecycle_gaps"])
        self.assertIn("installation", result["lifecycle_gaps"])
        mixed = self.live_receipts()
        mixed[-1] = self.duplicate(mixed[-1], artifact="orders-image-2")
        result = module.reduce_traceability_receipts(self.manifest(), "orders", "eu", mixed, "2026-08-12T12:00:00Z")
        self.assertNotEqual("verified_live", result["state"])

    def test_signed_receipt_payload_rejects_tampering_on_load(self):
        module = self.module()
        receipt = self.receipt()
        key = b"a" * 32
        payload = module._signed_traceability_receipt_payload([receipt], key)
        self.assertEqual("unadmitted", module._load_signed_traceability_receipts_payload(payload, key)[0]["admission"])
        payload["receipts"][0]["receipt"]["route"] = "other-route"
        with self.assertRaisesRegex(module.EngineeringError, "admission|receipt"):
            module._load_signed_traceability_receipts_payload(payload, key)

    def test_legacy_host_attestation_remains_readable_but_cannot_become_trusted(self):
        """v1 history is retained as evidence, never upgraded by the v2 trust path."""
        module = self.module()
        receipt = self.receipt()
        key = b"a" * 32
        normalized = module._traceability_receipt(
            receipt,
            module._assurance_timestamp(receipt["observed_at"]) + module.timedelta(minutes=5),
        )
        digest = json.loads(
            module._receipt_admission_material(normalized).decode("utf-8")
        )["receipt_digest"]
        payload = module._signed_traceability_receipt_payload(
            [receipt],
            key,
            host_attestations={
                digest: {"schema": "engineering.traceability-host-attestation.v1"}
            },
        )
        loaded = module._load_signed_traceability_receipts_payload(
            payload, key, root=Path("not-a-canonical-project")
        )
        self.assertNotIn("_traceability_trust_token", loaded[0])

    def test_map_uses_the_canonical_view_and_digest_matched_renderer(self):
        module = self.module()
        view = {"schema": module.TRACEABILITY_VIEW_SCHEMA, "digest": "sha256:" + "b" * 64, "envelope": {"commit": "d" * 40}}
        with (
            patch.object(module, "traceability_view", return_value=view),
            patch.object(module, "write_traceability_view_html", return_value={"output": "view.html", "digest": view["digest"]}),
        ):
            result = module.render_map(Path("."), open_output=False)
        self.assertEqual("engineering.map.v1", result["schema"])
        self.assertEqual(view["digest"], result["view_digest"])

    def test_relationship_projection_and_focus_include_upstream_downstream_only(self):
        module = self.module()
        checkpoint = {
            "nodes": [{"id": "intent-1"}, {"id": "code-1"}, {"id": "test-1"}, {"id": "unrelated"}],
            "edges": [
                {"from": "intent-1", "type": "refines", "to": "code-1", "provenance": "direct"},
                {"from": "code-1", "type": "verifies", "to": "test-1", "provenance": "derived"},
                {"from": "unrelated", "type": "refines", "to": None, "provenance": "missing"},
            ],
        }
        relationships, paths = module._traceability_relationships(checkpoint, "code-1")
        self.assertEqual(["code-1", "intent-1", "test-1"], paths)
        self.assertEqual(
            {("intent-1", "code-1"), ("code-1", "test-1")},
            {(item["from"], item["to"]) for item in relationships},
        )
        self.assertNotIn("unrelated", json.dumps(relationships))
        context = {"commit": "c" * 40, "relationships": relationships, "paths": paths, "focus": "code-1"}
        view = module.compose_traceability_view(self.manifest(), [], context, "2026-08-12T12:00:00Z")
        document = module.render_traceability_view_html(view)
        self.assertIn("From, type, to, and provenance", document)
        self.assertIn("intent-1", document)


if __name__ == "__main__":
    unittest.main()
