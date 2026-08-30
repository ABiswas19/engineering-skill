#!/usr/bin/env python3
"""Run project-scoped Engineering controls."""

from __future__ import annotations

import argparse
import ast
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import html
import json
import math
import os
from pathlib import Path, PosixPath, PurePosixPath
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import webbrowser
from urllib.parse import quote, unquote

_SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
sys.path.insert(0, _SCRIPT_DIRECTORY)
try:
    from engineering_host_boundary import (
        HostBoundaryError,
        canonical_host_home as _shared_canonical_host_home,
        native_powershell as _shared_native_powershell,
        native_powershell_environment as _shared_native_powershell_environment,
    )
finally:
    sys.path.remove(_SCRIPT_DIRECTORY)


GRAPHIFY_REPOSITORY = "https://github.com/safishamsi/graphify"
GRAPHIFY_TAG = "v0.9.5"
GRAPHIFY_VERSION = "0.9.5"
GRAPHIFY_COMMIT = "d89ec68af95e0cad801b56d88df383991e659823"
REQUIRED_GRAPHIFY_COMMANDS = ("update", "path", "explain")
# Graphify receives only the OS/runtime variables it needs to launch the
# absolute interpreter, locate Git, create its staged output, and preserve
# deterministic locale behavior.  In particular, HOME/USERPROFILE, proxy,
# provider, Git, SSH, and Python import settings never cross this boundary.
GRAPHIFY_ENVIRONMENT_ALLOWLIST = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
)
CLEANUP_TERMINATION_GRACE_SECONDS = 0.25
PROCESS_TREE_TERMINATION_PROOF_SECONDS = 5.0
ORPHAN_MINIMUM_AGE_SECONDS = 30.0
DEFAULT_CONTEXT_TOKEN_BUDGET = 1000
DEFAULT_INITIAL_CHECKPOINT_RECOVERY_SECONDS = 30.0
ASSURANCE_SCHEMA = "engineering.capability-assurance.v1"
TRACEABILITY_VIEW_SCHEMA = "engineering.traceability-view.v2"
TRACEABILITY_RECEIPTS_SCHEMA = "engineering.traceability-receipts.v2"
CHECKPOINT_QUARANTINE_SCHEMA = "engineering.checkpoint-quarantine.v1"
# A process-local capability used only after detached host-attestation
# verification.  It is intentionally not serializable or caller-forgeable via
# JSON, so a literal field in a receipt can never become live authority.
_TRACEABILITY_TRUST_TOKEN = object()
EXECUTION_CONTEXT_SCHEMA = "engineering.execution-context.v1"
TASK_AUTHORITY_SCHEMA = "engineering.task-authority.v2"
SCOPED_AUTHORITY_SCHEMA = "engineering.scoped-authority.v1"
AUTHORITY_LEDGER_SCHEMA = "engineering.authority-ledger.v1"
AUTHORITY_RESOLUTION_SCHEMA = "engineering.authority-resolution.v1"
AUTHORITY_AUDIT_SCHEMA = "engineering.authority-audit.v1"
OWNER_INTENT_SCHEMA = "engineering.owner-intent.v1"
OWNER_INTENT_LEDGER_SCHEMA = "engineering.owner-intents.v1"
OWNER_INTENT_STATUS_SCHEMA = "engineering.owner-intent-status.v1"
LEGACY_HOST_TRUST_ANCHOR_SCHEMA = "engineering.host-trust-anchor.v1"
HOST_TRUST_ANCHOR_SCHEMA = "engineering.host-trust-anchor.v2"
HOST_RECEIPT_SCHEMA = "engineering.host-receipt.v1"
HOST_AUTHORITY_APPROVAL_SCHEMA = "engineering.host-authority-approval.v3"
HOST_OWNER_INTENT_APPROVAL_SCHEMA = "engineering.host-owner-intent-approval.v3"
TRACEABILITY_HOST_ATTESTATION_SCHEMA = "engineering.traceability-host-attestation.v3"
OUTCOME_SURVIVAL_V2_SCHEMA = "engineering.outcome-survival.v2"
OUTCOME_EQUIVALENCE_SCHEMA = "engineering.outcome-equivalence.v2"
OWNER_EXCEPTION_SCHEMA = "engineering.host-owner-exception.v3"
OUTCOME_EQUIVALENCE_ATTESTATION_SCHEMA = "engineering.outcome-equivalence-attestation.v2"
OUTCOME_ACCEPTANCE_SCHEMA = "engineering.outcome-acceptance.v1"
OUTCOME_ACCEPTANCE_LEDGER_SCHEMA = "engineering.outcome-acceptances.v1"
INDEPENDENT_OUTCOME_AUDIT_SCHEMA = "engineering.independent-outcome-audit.v3"
LEGACY_OWNER_INTENT_IMPORT_SCHEMA = "engineering.owner-intent-import.v1"
OWNER_INTENT_IMPORT_SCHEMA = "engineering.owner-intent-import.v2"
OWNER_INTENT_IMPORT_LEDGER_SCHEMA = "engineering.owner-intent-imports.v1"
POST_ACTIVATION_IMPORT_SCOPES = {"accepted_owner_outcomes", "product_releases"}
LEGACY_RELEASE_TOKEN_SCHEMA = "engineering.release-token.v1"
RELEASE_TOKEN_SCHEMA = "engineering.release-token.v2"
RELEASE_TOKEN_LEDGER_SCHEMA = "engineering.release-tokens.v1"
LEGACY_V226_BOOTSTRAP_AUTHORIZATION_SCHEMA = "engineering.v2.2.6-bootstrap-authorization.v1"
V226_BOOTSTRAP_AUTHORIZATION_SCHEMA = "engineering.v2.2.6-bootstrap-authorization.v2"
V226_BOOTSTRAP_HOST_RECORD_SCHEMA = "engineering.v2.2.6-bootstrap-host-record.v1"
V226_BOOTSTRAP_TRUST_ANCHOR_SCHEMA = "engineering.v2.2.6-bootstrap-trust-anchor.v1"
V226_BOOTSTRAP_HOST_RECEIPT_SCHEMA = "engineering.v2.2.6-bootstrap-host-receipt.v1"
V226_BOOTSTRAP_OWNER_APPROVAL_SCHEMA = "engineering.v2.2.6-bootstrap-owner-approval.v1"
V226_BOOTSTRAP_AUDIT_SCHEMA = "engineering.v2.2.6-bootstrap-audit.v1"
V226_BOOTSTRAP_AUDIT_CATEGORIES = {"semantic", "technical"}
V226_BOOTSTRAP_MAX_EVIDENCE_AGE = timedelta(days=30)
NATIVE_APPROVAL_REQUIREMENTS = {"connector", "credential", "destructive", "system"}
MAX_SCOPED_AUTHORITIES = 256
MAX_AUTHORITY_AUDITS = 512
MAX_OWNER_INTENTS = 64
MAX_OWNER_INTENT_OUTCOMES = 256
MAX_OWNER_INTENT_EVIDENCE = 64
MAX_OUTCOME_ACCEPTANCES = 256
MAX_RELEASE_TOKENS = 256
OWNER_INTENT_CRITICALITIES = {"core", "supporting"}
OWNER_INTENT_PREDECESSOR_SCHEMA = "engineering.owner-intent-predecessor.v1"
OWNER_INTENT_PREDECESSOR_DISPOSITIONS = {
    "CARRIED_FORWARD",
    "REPLACED",
    "DEFERRED",
    "EXCLUDED",
}
OUTCOME_EVIDENCE_CLASSES = {
    "design",
    "proxy",
    "unit",
    "integration",
    "end_to_end",
    "real_outcome",
}
OUTCOME_EVIDENCE_CLASS_ORDER = {
    "design": 0,
    "proxy": 1,
    "unit": 2,
    "integration": 3,
    "end_to_end": 4,
    "real_outcome": 5,
}
OUTCOME_ACCEPTANCE_STATES = {"accepted", "failed", "unknown"}
RELEASE_TOKEN_ACTIONS = {"merge", "install", "activation"}
ASSURANCE_EVIDENCE_KINDS = {
    "intent", "requirement", "decision", "plan", "implementation", "code", "test", "artifact",
    "release", "installation", "configuration", "route", "schedule", "interface",
    "runtime",
    "implementation",
    "deployment",
    "availability",
    "synthetic",
    "feedback",
    "incident",
    "missing",
}
TASK_CHECK_EFFECTS = {
    "network",
    "connector",
    "publication",
    "deployment",
    "live_environment",
    "destructive",
}
HOOK_EVENTS = (
    "pre-commit",
    "post-commit",
    "post-merge",
    "post-checkout",
    "pre-push",
)
PRESERVED_HOOK_DIRECTORY = "engineering-traceability-preserved"
PRESERVED_HOOK_MANIFEST = "engineering-traceability-preserved.json"
MAX_PRESERVED_HOOK_ARTIFACTS = 64
MAX_PRESERVED_HOOK_BYTES = 4 * 1024 * 1024
PROVENANCE = {"direct", "derived", "inferred", "missing"}
EXACT_PROVENANCE = {"direct", "derived"}
NODE_TYPES = {
    "requirement",
    "decision",
    "specification",
    "route",
    "schema",
    "plan_task",
    "contract",
    "code_symbol",
    "test",
    "evaluation",
    "verification_receipt",
    "capability",
    "capability_assurance",
    "assurance_obligation",
    "obligation",
    "commit",
    "pull_request",
    "project",
    "checkpoint",
}
INTENT_IMPACT_GRAPH_NODE_TYPES = {
    "capability",
    "capability_assurance",
    "assurance_obligation",
    "obligation",
}
EXPLICIT_INTENT_CONTEXT_NODE_TYPES = {
    "requirement",
    "decision",
    *INTENT_IMPACT_GRAPH_NODE_TYPES,
}
EDGE_TYPES = {
    "satisfied_by",
    "decided_by",
    "specified_in",
    "planned_by",
    "implements",
    "changes_contract",
    "verified_by",
    "introduced_in",
    "reviewed_in",
    "supersedes",
    "depends_on",
    "may_impact",
}


V1_CONFIG = "engineering-traceability.json"
V1_TRACE_DIR = "docs/engineering-traceability"
V2_CONFIG = "engineering.json"
V2_TRACE_DIR = "docs/engineering"
ENGINEERING_MANAGED_START = "<!-- engineering-managed-start -->"
ENGINEERING_MANAGED_END = "<!-- engineering-managed-end -->"
ENGINEERING_GENERATED_IGNORES = ("/graphify-out/",)
LEGACY_GRAPHIFY_FILES = {
    ".graphify_analysis.json",
    ".graphify_labels.json",
    ".graphify_root",
    "GRAPH_REPORT.md",
    "graph.html",
    "graph.json",
    "needs_update",
}
GRAPHIFY_ADAPTER_PARAMETERS = (
    "watch_path",
    "changed_paths",
    "follow_symlinks",
    "force",
    "no_cluster",
    "acquire_lock",
    "block_on_lock",
)
AUTONOMY_LEVELS = {"guided", "collaborative", "steward"}
DEFAULT_AUTONOMY = "collaborative"
MATERIAL_CHANGE_CLASSES = {
    "redesign",
    "replacement",
    "capability_deletion",
    "simplification",
}
OUTCOME_SURVIVAL_DISPOSITIONS = {"INCLUDED", "REPLACED", "DEFERRED", "EXCLUDED"}
MAINTENANCE_IMPACT = {"routine", "blocking", "consequential", "ambiguous"}
MAINTENANCE_AGING_DAYS = 14
CONTRIBUTION_STATES = {
    "proposed",
    "evaluating",
    "approved_for_promotion",
    "promoted",
    "promoted_applied",
    "rejected",
}
MAX_ACTIVE_PRACTICES = 128
MAX_APPLIED_LEDGER_BYTES = 256 * 1024
CONTRIBUTION_KINDS = {
    "reusable_skill",
    "reusable_pattern",
    "reusable_test",
    "architecture_decision",
    "failure_lesson",
    "context_extraction_rule",
}
ALLOWED_PRACTICE_MODULES = {
    "setup",
    "preparation",
    "context",
    "readiness",
    "change_impact",
    "maintenance",
    "completion",
    "contribution",
}
PRACTICE_KEYS = {
    "schema",
    "title",
    "instruction",
    "applies_to",
    "verification",
    "sanitized",
}
PRACTICE_TEXT_LIMITS = {"title": 120, "instruction": 500, "verification": 300}
PRACTICE_UNSAFE = re.compile(
    r"(?i)(?:[a-z]:\\|/(?:users|home)/|https?://|\b(?:curl|wget|powershell|bash|subprocess|os\.system|git\s+clone|pip\s+install|npm\s+install|hook)\b|\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})\b)"
)
PREPARATION_BLOCKERS = {
    "ambiguous_project": "project identity or authority is ambiguous",
    "missing_current_checkpoint": "the current commit has no exact valid checkpoint",
    "conflicting_authority": "dirty work exists outside the authorized scope",
    "unapproved_contract_change": "public contract change lacks explicit approval",
    "unapproved_check_capability": "project check capability lacks explicit local approval",
    "missing_required_source": "required source or exact context is missing",
    "checkpoint_pending": "the first exact checkpoint is pending; run the reported foreground recovery",
    "semantic_matrix_incomplete": "an impacted declared ownership or routing matrix lacks atomic coverage",
    "outcome_survival_incomplete": "material change lacks a complete signed baseline outcome mapping",
    "owner_intent_required": "intent-impacting work lacks a matching external owner-intent binding",
}
PREPARATION_ADVISORIES = {
    "remote_freshness_unknown": "canonical remote freshness is unknown",
    "historical_gap_before_baseline_acceptance": (
        "historical gaps remain before baseline acceptance"
    ),
    "unrelated_maintenance": "unrelated maintenance is queued",
    "checkpoint_recovered": "the required exact checkpoint was rebuilt locally before preparation",
}


class EngineeringError(Exception):
    pass


UNITTEST_TERMINAL_SUMMARY_SCHEMA = "engineering.unittest-terminal-summary.v1"
ISOLATED_TEMP_RECEIPT_SCHEMA = "engineering.isolated-temp-preflight.v1"
ISOLATED_TEMP_PATHNAME_OBSERVATION_STATES = (
    "absent-at-observation",
    "identity-changed",
    "original-present",
    "reparse-present",
    "unknown",
)
CHECKPOINT_DIAGNOSTIC_SCHEMA = "engineering.checkpoint-diagnostic.v1"
PRESERVED_WINDOWS_TEMP_SUFFIX_LENGTH = 202
ENGINEERING_TEMP_PATH_SAFETY_MARGIN = 16
ENGINEERING_TEMP_WORST_CASE_SUFFIX_LENGTH = (
    PRESERVED_WINDOWS_TEMP_SUFFIX_LENGTH + ENGINEERING_TEMP_PATH_SAFETY_MARGIN
)


def parse_unittest_terminal_summary(log: bytes | str) -> dict:
    """Parse authoritative unittest terminal summaries without guessing."""
    if isinstance(log, bytes):
        try:
            text = log.decode("utf-8")
        except UnicodeDecodeError as error:
            raise EngineeringError("Unittest terminal output is not UTF-8.") from error
    elif isinstance(log, str):
        text = log
    else:
        raise EngineeringError("Unittest terminal output is invalid.")
    pattern = re.compile(
        r"(?m)^Ran\s+(\d+)\s+tests?\s+in\s+[^\r\n]+\r?\n"
        r"(?:\r?\n)?"
        r"(OK|FAILED)\s*(?:\(\s*([^)]*?)\s*\))?\s*$"
    )
    terminal_text = text.rstrip(" \t\r\n")
    parsed = []
    terminal_end = None
    for match in pattern.finditer(terminal_text):
        result, detail = match.group(2), match.group(3)
        values = {"failures": 0, "errors": 0, "skipped": 0}
        seen = set()
        if detail:
            for item in detail.split(","):
                field = re.fullmatch(
                    r"\s*(failures|errors|skipped)\s*=\s*(\d+)\s*", item
                )
                if field is None or field.group(1) in seen:
                    raise EngineeringError("Unittest terminal summary is ambiguous.")
                seen.add(field.group(1))
                values[field.group(1)] = int(field.group(2))
        if any(values[name] == 0 for name in seen):
            raise EngineeringError("Unittest terminal summary contains an impossible field.")
        if result == "OK" and seen - {"skipped"}:
            raise EngineeringError("Unittest terminal summary is inconsistent.")
        if result == "OK" and (values["failures"] or values["errors"]):
            raise EngineeringError("Unittest terminal summary is inconsistent.")
        if result == "FAILED" and not (values["failures"] or values["errors"]):
            raise EngineeringError("Unittest terminal summary is inconsistent.")
        counts = {"run": int(match.group(1)), **values}
        if (
            any(value > counts["run"] for value in values.values())
            or sum(values.values()) > counts["run"]
        ):
            raise EngineeringError("Unittest terminal summary totals are impossible.")
        parsed.append(counts)
        terminal_end = match.end()
    if not parsed:
        raise EngineeringError("Unittest terminal summary is absent.")
    if len(parsed) != 1 or terminal_end != len(terminal_text):
        raise EngineeringError("Unittest terminal summary is not uniquely terminal.")
    return parsed[0]


def _safe_temp_segment(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,47}", value):
        raise EngineeringError("Isolated TEMP run identity is invalid.")
    return value


def _temp_root_identity(path: Path) -> dict:
    retained = Path(path).stat(follow_symlinks=False)
    return {"device": retained.st_dev, "inode": retained.st_ino}


def _open_windows_directory_delete_handle(path: Path):
    """Open an exact directory object while denying rename/delete sharing."""
    if os.name != "nt":
        raise EngineeringError("Identity-bound TEMP deletion requires Windows.")
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    handle = kernel32.CreateFileW(
        str(Path(path)),
        0x00010000 | 0x00000080 | 0x00020000,  # DELETE | FILE_READ_ATTRIBUTES | READ_CONTROL
        0x00000001 | 0x00000002,  # FILE_SHARE_READ | FILE_SHARE_WRITE; never share delete
        None,
        3,  # OPEN_EXISTING
        0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        None,
    )
    if handle in (None, ctypes.c_void_p(-1).value):
        error = ctypes.get_last_error()
        raise EngineeringError(
            f"Identity-bound TEMP handle is unavailable (winerror={error})."
        )
    return handle


def _close_windows_handle(handle) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    if not kernel32.CloseHandle(handle):
        error = ctypes.get_last_error()
        raise EngineeringError(f"Identity-bound TEMP handle close failed (winerror={error}).")


def _windows_directory_handle_identity(handle) -> dict:
    import ctypes
    from ctypes import wintypes

    class FileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetFileInformationByHandle.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(FileInformation),
    )
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    information = FileInformation()
    if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(information)):
        error = ctypes.get_last_error()
        raise EngineeringError(
            f"Identity-bound TEMP handle identity is unavailable (winerror={error})."
        )
    return {
        "volume_serial": int(information.dwVolumeSerialNumber),
        "file_index": (int(information.nFileIndexHigh) << 32)
        | int(information.nFileIndexLow),
    }


def _mark_windows_directory_delete_on_close(handle) -> None:
    import ctypes
    from ctypes import wintypes

    class FileDispositionInformation(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOL)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetFileInformationByHandle.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    )
    kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
    disposition = FileDispositionInformation(True)
    if not kernel32.SetFileInformationByHandle(
        handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
    ):
        error = ctypes.get_last_error()
        raise EngineeringError(
            f"Identity-bound TEMP delete disposition failed (winerror={error})."
        )


def _capture_windows_directory_handle_identity(path: Path) -> dict:
    handle = _open_windows_directory_delete_handle(path)
    try:
        return _windows_directory_handle_identity(handle)
    finally:
        _close_windows_handle(handle)


def _rollback_unpublished_temp_root(root: Path, identity: dict) -> None:
    """Rollback only the exact new root before a receipt is published."""
    if (
        not root.is_dir()
        or root.is_symlink()
        or _is_reparse_point(root)
        or _temp_root_identity(root) != identity
    ):
        return
    marker = root / ".engineering-temp-owner.json"
    try:
        children = list(root.iterdir())
    except OSError:
        return
    if children == [marker] and marker.is_file() and not _is_reparse_point(marker):
        marker.unlink()
        children = []
    if not children:
        root.rmdir()


def prepare_isolated_temp_root(
    candidates: list[Path],
    run_id: str,
    candidate_root: Path,
    test_suffixes: list[str],
    max_path: int,
    long_paths_enabled: bool,
) -> dict:
    """Create one owned short TEMP root only after a deterministic path-budget check."""
    run_id = _safe_temp_segment(run_id)
    if not isinstance(max_path, int) or not 64 <= max_path <= 259:
        raise EngineeringError("Isolated TEMP path limit is invalid.")
    if long_paths_enabled:
        raise EngineeringError("Isolated TEMP preflight requires the bounded legacy path policy.")
    if not candidates or not test_suffixes:
        raise EngineeringError("Isolated TEMP preflight inputs are incomplete.")
    relative_suffixes = []
    for raw in test_suffixes:
        suffix = PurePosixPath(str(raw).replace("\\", "/"))
        if suffix.is_absolute() or not suffix.parts or ".." in suffix.parts:
            raise EngineeringError("Isolated TEMP test suffix is unsafe.")
        relative_suffixes.append(Path(*suffix.parts))
    candidate_identity = hashlib.sha256(
        os.path.normcase(str(Path(candidate_root).absolute())).encode("utf-8")
    ).hexdigest()
    root_name = "eg-" + hashlib.sha256(run_id.encode("ascii")).hexdigest()[:12]
    eligible = []
    for candidate in candidates:
        base = Path(candidate)
        if not base.is_absolute() or not base.is_dir() or _is_reparse_point(base):
            continue
        try:
            _reject_reparse_ancestors(base.absolute())
        except EngineeringError:
            continue
        resolved = base.resolve(strict=True)
        root = resolved / root_name
        lengths = [len(str(root / suffix)) for suffix in relative_suffixes]
        lengths.append(len(str(root)) + 1 + ENGINEERING_TEMP_WORST_CASE_SUFFIX_LENGTH)
        eligible.append((max(lengths), os.path.normcase(str(resolved)), resolved, root))
    if not eligible:
        raise EngineeringError("No safe isolated TEMP base is available.")
    eligible.sort(key=lambda item: (item[0], item[1]))
    worst, _, base, root = eligible[0]
    if worst > max_path:
        raise EngineeringError("Isolated TEMP path budget is unsafe.")
    if root.exists() or root.is_symlink():
        raise EngineeringError("Isolated TEMP root collides with existing state.")
    root.mkdir(mode=0o700)
    created_identity = _temp_root_identity(root)
    try:
        if _is_reparse_point(root) or root.parent.resolve(strict=True) != base:
            raise EngineeringError("Isolated TEMP root boundary is unsafe.")
        _reject_reparse_ancestors(root.absolute(), base.absolute())
        _enforce_owner_private(root)
        _verify_owner_private(root, directory=True)
        if (
            _is_reparse_point(root)
            or _temp_root_identity(root) != created_identity
            or root.parent.resolve(strict=True) != base
        ):
            raise EngineeringError("Isolated TEMP root was substituted after ACL verification.")
        marker = root / ".engineering-temp-owner.json"
        marker_value = {
            "schema": ISOLATED_TEMP_RECEIPT_SCHEMA,
            "run_id": run_id,
            "root": str(root),
            "root_name": root_name,
            "root_identity": created_identity,
        }
        marker_bytes = (json.dumps(marker_value, sort_keys=True) + "\n").encode("utf-8")
        marker.write_bytes(marker_bytes)
        if _is_reparse_point(root) or _temp_root_identity(root) != created_identity:
            raise EngineeringError("Isolated TEMP root was substituted before first use.")
        root_handle_identity = _capture_windows_directory_handle_identity(root)
    except Exception:
        _rollback_unpublished_temp_root(root, created_identity)
        raise
    return {
        **marker_value,
        "base": str(base),
        "candidate_identity": "sha256:" + candidate_identity,
        "max_path": max_path,
        "worst_case_path_length": worst,
        "long_paths_enabled": False,
        "marker_digest": "sha256:" + hashlib.sha256(marker_bytes).hexdigest(),
        "root_handle_identity": root_handle_identity,
        "owner_private_acl": {
            "applied": True,
            "verified": True,
            "contract": "owner-private-directory-v1",
        },
        "environment": {"TEMP": str(root), "TMP": str(root)},
    }


def _rollback_identity_error(state: str) -> EngineeringError:
    return EngineeringError(
        f"Isolated TEMP rollback pre-delete identity is unproven (state={state})."
    )


def _validate_isolated_temp_root_before_delete(
    root: Path, base: Path, receipt: dict
) -> dict:
    """Revalidate the exact owned object after traversal and immediately before deletion."""
    expected_identity = receipt.get("root_identity")
    marker = root / ".engineering-temp-owner.json"
    try:
        if root.is_symlink():
            raise _rollback_identity_error("reparse")
        if not root.is_dir():
            raise _rollback_identity_error("missing")
        if _is_reparse_point(root):
            raise _rollback_identity_error("reparse")
        if root.parent.resolve(strict=True) != base.resolve(strict=True):
            raise _rollback_identity_error("identity-changed")
        _reject_reparse_ancestors(root.absolute(), base.absolute())
        identity_before_acl = _temp_root_identity(root)
    except EngineeringError:
        raise
    except OSError as exc:
        raise _rollback_identity_error("unknown") from exc
    if identity_before_acl != expected_identity:
        raise _rollback_identity_error("identity-changed")
    try:
        _verify_owner_private(root, directory=True)
    except (EngineeringError, OSError) as exc:
        raise _rollback_identity_error("acl-changed") from exc
    try:
        if root.is_symlink():
            raise _rollback_identity_error("reparse")
        if not root.is_dir():
            raise _rollback_identity_error("missing")
        if _is_reparse_point(root):
            raise _rollback_identity_error("reparse")
        identity_after_acl = _temp_root_identity(root)
        if identity_after_acl != expected_identity:
            raise _rollback_identity_error("identity-changed")
        if root.parent.resolve(strict=True) != base.resolve(strict=True):
            raise _rollback_identity_error("identity-changed")
        if marker.is_symlink() or _is_reparse_point(marker) or not marker.is_file():
            raise _rollback_identity_error("marker-changed")
        marker_bytes = marker.read_bytes()
        if "sha256:" + hashlib.sha256(marker_bytes).hexdigest() != receipt.get(
            "marker_digest"
        ):
            raise _rollback_identity_error("marker-changed")
        identity_after_marker = _temp_root_identity(root)
    except EngineeringError:
        raise
    except OSError as exc:
        raise _rollback_identity_error("unknown") from exc
    if identity_after_marker != expected_identity:
        raise _rollback_identity_error("identity-changed")
    return {
        "normalized_root": os.path.normcase(os.path.abspath(root)),
        "resolved_base": os.path.normcase(str(base.resolve(strict=True))),
        "root_identity": identity_after_marker,
        "marker_digest": receipt["marker_digest"],
        "owner_private_verified": True,
        "non_reparse_verified": True,
    }


def _remove_identity_bound_isolated_temp_root(
    root: Path, base: Path, receipt: dict
) -> dict:
    """Delete only the creation-bound Windows directory object through its locked handle."""
    expected_handle_identity = receipt.get("root_handle_identity")
    if not isinstance(expected_handle_identity, dict):
        raise _rollback_identity_error("unknown")
    if root.is_symlink():
        raise _rollback_identity_error("reparse")
    if not root.is_dir():
        raise _rollback_identity_error("missing")
    if _is_reparse_point(root):
        raise _rollback_identity_error("reparse")
    handle = _open_windows_directory_delete_handle(root)
    disposition_applied = False
    try:
        handle_identity = _windows_directory_handle_identity(handle)
        if handle_identity != expected_handle_identity:
            raise _rollback_identity_error("identity-changed")
        pre_delete = _validate_isolated_temp_root_before_delete(root, base, receipt)
        if _windows_directory_handle_identity(handle) != expected_handle_identity:
            raise _rollback_identity_error("identity-changed")
        for child in list(root.iterdir()):
            if child.is_symlink() or _is_reparse_point(child):
                raise _rollback_identity_error("reparse")
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        if list(root.iterdir()):
            raise _rollback_identity_error("unknown")
        if _windows_directory_handle_identity(handle) != expected_handle_identity:
            raise _rollback_identity_error("identity-changed")
        _mark_windows_directory_delete_on_close(handle)
        disposition_applied = True
    finally:
        _close_windows_handle(handle)
    if not disposition_applied:
        raise _rollback_identity_error("unknown")
    post_close = _inspect_isolated_temp_root_after_handle_close(root, receipt)
    return {
        "pre_delete_validation": pre_delete,
        "removed_handle_identity": expected_handle_identity,
        **post_close,
        "removal_primitive": "windows-handle-disposition",
    }


def _inspect_isolated_temp_root_after_handle_close(root: Path, receipt: dict) -> dict:
    """Separate object disposition from a time-bounded pathname observation."""
    observation = _observe_isolated_temp_root_after_handle_close(root, receipt)
    if observation["state"] == "original-present":
        disposition = "original-object-retained"
    elif observation["state"] == "unknown":
        disposition = "unknown"
    else:
        disposition = "original-object-removed"
    return _publish_isolated_temp_cleanup_result(disposition, observation)


def _observe_isolated_temp_root_after_handle_close(root: Path, receipt: dict) -> dict:
    """Observe a pathname once; never promote that snapshot to durable absence."""
    expected_identity = receipt.get("root_identity")
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        current_identity = _temp_root_identity(root)
    except FileNotFoundError:
        try:
            current_identity = _temp_root_identity(root)
        except FileNotFoundError:
            return {
                "state": "absent-at-observation",
                "observed_at": observed_at,
                "identity": None,
            }
        except OSError:
            return {
                "state": "unknown",
                "observed_at": observed_at,
                "identity": None,
            }
    except OSError:
        return {
            "state": "unknown",
            "observed_at": observed_at,
            "identity": None,
        }
    if root.is_symlink() or _is_reparse_point(root):
        return {
            "state": "reparse-present",
            "observed_at": observed_at,
            "identity": current_identity,
        }
    if current_identity == expected_identity:
        return {
            "state": "original-present",
            "observed_at": observed_at,
            "identity": current_identity,
        }
    return {
        "state": "identity-changed",
        "observed_at": observed_at,
        "identity": current_identity,
    }


def _publish_isolated_temp_cleanup_result(
    original_object_disposition: str, pathname_observation: dict
) -> dict:
    """Publish only object truth plus an explicitly non-durable path snapshot."""
    if original_object_disposition not in {
        "original-object-removed",
        "original-object-retained",
        "unknown",
    }:
        raise EngineeringError("Isolated TEMP object disposition is invalid.")
    if (
        not isinstance(pathname_observation, dict)
        or pathname_observation.get("state")
        not in ISOLATED_TEMP_PATHNAME_OBSERVATION_STATES
    ):
        raise EngineeringError("Isolated TEMP pathname observation is invalid.")
    legacy_object_state = {
        "original-object-removed": "dispositioned",
        "original-object-retained": "retained",
        "unknown": "unknown",
    }[original_object_disposition]
    return {
        "state": "path-unverified",
        "original_object_disposition": original_object_disposition,
        "pathname_observation": pathname_observation,
        "original_object_state": legacy_object_state,
        "original_path_state": pathname_observation["state"],
        "post_removal_verified": False,
    }


def rollback_isolated_temp_root(receipt: dict) -> dict:
    """Remove only the freshly marked isolated root named by an exact receipt."""
    if not isinstance(receipt, dict) or receipt.get("schema") != ISOLATED_TEMP_RECEIPT_SCHEMA:
        raise EngineeringError("Isolated TEMP rollback receipt is invalid.")
    root = Path(str(receipt.get("root", "")))
    base = Path(str(receipt.get("base", "")))
    run_id = _safe_temp_segment(str(receipt.get("run_id", "")))
    if root.is_symlink():
        raise _rollback_identity_error("reparse")
    if not root.is_dir():
        raise _rollback_identity_error("missing")
    if _is_reparse_point(root):
        raise _rollback_identity_error("reparse")
    try:
        current_identity = _temp_root_identity(root)
        same_base = root.parent.resolve(strict=True) == base.resolve(strict=True)
    except OSError as exc:
        raise _rollback_identity_error("unknown") from exc
    if current_identity != receipt.get("root_identity"):
        raise _rollback_identity_error("identity-changed")
    if (
        root.name != receipt.get("root_name")
        or root.name != "eg-" + hashlib.sha256(run_id.encode("ascii")).hexdigest()[:12]
        or not same_base
    ):
        raise EngineeringError("Isolated TEMP rollback boundary is unsafe.")
    _reject_reparse_ancestors(root.absolute(), base.absolute())
    _verify_owner_private(root, directory=True)
    marker = root / ".engineering-temp-owner.json"
    if (
        not marker.is_file()
        or "sha256:" + hashlib.sha256(marker.read_bytes()).hexdigest()
        != receipt.get("marker_digest")
    ):
        raise EngineeringError("Isolated TEMP rollback ownership is unproven.")
    for child in root.rglob("*"):
        if child.is_symlink() or _is_reparse_point(child):
            raise EngineeringError("Isolated TEMP rollback contains a reparse boundary.")
    removal = _remove_identity_bound_isolated_temp_root(root, base, receipt)
    return {
        "schema": "engineering.isolated-temp-rollback.v1",
        "root": str(root),
        "root_identity": receipt["root_identity"],
        "removed_identity": removal["pre_delete_validation"]["root_identity"],
        "removed_handle_identity": removal["removed_handle_identity"],
        "pre_delete_validation": removal["pre_delete_validation"],
        "owner_private_verified_before_delete": True,
        "original_object_disposition": removal["original_object_disposition"],
        "pathname_observation": removal["pathname_observation"],
        "original_path_state": removal["original_path_state"],
        "original_object_state": removal["original_object_state"],
        "post_removal_verified": removal["post_removal_verified"],
        "removal_primitive": removal["removal_primitive"],
        "state": removal["state"],
    }


def _diagnostic_path_snapshot(path: Path) -> dict:
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return {"path": str(path), "state": "missing"}
    stat_result = path.lstat()
    result = {
        "path": str(path),
        "state": "reparse" if _is_reparse_point(path) else ("directory" if path.is_dir() else "file"),
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
    }
    if result["state"] == "file":
        result["digest"] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    elif result["state"] == "directory":
        rows = []
        for child in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
            relative = child.relative_to(path).as_posix()
            if child.is_symlink() or _is_reparse_point(child):
                rows.append([relative, "reparse", None])
            elif child.is_file():
                rows.append([relative, "file", hashlib.sha256(child.read_bytes()).hexdigest()])
            elif child.is_dir():
                rows.append([relative, "directory", None])
            else:
                rows.append([relative, "other", None])
        result["digest"] = "sha256:" + hashlib.sha256(
            json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
    return result


def capture_checkpoint_diagnostic(
    *,
    paths: dict[str, Path],
    environment: dict[str, str],
    processes: list[dict],
    observations: dict,
) -> dict:
    """Capture caller-observed causal inputs without changing checkpoint state."""
    path_snapshots = {
        str(name): _diagnostic_path_snapshot(Path(path))
        for name, path in sorted(paths.items())
    }
    process_rows = sorted(
        (dict(row) for row in processes),
        key=lambda row: (str(row.get("started_at", "")), int(row.get("pid", -1))),
    )
    observations = dict(observations)
    if (
        observations.get("path_error") is True
        and isinstance(observations.get("longest_path"), int)
        and isinstance(observations.get("path_limit"), int)
        and observations["longest_path"] > observations["path_limit"]
    ):
        classification = "PATH_ENVIRONMENT"
    elif (
        observations.get("shared_identity_conflict") is True
        and observations.get("overlap_proven") is True
    ):
        classification = "PROCESS_SHARED_STATE_INTERFERENCE"
    elif (
        observations.get("isolated_reproduction") is True
        and observations.get("expected_mismatch") is True
        and observations.get("clean_precondition") is True
    ):
        classification = "CODE_DEFECT"
    else:
        classification = "UNKNOWN"
    return {
        "schema": CHECKPOINT_DIAGNOSTIC_SCHEMA,
        "classification": classification,
        "paths": path_snapshots,
        "environment": {str(key): str(environment[key]) for key in sorted(environment)},
        "processes": process_rows,
        "observations": observations,
    }


TraceabilityError = EngineeringError


def _canonical_host_home() -> Path:
    try:
        return _shared_canonical_host_home()
    except HostBoundaryError as error:
        raise EngineeringError("Engineering canonical host home is unavailable.") from error


@dataclass(frozen=True)
class ProjectIdentity:
    root: Path
    common_dir: Path
    branch: str
    commit: str
    default_branch: str | None


@dataclass(frozen=True)
class GraphifyIdentity:
    executable: Path
    repository: str
    version: str
    commit: str
    required_commands: tuple[str, ...]


class BundleSnapshot(tuple):
    """Four-field compatibility tuple plus exact Git-object publication data."""

    def __new__(cls, files, manifest, commit, digest, source_git_tree, blobs):
        value = super().__new__(cls, (files, manifest, commit, digest))
        value.source_git_tree = source_git_tree
        value.blobs = blobs
        return value


def controller_argv() -> list[str]:
    """Return the installed launcher; raw Python remains troubleshooting only."""
    launcher = Path(__file__).with_name("engineering.cmd" if os.name == "nt" else "engineering")
    return [str(launcher.resolve())] if launcher.is_file() else [sys.executable, str(Path(__file__).resolve())]


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 15,
) -> str:
    if env is None and command and Path(command[0]).name.casefold() in {"git", "git.exe"}:
        env = _controller_git_environment()
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout, env=env
    )
    if result.returncode:
        raise TraceabilityError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _controller_git_environment() -> dict[str, str]:
    """Return host-native execution state without caller-routed Git state."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def git(root: Path, *arguments: str) -> str:
    return run(
        ["git", "-C", str(root), *arguments], env=_controller_git_environment()
    )


def _identity_git(root: Path, *arguments: str) -> str:
    """Run Git for trust decisions without caller-controlled Git state."""
    environment = _controller_git_environment()
    environment.update(
        {
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
    )
    return run(
        ["git", "--no-replace-objects", "-C", str(root), *arguments],
        env=environment,
    )


def _host_trust_anchor(value: object) -> dict:
    """Validate a current host-owned anchor or a readable legacy anchor."""
    if not isinstance(value, dict):
        raise EngineeringError("Engineering host trust anchor is invalid.")
    if value.get("schema") == HOST_TRUST_ANCHOR_SCHEMA:
        expected = {"schema", "anchor_id", "format_version", "signers_digest", "identity"}
        if (
            set(value) != expected
            or not isinstance(value.get("format_version"), int)
            or value["format_version"] != 1
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("signers_digest", "")))
            or value.get("identity") != {"state": "unknown"}
        ):
            raise EngineeringError("Engineering host trust anchor is invalid.")
        try:
            anchor_id = _assurance_id(value.get("anchor_id"), "host trust anchor")
        except EngineeringError as error:
            raise EngineeringError("Engineering host trust anchor is invalid.") from error
        return {
            "schema": HOST_TRUST_ANCHOR_SCHEMA,
            "anchor_id": anchor_id,
            "format_version": 1,
            "signers_digest": value["signers_digest"],
            "identity": {"state": "unknown"},
        }
    legacy_expected = {
        "schema",
        "remote_url_digest",
        "default_ref",
        "commit",
        "tree",
        "signers_blob",
        "signers_digest",
    }
    default_ref = value.get("default_ref")
    if (
        set(value) != legacy_expected
        or value.get("schema") != LEGACY_HOST_TRUST_ANCHOR_SCHEMA
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("remote_url_digest", "")))
        or not isinstance(default_ref, str)
        or not default_ref.startswith("refs/heads/")
        or not re.fullmatch(r"refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]*", default_ref)
        or ".." in default_ref
        or "//" in default_ref
        or "@{" in default_ref
        or any(
            not re.fullmatch(r"[0-9a-f]{40}", str(value.get(name, "")))
            for name in ("commit", "tree", "signers_blob")
        )
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("signers_digest", "")))
    ):
        raise EngineeringError("Engineering host trust anchor is invalid.")
    return dict(value)


def _host_authority_dir() -> Path:
    path = _canonical_host_home() / ".agents" / "engineering" / "host-authority"
    _reject_reparse_ancestors(path)
    return path


def _host_owned_trust_anchor(root: Path | None = None) -> tuple[dict, bytes]:
    """Read the host-owned post-activation trust material outside candidate Git."""
    directory = _host_authority_dir()
    anchor_path = directory / "host-trust-anchor.json"
    signers_path = directory / "allowed-signers"
    try:
        _reject_reparse_ancestors(directory)
        _reject_reparse_ancestors(anchor_path, directory)
        _reject_reparse_ancestors(signers_path, directory)
        _verify_owner_private(directory, directory=True)
        _verify_owner_private(anchor_path, directory=False)
        _verify_owner_private(signers_path, directory=False)
        anchor = _host_trust_anchor(json.loads(anchor_path.read_text(encoding="utf-8")))
        allowed = signers_path.read_bytes()
    except (OSError, json.JSONDecodeError, EngineeringError) as error:
        raise EngineeringError("Engineering host-owned trust is unavailable.") from error
    if (
        anchor.get("schema") != HOST_TRUST_ANCHOR_SCHEMA
        or not allowed
        or len(allowed) > 65536
        or b"\x00" in allowed
        or anchor["signers_digest"]
        != "sha256:" + hashlib.sha256(allowed).hexdigest()
    ):
        raise EngineeringError("Engineering host-owned trust is invalid.")
    if root is not None:
        try:
            project_root = resolve_project_root(str(root))
            if directory.resolve().is_relative_to(project_root.resolve()):
                raise EngineeringError("Engineering host-owned trust is inside candidate Git.")
        except (OSError, ValueError) as error:
            raise EngineeringError("Engineering host-owned trust is unavailable.") from error
    return anchor, allowed


def _host_receipt(
    root: Path,
    value: object,
    *,
    anchor: dict,
    authority_epoch: str | None,
    contract: str,
) -> dict:
    expected = {
        "schema",
        "receipt_id",
        "repository_id",
        "authority_epoch",
        "contract",
        "identity",
        "trust_anchor",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != HOST_RECEIPT_SCHEMA
        or value.get("repository_id") != _project_contribution_digest(root)
        or value.get("contract") != contract
        or value.get("trust_anchor") != anchor
        or value.get("identity") != {"state": "unknown"}
    ):
        raise EngineeringError("Engineering host receipt repository or contract is mismatched.")
    try:
        receipt_id = _assurance_id(value.get("receipt_id"), "host receipt")
        receipt_epoch = _assurance_id(value.get("authority_epoch"), "host receipt epoch")
    except EngineeringError as error:
        raise EngineeringError("Engineering host receipt is invalid.") from error
    if authority_epoch is not None and receipt_epoch != authority_epoch:
        raise EngineeringError("Engineering host receipt authority epoch is mismatched.")
    return {
        "schema": HOST_RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "repository_id": value["repository_id"],
        "authority_epoch": receipt_epoch,
        "contract": contract,
        "identity": {"state": "unknown"},
        "trust_anchor": anchor,
    }


def _verify_host_owned_signature(
    root: Path,
    approval: object,
    *,
    approval_schema: str,
    claims_schema: str,
    claims: dict,
    namespace: str,
    label: str,
    reference_prefix: str,
    contract: str,
    authority_epoch: str | None,
    required_principal: str | None = None,
) -> tuple[str, dict]:
    """Verify a new approval against the host-owned post-activation boundary."""
    anchor, allowed = _host_owned_trust_anchor(root)
    expected = {"schema", "approver", "claims", "host_receipt", "signature"}
    if (
        not isinstance(approval, dict)
        or set(approval) != expected
        or approval.get("schema") != approval_schema
        or approval.get("claims") != claims
        or not isinstance(approval.get("signature"), str)
        or not approval["signature"].startswith("-----BEGIN SSH SIGNATURE-----\n")
        or len(approval["signature"]) > 16384
    ):
        raise EngineeringError(f"{label} is invalid.")
    try:
        approver = _assurance_id(approval.get("approver"), f"{label} approver")
    except EngineeringError as error:
        raise EngineeringError(f"{label} is invalid.") from error
    if required_principal is not None and approver != required_principal:
        raise EngineeringError(f"{label} principal is not the declared independent reviewer.")
    receipt = _host_receipt(
        root,
        approval.get("host_receipt"),
        anchor=anchor,
        authority_epoch=authority_epoch,
        contract=contract,
    )
    material = _canonical_json(
        {"schema": claims_schema, "claims": claims, "host_receipt": receipt}
    )
    with tempfile.TemporaryDirectory(prefix="engineering-external-host-") as temporary:
        allowed_path = Path(temporary) / "allowed_signers"
        signature_path = Path(temporary) / "approval.sig"
        allowed_path.write_bytes(allowed)
        signature_path.write_text(approval["signature"], encoding="ascii")
        try:
            verified = subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_path),
                    "-I",
                    approver,
                    "-n",
                    namespace,
                    "-s",
                    str(signature_path),
                ],
                input=material,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EngineeringError(f"{label} verification is unavailable.") from error
    if verified.returncode != 0:
        raise EngineeringError(f"{label} signature is invalid.")
    reference = reference_prefix + hashlib.sha256(
        _canonical_json({"approval": approval, "host_receipt": receipt})
    ).hexdigest()[:32]
    return reference, anchor


def resolve_project_root(candidate: str) -> Path:
    root = Path(candidate).expanduser().resolve()
    if not root.is_dir():
        raise TraceabilityError(f"Project root does not exist: {root}")
    child_roots = set()
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            child_root = Path(git(child, "rev-parse", "--show-toplevel")).resolve()
            if child_root != root:
                child_roots.add(child_root)
        except TraceabilityError:
            pass
    if len(child_roots) > 1:
        raise TraceabilityError(
            "Refusing umbrella workspace: select exactly one Git project root."
        )
    try:
        project_root = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
        return root if os.path.samefile(root, project_root) else project_root
    except TraceabilityError as error:
        raise TraceabilityError(f"Not a Git project root: {root}") from error


def pre_repository_advisory(candidate: str) -> dict | None:
    """Bounded no-write first-use state for one folder that has no Git identity."""
    root = Path(candidate).expanduser().resolve()
    if not root.is_dir():
        raise TraceabilityError(f"Project root does not exist: {root}")
    try:
        git(root, "rev-parse", "--show-toplevel")
        return None
    except TraceabilityError:
        pass
    nested = []
    for child in root.iterdir():
        if child.is_dir():
            try:
                nested.append(Path(git(child, "rev-parse", "--show-toplevel")).resolve())
            except TraceabilityError:
                pass
    if nested:
        raise TraceabilityError(
            "Refusing umbrella workspace: select one folder that is not already another Git project."
        )
    return {
        "schema": "engineering.pre-repository.v1",
        "state": "not_version_controlled",
        "root": str(root),
        "readiness": "advisory",
        "canonical_map": "unknown",
        "next_action": "Initialize local Git and adopt Engineering when ready; this creates no remote or publication.",
    }


def pre_repository_setup_preview(advisory: dict) -> dict:
    plan = {
        "schema": "engineering.project-controls-plan.v1",
        "root": advisory["root"],
        "commands": [["git", "init", advisory["root"]]],
        "preserves_existing_files": True,
    }
    return {
        "schema": "engineering.setup.v2",
        "readiness": "proposal",
        "state": "not_version_controlled",
        "project_controls": plan,
        "project_plan_digest": _plan_digest(plan),
        "next_action": "Authorize this combined local Git-and-Engineering setup plan when ready; it creates no remote, commit, or publication.",
    }


def verify_graphify(executable: Path | str) -> GraphifyIdentity:
    interpreter = Path(executable).expanduser().resolve()
    if not interpreter.is_file():
        raise EngineeringError(
            f"Graphify is missing: interpreter not found at {interpreter}."
        )
    try:
        distribution = run(
            [
                str(interpreter),
                "-c",
                "import importlib.metadata as m; "
                "d=m.distribution('graphifyy'); "
                "print(d.version); "
                "print(d.read_text('direct_url.json') or '{}')",
            ]
        )
    except EngineeringError as error:
        raise EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        ) from error

    version, _, direct_url_text = distribution.partition("\n")
    try:
        direct_url = json.loads(direct_url_text)
        repository = direct_url["url"].removesuffix(".git")
        commit = direct_url["vcs_info"]["commit_id"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise EngineeringError(
            "Graphify identity is not bound to the reviewed pinned source."
        ) from error
    help_text = run([str(interpreter), "-m", "graphify", "--help"])
    missing = [
        command
        for command in REQUIRED_GRAPHIFY_COMMANDS
        if not re.search(rf"^\s*{re.escape(command)}(?:\s|$)", help_text, re.MULTILINE)
    ]
    if (
        version != GRAPHIFY_VERSION
        or repository != GRAPHIFY_REPOSITORY
        or commit != GRAPHIFY_COMMIT
        or missing
    ):
        raise EngineeringError(
            "Graphify is incompatible with the reviewed pinned identity "
            f"({version}, {commit or 'unknown'}); missing commands: "
            f"{', '.join(missing) or 'none'}."
        )
    return GraphifyIdentity(
        executable=interpreter,
        repository=GRAPHIFY_REPOSITORY,
        version=version,
        commit=commit,
        required_commands=REQUIRED_GRAPHIFY_COMMANDS,
    )


def graphify_install_argv(ref: str) -> list[str]:
    if ref not in {GRAPHIFY_TAG, GRAPHIFY_COMMIT}:
        raise EngineeringError("Graphify installation must use the reviewed pinned ref.")
    return [
        "uv",
        "tool",
        "install",
        f"git+{GRAPHIFY_REPOSITORY}.git@{GRAPHIFY_COMMIT}",
    ]


def _run_graphify_install(argv: list[str]) -> None:
    raise EngineeringError(
        "Legacy uv Graphify installation is not authorized by governed setup."
    )


def _interpreter_identity(root: Path, executable: Path | str) -> dict:
    supplied = Path(executable).expanduser()
    if not supplied.is_absolute():
        raise EngineeringError("Graphify interpreter must be an exact absolute path.")
    interpreter = supplied.resolve()
    _reject_reparse_ancestors(interpreter)
    if not interpreter.is_file() or _is_reparse_point(interpreter):
        raise EngineeringError("Graphify interpreter is unavailable or a reparse point.")
    try:
        interpreter.relative_to(root.resolve())
    except ValueError:
        pass
    else:
        raise EngineeringError("Graphify interpreter must be outside the project root.")
    return {
        "path": str(interpreter),
        "sha256": "sha256:" + hashlib.sha256(interpreter.read_bytes()).hexdigest(),
        "version": run(
            [str(interpreter), "--version"], env=_check_environment(), timeout=15
        ),
    }


def _governed_graphify_install_argv(interpreter: dict) -> list[str]:
    return [
        interpreter["path"],
        "-m",
        "pip",
        "install",
        f"git+{GRAPHIFY_REPOSITORY}.git@{GRAPHIFY_COMMIT}",
    ]


def _run_governed_graphify_install(argv: list[str], interpreter: dict) -> None:
    expected = _governed_graphify_install_argv(interpreter)
    if argv != expected:
        raise EngineeringError("Graphify installation argv does not match the pinned plan.")
    run(argv, env=_check_environment(), timeout=120)


def default_branch(root: Path) -> str:
    try:
        branch = git(
            root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"
        )
        git(root, "rev-parse", "--verify", f"refs/remotes/{branch}")
        return branch.removeprefix("origin/")
    except TraceabilityError:
        pass
    try:
        detail = git(root, "remote", "show", "-n", "origin")
        matches = re.findall(r"(?m)^\s*HEAD branch:\s*([^\s]+)\s*$", detail)
        if len(matches) != 1 or matches[0] in {"(not queried)", "unknown"}:
            raise ValueError
        branch = matches[0]
        git(root, "rev-parse", "--verify", f"refs/remotes/origin/{branch}")
        return branch
    except (TraceabilityError, ValueError) as error:
        raise TraceabilityError("Default branch identity is ambiguous.") from error


def project_name(root: Path) -> str:
    common = Path(git(root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (root / common).resolve()
    return common.parent.name if common.name == ".git" else root.name


def resolve_project(root: Path) -> ProjectIdentity:
    project_root = resolve_project_root(str(root))
    common = Path(git(project_root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (project_root / common).resolve()
    return ProjectIdentity(
        root=project_root,
        common_dir=common,
        branch=git(project_root, "symbolic-ref", "--quiet", "--short", "HEAD"),
        commit=git(project_root, "rev-parse", "HEAD"),
        default_branch=default_branch(project_root),
    )


def _tracked_manifest_name(root: Path) -> str | None:
    tracked = []
    for manifest_name in (V1_CONFIG, V2_CONFIG):
        try:
            git(root, "ls-files", "--error-unmatch", "--", manifest_name)
            tracked.append(manifest_name)
        except TraceabilityError:
            pass
    if not tracked:
        return None
    if len(tracked) != 1:
        raise EngineeringError(
            "invalid_manifest: exactly one Engineering manifest must be tracked"
        )
    return tracked[0]


def resolve_hook_project(root: Path) -> ProjectIdentity | None:
    if _tracked_manifest_name(root) is None:
        return None
    project_root = resolve_project_root(str(root))
    common = Path(git(project_root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (project_root / common).resolve()
    return ProjectIdentity(
        root=project_root,
        common_dir=common,
        branch=git(project_root, "symbolic-ref", "--quiet", "--short", "HEAD"),
        commit=git(project_root, "rev-parse", "HEAD"),
        default_branch=None,
    )


def load_project_config(root: Path) -> dict[str, object]:
    candidate = Path(root).expanduser().absolute()
    resolved = resolve_project_root(str(root))
    project_root = candidate if os.path.samefile(candidate, resolved) else resolved
    legacy = project_root / V1_CONFIG
    current = project_root / V2_CONFIG
    source_path = legacy if legacy.is_file() else current
    if source_path.is_file():
        try:
            config = json.loads(source_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise EngineeringError(f"Invalid Engineering configuration: {source_path}") from error
        if not isinstance(config, dict):
            raise EngineeringError("Engineering configuration must be a JSON object.")
    else:
        config = {"version": 2}
    return {**config, "source_path": source_path}


def _save_project_config(root: Path, config: dict[str, object]) -> None:
    source = Path(config["source_path"])
    project_root = resolve_project_root(str(root))
    if not source.is_file() or source.parent.resolve() != project_root.resolve():
        raise EngineeringError("Engineering project configuration is not adopted.")
    payload = {key: value for key, value in config.items() if key != "source_path"}
    _atomic_text(source, json.dumps(payload, indent=2) + "\n")


def get_autonomy(root: Path) -> str:
    level = load_project_config(root).get("autonomy", DEFAULT_AUTONOMY)
    if level not in AUTONOMY_LEVELS:
        raise EngineeringError(f"Invalid Engineering autonomy: {level}")
    return level


def _ensure_autonomy(root: Path, *, persist: bool = True) -> dict:
    config = load_project_config(root)
    level = config.get("autonomy", DEFAULT_AUTONOMY)
    if level not in AUTONOMY_LEVELS:
        raise EngineeringError(f"Invalid Engineering autonomy: {level}")
    explain = config.get("autonomy_explained") is not True
    if persist and (explain or "autonomy" not in config):
        config.update(autonomy=level, autonomy_explained=True)
        _save_project_config(root, config)
    return {
        "autonomy": level,
        "explain_autonomy": explain,
        "explanation": (
            "Collaborative is the default: it repairs routine in-scope drift and "
            "queues unrelated work. Guided asks before project edits. Steward also "
            "processes safe queued maintenance when Engineering runs; no level "
            "publishes, deploys, or bypasses approval."
            if explain
            else None
        ),
    }


def set_autonomy(root: Path, level: str) -> dict:
    if level not in AUTONOMY_LEVELS:
        raise EngineeringError(f"Invalid Engineering autonomy: {level}")
    project_root = resolve_project_root(str(root))
    operation = _begin_completion(project_root, "autonomy-change")
    try:
        config = load_project_config(project_root)
        source = Path(config["source_path"])
        _validate_project_controls(project_root, "WORKTREE", source.name)
        previous = config.get("autonomy", DEFAULT_AUTONOMY)
        if previous not in AUTONOMY_LEVELS:
            raise EngineeringError(f"Invalid Engineering autonomy: {previous}")
        history = config.get("history", [])
        dedicated = config.get("autonomy_history", [])
        if not isinstance(history, list) or not isinstance(dedicated, list):
            raise EngineeringError("Engineering project history is invalid.")
        migrated = [
            entry
            for entry in history
            if isinstance(entry, dict) and entry.get("kind") == "autonomy_change"
        ]
        unrelated_history = [
            entry
            for entry in history
            if not (isinstance(entry, dict) and entry.get("kind") == "autonomy_change")
        ]
        autonomy_history = []
        seen_history = set()
        for entry in [*migrated, *dedicated]:
            if not isinstance(entry, dict):
                raise EngineeringError("Engineering project history is invalid.")
            identity = json.dumps(entry, sort_keys=True, separators=(",", ":"))
            if identity not in seen_history:
                seen_history.add(identity)
                autonomy_history.append(entry)
        if any(
            set(entry)
            != {"kind", "previous", "new", "changed_at", "origin", "reason"}
            or entry["previous"] not in AUTONOMY_LEVELS
            or entry["new"] not in AUTONOMY_LEVELS
            or entry["origin"] != "engineering"
            or entry["reason"] != "saved autonomy changed"
            for entry in autonomy_history
        ):
            raise EngineeringError("Engineering project history is invalid.")
        for entry in autonomy_history:
            changed = _maintenance_time(entry["changed_at"])
            if changed > datetime.now(timezone.utc) + timedelta(minutes=5):
                raise EngineeringError("Engineering project history is invalid.")
        latest = autonomy_history[-1] if autonomy_history else None
        if latest is not None and latest["new"] != previous:
            raise EngineeringError("Engineering project history does not match autonomy.")
        if previous == level and latest is not None and latest["new"] == level:
            changed_at = latest["changed_at"]
        else:
            changed_at = _utc_now()
            autonomy_history.append(
                {
                    "kind": "autonomy_change",
                    "previous": previous,
                    "new": level,
                    "changed_at": changed_at,
                    "origin": "engineering",
                    "reason": "saved autonomy changed",
                }
            )
        autonomy_history = autonomy_history[-50:]
        config.update(autonomy=level, autonomy_explained=True)
        if "history" in config:
            config["history"] = unrelated_history
        config["autonomy_history"] = autonomy_history
        _save_project_config(project_root, config)
        return {
            "autonomy": level,
            "changed_at": changed_at,
            "explanation": {
                "guided": "Guided explains and recommends before project edits.",
                "collaborative": (
                    "Collaborative repairs routine in-scope drift and queues unrelated work."
                ),
                "steward": (
                    "Steward also processes safe queued maintenance only when Engineering runs."
                ),
            }[level],
            "approval_boundaries_preserved": True,
        }
    finally:
        _end_completion(project_root, operation)


def discover_checks(root: Path) -> list[list[str]]:
    project_root = resolve_project_root(str(root))
    config = load_project_config(project_root)
    managed = config.get("managed_instructions")
    if managed is not None and not isinstance(managed, dict):
        raise EngineeringError("Engineering managed instructions must be an object.")
    configured = managed.get("checks") if managed is not None else None
    label = "managed instruction checks" if configured is not None else "checks"
    if configured is None:
        configured = config.get("checks")
    if configured is not None:
        if not isinstance(configured, list) or any(
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(argument, str) or not argument for argument in argv)
            for argv in configured
        ):
            raise EngineeringError(
                f"Engineering {label} must be non-empty argv arrays."
            )
        return [list(argv) for argv in configured]

    checks: list[list[str]] = []
    if (project_root / "pyproject.toml").is_file() or (project_root / "tests").is_dir():
        checks.append(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
        )
    if (project_root / "package-lock.json").is_file():
        checks.append(["npm", "test", "--", "--run"])
    return checks


def _project_paths_for_manifest(manifest_name: str) -> tuple[str, str, str, str]:
    if manifest_name == V1_CONFIG:
        trace_dir = V1_TRACE_DIR
    else:
        trace_dir = V2_TRACE_DIR
    return (
        manifest_name,
        f"{trace_dir}/links.json",
        f"{trace_dir}/decision-ledger.md",
        f"{trace_dir}/README.md",
    )


def _project_paths(root: Path) -> tuple[str, str, str, str]:
    config_path = Path(load_project_config(root)["source_path"])
    return _project_paths_for_manifest(config_path.name)


def decision_ledger_path(root: Path, manifest: dict | None = None) -> str:
    """Return the one project-owned decision ledger; the overlay is never authority."""
    config = manifest if manifest is not None else load_project_config(root)
    declared = config.get("decision_ledger")
    if declared is None:
        if manifest is not None:
            return (
                f"{V1_TRACE_DIR}/decision-ledger.md"
                if config.get("version") == 1
                else f"{V2_TRACE_DIR}/decision-ledger.md"
            )
        return _project_paths(root)[2]
    if not isinstance(declared, str) or not declared or Path(declared).is_absolute() or ".." in Path(declared).parts:
        raise EngineeringError("Engineering decision_ledger must be a project-relative path.")
    return declared.replace("\\", "/")


def _ledger_decisions(root: Path, commit: str, manifest: dict) -> dict[str, int]:
    """Read stable IDs only; approval and implementation remain ledger-owned claims."""
    path = decision_ledger_path(root, manifest)
    text = _text_at(root, commit, path)
    headings: dict[str, int] = {}
    table_rows: dict[str, int] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        heading = re.match(
            r"^#{1,6}\s+([A-Z][A-Z0-9_-]*-DEC-\d+)\b", line
        )
        row = re.match(
            r"^\s*\|\s*([A-Z][A-Z0-9_-]*-DEC-\d+)\s*\|", line
        )
        if heading:
            identifier = heading.group(1)
            if identifier in headings:
                raise EngineeringError("Engineering decision ledger reuses a stable ID.")
            headings[identifier] = line_number
        elif row:
            identifier = row.group(1)
            if identifier in table_rows:
                raise EngineeringError("Engineering decision ledger reuses a stable ID.")
            table_rows[identifier] = line_number
    if headings.keys() & table_rows.keys():
        raise EngineeringError("Engineering decision ledger reuses a stable ID.")
    return {**table_rows, **headings}


def _decision_artifact_digest(
    root: Path, commit: str, manifest: dict, decision_id: str
) -> str:
    """Bind a scope approval to one exact, tracked decision-ledger line."""
    line_number = _ledger_decisions(root, commit, manifest).get(decision_id)
    if line_number is None:
        raise EngineeringError("Engineering scope approval decision is not in the authoritative ledger.")
    path = decision_ledger_path(root, manifest)
    lines = _text_at(root, commit, path).splitlines()
    if not 1 <= line_number <= len(lines):
        raise EngineeringError("Engineering scope approval decision artifact is invalid.")
    return _json_digest(
        {
            "commit": commit,
            "path": path,
            "line": line_number,
            "text": lines[line_number - 1],
        }
    )


def _scaffold_payload(root: Path, mode: str, graphify_version: str) -> dict[Path, str]:
    trace_dir = root / "docs" / "engineering"
    return {
        root / V2_CONFIG: json.dumps(
            {
                "version": 2,
                "mode": mode,
                "project": {
                    "name": project_name(root),
                    "default_branch": default_branch(root),
                },
                "graphify": {
                    "version": graphify_version,
                    "required_commands": list(REQUIRED_GRAPHIFY_COMMANDS),
                },
                "context": {"token_budget": DEFAULT_CONTEXT_TOKEN_BUDGET},
                "autonomy": DEFAULT_AUTONOMY,
                "overlay": {"version": 1},
                "decision_ledger": f"{V2_TRACE_DIR}/decision-ledger.md",
                "inputs": [f"{V2_TRACE_DIR}/links.json"],
                "integrity": {"min_retained_ratio": 0.8},
                "baseline": (
                    {"accepted": True, "historical_coverage": "strict"}
                    if mode == "greenfield"
                    else {
                        "accepted": False,
                        "historical_coverage": "advisory",
                        "uncertain": [
                            "approval",
                            "implementation",
                            "verification",
                        ],
                    }
                ),
            },
            indent=2,
        )
        + "\n",
        trace_dir / "links.json": json.dumps(
            {"version": 1, "nodes": [], "edges": []}, indent=2
        )
        + "\n",
        trace_dir / "decision-ledger.md": (
            "# Engineering Decision Ledger\n\n"
            "Use stable decision IDs. Link canonical sources; never invent approval.\n\n"
            + (
                "## Reconstruction status\n\n"
                "Uncertain historical approval, implementation, and verification "
                "remain advisory until the baseline is explicitly accepted.\n"
                if mode == "mid-flight"
                else "## Decisions\n\nNo decisions recorded.\n"
            )
        ),
        trace_dir / "README.md": (
            "# Engineering\n\n"
            "This project has its own Graphify graph and deterministic links. "
            "Do not merge it into a workspace-wide graph. Treat inferred paths "
            "as investigation leads, not verified coverage or authorization.\n"
        ),
    }


def scaffold(root: Path, mode: str, graphify_version: str) -> list[Path]:
    raise EngineeringError(
        "Direct scaffold mutation is disabled; use governed setup preview and approve-setup."
    )


def bootstrap(root: Path, graphify_version: str = GRAPHIFY_VERSION) -> dict:
    raise EngineeringError(
        "Direct bootstrap mutation is disabled; use governed setup preview and approve-setup."
    )


def _setup_mode(root: Path) -> str:
    tracked = [
        line
        for line in git(root, "ls-files").splitlines()
        if line and line not in {"README.md", ".gitignore"}
    ]
    return "greenfield" if not tracked else "mid-flight"


def _managed_instruction_block() -> str:
    return (
        f"{ENGINEERING_MANAGED_START}\n"
        "## Engineering\n\n"
        "For non-trivial engineering work in this Git project, use the installed "
        "Engineering skill. Engineering automatically prepares authorized work "
        "before edits and completes its evidence before a readiness claim. Use "
        "the project-local manifest, decision ledger, deterministic links, native "
        "checks, and exact Graphify checkpoint; do not substitute an umbrella "
        "workspace graph. Setup, tracked-control changes, hooks, dependency "
        "installation, publication, deployment, and consequential actions retain "
        "their explicit approval boundaries.\n"
        f"{ENGINEERING_MANAGED_END}"
    )


def _managed_instruction_text(path: Path) -> str:
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
    except (OSError, UnicodeDecodeError) as error:
        raise EngineeringError(
            f"Engineering cannot preserve unreadable instructions: {path.name}"
        ) from error
    starts = current.count(ENGINEERING_MANAGED_START)
    ends = current.count(ENGINEERING_MANAGED_END)
    start_at = current.find(ENGINEERING_MANAGED_START)
    end_at = current.find(ENGINEERING_MANAGED_END)
    if starts != ends or starts > 1 or (starts == 1 and start_at >= end_at):
        raise EngineeringError(
            f"Engineering managed instruction block is malformed: {path.name}"
        )
    block = _managed_instruction_block()
    if starts == 1:
        pattern = re.compile(
            re.escape(ENGINEERING_MANAGED_START)
            + r".*?"
            + re.escape(ENGINEERING_MANAGED_END),
            re.DOTALL,
        )
        updated, substitutions = pattern.subn(block, current)
        if substitutions != 1:
            raise EngineeringError(
                f"Engineering managed instruction block is malformed: {path.name}"
            )
        return updated
    if not current:
        return block + "\n"
    return current.rstrip() + "\n\n" + block + "\n"


def _generated_ignore_text(path: Path) -> str:
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
    except (OSError, UnicodeDecodeError) as error:
        raise EngineeringError("Engineering cannot preserve .gitignore.") from error
    lines = current.splitlines()
    for entry in ENGINEERING_GENERATED_IGNORES:
        if entry not in lines:
            lines.append(entry)
    return "\n".join(lines) + "\n"


def _validate_setup_project_path(root: Path, path: Path) -> None:
    lexical_root = root.absolute()
    candidate = path.absolute()
    if not candidate.is_relative_to(lexical_root):
        raise EngineeringError("Engineering setup target escapes the project boundary.")
    _reject_reparse_ancestors(candidate, lexical_root)
    if path.is_symlink() or (path.exists() and _is_reparse_point(path)):
        raise EngineeringError(
            "Engineering setup source/target is a link/reparse point."
        )
    if path.exists() and not path.is_file():
        raise EngineeringError("Engineering setup source/target is not a regular file.")


def _hooks_are_installed(root: Path, graphify_python: str) -> bool:
    hooks = _hooks_dir(root)
    expected = _managed_hook_documents(root, graphify_python, Path(__file__))
    for path, content in expected.items():
        try:
            retained = path.read_bytes()
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            return False
        if path.is_symlink() or retained != content or mode != _managed_hook_mode():
            return False
    preserved_state = _preserved_hook_state(root, PRESERVED_HOOK_DIRECTORY)
    manifest = hooks / PRESERVED_HOOK_MANIFEST
    try:
        retained = manifest.read_bytes()
        mode = stat.S_IMODE(manifest.stat().st_mode)
    except OSError:
        return False
    if (
        manifest.is_symlink()
        or _is_reparse_point(manifest)
        or retained != _preserved_hook_manifest_bytes(preserved_state)
        or mode != _managed_hook_mode()
    ):
        return False
    return True


def _setup_documents(root: Path, graphify_version: str) -> list[tuple[Path, bytes]]:
    planned_paths = (
        root / V1_CONFIG,
        root / V2_CONFIG,
        root / "AGENTS.md",
        root / "CLAUDE.md",
        root / ".gitignore",
        root / V1_TRACE_DIR / "links.json",
        root / V1_TRACE_DIR / "decision-ledger.md",
        root / V1_TRACE_DIR / "README.md",
        root / V2_TRACE_DIR / "links.json",
        root / V2_TRACE_DIR / "decision-ledger.md",
        root / V2_TRACE_DIR / "README.md",
    )
    for path in planned_paths:
        _validate_setup_project_path(root, path)
    manifests = [name for name in (V1_CONFIG, V2_CONFIG) if (root / name).exists()]
    if len(manifests) > 1:
        raise EngineeringError("invalid_manifest: multiple Engineering manifests")
    desired: dict[Path, str] = {}
    if manifests:
        _validate_project_controls(root, "WORKTREE", manifests[0])
    else:
        scaffold_payload = _scaffold_payload(root, _setup_mode(root), graphify_version)
        ledgers = [
            path for path in scaffold_payload
            if path.name == "decision-ledger.md" and path.exists()
        ]
        existing = [path for path in scaffold_payload if path.exists() and path not in ledgers]
        if existing:
            raise EngineeringError(
                "Refusing partial Engineering setup: "
                + ", ".join(str(path.relative_to(root)) for path in existing)
            )
        if len(ledgers) > 1:
            raise EngineeringError("Refusing ambiguous project decision ledgers.")
        if ledgers:
            ledger = ledgers[0]
            config = root / V2_CONFIG
            payload = json.loads(scaffold_payload[config])
            payload["decision_ledger"] = ledger.relative_to(root).as_posix()
            scaffold_payload[config] = json.dumps(payload, indent=2) + "\n"
            scaffold_payload.pop(ledger)
        desired.update(scaffold_payload)
    desired[root / "AGENTS.md"] = _managed_instruction_text(root / "AGENTS.md")
    desired[root / "CLAUDE.md"] = _managed_instruction_text(root / "CLAUDE.md")
    desired[root / ".gitignore"] = _generated_ignore_text(root / ".gitignore")
    return [
        (path, text.encode("utf-8"))
        for path, text in desired.items()
        if not path.exists() or path.read_bytes() != text.encode("utf-8")
    ]


def _plan_digest(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def _project_document_state(root: Path, path: Path) -> dict:
    _validate_setup_project_path(root, path)
    exists = path.exists()
    content = path.read_bytes() if exists else b""
    return {
        "exists": exists,
        "kind": "file" if exists else "absent",
        "bytes_hex": content.hex() if exists else None,
        "sha256": (
            "sha256:" + hashlib.sha256(content).hexdigest() if exists else None
        ),
        "mode": stat.S_IMODE(path.stat().st_mode) if exists else None,
    }


def _setup_project_plan(
    root: Path, graphify_version: str, graphify_python: str
) -> tuple[dict, list[tuple[Path, bytes]]]:
    documents = _setup_documents(root, graphify_version)
    hook_state = _hook_plan_state(root)
    expected_hooks = _managed_hook_documents(root, graphify_python, Path(__file__))
    install_hook_bundle = not _hooks_are_installed(root, graphify_python)
    document_states = {
        path: _project_document_state(root, path) for path, _ in documents
    }
    plan = {
        "schema": "engineering.setup-project-plan.v1",
        "documents": [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
                "content": content.decode("utf-8"),
                "expected_pre_state": document_states[path],
            }
            for path, content in documents
        ],
        "hook_installation": {
            "required": install_hook_bundle,
            "events": list(HOOK_EVENTS) if install_hook_bundle else [],
            "preserves_existing": True,
            "destination": str(_hooks_dir(root)),
            "existing": any(item["exists"] for item in hook_state),
            "artifacts": hook_state,
            "managed_artifacts": [
                {
                    "path": path.name,
                    "bytes_hex": content.hex(),
                    "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
                    "mode": _managed_hook_mode(),
                }
                for path, content in expected_hooks.items()
            ],
        },
        "approval_scope": (
            "The project-controls approval authorizes exactly these tracked "
            "instruction blocks, generated-output ignores, governed controls, "
            "and this hook installation as one bundle."
        ),
    }
    return plan, documents


def _setup_plan_summary(plan: dict) -> dict:
    """Keep approval previews compact; the digest still binds the full plan."""
    return {
        "schema": plan["schema"],
        "documents": [
            {
                "path": item["path"],
                "sha256": item["sha256"],
                "exists": item["expected_pre_state"]["exists"],
            }
            for item in plan["documents"]
        ],
        "hook_installation": {
            key: plan["hook_installation"][key]
            for key in ("required", "events", "preserves_existing", "existing")
        },
        "approval_scope": plan["approval_scope"],
    }


def _setup_public_projection(result: dict, claims: dict) -> dict:
    graphify = result["graphify"]
    return {
        "schema": result["schema"],
        "project": {"identity": claims["repository_id"]},
        "readiness": result["readiness"],
        "approvals_required": result["approvals_required"],
        "project_plan": result["project_plan"],
        "project_plan_digest": result["project_plan_digest"],
        "graphify": {
            "required": graphify["required"],
            "reason": graphify["reason"],
            "repository": graphify["repository"],
            "commit": graphify["commit"],
            "version": graphify["version"],
            "shell": False,
            "interpreter_sha256": graphify["interpreter"]["sha256"],
            "install_command": (
                ["<selected-python>", *graphify["install_argv"][1:]]
                if graphify["required"]
                else []
            ),
        },
        "graphify_plan_digest": result["graphify_plan_digest"],
        "writes_applied": result["writes_applied"],
        "approval_operation": result["approval_operation"],
    }


def _transactional_project_documents(
    root: Path,
    documents: list[tuple[Path, bytes]],
    expected_pre_states: dict[str, dict],
) -> None:
    token = uuid.uuid4().hex
    replacements: list[tuple[Path, Path]] = []
    created_parents: list[Path] = []
    try:
        for path, content in documents:
            _reject_reparse_ancestors(path)
            relative = path.relative_to(root).as_posix()
            expected = expected_pre_states.get(relative)
            if expected is None or _project_document_state(root, path) != expected:
                raise EngineeringError(
                    f"Engineering project document changed before staging: {relative}"
                )
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for candidate in reversed(missing):
                candidate.mkdir()
                created_parents.append(candidate)
            stage = path.with_name(f".{path.name}.stage-{token}")
            _atomic_bytes(stage, content)
            replacements.append((stage, path))

        intended_by_path = dict(documents)

        def verify_publication() -> None:
            for _, target in replacements:
                relative = target.relative_to(root).as_posix()
                intended = intended_by_path[target]
                if (
                    not target.is_file()
                    or target.is_symlink()
                    or _is_reparse_point(target)
                    or target.read_bytes() != intended
                ):
                    raise EngineeringError(
                        "Engineering project document publication verification "
                        f"failed: {relative}"
                    )

        _transactional_replace(
            replacements,
            token,
            {
                path: expected_pre_states[path.relative_to(root).as_posix()]
                for _, path in replacements
            },
            after_publication=verify_publication,
        )
    except Exception:
        for candidate in reversed(created_parents):
            try:
                candidate.rmdir()
            except OSError:
                pass
        raise
    finally:
        for stage, _ in replacements:
            stage.unlink(missing_ok=True)


def _snapshot_hooks(root: Path) -> tuple[Path, Path, bool]:
    hooks = _hooks_dir(root)
    if hooks.is_symlink() or _is_reparse_point(hooks):
        raise EngineeringError("Engineering hooks directory is a link/reparse point.")
    snapshot_root = Path(tempfile.mkdtemp(prefix="engineering-setup-hooks-"))
    backup = snapshot_root / "hooks"
    existed = hooks.exists()
    if existed:
        shutil.copytree(hooks, backup, symlinks=True)
    return hooks, snapshot_root, existed


def _restore_hooks(snapshot: tuple[Path, Path, bool]) -> None:
    hooks, snapshot_root, existed = snapshot
    if hooks.exists():
        shutil.rmtree(hooks)
    backup = snapshot_root / "hooks"
    if existed:
        shutil.copytree(backup, hooks, symlinks=True)
    shutil.rmtree(snapshot_root, ignore_errors=True)


def _discard_hook_snapshot(snapshot: tuple[Path, Path, bool]) -> None:
    shutil.rmtree(snapshot[1], ignore_errors=True)


def _setup_preview(root: Path, graphify_python: str) -> tuple[dict, dict]:
    project_root = resolve_project_root(str(root))
    interpreter = _interpreter_identity(project_root, graphify_python)
    project_plan, _ = _setup_project_plan(
        project_root, GRAPHIFY_VERSION, interpreter["path"]
    )
    project_plan_digest = _plan_digest(project_plan)
    try:
        verify_graphify(interpreter["path"])
        graphify_missing = False
        graphify_reason = "Reviewed pinned Graphify is already installed."
    except EngineeringError as error:
        graphify_missing = True
        graphify_reason = str(error)
    install_argv = (
        _governed_graphify_install_argv(interpreter) if graphify_missing else []
    )
    graphify_plan = {
        "schema": "engineering.setup-graphify-plan.v1",
        "required": graphify_missing,
        "install_argv": install_argv,
        "reason": graphify_reason,
        "repository": GRAPHIFY_REPOSITORY,
        "commit": GRAPHIFY_COMMIT,
        "version": GRAPHIFY_VERSION,
        "shell": False,
        "interpreter": interpreter,
    }
    graphify_plan_digest = _plan_digest(graphify_plan)
    project_changes = bool(
        project_plan["documents"] or project_plan["hook_installation"]["required"]
    )
    required = []
    if graphify_missing:
        required.append("graphify_install")
    if project_changes:
        required.append("project_controls")
    claims = {
        "repository_id": _project_contribution_digest(project_root),
        "project_plan_digest": project_plan_digest,
        "graphify_plan_digest": graphify_plan_digest,
        "scopes": sorted(required),
        "interpreter": interpreter,
        "installer_argv": install_argv,
    }
    return {
        "schema": "engineering.setup.v1",
        "readiness": "ready" if not required else "proposal",
        "project_root": str(project_root),
        "approvals_required": required,
        "project_plan": _setup_plan_summary(project_plan),
        "project_plan_digest": project_plan_digest,
        "graphify": graphify_plan,
        "graphify_plan_digest": graphify_plan_digest,
        "writes_applied": False,
        "approval_operation": "approve-setup",
    }, claims


def _matching_setup_attestation(root: Path, claims: dict) -> dict | None:
    controller = _project_controller_dir(root)
    registry = _load_attestations(controller)
    matches = [
        item
        for item in registry["items"]
        if item["kind"] == "setup" and item["claims"] == claims
    ]
    if len(matches) > 1:
        raise EngineeringError("Engineering setup attestation registry is ambiguous.")
    return matches[0] if matches else None


def _consume_setup_attestation(root: Path, claims: dict) -> dict:
    controller = _project_controller_dir(root)
    registry = _load_attestations(controller)
    matches = [
        item
        for item in registry["items"]
        if item["kind"] == "setup" and item["claims"] == claims
    ]
    if len(matches) != 1:
        raise EngineeringError("Engineering setup attestation is missing or mismatched.")
    retained = [item for item in registry["items"] if item["id"] != matches[0]["id"]]
    _transactional_json_documents(
        [
            (
                _attestation_path(controller),
                {"schema": "engineering.controller-attestations.v1", "items": retained},
            )
        ]
    )
    return matches[0]


def approve_setup(
    root: Path,
    graphify_python: str,
    project_plan_digest: str,
    *,
    scopes: list[str],
    graphify_plan_digest: str | None = None,
) -> dict:
    project_root = resolve_project_root(str(root))
    preview, base_claims = _setup_preview(project_root, graphify_python)
    allowed = set(preview["approvals_required"])
    selected = set(scopes)
    if (
        not selected
        or not selected.issubset(allowed)
        or len(selected) != len(scopes)
    ):
        raise EngineeringError("Engineering setup approval scopes are invalid.")
    if project_plan_digest != preview["project_plan_digest"]:
        raise EngineeringError("Engineering project setup plan changed before approval.")
    if "graphify_install" in selected and (
        graphify_plan_digest != preview["graphify_plan_digest"]
    ):
        raise EngineeringError("Engineering Graphify setup plan changed before approval.")
    claims = {
        **base_claims,
        "scopes": sorted(selected),
    }
    operation = _begin_completion(
        project_root,
        "approve-setup-" + project_plan_digest.removeprefix("sha256:")[:12],
    )
    try:
        current, current_claims = _setup_preview(project_root, graphify_python)
        if (
            current["project_plan_digest"] != project_plan_digest
            or current_claims["graphify_plan_digest"] != base_claims["graphify_plan_digest"]
            or current_claims["interpreter"] != base_claims["interpreter"]
        ):
            raise EngineeringError("Engineering setup plan changed before approval.")
        controller = _project_controller_dir(project_root)
        registry, attestation, new_key = _append_attestation(
            controller, "setup", claims
        )
        _transactional_json_documents(
            [(_attestation_path(controller), registry)],
            [(_controller_key_path(controller), new_key)] if new_key else None,
        )
        return {
            "approval_id": attestation["id"],
            "claims": claims,
            "scopes": sorted(selected),
        }
    finally:
        _end_completion(project_root, operation)


def _setup_readiness(root: Path, graphify_python: str) -> dict:
    """Never report written controls as usable before commit and exact read-back."""
    if _tracked_manifest_name(root) is None:
        return {"readiness": "controls_written_pending_commit", "checkpoint": None}
    readiness = check_merge_readiness(root)
    if readiness.get("ready"):
        return {"readiness": "operational", "checkpoint": readiness["checkpoint"]}
    return {
        "readiness": "checkpoint_pending",
        "checkpoint": None,
        "reason": readiness.get("reason", "canonical_checkpoint_missing"),
    }


def setup(root: Path, graphify_python: str) -> dict:
    project_root = resolve_project_root(str(root))
    result, claims = _setup_preview(project_root, graphify_python)
    if not result["approvals_required"]:
        return {**_setup_public_projection(result, claims), **_setup_readiness(project_root, graphify_python)}
    if _matching_setup_attestation(project_root, claims) is None:
        return _setup_public_projection(result, claims)

    operation = _begin_completion(
        project_root,
        "setup-" + result["project_plan_digest"].removeprefix("sha256:")[:12],
    )
    graphify_installed = False
    snapshot = None
    try:
        current, current_claims = _setup_preview(project_root, graphify_python)
        if current_claims != claims:
            raise EngineeringError("Engineering setup approval is stale.")
        _require_attestation(_project_controller_dir(project_root), "setup", claims)
        _consume_setup_attestation(project_root, claims)

        if current["graphify"]["required"]:
            try:
                _run_governed_graphify_install(
                    current["graphify"]["install_argv"], claims["interpreter"]
                )
            except Exception as error:
                raise EngineeringError(
                    "graphify_install_failed; recovery: project files, baseline, and "
                    "hooks were not written; inspect the approved interpreter environment"
                ) from error
            try:
                verify_graphify(claims["interpreter"]["path"])
                if _interpreter_identity(
                    project_root, claims["interpreter"]["path"]
                ) != claims["interpreter"]:
                    raise EngineeringError("Graphify interpreter identity changed.")
            except Exception as error:
                raise EngineeringError(
                    "external_change_unverified; recovery: the installer returned success "
                    "but the exact interpreter pin could not be verified; no project setup "
                    "or hooks were written"
                ) from error
            graphify_installed = True

        replanned, documents = _setup_project_plan(
            project_root, GRAPHIFY_VERSION, claims["interpreter"]["path"]
        )
        if _plan_digest(replanned) != claims["project_plan_digest"]:
            raise EngineeringError("Engineering project or hook plan changed before mutation.")
        snapshot = _snapshot_hooks(project_root)
        final_plan, documents = _setup_project_plan(
            project_root, GRAPHIFY_VERSION, claims["interpreter"]["path"]
        )
        if _plan_digest(final_plan) != claims["project_plan_digest"]:
            raise EngineeringError("Engineering project or hook plan changed before mutation.")
        if final_plan["hook_installation"]["required"]:
            _install_hooks_authorized(
                project_root,
                claims["interpreter"]["path"],
                Path(__file__),
                final_plan["hook_installation"]["artifacts"],
            )
        _transactional_project_documents(
            project_root,
            documents,
            {
                item["path"]: item["expected_pre_state"]
                for item in final_plan["documents"]
            },
        )
    except Exception as error:
        if snapshot is not None:
            _restore_hooks(snapshot)
            snapshot = None
        if graphify_installed:
            raise EngineeringError(
                "graphify_installed_project_setup_failed; recovery: verified pinned "
                "Graphify was retained while project files and hooks were restored"
            ) from error
        raise
    else:
        if snapshot is not None:
            _discard_hook_snapshot(snapshot)
    finally:
        _end_completion(project_root, operation)

    return {
        **_setup_public_projection(result, claims),
        "readiness": "controls_written_pending_commit",
        "writes_applied": True,
        "graphify_installed": graphify_installed,
        "created_or_updated": [
            item["path"] for item in result["project_plan"]["documents"]
        ],
        "hooks": result["project_plan"]["hook_installation"],
    }


def legacy_setup_forwarder(root: Path, graphify_python: str, command: str) -> dict:
    if command not in {"bootstrap", "reconstruct", "install-hooks"}:
        raise EngineeringError("Engineering legacy setup command is unsupported.")
    preview, claims = _setup_preview(resolve_project_root(str(root)), graphify_python)
    return {
        **_setup_public_projection(preview, claims),
        "readiness": "proposal" if preview["approvals_required"] else "ready",
        "compatibility_command": command,
        "forwarded_to": "setup",
        "writes_applied": False,
    }


def _json_at(root: Path, commit: str, path: str) -> dict:
    if commit == "WORKTREE":
        try:
            value = json.loads((root / path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise TraceabilityError(f"Invalid or missing JSON input: {path}") from error
        if not isinstance(value, dict):
            raise TraceabilityError(f"JSON input must be an object: {path}")
        return value
    revision = f":{path}" if commit == "INDEX" else f"{commit}:{path}"
    try:
        value = json.loads(git(root, "show", revision))
    except (json.JSONDecodeError, TraceabilityError) as error:
        raise TraceabilityError(f"Invalid or untracked JSON input: {path}") from error
    if not isinstance(value, dict):
        raise TraceabilityError(f"JSON input must be an object: {path}")
    return value


def _text_at(root: Path, commit: str, path: str) -> str:
    if Path(path).is_absolute() or ".." in Path(path).parts:
        raise TraceabilityError(f"Input path must stay inside the project: {path}")
    if commit == "WORKTREE":
        try:
            return (root / path).read_text(encoding="utf-8")
        except OSError as error:
            raise TraceabilityError(
                f"Missing source at commit {commit}: {path}"
            ) from error
    revision = f":{path}" if commit == "INDEX" else f"{commit}:{path}"
    try:
        return git(root, "show", revision)
    except TraceabilityError as error:
        raise TraceabilityError(f"Missing source at commit {commit}: {path}") from error


def _source(record: dict, label: str) -> tuple[str, int]:
    source = record.get("source")
    if not isinstance(source, dict):
        raise TraceabilityError(f"{label} requires a source object.")
    path, line = source.get("path"), source.get("line")
    if not isinstance(path, str) or not path or not isinstance(line, int) or line < 1:
        raise TraceabilityError(f"{label} has an invalid source location.")
    return path.replace("\\", "/"), line


def _semantic_matrix_issues(manifest: dict, nodes: list[dict], scope: set[str]) -> list[str]:
    """Validate only declared matrix rows touched by the authorized change."""
    matrices = manifest.get("semantic_matrices")
    if matrices is None:
        return []
    if not isinstance(matrices, list):
        raise EngineeringError("Engineering semantic_matrices must be an array.")
    by_id = {node["id"]: node for node in nodes}
    issues: list[str] = []
    for matrix in matrices:
        if not isinstance(matrix, dict) or not isinstance(matrix.get("source"), str):
            raise EngineeringError("Engineering semantic matrix is invalid.")
        items = matrix.get("items")
        if not isinstance(items, list) or not items:
            raise EngineeringError("Engineering semantic matrix items are invalid.")
        if not _semantic_matrix_impacted(matrix, by_id, scope):
            continue
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise EngineeringError("Engineering semantic matrix item is invalid.")
            owner, state = item.get("owner"), item.get("state")
            has_owner = isinstance(owner, str) and bool(owner)
            if not (has_owner ^ (state in {"unavailable", "unowned"})):
                issues.append(item["id"])
                continue
            targets = (item.get("implementation"), item.get("positive"), item.get("negative"))
            if any(not isinstance(target, str) or target not in by_id for target in targets):
                issues.append(item["id"])
                continue
            if by_id[targets[0]].get("type") != "code_symbol" or any(
                by_id[target].get("type") not in {"test", "evaluation", "verification_receipt"}
                for target in targets[1:]
            ):
                issues.append(item["id"])
    return sorted(set(issues))


def _semantic_matrix_impacted(matrix: dict, by_id: dict[str, dict], scope: set[str]) -> bool:
    references = [
        value
        for item in matrix.get("items", [])
        if isinstance(item, dict)
        for value in (item.get("implementation"), item.get("positive"), item.get("negative"))
    ]
    return matrix["source"].replace("\\", "/") in scope or any(
        isinstance(identifier, str)
        and identifier in by_id
        and isinstance(by_id[identifier].get("source"), dict)
        and by_id[identifier]["source"].get("path", "").replace("\\", "/") in scope
        for identifier in references
    )


def _validate_overlay(
    root: Path,
    commit: str,
    manifest: dict,
    links: dict,
    manifest_name: str | None = None,
) -> tuple[list, list, dict]:
    config_path = manifest_name or _project_paths(root)[0]
    expected_manifest_version = 1 if config_path == V1_CONFIG else 2
    if (
        manifest.get("version") != expected_manifest_version
        or links.get("version") != 1
    ):
        raise EngineeringError("Unsupported Engineering JSON version.")
    nodes, edges = links.get("nodes", []), links.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise EngineeringError("Engineering nodes and edges must be arrays.")

    identifiers: set[str] = set()
    node_ids: set[str] = set()
    sources: list[tuple[str, str, int]] = []
    config_path, links_path, _, _ = _project_paths_for_manifest(config_path)
    input_paths = {config_path, links_path}
    ledger_path = decision_ledger_path(root, manifest)
    input_paths.add(ledger_path)
    for matrix in manifest.get("semantic_matrices", []):
        if not isinstance(matrix, dict) or not isinstance(matrix.get("source"), str):
            raise TraceabilityError("Engineering semantic matrix is invalid.")
        input_paths.add(matrix["source"].replace("\\", "/"))
    for path in manifest.get("inputs", []):
        if not isinstance(path, str):
            raise TraceabilityError("Manifest inputs must be project-relative paths.")
        input_paths.add(path.replace("\\", "/"))

    for node in nodes:
        if not isinstance(node, dict):
            raise TraceabilityError("Every node must be an object.")
        identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise TraceabilityError(f"Invalid or duplicate stable identifier: {identifier}")
        if node.get("type") not in NODE_TYPES or not isinstance(node.get("title"), str):
            raise TraceabilityError(f"Invalid node schema: {identifier}")
        if node.get("retrospective_state") not in {
            None,
            "contradictory",
            "deferred",
            "excluded",
            "stale",
            "unknown",
        }:
            raise TraceabilityError(f"Invalid node retrospective state: {identifier}")
        path, line = _source(node, identifier)
        input_paths.add(path)
        sources.append((identifier, path, line))
        identifiers.add(identifier)
        node_ids.add(identifier)

    ledger_decisions = _ledger_decisions(root, commit, manifest)
    overlay_decisions = {
        node["id"]: node
        for node in nodes
        if node.get("type") == "decision"
        and isinstance(node.get("source"), dict)
        and node["source"].get("path", "").replace("\\", "/") == ledger_path
    }
    if set(ledger_decisions) != set(overlay_decisions):
        raise TraceabilityError(
            "Authoritative decision ledger and deterministic overlay disagree."
        )
    for identifier, line in ledger_decisions.items():
        if overlay_decisions[identifier]["source"].get("line") != line:
            raise TraceabilityError(
                f"Decision overlay source is stale: {identifier}."
            )

    for edge in edges:
        if not isinstance(edge, dict):
            raise TraceabilityError("Every edge must be an object.")
        identifier = edge.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise TraceabilityError(f"Invalid or duplicate stable identifier: {identifier}")
        provenance, target = edge.get("provenance"), edge.get("to")
        if (
            edge.get("type") not in EDGE_TYPES
            or provenance not in PROVENANCE
            or edge.get("from") not in node_ids
            or (provenance != "missing" and target not in node_ids)
            or (provenance == "missing" and target is None and not edge.get("target_type"))
        ):
            raise TraceabilityError(f"Invalid edge schema: {identifier}")
        path, line = _source(edge, identifier)
        input_paths.add(path)
        sources.append((identifier, path, line))
        identifiers.add(identifier)

    contents = {}
    digest = hashlib.sha256()
    for path in sorted(input_paths):
        content = _text_at(root, commit, path)
        contents[path] = content
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content.encode())
        digest.update(b"\0")
    for identifier, path, line in sources:
        if line > len(contents[path].splitlines()):
            raise TraceabilityError(
                f"{identifier} source line {line} exceeds {path} line count."
            )
    return nodes, edges, {
        "inputs": sorted(input_paths),
        "input_digest": digest.hexdigest(),
        "files": len(contents),
        "nodes": len(nodes),
        "edges": len(edges),
        "exact_edges": sum(edge["provenance"] in EXACT_PROVENANCE for edge in edges),
    }


def _common_graph_dir(root: Path) -> Path:
    common = Path(git(root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (root / common).resolve()
    return common / "engineering-graphs"


def _graphify_environment(*, output: Path | None = None) -> dict[str, str]:
    """Build the minimal, credentialless environment for one Graphify child."""
    environment = {
        key: os.environ[key]
        for key in GRAPHIFY_ENVIRONMENT_ALLOWLIST
        if key in os.environ
    }
    if output is not None:
        environment["GRAPHIFY_OUT"] = str(output)
    return environment


def _map_cache_key(checkpoint: dict, assurance: list[dict], options: dict) -> str:
    payload = {
        "base_graph": checkpoint["metadata"].get("graph_digest"),
        "deterministic_overlay": checkpoint["metadata"].get("input_digest"),
        "assurance_overlay": hashlib.sha256(
            json.dumps(assurance, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "renderer": "engineering-map.v1",
        "options": options,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def render_map(root: Path, *, open_output: bool = True, focus: str | None = None) -> dict:
    """Compatibility map payload over the exact canonical traceability view."""
    project_root = resolve_project_root(str(root))
    view = traceability_view(project_root, focus=focus)
    rendered = write_traceability_view_html(project_root, view)
    if open_output:
        webbrowser.open(Path(rendered["output"]).resolve().as_uri())
    return {
        "schema": "engineering.map.v1",
        "commit": view["envelope"]["commit"],
        "output": rendered["output"],
        "cached": False,
        "aggregate": bool(view.get("envelope", {}).get("aggregate", False)),
        "opened": open_output,
        "view_digest": rendered["digest"],
    }


def common_graph_dir(root: Path) -> Path:
    """Return this clone's one shared generated-graph root."""
    return _common_graph_dir(resolve_project_root(str(root)))


def _checkpoint_path(root: Path, commit: str) -> Path:
    matches = list(_common_graph_dir(root).glob(f"main/{commit}/checkpoint.json"))
    matches += list(_common_graph_dir(root).glob(f"features/*/{commit}/checkpoint.json"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        selected, used, seen = [], 0, set()
        for path in matches:
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))["metadata"]
            except (OSError, json.JSONDecodeError, KeyError):
                continue
            if metadata.get("branch") == branch:
                selected.append((path, metadata.get("kind")))
        if len(selected) == 1:
            return selected[0][0]
        canonical = [path for path, kind in selected if kind == "canonical"]
        if len(canonical) == 1:
            return canonical[0]
    if len(matches) != 1:
        raise TraceabilityError(f"Expected one commit-bound checkpoint for {commit}.")
    return matches[0]


def _load_checkpoint(root: Path, commit: str) -> dict:
    try:
        checkpoint = json.loads(_checkpoint_path(root, commit).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TraceabilityError(f"Invalid checkpoint for {commit}.") from error
    if checkpoint.get("metadata", {}).get("commit") != commit:
        raise TraceabilityError(f"Checkpoint is not bound to commit {commit}.")
    return checkpoint


def _identity(record: dict) -> dict:
    keys = ("id", "type", "from", "to", "target_type", "source")
    return {key: record.get(key) for key in keys if key in record}


def _guard_previous(current: dict, previous: dict, ratio: float) -> None:
    old = {item["id"]: item for item in previous["nodes"] + previous["edges"]}
    for item in current["nodes"] + current["edges"]:
        prior = old.get(item["id"])
        if prior and _identity(prior) != _identity(item):
            raise TraceabilityError(f"Stable identifier reused for different content: {item['id']}")
    for key in ("files", "nodes", "exact_edges"):
        before = previous["integrity"].get(key, 0)
        after = current["integrity"].get(key, 0)
        if before and after / before < ratio:
            raise TraceabilityError(
                f"Unexpected shrink in {key}: {before} -> {after}; previous checkpoint retained."
            )


def _checkpoint_candidate(
    root: Path,
    requested_commit: str,
    previous_commit: str | None,
    graphify_version: str | None = None,
    manifest_name: str | None = None,
) -> tuple[Path, dict]:
    commit = git(root, "rev-parse", requested_commit)
    head = git(root, "rev-parse", "HEAD")
    if commit != head:
        raise TraceabilityError("Checkpoint commit must equal the current HEAD.")
    branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    config_path, links_path, _, _ = (
        _project_paths_for_manifest(manifest_name)
        if manifest_name is not None
        else _project_paths(root)
    )
    manifest = _json_at(root, commit, config_path)
    links = _json_at(root, commit, links_path)
    nodes, edges, integrity = _validate_overlay(
        root, commit, manifest, links, manifest_name=config_path
    )
    default = manifest.get("project", {}).get("default_branch")
    if not isinstance(default, str) or not default:
        raise TraceabilityError("Manifest default branch is missing.")
    canonical_head = git(root, "rev-parse", f"refs/remotes/origin/{default}")
    canonical = branch == default and commit == canonical_head
    checkpoint = {
        "metadata": {
            "project_root": str(_common_graph_dir(root).parent),
            "project": manifest.get("project", {}).get("name", root.name),
            "branch": branch,
            "commit": commit,
            "kind": "canonical" if canonical else "feature",
            "graphify_version": (
                graphify_version
                if graphify_version is not None
                else manifest.get("graphify", {}).get("version")
            ),
            "overlay_version": manifest.get("overlay", {}).get("version"),
            "input_digest": integrity.pop("input_digest"),
            "inputs": integrity.pop("inputs"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "integrity": integrity,
        "nodes": nodes,
        "edges": edges,
    }
    if previous_commit:
        ratio = manifest.get("integrity", {}).get("min_retained_ratio", 0.8)
        if not isinstance(ratio, (int, float)) or not 0 <= ratio <= 1:
            raise TraceabilityError("Integrity retention ratio must be between 0 and 1.")
        _guard_previous(checkpoint, _load_checkpoint(root, previous_commit), float(ratio))
    graph_dir = _common_graph_dir(root)
    if canonical:
        destination = graph_dir / "main" / commit / "checkpoint.json"
    else:
        destination = graph_dir / "features" / quote(branch, safe="") / commit / "checkpoint.json"
    return destination, checkpoint


def _same_checkpoint(existing: dict, candidate: dict) -> bool:
    existing = json.loads(json.dumps(existing))
    candidate = json.loads(json.dumps(candidate))
    existing["metadata"].pop("generated_at", None)
    candidate["metadata"].pop("generated_at", None)
    return existing == candidate


def construct_checkpoint(
    root: Path, requested_commit: str, previous_commit: str | None
) -> Path:
    destination, checkpoint = _checkpoint_candidate(
        root, requested_commit, previous_commit
    )
    commit = checkpoint["metadata"]["commit"]
    branch = checkpoint["metadata"]["branch"]
    kind = checkpoint["metadata"]["kind"]
    quarantine = _quarantine_invalid_checkpoint(
        root,
        destination,
        commit,
        branch=branch,
        kind=kind,
    )
    try:
        if destination.exists():
            existing = json.loads(destination.read_text(encoding="utf-8"))
            if not _same_checkpoint(existing, checkpoint):
                raise TraceabilityError(
                    "Immutable checkpoint already exists with different content: "
                    f"{checkpoint['metadata']['commit']}"
                )
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, destination)
        return destination
    except Exception:
        if quarantine is not None:
            _restore_quarantined_checkpoint(root, quarantine)
        raise


def _legacy_rebuild(
    root: Path,
    requested_commit: str,
    graphify_python: str,
    manifest_name: str | None = None,
) -> Path:
    identity = verify_graphify(graphify_python)
    commit = git(root, "rev-parse", requested_commit)
    selected = manifest_name or _tracked_manifest_name(root)
    if selected is None:
        raise EngineeringError("manifest_not_tracked")
    branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    destination, checkpoint = _checkpoint_candidate_at(
        root,
        commit,
        branch=branch,
        kind="feature",
        graphify_version=identity.version,
        manifest_name=selected,
    )
    final_dir = destination.parent
    quarantine = _quarantine_invalid_checkpoint(
        root,
        destination,
        commit,
        branch=branch,
        kind="feature",
    )
    if final_dir.exists():
        if (
            not destination.is_file()
            or not validate_checkpoint(root, destination, commit)["valid"]
        ):
            raise TraceabilityError(
                f"Immutable checkpoint directory is incomplete: {final_dir}"
        )
        return destination

    try:
        final_dir.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        if quarantine is not None:
            _restore_quarantined_checkpoint(root, quarantine)
        raise
    stage = Path(
        tempfile.mkdtemp(
            prefix=".engineering-", dir=str(final_dir.parent)
        )
    )
    snapshot_container = Path(
        tempfile.mkdtemp(
            prefix=".engineering-snapshot-",
            dir=str(_common_graph_dir(root)),
        )
    )
    snapshot = snapshot_container / "project"
    empty_hooks = snapshot_container / "hooks"
    empty_hooks.mkdir()
    added = False
    try:
        run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                f"core.hooksPath={empty_hooks}",
                "worktree",
                "add",
                "--detach",
                str(snapshot),
                commit,
            ]
        )
        added = True
        if git(snapshot, "rev-parse", "HEAD") != commit:
            raise TraceabilityError("Detached Graphify snapshot is not bound to commit.")
        environment = _graphify_environment(output=stage)
        run(
            [
                str(Path(graphify_python).expanduser().resolve()),
                "-m",
                "graphify",
                "update",
                str(snapshot),
            ],
            env=environment,
            timeout=600,
        )
        if not (stage / "graph.json").is_file():
            raise TraceabilityError("Graphify did not produce graph.json.")
        graph = _read_base_graph(stage / "graph.json")
        if graph.get("built_at_commit") != commit:
            raise TraceabilityError("Graphify output is not bound to the target commit.")
        checkpoint["metadata"]["graph_digest"] = _graph_digest(stage / "graph.json")
        if (
            git(root, "rev-parse", "HEAD") != commit
            or git(snapshot, "rev-parse", "HEAD") != commit
        ):
            raise TraceabilityError(
                "Project HEAD changed during rebuild; previous checkpoint retained."
            )
        (stage / "checkpoint.json").write_text(
            json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8"
        )
        for attempt in range(3):
            try:
                os.replace(stage, final_dir)
                break
            except PermissionError as error:
                if getattr(error, "winerror", None) != 5 or attempt == 2:
                    raise
                time.sleep(0.1 * (attempt + 1))
        return final_dir / "checkpoint.json"
    except Exception:
        if quarantine is not None:
            _restore_quarantined_checkpoint(root, quarantine)
        raise
    finally:
        if added:
            try:
                run(
                    [
                        "git",
                        "-C",
                        str(root),
                        "-c",
                        f"core.hooksPath={empty_hooks}",
                        "worktree",
                        "remove",
                        "--force",
                        str(snapshot),
                    ]
                )
            except TraceabilityError:
                pass
        shutil.rmtree(snapshot_container, ignore_errors=True)
        shutil.rmtree(stage, ignore_errors=True)


def _checkpoint_files(root: Path) -> list[Path]:
    graph_dir = _common_graph_dir(root)
    return sorted(graph_dir.glob("main/*/checkpoint.json")) + sorted(
        graph_dir.glob("features/*/*/checkpoint.json")
    )


def _state_path(root: Path) -> Path:
    return _common_graph_dir(root) / "state" / "freshness.json"


def _read_stale(root: Path) -> dict[str, str]:
    path = _state_path(root)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Invalid Engineering freshness state.") from error
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(reason, str)
        for key, reason in value.items()
    ):
        raise EngineeringError("Invalid Engineering freshness state.")
    return value


def _write_stale(root: Path, state: dict[str, str]) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_text(path, json.dumps(state, indent=2) + "\n")


def _record_stale(root: Path, commit: str, reason: str) -> None:
    state = _read_stale(root)
    state[commit] = reason
    _write_stale(root, state)


def _clear_stale(root: Path, commit: str) -> None:
    state = _read_stale(root)
    if state.pop(commit, None) is not None:
        _write_stale(root, state)


def _stale_result(
    root: Path,
    commit: str,
    reason: str,
    ancestor: tuple[str, Path] | None,
) -> dict:
    _record_stale(root, commit, reason)
    return {
        "mode": "stale",
        "freshness": "stale",
        "reason": reason,
        "commit": commit,
        "checkpoint": None,
        "previous_checkpoint_preserved": ancestor is not None,
        "network_operation_kinds": [],
        "argv": [],
        "changed_files": [],
    }


def overlay_fingerprints(root: Path) -> dict[str, str]:
    project_root = resolve_project_root(str(root))
    manifest_name = _tracked_manifest_name(project_root)
    if manifest_name is None:
        raise EngineeringError("manifest_not_tracked")
    commit = git(project_root, "rev-parse", "HEAD")
    config_path, links_path, _, _ = _project_paths_for_manifest(manifest_name)
    manifest = _json_at(project_root, commit, config_path)
    links = _json_at(project_root, commit, links_path)
    _, _, integrity = _validate_overlay(
        project_root, commit, manifest, links, manifest_name=manifest_name
    )
    return {
        "manifest": manifest_name,
        "input_digest": integrity["input_digest"],
    }


def _tracked_manifest_name_at(root: Path, revision: str) -> str | None:
    tracked = []
    for manifest_name in (V1_CONFIG, V2_CONFIG):
        try:
            git(root, "cat-file", "-e", f"{revision}:{manifest_name}")
            tracked.append(manifest_name)
        except EngineeringError:
            pass
    if not tracked:
        return None
    if len(tracked) != 1:
        raise EngineeringError(
            "invalid_manifest: exactly one Engineering manifest must be tracked"
        )
    return tracked[0]


def checkpoint_identity(root: Path, commit: str = "HEAD") -> str:
    """Return a clone/worktree-stable identity derived only from tracked controls."""
    project_root = resolve_project_root(str(root))
    revision = git(project_root, "rev-parse", commit)
    manifest_name = _tracked_manifest_name_at(project_root, revision)
    if manifest_name is None:
        raise EngineeringError("manifest_not_tracked")
    manifest = _json_at(project_root, revision, manifest_name)
    project = manifest.get("project")
    if not isinstance(project, dict):
        raise EngineeringError("invalid_manifest: project")
    stable = {
        "manifest": manifest_name,
        "name": project.get("name"),
        "default_branch": project.get("default_branch"),
    }
    if not all(isinstance(value, str) and value for value in stable.values()):
        raise EngineeringError("invalid_manifest: stable project identity")
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _graph_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_base_graph(path: Path) -> dict:
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EngineeringError("invalid_json") from error
    if (
        not isinstance(graph, dict)
    ):
        raise EngineeringError("invalid_schema")
    links = graph.get("links", graph.get("edges"))
    if (
        not isinstance(graph.get("nodes"), list)
        or not isinstance(links, list)
        or any(not isinstance(item, dict) for item in graph["nodes"] + links)
    ):
        raise EngineeringError("invalid_schema")
    identifiers = [item.get("id") for item in graph["nodes"]]
    identifier_set = set(identifiers)
    link_identity_fields = (
        "source",
        "target",
        "relation",
        "confidence",
        "source_file",
        "source_location",
    )
    link_identities = [
        tuple(
            json.dumps(
                link.get(field), sort_keys=True, separators=(",", ":")
            )
            for field in link_identity_fields
        )
        for link in links
    ]
    if (
        any(not isinstance(identifier, str) or not identifier for identifier in identifiers)
        or len(identifier_set) != len(identifiers)
        or any(
            not isinstance(link.get("source"), str)
            or not isinstance(link.get("target"), str)
            or link["source"] not in identifier_set
            or link["target"] not in identifier_set
            for link in links
        )
        or len(set(link_identities)) != len(link_identities)
    ):
        raise EngineeringError("invalid_schema")
    return graph


def validate_checkpoint(
    root: Path, checkpoint: Path, expected_commit: str
) -> dict:
    project_root = resolve_project_root(str(root))
    commit = git(project_root, "rev-parse", expected_commit)
    try:
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"valid": False, "reason": "invalid_json"}
    if not isinstance(payload, dict):
        return {"valid": False, "reason": "invalid_schema"}
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return {"valid": False, "reason": "invalid_schema"}
    if metadata.get("commit") != commit:
        return {"valid": False, "reason": "commit_mismatch"}
    try:
        expected_identity = checkpoint_identity(project_root, commit)
    except EngineeringError:
        return {"valid": False, "reason": "root_binding_mismatch"}
    if metadata.get("project_identity") != expected_identity:
        return {"valid": False, "reason": "root_binding_mismatch"}
    graph_path = checkpoint.parent / "graph.json"
    try:
        graph = _read_base_graph(graph_path)
    except EngineeringError as error:
        return {"valid": False, "reason": str(error)}
    if graph.get("built_at_commit") != commit:
        return {"valid": False, "reason": "commit_mismatch"}
    try:
        digest = _graph_digest(graph_path)
    except OSError:
        return {"valid": False, "reason": "invalid_json"}
    if metadata.get("graph_digest") != digest:
        return {"valid": False, "reason": "digest_mismatch"}
    if metadata.get("graphify_version") != GRAPHIFY_VERSION:
        return {"valid": False, "reason": "invalid_schema"}
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    integrity = payload.get("integrity")
    if (
        not isinstance(nodes, list)
        or not isinstance(edges, list)
        or not isinstance(integrity, dict)
        or any(not isinstance(item, dict) for item in nodes + edges)
    ):
        return {"valid": False, "reason": "invalid_schema"}
    try:
        manifest_name = _tracked_manifest_name_at(project_root, commit)
        if manifest_name is None:
            return {"valid": False, "reason": "overlay_mismatch"}
        config_path, links_path, _, _ = _project_paths_for_manifest(manifest_name)
        manifest = _json_at(project_root, commit, config_path)
        links = _json_at(project_root, commit, links_path)
        expected_nodes, expected_edges, expected_integrity = _validate_overlay(
            project_root,
            commit,
            manifest,
            links,
            manifest_name=manifest_name,
        )
    except EngineeringError:
        return {"valid": False, "reason": "overlay_mismatch"}
    if (
        nodes != expected_nodes
        or edges != expected_edges
        or integrity
        != {
            key: value
            for key, value in expected_integrity.items()
            if key not in {"input_digest", "inputs"}
        }
        or metadata.get("input_digest") != expected_integrity["input_digest"]
        or metadata.get("inputs") != expected_integrity["inputs"]
    ):
        return {"valid": False, "reason": "overlay_mismatch"}
    return {
        "valid": True,
        "reason": "exact_current",
        "checkpoint": str(checkpoint),
        "graph_digest": digest,
    }


def _checkpoint_destination(
    root: Path, commit: str, *, branch: str, kind: str
) -> Path:
    _validate_checkpoint_address(commit, branch, kind)
    graph_dir = _common_graph_dir(root)
    if kind == "canonical":
        return graph_dir / "main" / commit / "checkpoint.json"
    return (
        graph_dir
        / "features"
        / quote(branch, safe="")
        / commit
        / "checkpoint.json"
    )


def _validate_checkpoint_address(commit: object, branch: object, kind: object) -> None:
    if (
        not isinstance(commit, str)
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
        or not isinstance(kind, str)
        or kind not in {"canonical", "feature"}
        or not isinstance(branch, str)
        or not branch
        or len(branch) > 255
        or any(ord(character) < 32 or ord(character) == 127 for character in branch)
        or any(part in {"", ".", ".."} for part in PurePosixPath(branch).parts)
        or "\\" in branch
    ):
        raise EngineeringError("checkpoint_quarantine_identity_invalid")


def _checkpoint_tree_digest(path: Path, boundary: Path) -> tuple[str, int]:
    """Hash a checkpoint tree without following links or leaving its graph root."""
    path = Path(path).absolute()
    boundary = Path(boundary).absolute()
    try:
        _reject_reparse_ancestors(path, boundary)
    except EngineeringError as error:
        raise EngineeringError("checkpoint_quarantine_boundary_invalid") from error
    if not path.is_dir() or _is_reparse_point(path):
        raise EngineeringError("checkpoint_quarantine_boundary_invalid")
    entries: list[tuple[str, int, int, str]] = []
    for candidate in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        if _is_reparse_point(candidate):
            raise EngineeringError("checkpoint_quarantine_boundary_invalid")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise EngineeringError("checkpoint_quarantine_boundary_invalid")
        relative = candidate.relative_to(path).as_posix()
        if not relative or relative.startswith("../") or "\\" in relative:
            raise EngineeringError("checkpoint_quarantine_boundary_invalid")
        digest = hashlib.sha256()
        size = 0
        with candidate.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        entries.append(
            (relative, stat.S_IMODE(candidate.stat().st_mode), size, digest.hexdigest())
        )
    manifest = "\n".join(
        f"{relative}\0{mode:o}\0{size}\0{digest}"
        for relative, mode, size, digest in entries
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(manifest).hexdigest(), len(entries)


def _checkpoint_quarantine_record_path(graph_dir: Path, relative: str) -> Path:
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or "\\" in relative
        or ".." in parsed.parts
        or not parsed.parts
        or parsed.parts[0] != "quarantine"
    ):
        raise EngineeringError("checkpoint_quarantine_boundary_invalid")
    path = graph_dir.joinpath(*parsed.parts)
    try:
        _reject_reparse_ancestors(path, graph_dir)
        path.resolve().relative_to(graph_dir.resolve())
    except (EngineeringError, ValueError) as error:
        raise EngineeringError("checkpoint_quarantine_boundary_invalid") from error
    return path


def _quarantine_invalid_checkpoint(
    root: Path,
    destination: Path,
    commit: str,
    *,
    branch: str,
    kind: str,
) -> dict | None:
    """Move one invalid immutable address aside, preserving every byte."""
    _validate_checkpoint_address(commit, branch, kind)
    graph_dir = _common_graph_dir(root).absolute()
    _reject_reparse_ancestors(Path(destination).absolute(), graph_dir)
    source = Path(destination).absolute().parent
    if not source.exists():
        return None
    if not source.is_dir() or _is_reparse_point(source):
        raise EngineeringError("checkpoint_quarantine_boundary_invalid")
    try:
        validation = (
            validate_checkpoint(root, destination, commit)
            if destination.is_file()
            else {"valid": False, "reason": "missing_checkpoint"}
        )
    except (EngineeringError, OSError):
        validation = {"valid": False, "reason": "invalid_checkpoint"}
    if validation.get("valid"):
        return None
    digest, file_count = _checkpoint_tree_digest(source, graph_dir)
    try:
        original_relative = source.relative_to(graph_dir).as_posix()
    except ValueError as error:
        raise EngineeringError("checkpoint_quarantine_boundary_invalid") from error
    try:
        expected_identity = checkpoint_identity(root, commit)
    except EngineeringError:
        expected_identity = None
    observed_identity = None
    try:
        payload = json.loads(destination.read_text(encoding="utf-8"))
        observed_identity = payload.get("metadata", {}).get("project_identity")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        pass
    identity_status = (
        "matched"
        if isinstance(expected_identity, str)
        and expected_identity
        and observed_identity == expected_identity
        else "mismatch"
        if observed_identity is not None
        else "unavailable"
    )
    relative = PurePosixPath(
        "quarantine",
        kind,
        quote(branch, safe=""),
        commit,
        digest.removeprefix("sha256:"),
    )
    quarantine = _checkpoint_quarantine_record_path(graph_dir, relative.as_posix())
    metadata_path = quarantine.with_name(quarantine.name + ".json")
    try:
        _reject_reparse_ancestors(quarantine.parent, graph_dir)
        if quarantine.exists() or metadata_path.exists():
            raise EngineeringError("checkpoint_quarantine_collision")
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        _reject_reparse_ancestors(quarantine.parent, graph_dir)
    except EngineeringError:
        raise
    record = {
        "schema": CHECKPOINT_QUARANTINE_SCHEMA,
        "commit": commit,
        "branch": branch,
        "kind": kind,
        "reason": validation.get("reason", "invalid_checkpoint"),
        "digest": digest,
        "file_count": file_count,
        "original_relative_path": original_relative,
        "relative_path": relative.as_posix(),
        "identity": {
            "status": identity_status,
            "observed": observed_identity,
            "expected": expected_identity,
        },
        "quarantined_at": datetime.now(timezone.utc).isoformat(),
    }
    moved = False
    try:
        os.replace(source, quarantine)
        moved = True
        _atomic_text(metadata_path, json.dumps(record, indent=2) + "\n")
        return record
    except Exception as error:
        temporary_metadata = metadata_path.with_name(
            f".{metadata_path.name}.{os.getpid()}.tmp"
        )
        try:
            if temporary_metadata.is_file() and not _is_reparse_point(temporary_metadata):
                temporary_metadata.unlink()
            if metadata_path.exists() and not _is_reparse_point(metadata_path):
                metadata_path.unlink()
            if moved and quarantine.exists() and not source.exists():
                os.replace(quarantine, source)
        except Exception as rollback_error:
            raise EngineeringError(
                "checkpoint_quarantine_rollback_failed"
            ) from rollback_error
        raise EngineeringError("checkpoint_quarantine_failed") from error


def _restore_quarantined_checkpoint(root: Path, record: dict) -> dict:
    """Restore a quarantined tree only when its exact preimage is unchanged."""
    if not isinstance(record, dict) or record.get("schema") != CHECKPOINT_QUARANTINE_SCHEMA:
        raise EngineeringError("checkpoint_quarantine_record_invalid")
    commit = record.get("commit")
    branch = record.get("branch")
    kind = record.get("kind")
    relative = record.get("relative_path")
    digest = record.get("digest")
    if (
        not isinstance(relative, str)
        or not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        or not isinstance(record.get("file_count"), int)
        or record["file_count"] < 0
    ):
        raise EngineeringError("checkpoint_quarantine_record_invalid")
    _validate_checkpoint_address(commit, branch, kind)
    identity = record.get("identity")
    if (
        not isinstance(identity, dict)
        or identity.get("status") not in {"matched", "mismatch", "unavailable"}
        or any(
            value is not None and not isinstance(value, str)
            for value in (identity.get("observed"), identity.get("expected"))
        )
    ):
        raise EngineeringError("checkpoint_quarantine_record_invalid")
    graph_dir = _common_graph_dir(root).absolute()
    quarantine = _checkpoint_quarantine_record_path(graph_dir, relative)
    destination = _checkpoint_destination(root, commit, branch=branch, kind=kind)
    _reject_reparse_ancestors(destination, graph_dir)
    original = destination.parent
    expected_original = original.relative_to(graph_dir).as_posix()
    expected_relative = PurePosixPath(
        "quarantine",
        kind,
        quote(branch, safe=""),
        commit,
        digest.removeprefix("sha256:"),
    ).as_posix()
    if (
        record.get("original_relative_path") != expected_original
        or relative != expected_relative
    ):
        raise EngineeringError("checkpoint_quarantine_record_invalid")
    if not quarantine.exists():
        if destination.is_file() and validate_checkpoint(root, destination, commit)["valid"]:
            return {"restored": True, "already_regenerated": True}
        raise EngineeringError("checkpoint_quarantine_payload_missing")
    actual_digest, actual_file_count = _checkpoint_tree_digest(quarantine, graph_dir)
    if actual_digest != digest:
        raise EngineeringError("checkpoint_quarantine_digest_mismatch")
    if actual_file_count != record["file_count"]:
        raise EngineeringError("checkpoint_quarantine_file_count_mismatch")
    if original.exists():
        if destination.is_file() and validate_checkpoint(root, destination, commit)["valid"]:
            return {"restored": False, "reason": "regenerated_checkpoint_present"}
        if original.is_dir() and not _is_reparse_point(original):
            try:
                empty = not any(original.iterdir())
            except OSError as error:
                raise EngineeringError("checkpoint_quarantine_restore_conflict") from error
            if empty:
                original.rmdir()
            else:
                raise EngineeringError("checkpoint_quarantine_restore_conflict")
        else:
            raise EngineeringError("checkpoint_quarantine_restore_conflict")
    try:
        _reject_reparse_ancestors(original, graph_dir)
        original.parent.mkdir(parents=True, exist_ok=True)
        _reject_reparse_ancestors(original.parent, graph_dir)
        os.replace(quarantine, original)
        metadata_path = quarantine.with_name(quarantine.name + ".json")
        if metadata_path.is_file() and not _is_reparse_point(metadata_path):
            metadata_path.unlink()
    except EngineeringError:
        raise
    except OSError as error:
        raise EngineeringError("checkpoint_quarantine_restore_failed") from error
    return {"restored": True, "already_regenerated": False}


def _checkpoint_quarantine_records(root: Path) -> list[dict]:
    graph_dir = _common_graph_dir(root).absolute()
    quarantine_root = graph_dir / "quarantine"
    if not quarantine_root.exists():
        return []
    _reject_reparse_ancestors(quarantine_root, graph_dir)
    for current, directories, files in os.walk(quarantine_root, topdown=True, followlinks=False):
        current_path = Path(current)
        _reject_reparse_ancestors(current_path, graph_dir)
        for name in [*directories, *files]:
            candidate = current_path / name
            _reject_reparse_ancestors(candidate, graph_dir)
    records: list[dict] = []
    for metadata_path in sorted(quarantine_root.glob("*/*/*/*.json")):
        if metadata_path.is_symlink() or _is_reparse_point(metadata_path) or not metadata_path.is_file():
            raise EngineeringError("checkpoint_quarantine_boundary_invalid")
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EngineeringError("checkpoint_quarantine_record_invalid") from error
        if not isinstance(payload, dict) or payload.get("schema") != CHECKPOINT_QUARANTINE_SCHEMA:
            raise EngineeringError("checkpoint_quarantine_record_invalid")
        _validate_checkpoint_address(
            payload.get("commit"), payload.get("branch"), payload.get("kind")
        )
        identity = payload.get("identity")
        if (
            not isinstance(identity, dict)
            or identity.get("status") not in {"matched", "mismatch", "unavailable"}
            or any(
                value is not None and not isinstance(value, str)
                for value in (identity.get("observed"), identity.get("expected"))
            )
        ):
            raise EngineeringError("checkpoint_quarantine_record_invalid")
        relative = payload.get("relative_path")
        if (
            not isinstance(relative, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", payload.get("digest", ""))
            or not isinstance(payload.get("file_count"), int)
            or payload["file_count"] < 0
        ):
            raise EngineeringError("checkpoint_quarantine_record_invalid")
        expected_relative = PurePosixPath(
            "quarantine",
            payload["kind"],
            quote(payload["branch"], safe=""),
            payload["commit"],
            payload["digest"].removeprefix("sha256:"),
        ).as_posix()
        if relative != expected_relative:
            raise EngineeringError("checkpoint_quarantine_record_invalid")
        quarantine = _checkpoint_quarantine_record_path(graph_dir, relative)
        if metadata_path.absolute() != quarantine.with_name(quarantine.name + ".json").absolute():
            raise EngineeringError("checkpoint_quarantine_record_invalid")
        destination = _checkpoint_destination(
            root,
            payload["commit"],
            branch=payload["branch"],
            kind=payload["kind"],
        )
        _reject_reparse_ancestors(destination, graph_dir)
        if (
            payload.get("original_relative_path")
            != destination.parent.relative_to(graph_dir).as_posix()
        ):
            raise EngineeringError("checkpoint_quarantine_record_invalid")
        reason = payload.get("reason", "invalid_checkpoint")
        try:
            digest, file_count = _checkpoint_tree_digest(quarantine, graph_dir)
        except EngineeringError:
            digest = None
            file_count = None
            reason = "checkpoint_quarantine_payload_invalid"
        if digest is not None and digest != payload.get("digest"):
            reason = "checkpoint_quarantine_digest_mismatch"
        if file_count is not None and file_count != payload["file_count"]:
            reason = "checkpoint_quarantine_file_count_mismatch"
        records.append(
            {
                "commit": payload.get("commit"),
                "branch": payload.get("branch"),
                "kind": payload.get("kind"),
                "state": "quarantined",
                "reason": reason,
                "digest": payload.get("digest"),
                "relative_path": relative,
                "identity": payload.get("identity"),
            }
        )
    return records


def _select_exact_checkpoint(
    root: Path, commit: str, *, branch: str, kind: str
) -> Path | None:
    destination = _checkpoint_destination(
        root, commit, branch=branch, kind=kind
    )
    if commit in _read_stale(root) or not destination.is_file():
        return None
    if not validate_checkpoint(root, destination, commit)["valid"]:
        return None
    return destination


def _checkpoint_candidate_at(
    root: Path,
    commit: str,
    *,
    branch: str,
    kind: str,
    graphify_version: str,
    manifest_name: str,
    graph_digest: str | None = None,
) -> tuple[Path, dict]:
    config_path, links_path, _, _ = _project_paths_for_manifest(manifest_name)
    manifest = _json_at(root, commit, config_path)
    links = _json_at(root, commit, links_path)
    nodes, edges, integrity = _validate_overlay(
        root, commit, manifest, links, manifest_name=manifest_name
    )
    checkpoint = {
        "metadata": {
            "project_identity": checkpoint_identity(root, commit),
            "project": manifest.get("project", {}).get("name", root.name),
            "branch": branch,
            "commit": commit,
            "kind": kind,
            "graphify_version": graphify_version,
            "graph_digest": graph_digest,
            "overlay_version": manifest.get("overlay", {}).get("version"),
            "input_digest": integrity.pop("input_digest"),
            "inputs": integrity.pop("inputs"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "integrity": integrity,
        "nodes": nodes,
        "edges": edges,
    }
    destination = _checkpoint_destination(
        root, commit, branch=branch, kind=kind
    )
    return destination, checkpoint


def _compatible_ancestor(
    root: Path, commit: str, graphify_version: str
) -> tuple[str, Path] | None:
    compatible: list[tuple[int, str, Path]] = []
    for path in _checkpoint_files(root):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            candidate = payload["metadata"]["commit"]
            if payload["metadata"].get("graphify_version") != graphify_version:
                continue
            if not validate_checkpoint(root, path, candidate)["valid"]:
                continue
            if subprocess.run(
                ["git", "-C", str(root), "merge-base", "--is-ancestor", candidate, commit],
                capture_output=True,
                text=True,
                env=_controller_git_environment(),
            ).returncode:
                continue
            distance = int(git(root, "rev-list", "--count", f"{candidate}..{commit}"))
            compatible.append((distance, candidate, path))
        except (EngineeringError, KeyError, OSError, ValueError, json.JSONDecodeError):
            continue
    if not compatible:
        return None
    _, candidate, path = min(compatible, key=lambda item: (item[0], item[1]))
    return candidate, path


def _changed_files(root: Path, ancestor: str, commit: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--name-status",
            "-z",
            "-M",
            "--diff-filter=ACDMRT",
            ancestor,
            commit,
            "--",
        ],
        capture_output=True,
        env=_controller_git_environment(),
    )
    if result.returncode:
        raise EngineeringError(result.stderr.decode(errors="replace").strip())
    fields = result.stdout.decode("utf-8", errors="strict").split("\0")
    fields.pop() if fields and fields[-1] == "" else None
    changed: list[str] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        count = 2 if status.startswith(("R", "C")) else 1
        if index + count > len(fields):
            raise EngineeringError("Invalid Git changed-path record.")
        changed.extend(fields[index : index + count])
        index += count
    return list(dict.fromkeys(path.replace("\\", "/") for path in changed))


def _semantic_changes(
    changed: list[str], code_extensions: list[str], manifest_name: str
) -> list[str]:
    control_prefix = (
        "docs/engineering-traceability/"
        if manifest_name == V1_CONFIG
        else "docs/engineering/"
    )
    controls = {manifest_name}
    supported_suffixes = {suffix.lower() for suffix in code_extensions}
    return [
        path
        for path in changed
        if path in controls
        or path.startswith(control_prefix)
        or Path(path).suffix.lower() not in supported_suffixes
    ]


def _lexical_absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.path.normpath(os.fspath(path))))


def _trusted_common_dirs(root: Path) -> tuple[Path, Path]:
    common = Path(
        git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    lexical = _lexical_absolute(common if common.is_absolute() else root / common)
    return lexical, lexical.resolve()


def _validated_operation_paths(root: Path, operation_id: str) -> dict[str, Path]:
    if not re.fullmatch(r"[0-9a-f]{32}", operation_id):
        raise EngineeringError("invalid_hook_operation_record")
    lexical_common, resolved_common = _trusted_common_dirs(root)
    state = lexical_common / "engineering-graphs" / "state"
    operations = state / "operations"
    paths = {
        "operation_root": operations / operation_id,
        "record_path": operations / operation_id / "resources.json",
        "worktree_path": operations / operation_id / "worktree",
        "staging_path": operations / operation_id / "staging",
        "repository_lock_path": state / "lock",
        "result_path": operations / operation_id / "result.json",
    }
    targets = [*paths.values(), paths["repository_lock_path"] / "owner.json"]
    inspected: set[Path] = set()
    for target in targets:
        if not target.is_relative_to(lexical_common):
            raise EngineeringError("invalid_hook_operation_boundary")
        current = lexical_common
        for part in target.relative_to(lexical_common).parts:
            current /= part
            if current in inspected:
                continue
            inspected.add(current)
            try:
                current.lstat()
            except FileNotFoundError:
                break
            except OSError as error:
                raise EngineeringError("invalid_hook_operation_boundary") from error
            if _is_reparse_point(current):
                raise EngineeringError("invalid_hook_operation_boundary")
    resolved_state = (resolved_common / "engineering-graphs" / "state").resolve()
    resolved_operations = (resolved_state / "operations").resolve()
    resolved_root = paths["operation_root"].resolve()
    if (
        not paths["operation_root"].is_relative_to(operations)
        or resolved_root != (resolved_operations / operation_id).resolve()
        or paths["repository_lock_path"] != state / "lock"
        or paths["repository_lock_path"].resolve()
        != (resolved_state / "lock").resolve()
        or any(
            not paths[key].resolve().is_relative_to(resolved_root)
            for key in (
                "record_path",
                "worktree_path",
                "staging_path",
                "result_path",
            )
        )
    ):
        raise EngineeringError("invalid_hook_operation_boundary")
    return paths


def register_hook_operation(root: Path) -> dict:
    project_root = resolve_project_root(str(root))
    operation_id = uuid.uuid4().hex
    paths = _validated_operation_paths(project_root, operation_id)
    paths["operation_root"].mkdir(parents=True)
    paths = _validated_operation_paths(project_root, operation_id)
    token = uuid.uuid4().hex
    record = {
        "operation_id": operation_id,
        "lock_token": token,
        "phase": "registered",
        "owner_pid": os.getpid(),
        "owner_identity": _process_identity(os.getpid()),
        "created_at": time.time(),
        **{key: str(_lexical_absolute(value)) for key, value in paths.items()},
    }
    _atomic_text(paths["record_path"], json.dumps(record, indent=2) + "\n")
    return record


def _read_operation(root: Path, operation_id: str) -> dict:
    paths = _validated_operation_paths(root, operation_id)
    try:
        record = json.loads(paths["record_path"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("invalid_hook_operation_record") from error
    for key, expected in paths.items():
        try:
            serialized = Path(record[key])
            candidate = _lexical_absolute(serialized)
        except (KeyError, OSError, TypeError, ValueError) as error:
            raise EngineeringError("invalid_hook_operation_record") from error
        if not serialized.is_absolute() or candidate != expected:
            raise EngineeringError("invalid_hook_operation_record")
    if record.get("operation_id") != operation_id:
        raise EngineeringError("invalid_hook_operation_record")
    return {**record, **{key: str(value) for key, value in paths.items()}}


def _write_operation(record: dict) -> None:
    _atomic_text(
        Path(record["record_path"]),
        json.dumps(record, indent=2) + "\n",
    )


def _acquire_repository_lock(record: dict) -> bool:
    lock = Path(record["repository_lock_path"])
    try:
        lock.mkdir(parents=True)
    except FileExistsError:
        return False
    owner = {
        "operation_id": record["operation_id"],
        "lock_token": record["lock_token"],
        "owner_pid": os.getpid(),
        "owner_identity": _process_identity(os.getpid()),
        "created_at": time.time(),
    }
    if "run_id" in record:
        owner["run_id"] = record["run_id"]
    _atomic_text(lock / "owner.json", json.dumps(owner, indent=2) + "\n")
    return True


def _lock_owner(record: dict) -> dict | None:
    path = Path(record["repository_lock_path"]) / "owner.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _process_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint32,
        )
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_uint32()
        try:
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_process_state(pid: int) -> str:
    """Distinguish an exited Windows PID from an inaccessible live PID."""
    if os.name != "nt":
        return "unknown"
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint32,
    )
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    )
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.OpenProcess(0x1000 | 0x0400, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        return "dead" if error in (87, 1168) else "unknown"
    exit_code = ctypes.c_uint32()
    try:
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return "unknown"
        return "live" if exit_code.value == 259 else "dead"
    finally:
        kernel32.CloseHandle(handle)


def _process_state(pid: object) -> str:
    """Return live/dead/unknown without treating access denial as death."""
    if not isinstance(pid, int) or pid <= 0:
        return "dead"
    if _process_alive(pid):
        return "live"
    if os.name == "nt":
        return _windows_process_state(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "dead"
    except PermissionError:
        return "unknown"
    except OSError:
        return "unknown"
    return "live"


def _owner_process_state(owner: dict | None) -> str:
    """Conservatively validate a durable lock owner's PID and start identity."""
    if not isinstance(owner, dict):
        return "dead"
    pid = owner.get("owner_pid")
    expected = owner.get("owner_identity")
    if not isinstance(pid, int) or pid <= 0:
        return "ambiguous"
    state = _process_state(pid)
    current = _process_identity(pid)
    if state == "dead":
        if current is not None:
            if not isinstance(expected, dict) or current.get("start_time") != expected.get("start_time"):
                return "ambiguous"
        return "dead"
    if not isinstance(expected, dict):
        return "ambiguous"
    if state == "live":
        if current is None:
            return "ambiguous"
        if current.get("start_time") != expected.get("start_time"):
            return "ambiguous"
        return "live"
    return "ambiguous"


def _same_process_identity(current: dict | None, expected: dict) -> bool:
    return (
        isinstance(current, dict)
        and current.get("pid") == expected.get("pid")
        and current.get("start_time") == expected.get("start_time")
    )


def _process_tree_status(record: dict) -> dict:
    """Return conservative process-tree evidence for an orphan operation."""
    worker_pid = record.get("worker_pid")
    expected = record.get("worker_identity")
    tree = record.get("worker_process_tree")
    if not isinstance(worker_pid, int) or worker_pid <= 0:
        return {"state": "dead", "evidence": "no_worker_started"}
    if not isinstance(expected, dict) or not isinstance(tree, list) or not tree:
        if (
            record.get("worker_process_tree_dead") is True
            and isinstance(record.get("worker_process_tree_evidence"), dict)
            and record["worker_process_tree_evidence"].get("state") == "dead"
            and (
                os.name != "nt"
                or record.get("worker_process_tree_authoritative") is True
            )
        ):
            return {"state": "dead", "evidence": "termination_confirmed"}
        return {"state": "identity_ambiguous", "evidence": "missing_process_tree_identity"}
    expected_by_pid = {}
    for item in tree:
        if not isinstance(item, dict) or not isinstance(item.get("pid"), int):
            return {"state": "identity_ambiguous", "evidence": "invalid_process_tree_identity"}
        if not isinstance(item.get("start_time"), str) or not item["start_time"]:
            return {"state": "identity_ambiguous", "evidence": "invalid_process_tree_identity"}
        if item["pid"] in expected_by_pid:
            return {"state": "identity_ambiguous", "evidence": "duplicate_process_identity"}
        expected_by_pid[item["pid"]] = item
    leader = expected_by_pid.get(worker_pid)
    if leader is None or leader.get("start_time") != expected.get("start_time"):
        return {"state": "identity_ambiguous", "evidence": "leader_identity_mismatch"}
    if record.get("worker_process_tree_complete") is False:
        return {"state": "identity_ambiguous", "evidence": "incomplete_process_tree_snapshot"}
    fresh_tree = _capture_process_tree(worker_pid)
    if fresh_tree is None:
        return {"state": "identity_ambiguous", "evidence": "fresh_process_tree_unavailable"}
    for current in fresh_tree:
        if not isinstance(current, dict) or not isinstance(current.get("pid"), int):
            return {"state": "identity_ambiguous", "evidence": "invalid_fresh_process_tree"}
        saved = expected_by_pid.get(current["pid"])
        if saved is None:
            return {
                "state": "live",
                "evidence": "fresh_process_tree_child",
                "pid": current["pid"],
            }
        if not _same_process_identity(current, saved):
            return {
                "state": "identity_ambiguous",
                "evidence": "pid_reused",
                "pid": current["pid"],
            }
    for pid, saved in expected_by_pid.items():
        state = _process_state(pid)
        if state == "unknown":
            return {"state": "identity_ambiguous", "evidence": "process_state_unknown", "pid": pid}
        if state == "dead":
            identity = _process_identity(pid)
            if identity is not None and not _same_process_identity(identity, saved):
                return {"state": "identity_ambiguous", "evidence": "pid_reused", "pid": pid}
            continue
        current = _process_identity(pid)
        if current is None:
            return {"state": "identity_ambiguous", "evidence": "process_identity_unreadable", "pid": pid}
        if not _same_process_identity(current, saved):
            return {"state": "identity_ambiguous", "evidence": "pid_reused", "pid": pid}
        return {"state": "live", "evidence": "saved_process_alive", "pid": pid}
    return {"state": "dead", "evidence": "saved_process_tree_absent"}


def _process_identity(pid: int) -> dict | None:
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name == "nt":
        import ctypes

        class _FileTime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetProcessTimes.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
        )
        kernel32.GetProcessTimes.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel32.OpenProcess(0x0400 | 0x1000, False, pid)
        if not handle:
            return None
        creation = _FileTime()
        exit_time = _FileTime()
        kernel_time = _FileTime()
        user_time = _FileTime()
        try:
            if not kernel32.GetProcessTimes(
                handle, ctypes.byref(creation), ctypes.byref(exit_time),
                ctypes.byref(kernel_time), ctypes.byref(user_time)
            ):
                return None
            start = (int(creation.high) << 32) | int(creation.low)
            return {"pid": pid, "start_time": str(start)}
        finally:
            kernel32.CloseHandle(handle)
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        fields = stat_path.read_text(encoding="utf-8").split()
        return {"pid": pid, "start_time": fields[21]}
    except (OSError, IndexError):
        return None


def _release_failed_start_lock(record: dict) -> bool:
    """Release only the exact lock acquired by this controller before Popen failed."""
    lock = Path(record["repository_lock_path"])
    owner_path = lock / "owner.json"
    try:
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    current_identity = _process_identity(os.getpid())
    identity_matches = owner.get("owner_identity") == record.get("owner_identity")
    if current_identity is not None:
        identity_matches = identity_matches and owner.get("owner_identity") == current_identity
    if (
        owner.get("operation_id") != record.get("operation_id")
        or owner.get("lock_token") != record.get("lock_token")
        or owner.get("owner_pid") != os.getpid()
        or not identity_matches
    ):
        return False
    try:
        _reject_reparse_ancestors(lock)
        owner_path.unlink()
        lock.rmdir()
    except OSError:
        return False
    return True
def _windows_process_entries() -> list[dict] | None:
    """Enumerate Windows processes and parent IDs without a shell command."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class _ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W))
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W))
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        return None
    entries = []
    entry = _ProcessEntry32W()
    entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
    try:
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return None
        while True:
            entries.append(
                {
                    "pid": int(entry.th32ProcessID),
                    "parent_pid": int(entry.th32ParentProcessID),
                }
            )
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return entries


def _capture_process_tree(pid: int) -> list[dict] | None:
    """Capture a bounded PID/parent/start-time snapshot without shelling out."""
    root = _process_identity(pid)
    if root is None:
        return [] if not _process_alive(pid) else None
    if os.name == "nt":
        raw_entries = _windows_process_entries()
        if raw_entries is None:
            return None
        by_pid = {item["pid"]: item for item in raw_entries}
        if pid not in by_pid:
            return [root]
        selected = []
        for candidate_pid in by_pid:
            if candidate_pid == pid or _is_descendant(candidate_pid, by_pid, pid):
                identity = _process_identity(candidate_pid)
                if identity is None:
                    if _process_state(candidate_pid) != "dead":
                        return None
                    continue
                selected.append({**identity, "parent_pid": by_pid[candidate_pid]["parent_pid"]})
        return selected or [root]
    entries = {pid: {**root, "parent_pid": None}}
    parent_by_pid = {pid: None}
    proc_root = Path("/proc")
    try:
        candidates = [item for item in proc_root.iterdir() if item.name.isdigit()]
    except OSError:
        return [root]
    for item in candidates:
        try:
            fields = (item / "stat").read_text(encoding="utf-8").split()
            child_pid = int(item.name)
            parent_pid = int(fields[3])
            identity = _process_identity(child_pid)
        except (OSError, ValueError, IndexError):
            continue
        parent_by_pid[child_pid] = parent_pid
        if identity is not None:
            entries[child_pid] = {**identity, "parent_pid": parent_pid}
    for child_pid, parent_pid in parent_by_pid.items():
        if child_pid == pid or _is_descendant(child_pid, parent_by_pid, pid):
            if child_pid not in entries:
                if _process_state(child_pid) != "dead":
                    return None
    descendants = [item for child_pid, item in entries.items() if child_pid == pid or _is_descendant(child_pid, parent_by_pid, pid)]
    return descendants or [root]


def _is_descendant(pid: int, entries: dict[int, dict], root_pid: int) -> bool:
    seen = set()
    current = pid
    while current not in seen:
        seen.add(current)
        item = entries.get(current)
        parent = item.get("parent_pid") if isinstance(item, dict) else item
        if parent == root_pid:
            return True
        if not isinstance(parent, int):
            return False
        current = parent
    return False


def orphan_operation_status(root: Path) -> dict:
    """List durable operation records with conservative process-tree status."""
    project_root = resolve_project_root(str(root))
    operations = _common_graph_dir(project_root) / "state" / "operations"
    result = []
    if operations.is_dir():
        for child in sorted(operations.iterdir()):
            if not child.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", child.name):
                continue
            try:
                record = _read_operation(project_root, child.name)
                status = _process_tree_status(record)
            except EngineeringError as error:
                result.append({"operation_id": child.name, "state": "invalid", "reason": str(error)})
                continue
            result.append({
                "operation_id": child.name,
                "phase": record.get("phase"),
                "worker_identity": record.get("worker_identity"),
                "worker_process_tree": record.get("worker_process_tree"),
                "process_tree": status,
                "lock": _lock_owner(record),
            })
    return {"schema": "engineering.orphan-status.v1", "operations": result}


def reap_orphan_operation(root: Path, operation_id: str, *, timeout_seconds: float) -> dict:
    """Reap one orphan only after fresh, exact process and lock evidence."""
    project_root = resolve_project_root(str(root))
    try:
        record = _read_operation(project_root, operation_id)
    except EngineeringError as error:
        return {"completed": False, "reason": str(error), "user_visible": True}
    if record.get("phase") not in {
        "orphaned",
        "registered",
        "worktree_created",
        "staging_ready",
        "validating",
        "published",
    }:
        return {"completed": False, "reason": "operation_not_orphaned", "user_visible": True}
    owner = _lock_owner(record)
    if owner is None:
        return {"completed": False, "reason": "repository_lock_owner_missing", "user_visible": True}
    if not _orphan_is_old_enough(record, owner):
        return {"completed": False, "reason": "orphan_too_young", "user_visible": True}
    if record.get("worker_start_pending") is True:
        return {"completed": False, "reason": "live_hook_operation", "user_visible": True}
    owner_pid = owner.get("owner_pid")
    owner_identity = owner.get("owner_identity")
    if not isinstance(owner_pid, int) or not isinstance(owner_identity, dict):
        return {"completed": False, "reason": "ambiguous_worker_process_identity", "user_visible": True}
    owner_state = _owner_process_state(owner)
    if owner_state == "live":
        if record.get("worker_pid") is None:
            return {"completed": False, "reason": "live_hook_operation", "user_visible": True}
        return {"completed": False, "reason": "live_hook_operation", "user_visible": True}
    if owner_state != "dead":
        return {"completed": False, "reason": "ambiguous_worker_process_identity", "user_visible": True}
    status = _process_tree_status(record)
    if status.get("state") == "live":
        return {"completed": False, "reason": "live_worker_process_tree", "user_visible": True}
    if status.get("state") != "dead":
        return {"completed": False, "reason": "ambiguous_worker_process_identity", "user_visible": True}
    if (
        owner.get("operation_id") != operation_id
        or owner.get("lock_token") != record.get("lock_token")
    ):
        return {"completed": False, "reason": "repository_lock_owner_mismatch", "user_visible": True}
    if owner is not None and record.get("worker_pid") is not None:
        if owner.get("owner_pid") != record.get("worker_pid"):
            return {"completed": False, "reason": "repository_lock_owner_mismatch", "user_visible": True}
        if owner.get("owner_identity") != record.get("worker_identity"):
            return {"completed": False, "reason": "ambiguous_worker_process_identity", "user_visible": True}
    status = _process_tree_status(record)
    if status.get("state") != "dead":
        return {
            "completed": False,
            "reason": "live_worker_process_tree"
            if status.get("state") == "live"
            else "ambiguous_worker_process_identity",
            "user_visible": True,
        }
    record["worker_process_tree_dead"] = True
    record["worker_process_tree_evidence"] = status
    record["process_tree_reaped_at"] = time.time()
    _write_operation(record)
    return cleanup_hook_operation(project_root, operation_id, timeout_seconds=timeout_seconds)


def _orphan_is_old_enough(record: dict, owner: dict | None) -> bool:
    now = time.time()
    timestamps = [record.get("created_at")]
    if owner is not None:
        timestamps.append(owner.get("created_at"))
    return all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= now - value
        and now - value >= ORPHAN_MINIMUM_AGE_SECONDS
        for value in timestamps
    )


def _process_group_alive(process: subprocess.Popen, pgid: int) -> bool:
    process.poll()
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_process_group(
    process: subprocess.Popen, pgid: int, timeout: float
) -> bool:
    deadline = time.monotonic() + timeout
    while _process_group_alive(process, pgid):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))
    return True


def _saved_process_tree_absent(tree: object) -> tuple[bool, str]:
    if not isinstance(tree, list) or not tree:
        return False, "missing_process_tree_identity"
    for saved in tree:
        if not isinstance(saved, dict) or not isinstance(saved.get("pid"), int):
            return False, "invalid_process_tree_identity"
        state = _process_state(saved["pid"])
        if state == "unknown":
            return False, "process_state_unknown"
        if state == "dead":
            identity = _process_identity(saved["pid"])
            if identity is not None and identity.get("start_time") != saved.get("start_time"):
                return False, "pid_reused"
            continue
        current = _process_identity(saved["pid"])
        if current is None:
            return False, "process_identity_unreadable"
        if current.get("start_time") != saved.get("start_time"):
            return False, "pid_reused"
        return False, "saved_process_alive"
    return True, "saved_process_tree_absent"


def _wait_saved_process_tree_absent(tree: object, timeout: float) -> bool:
    """Bound whole-tree proof after a Windows termination request."""
    deadline = time.monotonic() + timeout
    while True:
        proven, _ = _saved_process_tree_absent(tree)
        if proven:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def _terminate_process_tree(
    process: subprocess.Popen,
    pgid: int | None = None,
    *,
    expected_tree: list[dict] | None = None,
) -> bool:
    if os.name == "nt":
        if process.poll() is not None:
            if expected_tree is None:
                setattr(process, "_engineering_tree_proven", False)
                return False
            proven = _wait_saved_process_tree_absent(
                expected_tree, PROCESS_TREE_TERMINATION_PROOF_SECONDS
            )
            setattr(process, "_engineering_tree_proven", proven)
            return proven
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        if expected_tree is not None:
            proven = _wait_saved_process_tree_absent(
                expected_tree, PROCESS_TREE_TERMINATION_PROOF_SECONDS
            )
        else:
            # A leader exit without a saved tree is not whole-tree proof.
            proven = False
        setattr(process, "_engineering_tree_proven", proven)
        return proven
    if pgid is None:
        if process.poll() is not None:
            return True
        try:
            pgid = os.getpgid(process.pid)
        except OSError:
            process.kill()
            process.wait(timeout=2)
            return process.poll() is not None
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    if _wait_process_group(process, pgid, 2):
        return True
    try:
        os.killpg(pgid, getattr(signal, "SIGKILL", 9))
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return _wait_process_group(process, pgid, 2)


def _rmtree_argv(*paths: Path) -> list[str]:
    return [
        str(Path(sys.executable).resolve()),
        "-c",
        (
            "import pathlib,shutil,sys;"
            "[(shutil.rmtree(p) if p.is_dir() else p.unlink()) "
            "for p in map(pathlib.Path,sys.argv[1:]) if p.exists()]"
        ),
        *(str(path) for path in paths),
    ]


def _start_cleanup(command: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=(
            _controller_git_environment()
            if command and Path(command[0]).name.casefold() in {"git", "git.exe"}
            else None
        ),
    )


def _kill_and_reap_cleanup(
    process: subprocess.Popen, wait_seconds: float
) -> bool:
    process.kill()
    try:
        process.wait(timeout=max(0.0, wait_seconds))
    except subprocess.TimeoutExpired:
        return False
    finally:
        for stream_name in ("stdout", "stderr"):
            stream = getattr(process, stream_name, None)
            if stream is not None:
                stream.close()
    return True


def _bounded_cleanup_command(
    command: list[str], deadline: float
) -> tuple[bool, str, int | None]:
    remaining = deadline - time.monotonic()
    if remaining < 0.05:
        return False, "cleanup_timeout", None
    try:
        process = _start_cleanup(command)
    except OSError:
        return False, "remove_failed", None
    remaining = deadline - time.monotonic()
    if remaining <= CLEANUP_TERMINATION_GRACE_SECONDS:
        reaped = _kill_and_reap_cleanup(process, remaining)
        return False, "cleanup_timeout", None if reaped else process.pid
    try:
        process.communicate(timeout=remaining - CLEANUP_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        reaped = _kill_and_reap_cleanup(
            process, CLEANUP_TERMINATION_GRACE_SECONDS
        )
        return False, "cleanup_timeout", None if reaped else process.pid
    return (
        (True, "clean", None)
        if process.returncode == 0
        else (False, "remove_failed", None)
    )


def _bounded_rmtree_many(
    paths: list[Path], deadline: float
) -> tuple[bool, str, int | None]:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return True, "clean", None
    return _bounded_cleanup_command(_rmtree_argv(*existing), deadline)


def _bounded_worktree_remove(
    root: Path, worktree: Path, deadline: float
) -> tuple[bool, str, int | None]:
    if not worktree.exists():
        return True, "clean", None
    completed, reason, surviving_pid = _bounded_cleanup_command(
        [
            "git",
            "-C",
            str(root),
            "worktree",
            "remove",
            "--force",
            str(worktree),
        ],
        deadline,
    )
    return (
        (completed, reason, surviving_pid)
        if completed or reason == "cleanup_timeout"
        else (False, "registered_worktree_remove_failed", surviving_pid)
    )


def _orphan_cleanup_result(
    root: Path,
    operation_id: str,
    record: dict,
    reason: str,
    started: float,
    surviving_pid: int | None = None,
) -> dict:
    try:
        paths = _validated_operation_paths(root, operation_id)
    except EngineeringError:
        return {
            "completed": False,
            "reason": "invalid_hook_operation_boundary",
            "user_visible": True,
            "duration": time.monotonic() - started,
        }
    trusted_record = {
        **record,
        **{key: str(value) for key, value in paths.items()},
        "phase": "orphaned",
    }
    if surviving_pid is not None:
        trusted_record["cleanup_pid"] = surviving_pid
        trusted_record["cleanup_process_dead"] = False
    _write_operation(trusted_record)
    return {
        "completed": False,
        "reason": reason,
        "user_visible": True,
        "duration": time.monotonic() - started,
    }


def _recover_worker_tree_state(
    root: Path, operation_id: str, record: dict
) -> dict | None:
    if record.get("worker_start_pending") is True:
        return None
    if "worker_pid" not in record:
        return record
    if record.get("worker_process_tree_dead") is True:
        status = _process_tree_status(record)
        if status.get("state") != "dead":
            return None
        paths = _validated_operation_paths(root, operation_id)
        trusted_record = {
            **record,
            **{key: str(value) for key, value in paths.items()},
            "worker_process_tree_evidence": status,
        }
        _write_operation(trusted_record)
        return trusted_record
    worker_pid = record.get("worker_pid")
    pgid = record.get("worker_pgid")
    killpg = getattr(os, "killpg", None)
    if os.name == "nt" and not isinstance(pgid, int):
        status = _process_tree_status(record)
        if status.get("state") != "dead":
            return None
        paths = _validated_operation_paths(root, operation_id)
        trusted_record = {
            **record,
            **{key: str(value) for key, value in paths.items()},
            "worker_process_tree_dead": True,
            "worker_process_tree_evidence": status,
        }
        _write_operation(trusted_record)
        return trusted_record
    if (
        not isinstance(worker_pid, int)
        or worker_pid <= 0
        or not isinstance(pgid, int)
        or pgid <= 0
        or killpg is None
    ):
        return None
    try:
        killpg(pgid, 0)
    except ProcessLookupError:
        paths = _validated_operation_paths(root, operation_id)
        trusted_record = {
            **record,
            **{key: str(value) for key, value in paths.items()},
            "worker_process_tree_dead": True,
        }
        _write_operation(trusted_record)
        return trusted_record
    except OSError:
        return None
    return None


def cleanup_hook_operation(
    root: Path,
    operation_id: str,
    *,
    timeout_seconds: float,
    allow_replaced_completion_lock: bool = False,
) -> dict:
    started = time.monotonic()
    deadline = started + max(0.0, timeout_seconds)
    if timeout_seconds < 0.05:
        return {
            "completed": False,
            "reason": "cleanup_timeout",
            "user_visible": True,
            "duration": time.monotonic() - started,
        }
    project_root = resolve_project_root(str(root))
    try:
        record = _read_operation(project_root, operation_id)
    except EngineeringError as error:
        return {"completed": False, "reason": str(error), "user_visible": True}

    def trusted_paths() -> dict[str, Path] | None:
        try:
            return _validated_operation_paths(project_root, operation_id)
        except EngineeringError:
            return None

    def invalid_boundary() -> dict:
        return {
            "completed": False,
            "reason": "invalid_hook_operation_boundary",
            "user_visible": True,
            "duration": time.monotonic() - started,
        }

    try:
        recovered_record = _recover_worker_tree_state(
            project_root, operation_id, record
        )
    except EngineeringError:
        return invalid_boundary()
    if recovered_record is None:
        return {
            "completed": False,
            "reason": "live_worker_process_tree",
            "user_visible": True,
            "duration": time.monotonic() - started,
        }
    record = recovered_record
    cleanup_pid = record.get("cleanup_pid")
    if cleanup_pid is not None:
        if _process_state(cleanup_pid) != "dead":
            return {
                "completed": False,
                "reason": "live_cleanup_process",
                "user_visible": True,
                "duration": time.monotonic() - started,
            }
        record.pop("cleanup_pid")
        record["cleanup_process_dead"] = True
        _write_operation(record)
    if (
        record.get("phase") == "registered"
        and _owner_process_state(
            {
                "owner_pid": record.get("owner_pid"),
                "owner_identity": record.get("owner_identity"),
            }
        ) == "live"
    ):
        return {
            "completed": False,
            "reason": "live_hook_operation",
            "user_visible": True,
            "duration": time.monotonic() - started,
        }
    paths = trusted_paths()
    if paths is None:
        return invalid_boundary()
    owner = _lock_owner({**record, **{key: str(value) for key, value in paths.items()}})
    replaced_completion_lock = False
    if owner is not None:
        if (
            owner.get("operation_id") != operation_id
            or owner.get("lock_token") != record.get("lock_token")
        ):
            if not (
                allow_replaced_completion_lock
                and record.get("controller_owned_completion") is True
                and not isinstance(record.get("worker_pid"), int)
            ):
                return _orphan_cleanup_result(
                    project_root,
                    operation_id,
                    record,
                    "repository_lock_owner_mismatch",
                    started,
                )
            replaced_completion_lock = True
        owner_state = _owner_process_state(owner) if not replaced_completion_lock else "dead"
        if owner_state != "dead":
            return _orphan_cleanup_result(
                project_root,
                operation_id,
                record,
                "repository_lock_owner_mismatch"
                if owner_state == "live"
                else "ambiguous_worker_process_identity",
                started,
            )
    paths = trusted_paths()
    if paths is None:
        return invalid_boundary()
    worktree = paths["worktree_path"]
    completed, reason, surviving_pid = _bounded_worktree_remove(
        project_root, worktree, deadline
    )
    if not completed:
        return _orphan_cleanup_result(
            project_root,
            operation_id,
            record,
            reason,
            started,
            surviving_pid,
        )
    paths = trusted_paths()
    if paths is None:
        return invalid_boundary()
    staging = paths["staging_path"]
    completed, reason, surviving_pid = _bounded_rmtree_many(
        [staging], deadline
    )
    if not completed:
        return _orphan_cleanup_result(
            project_root,
            operation_id,
            record,
            reason,
            started,
            surviving_pid,
        )
    paths = trusted_paths()
    if paths is None:
        return invalid_boundary()
    lock = paths["repository_lock_path"]
    if lock.exists():
        owner = _lock_owner(
            {**record, **{key: str(value) for key, value in paths.items()}}
        )
        if owner is None or (
            owner.get("operation_id") != operation_id
            or owner.get("lock_token") != record.get("lock_token")
        ):
            if not (
                allow_replaced_completion_lock
                and record.get("controller_owned_completion") is True
                and not isinstance(record.get("worker_pid"), int)
            ):
                return _orphan_cleanup_result(
                    project_root,
                    operation_id,
                    record,
                    "repository_lock_owner_mismatch",
                    started,
                )
            replaced_completion_lock = True
    if time.monotonic() >= deadline:
        return _orphan_cleanup_result(
            project_root, operation_id, record, "cleanup_timeout", started
        )
    try:
        paths = trusted_paths()
        if paths is None:
            return invalid_boundary()
        result_path = paths["result_path"]
        if result_path.exists():
            paths = trusted_paths()
            if paths is None:
                return invalid_boundary()
            paths["result_path"].unlink()
        paths = trusted_paths()
        if paths is None:
            return invalid_boundary()
        lock = paths["repository_lock_path"]
        if lock.exists() and not replaced_completion_lock:
            owner_path = lock / "owner.json"
            if owner_path.exists():
                paths = trusted_paths()
                if paths is None:
                    return invalid_boundary()
                current_owner = _lock_owner(
                    {**record, **{key: str(value) for key, value in paths.items()}}
                )
                if current_owner is not None and (
                    current_owner.get("operation_id") == operation_id
                    and current_owner.get("lock_token") == record.get("lock_token")
                ):
                    (paths["repository_lock_path"] / "owner.json").unlink()
                elif allow_replaced_completion_lock and record.get("controller_owned_completion") is True:
                    replaced_completion_lock = True
                else:
                    return _orphan_cleanup_result(
                        project_root,
                        operation_id,
                        record,
                        "repository_lock_owner_mismatch",
                        started,
                    )
            paths = trusted_paths()
            if paths is None:
                return invalid_boundary()
            if not replaced_completion_lock and paths["repository_lock_path"].exists():
                paths["repository_lock_path"].rmdir()
        paths = trusted_paths()
        if paths is None:
            return invalid_boundary()
        paths["record_path"].unlink()
        paths = trusted_paths()
        if paths is None:
            return invalid_boundary()
        paths["operation_root"].rmdir()
    except OSError:
        paths = trusted_paths()
        if paths is None:
            return invalid_boundary()
        paths["operation_root"].mkdir(parents=True, exist_ok=True)
        paths = trusted_paths()
        if paths is None:
            return invalid_boundary()
        return _orphan_cleanup_result(
            project_root,
            operation_id,
            {**record, **{key: str(value) for key, value in paths.items()}},
            "registered_operation_remove_failed",
            started,
        )
    return {
        "completed": True,
        "reason": "clean",
        "user_visible": True,
        "duration": time.monotonic() - started,
    }


def reconcile_orphaned_operations(
    root: Path,
    *,
    timeout_seconds: float,
) -> dict:
    project_root = resolve_project_root(str(root))
    operations = _common_graph_dir(project_root) / "state" / "operations"
    if not operations.is_dir():
        return {"reconciled": [], "unresolved": [], "live": []}
    reconciled, unresolved, live = [], [], []
    for child in sorted(operations.iterdir()):
        if not child.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", child.name):
            unresolved.append(child.name)
            continue
        try:
            record = _read_operation(project_root, child.name)
        except EngineeringError:
            unresolved.append(child.name)
            continue
        if record.get("phase") not in {
            "orphaned",
            "registered",
            "worktree_created",
            "staging_ready",
            "validating",
            "published",
        }:
            unresolved.append(child.name)
            continue
        try:
            recovered_record = _recover_worker_tree_state(
                project_root, child.name, record
            )
        except EngineeringError:
            unresolved.append(child.name)
            continue
        if recovered_record is None:
            unresolved.append(child.name)
            continue
        record = recovered_record
        cleanup_pid = record.get("cleanup_pid")
        if cleanup_pid is not None and _process_alive(cleanup_pid):
            live.append(child.name)
            continue
        if cleanup_pid is not None:
            record.pop("cleanup_pid")
            record["cleanup_process_dead"] = True
            _write_operation(record)
        owner = _lock_owner(record)
        if owner is not None and (
            owner.get("operation_id") != child.name
            or owner.get("lock_token") != record.get("lock_token")
        ):
            unresolved.append(child.name)
            continue
        if (
            owner is None
            and record.get("worker_process_tree_dead") is True
            and not isinstance(record.get("worker_pid"), int)
        ):
            # Legacy records with no lock and no worker have no live resource
            # owner left to protect; the durable dead marker is sufficient.
            owner_state = "dead"
        else:
            owner_state = _owner_process_state(owner) if owner is not None else _owner_process_state(
                {"owner_pid": record.get("owner_pid"), "owner_identity": record.get("owner_identity")}
            )
        if owner_state == "live":
            live.append(child.name)
            continue
        if owner_state == "ambiguous":
            unresolved.append(child.name)
            continue
        if not _orphan_is_old_enough(record, owner):
            unresolved.append(child.name)
            continue
        if record.get("phase") != "orphaned":
            record["phase"] = "orphaned"
            _write_operation(record)
        result = cleanup_hook_operation(
            project_root,
            child.name,
            timeout_seconds=timeout_seconds,
        )
        (reconciled if result["completed"] else unresolved).append(child.name)
    return {"reconciled": reconciled, "unresolved": unresolved, "live": live}


def _verify_graphify_adapter_in_process() -> tuple[dict, object]:
    import importlib.metadata as metadata
    import inspect

    try:
        distribution = metadata.distribution("graphifyy")
        direct_url = json.loads(distribution.read_text("direct_url.json") or "{}")
        from graphify.detect import CODE_EXTENSIONS
        from graphify.watch import _rebuild_code
    except (ImportError, metadata.PackageNotFoundError, KeyError, json.JSONDecodeError) as error:
        raise EngineeringError("graphify_adapter_incompatible") from error
    signature = inspect.signature(_rebuild_code)
    parameters = list(signature.parameters)
    repository = direct_url.get("url", "").removesuffix(".git")
    commit = direct_url.get("vcs_info", {}).get("commit_id")
    if (
        distribution.version != GRAPHIFY_VERSION
        or repository != GRAPHIFY_REPOSITORY
        or commit != GRAPHIFY_COMMIT
        or parameters != list(GRAPHIFY_ADAPTER_PARAMETERS)
        or signature.parameters["changed_paths"].kind
        is not inspect.Parameter.KEYWORD_ONLY
    ):
        raise EngineeringError("graphify_adapter_incompatible")
    return {
        "version": distribution.version,
        "commit": commit,
        "parameters": parameters,
        "changed_paths_keyword_only": True,
        "code_extensions": sorted(CODE_EXTENSIONS),
    }, _rebuild_code


def _guard_base_graph(
    current: dict,
    previous: dict,
    *,
    ratio: float,
    deleted_sources: set[str],
) -> None:
    old_nodes = {
        item.get("id"): item
        for item in previous.get("nodes", [])
        if isinstance(item.get("id"), str)
    }
    for item in current.get("nodes", []):
        identifier = item.get("id")
        prior = old_nodes.get(identifier)
        if prior is None:
            continue
        stable_keys = ("source_file", "file_type")
        if any(
            prior.get(key) is not None
            and item.get(key) is not None
            and prior.get(key) != item.get(key)
            for key in stable_keys
        ):
            raise EngineeringError("duplicate_stable_id")
    before = len(previous.get("nodes", []))
    after = len(current.get("nodes", []))
    normalized_deletions = {
        path.replace("\\", "/").removeprefix("./")
        for path in deleted_sources
    }
    deletion_budget = sum(
        1
        for item in previous.get("nodes", [])
        if isinstance(item.get("source_file"), str)
        and item["source_file"].replace("\\", "/").removeprefix("./")
        in normalized_deletions
    )
    if before and after + deletion_budget < before * ratio:
        raise EngineeringError("unexpected_shrink")


def _worker_authority_valid(root: Path, authority: dict | None, commit: str) -> bool:
    if authority is None:
        return True
    remote = authority.get("remote")
    if remote is None:
        try:
            return (
                git(root, "rev-parse", "--verify", f"refs/heads/{authority['branch']}")
                == commit
            )
        except EngineeringError:
            return False
    try:
        _, remote_url_digest = _bound_remote_url(root, remote)
        mappings = git(root, "config", "--get-all", f"remote.{remote}.fetch").splitlines()
        source, destination = _validated_fetch_mapping(
            remote, authority["branch"], mappings
        )
        return (
            remote_url_digest == authority.get("remote_url_digest")
            and source == authority.get("source")
            and destination == authority.get("destination")
            and git(root, "rev-parse", "--verify", destination) == commit
        )
    except EngineeringError:
        return False


def _queue_graph_worker_stale(root: Path, operation_id: str) -> None:
    record = _read_operation(root, operation_id)
    _queue_maintenance_locked(
        root,
        [
            {
                "area": "graph",
                "artifact": "checkpoint",
                "kind": "checkpoint_stale",
                "impact": "routine",
            }
        ],
        record,
    )


def _graph_worker_entry(root: Path, operation_id: str) -> int:
    """Internal one-process worker: diff, snapshot, adapter, validation, publish."""
    project_root = resolve_project_root(str(root))
    record = _read_operation(project_root, operation_id)
    worktree = Path(record["worktree_path"])
    stage = Path(record["staging_path"])
    result_path = Path(record["result_path"])
    commit = record["commit"]
    empty_hooks = Path(record["operation_root"]) / "hooks"
    quarantine = None
    quarantine_rollback = None
    cwd_before = Path.cwd()
    environment_before = dict(os.environ)
    try:
        graphify_environment = _graphify_environment(output=stage)
        os.environ.clear()
        os.environ.update(graphify_environment)
        adapter_details, adapter = _verify_graphify_adapter_in_process()
        ancestor = _compatible_ancestor(
            project_root, commit, adapter_details["version"]
        )
        changed = _changed_files(project_root, ancestor[0], commit) if ancestor else []
        semantic = _semantic_changes(
            changed, adapter_details["code_extensions"], record["manifest_name"]
        )
        if semantic:
            _queue_graph_worker_stale(project_root, operation_id)
            _atomic_text(
                result_path,
                json.dumps(
                    {
                        "mode": "stale",
                        "freshness": "stale",
                        "reason": "semantic_completion_required",
                        "commit": commit,
                        "changed_paths": changed,
                        "previous_checkpoint_preserved": ancestor is not None,
                    }
                )
                + "\n",
            )
            return 0
        if ancestor is None and record.get("hook"):
            _queue_graph_worker_stale(project_root, operation_id)
            _atomic_text(
                result_path,
                json.dumps(
                    {
                        "mode": "stale",
                        "freshness": "stale",
                        "reason": "cold_rebuild_deferred",
                        "commit": commit,
                        "changed_paths": changed,
                        "previous_checkpoint_preserved": False,
                    }
                )
                + "\n",
            )
            return 0
        destination = _checkpoint_destination(
            project_root,
            commit,
            branch=record["branch"],
            kind=record["kind"],
        )
        quarantine = _quarantine_invalid_checkpoint(
            project_root,
            destination,
            commit,
            branch=record["branch"],
            kind=record["kind"],
        )
        run(
            [
                "git",
                "-C",
                str(project_root),
                "-c",
                f"core.hooksPath={empty_hooks}",
                "worktree",
                "add",
                "--detach",
                str(worktree),
                commit,
            ],
            timeout=30,
        )
        record["phase"] = "worktree_created"
        _write_operation(record)
        stage.mkdir()
        if ancestor:
            shutil.copytree(ancestor[1].parent, stage, dirs_exist_ok=True)
        record["phase"] = "staging_ready"
        _write_operation(record)
        try:
            os.chdir(worktree)
            if ancestor:
                if not adapter(
                    worktree,
                    changed_paths=[Path(path) for path in changed],
                ):
                    raise EngineeringError("graphify_adapter_failed")
            else:
                command = (
                    str(Path(sys.executable).resolve()),
                    "-m",
                    "graphify",
                    "update",
                    str(worktree),
                )
                run(list(command), env=_graphify_environment(output=stage), timeout=600)
        finally:
            os.chdir(cwd_before)
        graph_path = stage / "graph.json"
        if ancestor:
            incremented_graph = _read_base_graph(graph_path)
            incremented_graph["built_at_commit"] = commit
            _atomic_text(
                graph_path,
                json.dumps(incremented_graph, indent=2) + "\n",
            )
        graph = _read_base_graph(graph_path)
        if graph.get("built_at_commit") != commit:
            raise EngineeringError("commit_mismatch")
        graph_digest = _graph_digest(graph_path)
        destination, checkpoint = _checkpoint_candidate_at(
            project_root,
            commit,
            branch=record["branch"],
            kind=record["kind"],
            graphify_version=adapter_details["version"],
            manifest_name=record["manifest_name"],
            graph_digest=graph_digest,
        )
        if ancestor:
            previous_checkpoint = json.loads(
                ancestor[1].read_text(encoding="utf-8")
            )
            manifest = _json_at(project_root, commit, record["manifest_name"])
            ratio = float(manifest.get("integrity", {}).get("min_retained_ratio", 0.8))
            _guard_previous(checkpoint, previous_checkpoint, ratio)
            previous_graph = _read_base_graph(ancestor[1].parent / "graph.json")
            deleted_sources = {
                path.replace("\\", "/")
                for path in git(
                    project_root,
                    "diff",
                    "--name-only",
                    "--diff-filter=D",
                    ancestor[0],
                    commit,
                ).splitlines()
                if path
            }
            _guard_base_graph(
                graph,
                previous_graph,
                ratio=ratio,
                deleted_sources=deleted_sources,
            )
        (stage / "checkpoint.json").write_text(
            json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8"
        )
        record["phase"] = "validating"
        _write_operation(record)
        if not validate_checkpoint(
            project_root, stage / "checkpoint.json", commit
        )["valid"]:
            raise EngineeringError("candidate_checkpoint_invalid")
        if not _worker_authority_valid(
            project_root, record.get("authority"), commit
        ):
            raise EngineeringError("canonical_authority_changed")
        if destination.parent.exists():
            existing = validate_checkpoint(project_root, destination, commit)
            if existing["valid"]:
                shutil.rmtree(stage)
            else:
                raise EngineeringError("immutable_checkpoint_incomplete")
        else:
            destination.parent.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, destination.parent)
        record["phase"] = "published"
        _write_operation(record)
        _mutate_maintenance_locked(
            project_root,
            [],
            _read_operation(project_root, operation_id),
            resolved_checkpoint=commit,
        )
        _atomic_text(
            result_path,
            json.dumps(
                {
                    "mode": "changed_path_adapter" if ancestor else "full",
                    "freshness": "current",
                    "commit": commit,
                    "checkpoint": str(destination),
                    "changed_paths": changed,
                    "changed_files": changed,
                    "built_at_commit": graph["built_at_commit"],
                    "snapshot": str(worktree),
                    "child_cwd": str(worktree),
                    "detached_snapshot": True,
                    "staged_graphify_out": True,
                    "previous_checkpoint_preserved": ancestor is not None,
                    "argv": [],
                    **({"quarantine": quarantine} if quarantine is not None else {}),
                },
                indent=2,
            )
            + "\n",
        )
        return 0
    except Exception as error:
        if quarantine is not None:
            try:
                quarantine_rollback = _restore_quarantined_checkpoint(
                    project_root, quarantine
                )
            except Exception as rollback_error:
                error = EngineeringError("checkpoint_quarantine_rollback_failed")
        try:
            _queue_graph_worker_stale(project_root, operation_id)
        except Exception as maintenance_error:
            error = maintenance_error
        _atomic_text(
            result_path,
            json.dumps(
                {
                    "mode": "stale",
                    "freshness": "stale",
                    "reason": (
                        str(error)
                        if str(error)
                        else type(error).__name__
                    ),
                    "commit": commit,
                    "previous_checkpoint_preserved": bool(
                        _compatible_ancestor(
                            project_root, commit, GRAPHIFY_VERSION
                        )
                    ),
                    **({"quarantine": quarantine} if quarantine is not None else {}),
                    **(
                        {"quarantine_rollback": quarantine_rollback}
                        if quarantine_rollback is not None
                        else {}
                    ),
                }
            )
            + "\n",
        )
        return 1
    finally:
        os.chdir(cwd_before)
        os.environ.clear()
        os.environ.update(environment_before)


def _start_worker(command: list[str]) -> subprocess.Popen:
    command = [command[0], "-B", *command[1:]]
    return subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=(os.name != "nt"),
        env=_graphify_environment(),
    )


def _run_graph_operation(
    root: Path,
    *,
    graphify_python: str,
    commit: str,
    branch: str,
    kind: str,
    manifest_name: str,
    hook: bool,
    timeout_seconds: float | None,
    cleanup_timeout_seconds: float,
    authority: dict | None = None,
) -> dict:
    project_root = resolve_project_root(str(root))
    orphan = reconcile_orphaned_operations(
        project_root,
        timeout_seconds=cleanup_timeout_seconds,
    )
    if orphan["unresolved"] or orphan["live"]:
        reason = (
            "live_hook_operation"
            if orphan["live"]
            else "unresolved_hook_worker_orphan"
        )
        for unresolved_id in orphan["unresolved"]:
            try:
                unresolved_record = _read_operation(project_root, unresolved_id)
                owner = _lock_owner(unresolved_record)
            except EngineeringError:
                continue
            if owner is not None and (
                owner.get("operation_id") != unresolved_id
                or owner.get("lock_token") != unresolved_record.get("lock_token")
            ):
                reason = "repository_lock_owner_mismatch"
                break
            if owner is not None and _owner_process_state(owner) == "live":
                reason = "repository_lock_owner_mismatch"
                break
        return {
            "mode": "blocked",
            "freshness": "stale",
            "readiness": "blocked",
            "reason": reason,
            "commit": commit,
            "previous_checkpoint_preserved": True,
        }
    operation = register_hook_operation(project_root)
    record = _read_operation(project_root, operation["operation_id"])
    record.update(
        {
            "root": str(project_root),
            "commit": commit,
            "branch": branch,
            "kind": kind,
            "manifest_name": manifest_name,
            "hook": hook,
            "authority": authority,
        }
    )
    _write_operation(record)
    if not _acquire_repository_lock(record):
        record["phase"] = "orphaned"
        _write_operation(record)
        return {
            "mode": "blocked",
            "freshness": "stale",
            "readiness": "blocked",
            "reason": "repository_lock_owner_mismatch",
            "commit": commit,
            "operation": record,
        }
    command = [
        str(Path(graphify_python).expanduser().resolve()),
        str(Path(__file__).resolve()),
        "_graph-worker",
        str(project_root),
        operation["operation_id"],
    ]
    record.update(
        worker_start_pending=True,
        worker_process_tree_dead=False,
    )
    _write_operation(record)
    try:
        process = _start_worker(command)
    except OSError:
        record.update(
            worker_start_pending=False,
            worker_process_tree_dead=True,
            worker_start_failed=True,
            phase="orphaned",
        )
        _write_operation(record)
        _release_failed_start_lock(record)
        cleanup_hook_operation(
            project_root,
            operation["operation_id"],
            timeout_seconds=cleanup_timeout_seconds,
        )
        raise
    worker_pgid = process.pid if os.name != "nt" else None
    record.update(
        {
            "owner_pid": process.pid,
            "worker_pid": process.pid,
            "worker_start_pending": False,
            "worker_process_tree_dead": False,
            "worker_identity": _process_identity(process.pid),
            "worker_process_tree": _capture_process_tree(process.pid),
        }
    )
    record["worker_process_tree_complete"] = bool(record.get("worker_process_tree"))
    if worker_pgid is not None:
        record["worker_pgid"] = worker_pgid
    else:
        record.pop("worker_pgid", None)
    if record.get("worker_identity") is None or not record.get("worker_process_tree"):
        record["worker_process_tree_identity_ambiguous"] = True
    _write_operation(record)
    _atomic_text(
        Path(record["repository_lock_path"]) / "owner.json",
        json.dumps(
            {
                "operation_id": record["operation_id"],
                "lock_token": record["lock_token"],
                "owner_pid": process.pid,
                "owner_identity": record.get("worker_identity"),
                "created_at": time.time(),
            },
            indent=2,
        )
        + "\n",
    )
    timed_out = False
    worker_process_tree_dead = False
    try:
        process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "nt":
            refreshed_tree = _capture_process_tree(process.pid)
            if isinstance(refreshed_tree, list) and refreshed_tree:
                record["worker_process_tree"] = refreshed_tree
                record["worker_process_tree_complete"] = True
            elif refreshed_tree is None:
                record["worker_process_tree_complete"] = False
            _write_operation(record)
        expected_tree = record.get("worker_process_tree")
        if isinstance(expected_tree, list) and expected_tree:
            worker_process_tree_dead = _terminate_process_tree(
                process, worker_pgid, expected_tree=expected_tree
            )
        else:
            worker_process_tree_dead = _terminate_process_tree(process, worker_pgid)
    else:
        worker_process_tree_dead = (
            process.poll() is not None
            if worker_pgid is None
            else not _process_group_alive(process, worker_pgid)
        )
    result_path = Path(record["result_path"])
    if timed_out:
        result = {
            "mode": "stale",
            "freshness": "stale",
            "reason": "hook_budget_exceeded",
            "commit": commit,
            "previous_checkpoint_preserved": bool(
                _compatible_ancestor(project_root, commit, GRAPHIFY_VERSION)
            ),
            "worker_process_tree_terminated": worker_process_tree_dead,
        }
    elif result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = {
            "mode": "stale",
            "freshness": "stale",
            "reason": "graph_worker_failed",
            "commit": commit,
            "previous_checkpoint_preserved": True,
        }
    latest_record = _read_operation(project_root, operation["operation_id"])
    latest_record["worker_process_tree_dead"] = worker_process_tree_dead
    latest_record["worker_process_tree_authoritative"] = bool(
        os.name != "nt"
        or getattr(process, "_engineering_tree_proven", False)
    )
    latest_record["worker_process_tree_evidence"] = (
        {"state": "dead", "evidence": "termination_confirmed"}
        if worker_process_tree_dead
        else _process_tree_status(latest_record)
    )
    latest_record["phase"] = "orphaned"
    _write_operation(latest_record)
    record = latest_record
    cleanup = cleanup_hook_operation(
        project_root,
        operation["operation_id"],
        timeout_seconds=cleanup_timeout_seconds,
    )
    if not cleanup["completed"]:
        result.update(
            {
                "readiness": "blocked",
                "reason": (
                    cleanup["reason"]
                    if cleanup["reason"] == "repository_lock_owner_mismatch"
                    else "unresolved_hook_worker_orphan"
                ),
            }
        )
    result["operation"] = record
    result["cleanup"] = cleanup
    result["orphan_reconciled_before_worker"] = bool(orphan["reconciled"])
    if result.get("freshness") == "current":
        _clear_stale(project_root, commit)
    else:
        _record_stale(project_root, commit, result["reason"])
    return result


def rebuild(
    root: Path,
    graphify_or_commit: Path | str,
    graphify_python: str | None = None,
    manifest_name: str | None = None,
    *,
    target_commit: str | None = None,
    hook_budget_seconds: float | None = None,
    cleanup_timeout_seconds: float = 5.0,
) -> dict | Path:
    """Build an exact target; retain the installed-v1 positional interface."""
    if graphify_python is not None:
        return _legacy_rebuild(
            root,
            str(graphify_or_commit),
            graphify_python,
            manifest_name=manifest_name,
        )
    project_root = resolve_project_root(str(root))
    selected = manifest_name or _tracked_manifest_name(project_root)
    if selected is None:
        raise EngineeringError("manifest_not_tracked")
    commit = git(project_root, "rev-parse", target_commit or "HEAD")
    _validate_project_controls(project_root, commit, selected)
    branch = git(project_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    manifest = _json_at(project_root, commit, selected)
    configured_default = manifest["project"]["default_branch"]
    kind = "feature"
    authority = None
    if not git(project_root, "remote").strip() and branch == configured_default and commit == git(
        project_root, "rev-parse", f"refs/heads/{configured_default}"
    ):
        kind = "canonical"
        authority = {
            "branch": configured_default,
            "remote": None,
        }
    destination = _select_exact_checkpoint(
        project_root, commit, branch=branch, kind=kind
    )
    if destination is not None:
        return {
            "mode": "exact_cache",
            "freshness": "current",
            "commit": commit,
            "checkpoint": str(destination),
            "previous_checkpoint_preserved": True,
            "changed_paths": [],
            "changed_files": [],
            "argv": [],
        }
    if hook_budget_seconds is not None and hook_budget_seconds <= 0:
        result = _stale_result(
            project_root,
            commit,
            "hook_budget_exceeded",
            _compatible_ancestor(project_root, commit, GRAPHIFY_VERSION),
        )
        result["changed_paths"] = []
        return result
    return _run_graph_operation(
        project_root,
        graphify_python=str(graphify_or_commit),
        commit=commit,
        branch=branch,
        kind=kind,
        manifest_name=selected,
        hook=hook_budget_seconds is not None,
        timeout_seconds=hook_budget_seconds,
        cleanup_timeout_seconds=cleanup_timeout_seconds,
        authority=authority,
    )


def recover_checkpoint(
    root: Path, requested_commit: str, graphify_python: str = sys.executable
) -> dict:
    """Regenerate one exact checkpoint after losslessly quarantining an invalid address."""
    project_root = resolve_project_root(str(root))
    commit = git(project_root, "rev-parse", requested_commit)
    manifest_name = _tracked_manifest_name_at(project_root, commit)
    if manifest_name is None:
        raise EngineeringError("manifest_not_tracked")
    manifest = _json_at(project_root, commit, manifest_name)
    default_branch = manifest.get("project", {}).get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise EngineeringError("invalid_manifest: project.default_branch")
    current_branch = git(project_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    canonical_destination = _checkpoint_destination(
        project_root, commit, branch=default_branch, kind="canonical"
    )
    feature_destination = _checkpoint_destination(
        project_root, commit, branch=current_branch, kind="feature"
    )
    canonical_ref = None
    for ref in (f"refs/remotes/origin/{default_branch}", f"refs/heads/{default_branch}"):
        try:
            canonical_ref = git(project_root, "rev-parse", "--verify", ref)
        except EngineeringError:
            continue
        break
    quarantined_targets = [
        record
        for record in _checkpoint_quarantine_records(project_root)
        if record.get("commit") == commit
    ]
    if len(quarantined_targets) > 1:
        raise EngineeringError("checkpoint_recovery_target_ambiguous")
    quarantined_target = quarantined_targets[0] if quarantined_targets else None
    if quarantined_target is not None and (
        quarantined_target.get("kind") == "feature"
        and quarantined_target.get("branch") != current_branch
    ):
        raise EngineeringError("checkpoint_recovery_target_mismatch")
    canonical_present = canonical_destination.parent.exists()
    feature_present = feature_destination.parent.exists()
    if canonical_present and feature_present and canonical_destination.parent != feature_destination.parent:
        raise EngineeringError("checkpoint_recovery_target_ambiguous")
    canonical_target = (
        (quarantined_target is not None and quarantined_target.get("kind") == "canonical")
        or canonical_present
        or (
        not feature_present and canonical_ref == commit
        )
    )
    if canonical_target:
        result = reconcile_canonical(
            project_root,
            refresh_remote=False,
            allow_cached_remote=True,
            graphify_python=graphify_python,
        )
        if result.get("commit") not in {None, commit}:
            raise EngineeringError("checkpoint_recovery_target_mismatch")
    else:
        result = rebuild(project_root, graphify_python, target_commit=commit)
    if result.get("freshness") == "not_configured" and result.get("checkpoint"):
        result = {**result, "freshness": "current"}
    if isinstance(result, Path):
        return {
            "schema": "engineering.checkpoint-recovery.v1",
            "freshness": "current",
            "commit": commit,
            "checkpoint": str(result),
        }
    return {"schema": "engineering.checkpoint-recovery.v1", **result}


def _validated_fetch_mapping(
    remote: str, branch: str, mappings: list[str]
) -> tuple[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", remote) or not re.fullmatch(
        r"[A-Za-z0-9._/-]+", branch
    ):
        raise EngineeringError("remote authority is invalid")
    expected_destination = f"refs/remotes/{remote}/{branch}"
    matches: list[tuple[str, str]] = []
    for raw in mappings:
        mapping = raw.removeprefix("+")
        if ":" not in mapping:
            continue
        source, destination = mapping.split(":", 1)
        if "*" in source or "*" in destination:
            if source.count("*") == destination.count("*") == 1:
                prefix, suffix = source.split("*")
                candidate = f"refs/heads/{branch}"
                if candidate.startswith(prefix) and candidate.endswith(suffix):
                    middle = candidate[len(prefix) : len(candidate) - len(suffix) or None]
                    mapped = destination.replace("*", middle)
                    if mapped == expected_destination:
                        matches.append((candidate, mapped))
            continue
        if source == f"refs/heads/{branch}" and destination == expected_destination:
            matches.append((source, destination))
    if len(matches) != 1:
        raise EngineeringError("remote fetch mapping is missing, narrow, or ambiguous")
    return matches[0]


def _bound_remote_url(root: Path, remote: str) -> tuple[str, str]:
    urls = git(root, "remote", "get-url", "--all", remote).splitlines()
    if len(urls) != 1 or not urls[0] or any(character in urls[0] for character in "\r\n\0"):
        raise EngineeringError("remote authority URL is missing or ambiguous")
    url = urls[0]
    if "://" in url and "@" in url.split("://", 1)[1].split("/", 1)[0]:
        raise EngineeringError("remote authority URL contains embedded credentials")
    return url, "sha256:" + hashlib.sha256(url.encode("utf-8")).hexdigest()


def _canonical_authority_details(
    root: Path, *, refresh_remote: bool, allow_cached_remote: bool = False
) -> dict:
    project_root = resolve_project_root(str(root))
    manifest_name = _tracked_manifest_name(project_root)
    if manifest_name is None:
        raise EngineeringError("manifest_not_tracked")
    manifest = _json_at(project_root, "HEAD", manifest_name)
    branch = manifest.get("project", {}).get("default_branch")
    if not isinstance(branch, str) or not branch:
        raise EngineeringError("invalid_manifest: project.default_branch")
    remotes = [item for item in git(project_root, "remote").splitlines() if item]
    if len(remotes) > 1:
        raise EngineeringError("remote authority is ambiguous")
    if not remotes:
        commit = git(project_root, "rev-parse", "--verify", f"refs/heads/{branch}")
        return {
            "branch": branch,
            "commit": commit,
            "remote": None,
            "remote_url_digest": None,
            "freshness": "not_configured",
            "source": f"refs/heads/{branch}",
            "destination": f"refs/heads/{branch}",
            "fetch_argv": [],
            "refresh_source": "local_branch",
        }
    remote = remotes[0]
    try:
        remote_url, remote_url_digest = _bound_remote_url(project_root, remote)
        mappings = git(
            project_root, "config", "--get-all", f"remote.{remote}.fetch"
        ).splitlines()
        source, destination = _validated_fetch_mapping(remote, branch, mappings)
    except EngineeringError:
        return {
            "branch": branch,
            "commit": None,
            "remote": remote,
            "remote_url_digest": None,
            "freshness": "unknown",
            "source": None,
            "destination": None,
            "fetch_argv": [],
            "refresh_source": None,
        }
    if not refresh_remote:
        if allow_cached_remote:
            try:
                commit = git(project_root, "rev-parse", "--verify", destination)
            except EngineeringError:
                pass
            else:
                return {
                    "branch": branch,
                    "commit": commit,
                    "remote": remote,
                    "remote_url_digest": remote_url_digest,
                    "freshness": "cached",
                    "source": source,
                    "destination": destination,
                    "fetch_argv": [],
                    "refresh_source": "cached_destination",
                }
        return {
            "branch": branch,
            "commit": None,
            "remote": remote,
            "remote_url_digest": remote_url_digest,
            "freshness": "unknown",
            "source": source,
            "destination": destination,
            "fetch_argv": [],
            "refresh_source": None,
        }
    refspec = f"{source}:{destination}"
    argv = [
        "git",
        "-C",
        str(project_root),
        "fetch",
        "--no-tags",
        remote_url,
        refspec,
    ]
    try:
        run(argv, timeout=15)
        if _bound_remote_url(project_root, remote)[1] != remote_url_digest:
            raise EngineeringError("remote authority changed during fetch")
        commit = git(project_root, "rev-parse", "--verify", destination)
    except (EngineeringError, subprocess.SubprocessError):
        return {
            "branch": branch,
            "commit": None,
            "remote": remote,
            "remote_url_digest": remote_url_digest,
            "freshness": "unknown",
            "source": source,
            "destination": destination,
            "fetch_argv": argv,
            "refresh_source": "explicit_destination",
        }
    return {
        "branch": branch,
        "commit": commit,
        "remote": remote,
        "remote_url_digest": remote_url_digest,
        "freshness": "current",
        "source": source,
        "destination": destination,
        "fetch_argv": argv,
        "refresh_source": "explicit_destination",
    }


def reconcile_canonical(
    root: Path,
    *,
    refresh_remote: bool,
    allow_cached_remote: bool = False,
    graphify_python: str = sys.executable,
    hook_budget_seconds: float | None = None,
) -> dict:
    project_root = resolve_project_root(str(root))
    authority = _canonical_authority_details(
        project_root,
        refresh_remote=refresh_remote,
        allow_cached_remote=allow_cached_remote,
    )
    if authority["freshness"] == "unknown" or authority["commit"] is None:
        return {
            **authority,
            "canonical_published": False,
            "authority_revalidated_before_publication": False,
            "fetched_source": authority.get("source"),
            "fetched_destination": authority.get("destination"),
            "fetched_commit": authority.get("commit"),
        }
    manifest_name = _tracked_manifest_name_at(project_root, authority["commit"])
    if manifest_name is None:
        raise EngineeringError("manifest_not_tracked")
    exact = _select_exact_checkpoint(
        project_root,
        authority["commit"],
        branch=authority["branch"],
        kind="canonical",
    )
    if exact is not None:
        authority_valid = _worker_authority_valid(
            project_root, authority, authority["commit"]
        )
        if not authority_valid:
            return {
                **authority,
                "mode": "stale",
                "readiness": "blocked",
                "reason": "canonical_authority_changed",
                "canonical_published": False,
                "authority_revalidated_before_publication": False,
                "fetched_source": authority.get("source"),
                "fetched_destination": authority.get("destination"),
                "fetched_commit": authority.get("commit"),
            }
        return {
            **authority,
            "mode": "exact_cache",
            "freshness": authority["freshness"],
            "checkpoint": str(exact),
            "commit": authority["commit"],
            "changed_paths": [],
            "changed_files": [],
            "previous_checkpoint_preserved": True,
            "argv": [],
            "canonical_published": True,
            "authority_revalidated_before_publication": True,
            "fetched_source": authority.get("source"),
            "fetched_destination": authority.get("destination"),
            "fetched_commit": authority.get("commit"),
        }
    result = _run_graph_operation(
        project_root,
        graphify_python=graphify_python,
        commit=authority["commit"],
        branch=authority["branch"],
        kind="canonical",
        manifest_name=manifest_name,
        hook=hook_budget_seconds is not None,
        timeout_seconds=hook_budget_seconds,
        cleanup_timeout_seconds=5.0,
        authority=authority,
    )
    result.update(
        {
            "remote": authority["remote"],
            "freshness": (
                "not_configured"
                if authority["freshness"] == "not_configured"
                and result.get("freshness") == "current"
                else result.get("freshness")
            ),
            "fetch_argv": authority["fetch_argv"],
            "refresh_source": authority["refresh_source"],
            "fetched_source": authority["source"],
            "fetched_destination": authority["destination"],
            "fetched_commit": authority["commit"],
            "canonical_published": result.get("freshness")
            in {"current", "cached", "not_configured"},
            "authority_revalidated_before_publication": (
                result.get("freshness") in {"current", "cached", "not_configured"}
            ),
        }
    )
    return result


def bootstrap_graph(
    root: Path,
    *,
    setup_authorized: bool,
    graphify_python: str = sys.executable,
    recovery_timeout_seconds: float | None = None,
) -> dict:
    """Assess or build the single canonical default-branch graph checkpoint.

    This controller owns only the local exact-ref checkpoint.  It never treats a
    feature checkpoint as canonical and never invents a substitute graph engine.
    """
    project_root = resolve_project_root(str(root))
    if _tracked_manifest_name(project_root) is None:
        return {
            "state": "advisory",
            "reason": "unmanaged_project",
            "next_action": "adopt_engineering",
            "graph_derived_claims": "unknown",
        }
    catalogue = graph_checkpoint_catalogue(project_root)
    try:
        cached = reconcile_canonical(
            project_root,
            refresh_remote=False,
            allow_cached_remote=True,
            graphify_python=graphify_python,
            hook_budget_seconds=0.0,
        )
    except EngineeringError as error:
        return {
            "state": "unknown",
            "reason": str(error),
            "graph_derived_claims": "unknown",
        }
    if cached.get("canonical_published") and cached.get("checkpoint"):
        return {
            "state": "current",
            "checkpoint": cached["checkpoint"],
            "commit": cached.get("commit"),
            "freshness": cached.get("freshness"),
            "graph_derived_claims": "available",
            "catalogue": catalogue,
        }
    if not setup_authorized:
        return {
            "state": "pending_setup_authority",
            "reason": cached.get("reason", "canonical_checkpoint_missing"),
            "next_action": "authorize_engineering_setup",
            "graph_derived_claims": "unknown",
            "catalogue": catalogue,
        }
    try:
        verify_graphify(graphify_python)
    except EngineeringError:
        return {
            "state": "blocked",
            "reason": "graphify_unavailable_or_incompatible",
            "next_action": "authorize_supported_graphify_setup",
            "graph_derived_claims": "unknown",
            "catalogue": catalogue,
        }
    result = reconcile_canonical(
        project_root,
        refresh_remote=False,
        allow_cached_remote=True,
        graphify_python=graphify_python,
        hook_budget_seconds=recovery_timeout_seconds,
    )
    if result.get("canonical_published") and result.get("checkpoint"):
        return {
            "state": "current",
            "preflight": {
                "action": "reconcile_canonical_graph_and_overlay",
                "scope": "one exact local default-branch checkpoint",
                "changes": "local checkpoint catalogue only; no source, branch, or remote mutation",
            },
            "checkpoint": result["checkpoint"],
            "commit": result.get("commit"),
            "freshness": result.get("freshness"),
            "graph_derived_claims": "available",
            "catalogue": graph_checkpoint_catalogue(project_root),
        }
    return {
        "state": "unknown",
        "reason": result.get("reason", "canonical_checkpoint_pending"),
        "graph_derived_claims": "unknown",
        "catalogue": graph_checkpoint_catalogue(project_root),
    }


def graph_checkpoint_catalogue(root: Path) -> dict:
    """Classify local checkpoints without promoting or deleting any of them."""
    project_root = resolve_project_root(str(root))
    manifest_name = _tracked_manifest_name(project_root)
    if manifest_name is None:
        return {"canonical": None, "features": [], "state": "unmanaged"}
    manifest = _json_at(project_root, "HEAD", manifest_name)
    default = manifest["project"]["default_branch"]
    try:
        canonical_commit = git(project_root, "rev-parse", f"refs/remotes/origin/{default}")
    except EngineeringError:
        canonical_commit = git(project_root, "rev-parse", f"refs/heads/{default}")
    graph_dir = _common_graph_dir(project_root)
    current: dict | None = None
    features_by_commit: dict[str, dict] = {}
    quarantined = _checkpoint_quarantine_records(project_root)
    for checkpoint in sorted(graph_dir.glob("main/*/checkpoint.json")):
        commit = checkpoint.parent.name
        validation = validate_checkpoint(project_root, checkpoint, commit)
        item = {"commit": commit, "state": "current" if validation["valid"] and commit == canonical_commit else "historical"}
        if not validation["valid"]:
            item["state"] = "quarantined"
            item["reason"] = validation["reason"]
            item["relative_path"] = checkpoint.relative_to(graph_dir).as_posix()
            quarantined.append(item)
        if item["state"] == "current":
            current = item
    for checkpoint in sorted(graph_dir.glob("features/*/*/checkpoint.json")):
        commit, branch_token = checkpoint.parent.name, checkpoint.parent.parent.name
        branch = unquote(branch_token)
        validation = validate_checkpoint(project_root, checkpoint, commit)
        item = {"commit": commit, "branch": branch, "state": "archived"}
        if not validation["valid"]:
            item.update(state="quarantined", reason=validation["reason"])
            item["relative_path"] = checkpoint.relative_to(graph_dir).as_posix()
            quarantined.append(item)
        elif _is_ancestor_or_equal(project_root, commit, canonical_commit):
            item["state"] = "historical"
        else:
            try:
                branch_head = git(project_root, "rev-parse", f"refs/heads/{branch}")
            except EngineeringError:
                item["state"] = "archived"
            else:
                item["state"] = "active" if _is_ancestor_or_equal(project_root, commit, branch_head) else "archived"
        previous = features_by_commit.get(commit)
        priority = {"active": 3, "historical": 2, "archived": 1, "quarantined": 0}
        if previous is None or priority[item["state"]] > priority[previous["state"]]:
            features_by_commit[commit] = item
    return {
        "canonical": current,
        "features": [features_by_commit[key] for key in sorted(features_by_commit)],
        "quarantined": quarantined,
        "state": "managed",
    }


def status(root: Path, *, target_commit: str | None = None) -> dict:
    project_root = resolve_project_root(str(root))
    commit = git(project_root, "rev-parse", target_commit or "HEAD")
    if commit in _read_stale(project_root):
        return {"commit": commit, "freshness": "stale"}
    try:
        checkpoint = _checkpoint_path(project_root, commit)
    except EngineeringError:
        return {"commit": commit, "freshness": "stale"}
    validation = validate_checkpoint(project_root, checkpoint, commit)
    return {
        "commit": commit,
        "freshness": "current" if validation["valid"] else "stale",
        "reason": validation["reason"],
        "checkpoint": str(checkpoint),
    }


def check_merge_readiness(root: Path) -> dict:
    project_root = resolve_project_root(str(root))
    commit = git(project_root, "rev-parse", "HEAD")
    stale = _read_stale(project_root)
    if commit in stale:
        return {"ready": False, "reason": "stale", "commit": commit}
    try:
        path = _checkpoint_path(project_root, commit)
    except EngineeringError:
        return {"ready": False, "reason": "inexact", "commit": commit}
    validation = validate_checkpoint(project_root, path, commit)
    if not validation["valid"]:
        return {
            "ready": False,
            "reason": validation["reason"],
            "commit": commit,
        }
    selected = _tracked_manifest_name(project_root)
    if selected is None:
        return {"ready": False, "reason": "inexact", "commit": commit}
    config_path, links_path, _, _ = _project_paths_for_manifest(selected)
    try:
        manifest = _json_at(project_root, commit, config_path)
        links = _json_at(project_root, commit, links_path)
        _, _, integrity = _validate_overlay(
            project_root, commit, manifest, links, manifest_name=config_path
        )
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (EngineeringError, OSError, json.JSONDecodeError):
        return {"ready": False, "reason": "inexact", "commit": commit}
    if checkpoint["metadata"].get("input_digest") != integrity["input_digest"]:
        return {"ready": False, "reason": "inexact", "commit": commit}
    return {
        "ready": True,
        "reason": "exact_current",
        "commit": commit,
        "checkpoint": str(path),
    }


def run_full_graph_maintenance(
    root: Path, graphify_python: Path | str, recorder: object | None = None
) -> dict:
    """Explicit public full-corpus maintenance; never called by incremental hooks."""
    project_root = resolve_project_root(str(root))
    verify_graphify(graphify_python)
    argv = ["graphify", "update", str(project_root)]
    if recorder is not None and hasattr(recorder, "argv"):
        recorder.argv.append(argv)
    output = _common_graph_dir(project_root) / "maintenance"
    run(
        [
            str(Path(graphify_python).expanduser().resolve()),
            "-m",
            "graphify",
            "update",
            str(project_root),
        ],
        env=_graphify_environment(output=output),
        timeout=600,
    )
    return {"mode": "full_maintenance", "argv": argv, "output": str(output)}


def _exact_edges(checkpoint: dict) -> list[dict]:
    return [edge for edge in checkpoint["edges"] if edge["provenance"] in EXACT_PROVENANCE]


def _reachable(checkpoint: dict, start: str, *, reverse: bool = False, exact: bool = True) -> list[str]:
    edges = _exact_edges(checkpoint) if exact else [
        edge for edge in checkpoint["edges"] if edge["provenance"] != "missing"
    ]
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        source, target = (edge["to"], edge["from"]) if reverse else (edge["from"], edge["to"])
        adjacency.setdefault(source, []).append(target)
    seen, queue = {start}, deque([start])
    result = []
    while queue:
        current = queue.popleft()
        for target in sorted(adjacency.get(current, [])):
            if target not in seen:
                seen.add(target)
                result.append(target)
                queue.append(target)
    return result


def _traceability_relationships(checkpoint: dict, focus: str | None = None) -> tuple[list[dict], list[str]]:
    """Return a bounded, privacy-safe relationship projection and focused paths.

    The graph checkpoint is already commit-bound and validated by the normal
    checkpoint loader.  The machine view exposes only stable node/edge
    identifiers and provenance; source locations and filesystem paths remain
    outside this projection.
    """
    edges = checkpoint.get("edges", [])
    if not isinstance(edges, list):
        raise EngineeringError("Engineering traceability checkpoint edges are invalid.")
    node_ids = {
        node.get("id")
        for node in checkpoint.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    paths: list[str] = []
    focused_ids: set[str] | None = None
    if focus is not None:
        if focus not in node_ids:
            raise EngineeringError("Engineering traceability focus is unknown.")
        upstream = _reachable(checkpoint, focus, reverse=True, exact=False)
        downstream = _reachable(checkpoint, focus, exact=False)
        paths = [focus, *upstream, *downstream]
        focused_ids = set(paths)
    relationships: list[dict] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source, target = edge.get("from"), edge.get("to")
        if not isinstance(source, str) or not isinstance(edge.get("type"), str):
            continue
        if focused_ids is not None and source not in focused_ids and target not in focused_ids:
            continue
        relationships.append({
            "from": source,
            "type": edge["type"],
            "to": target if isinstance(target, str) else None,
            "provenance": edge.get("provenance", "unknown"),
        })
    relationships.sort(key=lambda item: (
        item["from"], item["type"], item["to"] or "", item["provenance"]
    ))
    return relationships, paths


def coverage(checkpoint: dict, *, source_paths: set[str] | None = None) -> list[dict]:
    nodes = {node["id"]: node for node in checkpoint["nodes"]}
    design_types = {"decision", "specification", "plan_task", "contract"}
    verification_types = {"test", "evaluation", "verification_receipt"}
    result = []
    for requirement in sorted(
        (
            node
            for node in checkpoint["nodes"]
            if node["type"] == "requirement"
            and (
                source_paths is None
                or node.get("source", {}).get("path", "").replace("\\", "/")
                in source_paths
            )
        ),
        key=lambda node: node["id"],
    ):
        reachable = [nodes[item] for item in _engineering_path(checkpoint, requirement["id"])]
        missing = []
        if not any(node["type"] in design_types for node in reachable):
            missing.append("design")
        if not any(node["type"] == "code_symbol" for node in reachable):
            missing.append("implementation")
        if not any(node["type"] in verification_types for node in reachable):
            missing.append("verification")
        result.append(
            {"requirement": requirement["id"], "covered": not missing, "missing": missing}
        )
    return result


def _retrospective_inventory(
    manifest: dict, checkpoint: dict, universe: set[str]
) -> list[dict]:
    """Classify only declared, source-resolvable evidence; never infer intent."""
    tracked_types = {
        "requirement",
        "decision",
        "specification",
        "route",
        "schema",
        "contract",
        "code_symbol",
        "test",
        "evaluation",
        "verification_receipt",
    }
    edges_by_node: dict[str, list[dict]] = {}
    for edge in checkpoint["edges"]:
        edges_by_node.setdefault(edge["from"], []).append(edge)
        if isinstance(edge.get("to"), str):
            edges_by_node.setdefault(edge["to"], []).append(edge)
    baseline_unknown = manifest.get("baseline", {}).get("accepted") is False
    result = []
    for node in sorted(checkpoint["nodes"], key=lambda item: item["id"]):
        source = node.get("source", {})
        path = source.get("path", "").replace("\\", "/")
        if node.get("type") not in tracked_types or path not in universe:
            continue
        edges = edges_by_node.get(node["id"], [])
        explicit = node.get("retrospective_state")
        if explicit in {"contradictory", "deferred", "excluded", "stale", "unknown"}:
            classification = explicit
        elif any(edge.get("provenance") == "missing" for edge in edges):
            classification = "missing"
        elif not edges:
            classification = "orphaned"
        elif baseline_unknown or any(edge.get("provenance") == "inferred" for edge in edges):
            classification = "unknown"
        else:
            classification = "current"
        result.append(
            {
                "id": node["id"],
                "type": node["type"],
                "source": path,
                "classification": classification,
            }
        )
    return result


def _retrospective_universe(
    manifest: dict, selected: str, nodes: list[dict]
) -> list[str]:
    inputs = manifest.get("inputs", [])
    if not isinstance(inputs, list) or any(not isinstance(path, str) for path in inputs):
        raise EngineeringError("Engineering retrospective inputs are invalid.")
    universe = {selected, decision_ledger_path(Path("."), manifest)}
    universe.update(path.replace("\\", "/") for path in inputs)
    universe.update(
        matrix["source"].replace("\\", "/")
        for matrix in manifest.get("semantic_matrices", [])
        if isinstance(matrix, dict) and isinstance(matrix.get("source"), str)
    )
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            raise EngineeringError("Engineering retrospective overlay is invalid.")
        path, _ = _source(node, node["id"])
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise EngineeringError("Engineering retrospective source is invalid.")
        universe.add(path)
    return sorted(universe)


def retrospective_preview(
    root: Path, *, scope: list[str] | None = None, llm_reconcile: bool = False
) -> dict:
    """Describe the exact read-only audit before any checkpoint inventory runs."""
    project_root = resolve_project_root(str(root))
    commit = git(project_root, "rev-parse", "HEAD")
    selected = _tracked_manifest_name(project_root)
    if selected is None:
        return {
            "schema": "engineering.retrospective-preview.v1",
            "state": "advisory",
            "read_only": True,
            "finite_universe": [],
            "reason": "manifest_not_tracked",
        }
    manifest = _json_at(project_root, commit, selected)
    links_path = _project_paths_for_manifest(selected)[1]
    links = _json_at(project_root, commit, links_path)
    nodes = links.get("nodes", [])
    if not isinstance(nodes, list):
        raise EngineeringError("Engineering retrospective overlay is invalid.")
    requested = [] if scope is None else list(dict.fromkeys(scope))
    if any(
        not isinstance(path, str)
        or not path
        or Path(path).is_absolute()
        or ".." in Path(path).parts
        for path in requested
    ):
        raise EngineeringError("Engineering retrospective scope must stay inside the project.")
    declared = _retrospective_universe(manifest, selected, nodes)
    unknown = sorted(set(requested) - set(declared))
    if unknown:
        raise EngineeringError("Engineering retrospective scope is not declared by the project.")
    universe = sorted(requested) if requested else declared
    by_id = {node["id"]: node for node in nodes}
    matrices = [
        {
            "source": matrix["source"].replace("\\", "/"),
            "axes": ["owner_or_state", "implementation", "positive", "negative"],
            "items": len(matrix.get("items", [])) if isinstance(matrix.get("items", []), list) else 0,
        }
        for matrix in manifest.get("semantic_matrices", [])
        if isinstance(matrix, dict)
        and isinstance(matrix.get("source"), str)
        and (not requested or _semantic_matrix_impacted(matrix, by_id, set(universe)))
    ]
    preview = {
        "schema": "engineering.retrospective-preview.v1",
        "state": "preview",
        "read_only": True,
        "commit": commit,
        "finite_universe": universe,
        "semantic_matrices": matrices,
        "deterministic_work": [
            "validate_current_checkpoint",
            "classify_declared_evidence",
            "compare_requirement_and_decision_coverage",
            "propose_remediation_only",
        ],
        "llm": {
            "requested": bool(llm_reconcile),
            "controller_calls": 0,
            "host_cost": "bounded_by_selected_sources_and_host_model" if llm_reconcile else "none",
        },
        "permissions": {"project_reads": True, "project_writes": False, "external_access": False},
        "outputs": ["evidence_classifications", "coverage_findings", "remediation_plan"],
    }
    preview["preview_digest"] = "sha256:" + hashlib.sha256(_canonical_json(preview)).hexdigest()
    return preview


def retrospective(
    root: Path,
    *,
    scope: list[str] | None = None,
    llm_reconcile: bool = False,
    preview_digest: str | None = None,
) -> dict:
    """Read only the declared engineering evidence universe; never invokes an LLM."""
    preview = retrospective_preview(root, scope=scope, llm_reconcile=llm_reconcile)
    if preview.get("preview_digest") != preview_digest:
        raise EngineeringError("Engineering retrospective preview is required.")
    project_root = resolve_project_root(str(root))
    commit = git(project_root, "rev-parse", "HEAD")
    selected = _tracked_manifest_name(project_root)
    if selected is None:
        return {
            "schema": "engineering.retrospective.v1",
            "state": "advisory",
            "read_only": True,
            "finite_universe": [],
            "findings": [{"classification": "unknown", "reason": "manifest_not_tracked"}],
            "remediation": [{"action": "adopt_engineering", "requires_authority": True}],
            "llm_reconciliation": {"status": "not_available_in_controller"},
        }
    manifest = _json_at(project_root, commit, selected)
    requested = [] if scope is None else list(dict.fromkeys(scope))
    if any(
        not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts
        for path in requested
    ):
        raise EngineeringError("Engineering retrospective scope must stay inside the project.")
    universe = list(preview["finite_universe"])
    readiness = check_merge_readiness(project_root)
    if not readiness["ready"]:
        return {
            "schema": "engineering.retrospective.v1",
            "state": "advisory",
            "read_only": True,
            "commit": commit,
            "finite_universe": universe,
            "findings": [{"classification": "unknown", "reason": readiness["reason"]}],
            "remediation": [{"action": "recover_canonical_checkpoint", "requires_authority": True}],
            "llm_reconciliation": {"status": "not_available_in_controller"},
        }
    checkpoint = _load_checkpoint(project_root, commit)
    nodes = {node["id"]: node for node in checkpoint["nodes"]}
    inventory = _retrospective_inventory(manifest, checkpoint, set(universe))
    findings = [
        {"classification": "uncovered", "requirement": item["requirement"], "missing": item["missing"]}
        for item in coverage(checkpoint, source_paths=set(universe) if requested else None)
        if not item["covered"]
    ]
    matrix_scope = set(requested) if requested else {
        matrix["source"].replace("\\", "/")
        for matrix in manifest.get("semantic_matrices", [])
        if isinstance(matrix, dict) and isinstance(matrix.get("source"), str)
    }
    findings.extend(
        {"classification": "uncovered_semantic_matrix_cell", "id": identifier}
        for identifier in _semantic_matrix_issues(manifest, checkpoint["nodes"], matrix_scope)
    )
    ledger = _ledger_decisions(project_root, commit, manifest)
    overlay = {identifier for identifier, node in nodes.items() if node.get("type") == "decision"}
    if decision_ledger_path(project_root, manifest) in universe:
        findings.extend(
            {"classification": "missing_from_overlay", "decision": identifier}
            for identifier in sorted(set(ledger) - overlay)
        )
        findings.extend(
            {"classification": "orphaned_overlay_decision", "decision": identifier}
            for identifier in sorted(overlay - set(ledger))
        )
    findings.extend(
        {key: value for key, value in item.items() if key != "source"}
        for item in inventory
        if item["classification"] != "current"
        and not (
            item["type"] == "requirement"
            and any(
                finding.get("requirement") == item["id"]
                for finding in findings
            )
        )
    )
    for finding in findings:
        identity = {
            key: finding[key]
            for key in ("classification", "requirement", "id", "decision", "reason")
            if key in finding
        }
        finding["finding_id"] = "finding-" + hashlib.sha256(_canonical_json(identity)).hexdigest()[:16]
    return {
        "schema": "engineering.retrospective.v1",
        "state": "review_required" if findings else "advisory",
        "read_only": True,
        "commit": commit,
        "finite_universe": universe,
        "inventory": inventory,
        "findings": findings,
        "remediation": [
            {
                "action": "reconcile_declared_evidence",
                "finding_id": finding["finding_id"],
                "classification": finding["classification"],
                "evidence_refs": [
                    str(finding[key])
                    for key in ("requirement", "id", "decision", "reason")
                    if key in finding
                ],
                "requires_authority": True,
            }
            for finding in findings
        ],
        "llm_reconciliation": {
            "status": "advisory_packet_only" if llm_reconcile else "not_requested",
            "sources": universe if llm_reconcile else [],
            "note": "Any host inference is advisory until the project owner records it."
            if llm_reconcile
            else None,
        },
    }


def _engineering_path(checkpoint: dict, start: str) -> list[str]:
    nodes = {node["id"]: node for node in checkpoint["nodes"]}
    design_types = {"decision", "specification", "plan_task", "contract"}
    verification_types = {"test", "evaluation", "verification_receipt"}

    def approved(edge: dict) -> bool:
        source_type = nodes[edge["from"]]["type"]
        target_type = nodes[edge["to"]]["type"]
        if source_type == "requirement":
            return (
                edge["type"]
                in {"satisfied_by", "decided_by", "specified_in", "planned_by"}
                and target_type in design_types
            )
        if source_type in design_types:
            return edge["type"] == "implements" and target_type == "code_symbol"
        if source_type == "code_symbol":
            return edge["type"] == "verified_by" and target_type in verification_types
        if source_type in verification_types:
            return edge["type"] == "introduced_in" and target_type == "commit"
        return (
            source_type == "commit"
            and edge["type"] == "reviewed_in"
            and target_type == "pull_request"
        )

    adjacency: dict[str, list[str]] = {}
    for edge in _exact_edges(checkpoint):
        if approved(edge):
            adjacency.setdefault(edge["from"], []).append(edge["to"])
    queue = deque([[start]])
    seen = {start}
    best = [start]
    while queue:
        path = queue.popleft()
        if len(path) > len(best):
            best = path
        for target in sorted(adjacency.get(path[-1], [])):
            if target not in seen:
                seen.add(target)
                queue.append(path + [target])
    return best


def query_result(command: str, checkpoint: dict, identifier: str | None = None) -> dict:
    nodes = {node["id"]: node for node in checkpoint["nodes"]}
    if identifier is not None and identifier not in nodes:
        raise EngineeringError(f"Unknown Engineering identifier: {identifier}")
    if command == "coverage":
        return {"requirements": coverage(checkpoint)}
    if command == "trace":
        return {"start": identifier, "path": _engineering_path(checkpoint, identifier)}
    if command == "impact":
        exact = _reachable(checkpoint, identifier)
        all_reachable = _reachable(checkpoint, identifier, exact=False)
        return {
            "start": identifier,
            "exact": exact,
            "suggested": [item for item in all_reachable if item not in exact],
        }
    reverse = _reachable(checkpoint, identifier, reverse=True)
    if command == "why-code":
        return {
            "symbol": identifier,
            "requirements": sorted(item for item in reverse if nodes[item]["type"] == "requirement"),
            "decisions": sorted(item for item in reverse if nodes[item]["type"] == "decision"),
        }
    return {
        "test": identifier,
        "requirements": sorted(item for item in reverse if nodes[item]["type"] == "requirement"),
        "contracts": sorted(item for item in reverse if nodes[item]["type"] == "contract"),
    }


_CREDENTIAL_PATTERNS = (
        r"(?i)\b(?:authorization\s*:\s*)?bearer\s+(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"(?i)\b(?:password|passwd|pwd|api[ _-]?key|access[ _-]?token|auth[ _-]?token|secret)\b\s*(?:is|=|:)\s*(?:\"[^\"]*\"|'[^']*'|[^,;]+)",
        r"(?i)\b(?:sk|gh[pousr])[-_][A-Za-z0-9_-]{8,}\b",
        r"\bAIza[0-9A-Za-z_-]{20,}\b",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"(?i)\bxox[baprs]-[A-Za-z0-9-]{8,}\b",
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
)


def _redact_credentials(value: str) -> str:
    for pattern in _CREDENTIAL_PATTERNS:
        value = re.sub(pattern, "[credential redacted]", value)
    return value


def _bounded_intent(intent: str) -> str:
    if not isinstance(intent, str) or not intent.strip():
        raise EngineeringError("Preparation intent must be a non-empty string.")
    value = _redact_credentials(" ".join(intent.split()))
    return value[:512]


def _intent_projection(intent: str) -> dict[str, str]:
    """Keep request prose only for this process; retain a minimal purpose."""
    lowered = intent.lower()
    purpose = next(
        (
            name
            for name, terms in (
                ("debug", ("debug", "defect", "failure", "incident")),
                ("review", ("review", "assess", "audit")),
                ("design", ("design", "plan", "architecture")),
                ("maintenance", ("maintain", "stale", "drift")),
            )
            if any(term in lowered for term in terms)
        ),
        "implementation",
    )
    return {"digest": "sha256:" + hashlib.sha256(intent.encode("utf-8")).hexdigest(), "purpose": purpose}


def _contains_credential(value: str) -> bool:
    return _redact_credentials(value) != value


def _outcome_survival(value: object, architect_scope: list[str]) -> dict[str, object]:
    """Validate one complete baseline-to-candidate mapping without a second ledger."""
    if not isinstance(value, dict) or set(value) != {"baseline_ids", "mappings"}:
        raise EngineeringError("Engineering outcome survival mapping is invalid.")
    baseline = value["baseline_ids"]
    mappings = value["mappings"]
    if (
        not isinstance(baseline, list)
        or not baseline
        or len(baseline) > 256
        or any(not isinstance(item, str) for item in baseline)
        or not isinstance(mappings, list)
        or not mappings
        or len(mappings) > 256
    ):
        raise EngineeringError("Engineering outcome survival mapping is invalid.")
    try:
        baseline_ids = sorted(
            _assurance_id(item, "baseline outcome") for item in baseline
        )
    except EngineeringError as error:
        raise EngineeringError("Engineering outcome survival mapping is invalid.") from error
    if len(set(baseline_ids)) != len(baseline_ids):
        raise EngineeringError("Engineering outcome survival baseline is duplicated.")

    expected_keys = {
        "baseline_id",
        "disposition",
        "reason",
        "verification_ids",
        "replacement_ids",
        "equivalence_decision_id",
    }
    normalized_mappings = []
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) != expected_keys:
            raise EngineeringError("Engineering outcome survival mapping is invalid.")
        try:
            baseline_id = _assurance_id(mapping["baseline_id"], "baseline outcome")
        except (EngineeringError, TypeError) as error:
            raise EngineeringError("Engineering outcome survival mapping is invalid.") from error
        disposition = mapping["disposition"]
        reason = mapping["reason"]
        if (
            disposition not in OUTCOME_SURVIVAL_DISPOSITIONS
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 500
            or _contains_credential(reason)
        ):
            raise EngineeringError("Engineering outcome survival mapping is invalid.")

        normalized_lists: dict[str, list[str]] = {}
        for key in ("verification_ids", "replacement_ids"):
            items = mapping[key]
            if (
                not isinstance(items, list)
                or len(items) > 64
                or any(not isinstance(item, str) for item in items)
            ):
                raise EngineeringError("Engineering outcome survival mapping is invalid.")
            try:
                normalized_lists[key] = sorted(
                    _assurance_id(item, f"outcome survival {key}") for item in items
                )
            except EngineeringError as error:
                raise EngineeringError("Engineering outcome survival mapping is invalid.") from error
            if len(set(normalized_lists[key])) != len(normalized_lists[key]):
                raise EngineeringError("Engineering outcome survival mapping is invalid.")
        if not normalized_lists["verification_ids"]:
            raise EngineeringError("Engineering outcome survival verification is missing.")

        equivalence = mapping["equivalence_decision_id"]
        if equivalence is not None:
            try:
                equivalence = _assurance_id(
                    equivalence, "outcome-equivalence decision"
                )
            except EngineeringError as error:
                raise EngineeringError(
                    "Engineering outcome-equivalence decision is invalid."
                ) from error
        if disposition == "REPLACED":
            if not normalized_lists["replacement_ids"] or equivalence is None:
                raise EngineeringError(
                    "Engineering REPLACED outcome lacks outcome-equivalence evidence."
                )
        elif normalized_lists["replacement_ids"] or equivalence is not None:
            raise EngineeringError(
                "Engineering non-replacement outcome carries replacement evidence."
            )

        normalized_mappings.append(
            {
                "baseline_id": baseline_id,
                "disposition": disposition,
                "reason": reason.strip(),
                "verification_ids": normalized_lists["verification_ids"],
                "replacement_ids": normalized_lists["replacement_ids"],
                "equivalence_decision_id": equivalence,
            }
        )

    mapped_ids = [item["baseline_id"] for item in normalized_mappings]
    missing = sorted(set(baseline_ids) - set(mapped_ids))
    unexpected = sorted(set(mapped_ids) - set(baseline_ids))
    if missing:
        raise EngineeringError(
            "Engineering outcome survival is incomplete; missing baseline mappings: "
            + ", ".join(missing)
        )
    if unexpected or len(set(mapped_ids)) != len(mapped_ids):
        raise EngineeringError("Engineering outcome survival mapping is ambiguous.")

    architect = set(architect_scope)
    referenced = set(baseline_ids)
    for mapping in normalized_mappings:
        referenced.update(mapping["verification_ids"])
        referenced.update(mapping["replacement_ids"])
        if mapping["equivalence_decision_id"] is not None:
            referenced.add(mapping["equivalence_decision_id"])
    outside = sorted(referenced - architect)
    if outside:
        raise EngineeringError(
            "Engineering outcome survival evidence is outside architect scope: "
            + ", ".join(outside)
        )
    return {
        "baseline_ids": baseline_ids,
        "mappings": sorted(normalized_mappings, key=lambda item: item["baseline_id"]),
    }


def _active_owner_intent(
    root: Path,
    intent_id: str | None = None,
    intent_digest: str | None = None,
) -> dict:
    """Return the sole active external owner baseline, never a caller substitute."""
    if intent_id is not None:
        intent_id = _assurance_id(intent_id, "owner intent")
    if intent_digest is not None and not re.fullmatch(
        r"sha256:[0-9a-f]{64}", intent_digest
    ):
        raise EngineeringError("Engineering owner intent digest is invalid.")
    active = [
        record
        for record in _load_owner_intents(root)["intents"]
        if record["status"] == "active"
    ]
    if len(active) > 1:
        raise EngineeringError("Engineering owner intent ledger is ambiguous.")
    if not active:
        raise EngineeringError("Engineering owner intent is unknown.")
    record = active[0]
    if (
        "approval_trust_anchor" not in record
        or record["approval_trust_anchor"].get("schema") != HOST_TRUST_ANCHOR_SCHEMA
    ):
        raise EngineeringError("Engineering owner intent is historical and cannot govern new release work.")
    if intent_id is not None and record["intent_id"] != intent_id:
        raise EngineeringError("Engineering owner intent is not active for this scope.")
    if (
        intent_digest is not None
        and record["owner_intent_digest"] != intent_digest
    ):
        raise EngineeringError("Engineering owner intent digest is mismatched.")
    return record


def _verify_host_owner_exception(
    root: Path,
    owner_intent: dict,
    outcome_id: str,
    disposition: str,
    value: object,
) -> dict:
    """Verify the narrow owner exception required to defer or exclude one outcome."""
    if not isinstance(value, dict) or set(value) != {
        "schema", "approver", "claims", "host_receipt", "signature"
    }:
        raise EngineeringError("Engineering owner exception is invalid.")
    raw_claims = value.get("claims")
    if not isinstance(raw_claims, dict) or set(raw_claims) != {
        "exception_id",
        "owner_intent_id",
        "owner_intent_digest",
        "outcome_id",
        "disposition",
    }:
        raise EngineeringError("Engineering owner exception is invalid.")
    try:
        claims = {
            "exception_id": _assurance_id(raw_claims["exception_id"], "owner exception"),
            "owner_intent_id": _assurance_id(
                raw_claims["owner_intent_id"], "owner exception owner intent"
            ),
            "owner_intent_digest": raw_claims["owner_intent_digest"],
            "outcome_id": _assurance_id(raw_claims["outcome_id"], "owner exception outcome"),
            "disposition": raw_claims["disposition"],
        }
    except (EngineeringError, KeyError) as error:
        raise EngineeringError("Engineering owner exception is invalid.") from error
    if (
        not re.fullmatch(r"sha256:[0-9a-f]{64}", str(claims["owner_intent_digest"]))
        or claims["owner_intent_id"] != owner_intent["intent_id"]
        or claims["owner_intent_digest"] != owner_intent["owner_intent_digest"]
        or claims["outcome_id"] != outcome_id
        or claims["disposition"] != disposition
        or disposition not in {"DEFERRED", "EXCLUDED"}
    ):
        raise EngineeringError("Engineering owner exception is invalid.")
    _verify_host_owned_signature(
        root,
        value,
        approval_schema=OWNER_EXCEPTION_SCHEMA,
        claims_schema="engineering.host-owner-exception-claims.v3",
        claims=claims,
        namespace="engineering-owner-exception",
        label="Engineering owner exception",
        reference_prefix="owner-exception-",
        contract=OWNER_EXCEPTION_SCHEMA,
        authority_epoch=owner_intent["authority_epoch"],
    )
    return {
        "schema": OWNER_EXCEPTION_SCHEMA,
        "approver": value["approver"],
        "claims": claims,
        "host_receipt": value["host_receipt"],
        "signature": value["signature"],
    }


def _outcome_equivalence(root: Path, owner_intent: dict, value: object) -> dict:
    """Require an externally attested, role-bound replacement equivalence claim."""
    expected = {
        "schema",
        "reviewer_id",
        "architect_id",
        "implementer_id",
        "writer_id",
        "evidence_id",
        "evidence_digest",
        "equivalence_attestation",
    }
    if not isinstance(value, dict):
        raise EngineeringError("Engineering outcome equivalence is invalid.")
    if "equivalence_attestation" not in value:
        raise EngineeringError(
            "Engineering REPLACED outcome requires external equivalence attestation."
        )
    if (
        set(value) != expected
        or value.get("schema") != OUTCOME_EQUIVALENCE_SCHEMA
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("evidence_digest", "")))
    ):
        raise EngineeringError("Engineering outcome equivalence is invalid.")
    try:
        normalized = {
            "schema": OUTCOME_EQUIVALENCE_SCHEMA,
            "reviewer_id": _assurance_id(value["reviewer_id"], "outcome equivalence reviewer"),
            "architect_id": _assurance_id(value["architect_id"], "outcome equivalence architect"),
            "implementer_id": _assurance_id(value["implementer_id"], "outcome equivalence implementer"),
            "writer_id": _assurance_id(value["writer_id"], "outcome equivalence writer"),
            "evidence_id": _assurance_id(value["evidence_id"], "outcome equivalence evidence"),
            "evidence_digest": value["evidence_digest"],
        }
    except EngineeringError as error:
        raise EngineeringError("Engineering outcome equivalence is invalid.") from error
    if normalized["reviewer_id"] in {
        normalized["architect_id"],
        normalized["implementer_id"],
        normalized["writer_id"],
    }:
        raise EngineeringError("Engineering outcome equivalence reviewer is not independent.")
    claims = {
        name: normalized[name]
        for name in (
            "reviewer_id",
            "architect_id",
            "implementer_id",
            "writer_id",
            "evidence_id",
            "evidence_digest",
        )
    }
    _verify_host_owned_signature(
        root,
        value["equivalence_attestation"],
        approval_schema=OUTCOME_EQUIVALENCE_ATTESTATION_SCHEMA,
        claims_schema="engineering.outcome-equivalence-claims.v2",
        claims=claims,
        namespace="engineering-outcome-equivalence",
        label="Engineering outcome equivalence attestation",
        reference_prefix="outcome-equivalence-",
        contract=OUTCOME_EQUIVALENCE_SCHEMA,
        authority_epoch=owner_intent["authority_epoch"],
        required_principal=normalized["reviewer_id"],
    )
    return {
        **normalized,
        "equivalence_attestation": {
            "schema": OUTCOME_EQUIVALENCE_ATTESTATION_SCHEMA,
            "approver": normalized["reviewer_id"],
            "claims": claims,
            "host_receipt": value["equivalence_attestation"]["host_receipt"],
            "signature": value["equivalence_attestation"]["signature"],
        },
    }


def _outcome_survival_v2(
    value: object,
    owner_intent: dict,
    *,
    root: Path | None = None,
    architect_scope: list[str] | None = None,
    allow_controller_baseline: bool = False,
) -> dict[str, object]:
    """Inject and completely map the external owner baseline for one handoff."""
    if not isinstance(value, dict):
        raise EngineeringError("Engineering outcome survival v2 mapping is invalid.")
    expected = {
        "schema",
        "owner_intent_id",
        "owner_intent_digest",
        "mappings",
    }
    controller_expected = expected | {"baseline_ids", "mapping_digest"}
    if "baseline_ids" in value and not allow_controller_baseline:
        raise EngineeringError(
            "Engineering outcome survival v2 baseline is controller-injected; candidate baseline_ids are prohibited."
        )
    allowed_key_sets = (
        {frozenset(expected)}
        if not allow_controller_baseline
        else {frozenset(expected), frozenset(controller_expected)}
    )
    if frozenset(value) not in allowed_key_sets:
        raise EngineeringError("Engineering outcome survival v2 mapping is invalid.")
    if value.get("schema") != OUTCOME_SURVIVAL_V2_SCHEMA:
        raise EngineeringError("Engineering outcome survival v2 mapping is invalid.")
    if (
        value.get("owner_intent_id") != owner_intent.get("intent_id")
        or value.get("owner_intent_digest") != owner_intent.get("owner_intent_digest")
    ):
        raise EngineeringError("Engineering outcome survival v2 owner intent is mismatched.")
    baseline_ids = sorted(outcome["id"] for outcome in owner_intent["outcomes"])
    if "baseline_ids" in value:
        supplied = value["baseline_ids"]
        if (
            not isinstance(supplied, list)
            or sorted(supplied) != baseline_ids
            or len(set(supplied)) != len(supplied)
        ):
            raise EngineeringError("Engineering outcome survival v2 controller baseline is mismatched.")
        if not re.fullmatch(
            r"sha256:[0-9a-f]{64}", str(value.get("mapping_digest", ""))
        ):
            raise EngineeringError("Engineering outcome survival v2 mapping digest is invalid.")
    mappings = value.get("mappings")
    if (
        not isinstance(mappings, list)
        or not mappings
        or len(mappings) > MAX_OWNER_INTENT_OUTCOMES
    ):
        raise EngineeringError("Engineering outcome survival v2 mapping is invalid.")
    normalized_mappings = []
    for mapping in mappings:
        expected_mapping = {
            "outcome_id",
            "disposition",
            "reason",
            "verification_ids",
            "replacement_ids",
            "equivalence",
            "owner_exception",
        }
        if not isinstance(mapping, dict) or set(mapping) != expected_mapping:
            raise EngineeringError("Engineering outcome survival v2 mapping is invalid.")
        try:
            outcome_id = _assurance_id(mapping["outcome_id"], "owner outcome")
        except EngineeringError as error:
            raise EngineeringError("Engineering outcome survival v2 mapping is invalid.") from error
        disposition = mapping.get("disposition")
        reason = mapping.get("reason")
        if (
            disposition not in OUTCOME_SURVIVAL_DISPOSITIONS
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 500
            or _contains_credential(reason)
        ):
            raise EngineeringError("Engineering outcome survival v2 mapping is invalid.")
        lists: dict[str, list[str]] = {}
        for key in ("verification_ids", "replacement_ids"):
            items = mapping[key]
            if (
                not isinstance(items, list)
                or len(items) > 64
                or any(not isinstance(item, str) for item in items)
            ):
                raise EngineeringError("Engineering outcome survival v2 mapping is invalid.")
            try:
                lists[key] = sorted(
                    _assurance_id(item, f"outcome survival v2 {key}")
                    for item in items
                )
            except EngineeringError as error:
                raise EngineeringError("Engineering outcome survival v2 mapping is invalid.") from error
            if len(set(lists[key])) != len(lists[key]):
                raise EngineeringError("Engineering outcome survival v2 mapping is invalid.")
        if not lists["verification_ids"]:
            raise EngineeringError("Engineering outcome survival v2 verification is missing.")
        equivalence = mapping["equivalence"]
        owner_exception = mapping["owner_exception"]
        if disposition == "INCLUDED":
            if lists["replacement_ids"] or equivalence is not None or owner_exception is not None:
                raise EngineeringError("Engineering included outcome carries incompatible disposition evidence.")
            normalized_equivalence = None
            normalized_exception = None
        elif disposition == "REPLACED":
            if not lists["replacement_ids"] or equivalence is None or owner_exception is not None:
                raise EngineeringError("Engineering REPLACED outcome lacks independent equivalence evidence.")
            if root is None:
                raise EngineeringError(
                    "Engineering REPLACED outcome requires an externally attested equivalence root."
                )
            normalized_equivalence = _outcome_equivalence(root, owner_intent, equivalence)
            normalized_exception = None
        else:
            if lists["replacement_ids"] or equivalence is not None or owner_exception is None:
                raise EngineeringError("Engineering DEFERRED or EXCLUDED outcome requires external owner exception.")
            if root is None:
                raise EngineeringError("Engineering owner exception verification requires a project root.")
            normalized_equivalence = None
            normalized_exception = _verify_host_owner_exception(
                root, owner_intent, outcome_id, disposition, owner_exception
            )
        normalized_mappings.append(
            {
                "outcome_id": outcome_id,
                "disposition": disposition,
                "reason": reason.strip(),
                "verification_ids": lists["verification_ids"],
                "replacement_ids": lists["replacement_ids"],
                "equivalence": normalized_equivalence,
                "owner_exception": normalized_exception,
            }
        )
    mapped_ids = [item["outcome_id"] for item in normalized_mappings]
    missing = sorted(set(baseline_ids) - set(mapped_ids))
    unexpected = sorted(set(mapped_ids) - set(baseline_ids))
    if missing:
        raise EngineeringError(
            "Engineering outcome survival v2 is incomplete; missing controller baseline mappings: "
            + ", ".join(missing)
        )
    if unexpected or len(set(mapped_ids)) != len(mapped_ids):
        raise EngineeringError("Engineering outcome survival v2 mapping is ambiguous.")
    if architect_scope is not None:
        allowed = set(architect_scope)
        referenced = set()
        for mapping in normalized_mappings:
            referenced.update(mapping["verification_ids"])
            referenced.update(mapping["replacement_ids"])
            if mapping["equivalence"] is not None:
                referenced.add(mapping["equivalence"]["evidence_id"])
        outside = sorted(referenced - allowed)
        if outside:
            raise EngineeringError(
                "Engineering outcome survival v2 evidence is outside architect scope: "
                + ", ".join(outside)
            )
    normalized = {
        "schema": OUTCOME_SURVIVAL_V2_SCHEMA,
        "owner_intent_id": owner_intent["intent_id"],
        "owner_intent_digest": owner_intent["owner_intent_digest"],
        "baseline_ids": baseline_ids,
        "mappings": sorted(normalized_mappings, key=lambda item: item["outcome_id"]),
    }
    normalized["mapping_digest"] = _json_digest(normalized)
    if "mapping_digest" in value and value["mapping_digest"] != normalized["mapping_digest"]:
        raise EngineeringError("Engineering outcome survival v2 mapping digest is mismatched.")
    return normalized


def _scope_handoff(
    value: object,
    *,
    require_approval: bool = True,
    allow_controller_baseline: bool = False,
) -> dict[str, object]:
    """Validate the bounded scope contract carried from investigation to delivery."""
    base_keys = {
        "seed_evidence",
        "reconstructed_scope",
        "architect_scope",
        "result_scope",
        "result_artifacts",
    }
    approval_keys = {"approval_id", "decision_id", "decision_digest"}
    required = base_keys | approval_keys if require_approval else base_keys
    allowed = required | {"outcome_survival"}
    if not isinstance(value, dict) or frozenset(value) not in {
        frozenset(required),
        frozenset(allowed),
    }:
        raise EngineeringError("Preparation scope handoff is invalid.")
    normalized: dict[str, object] = {}
    for key in ("seed_evidence", "reconstructed_scope", "architect_scope", "result_scope"):
        items = value[key]
        if (
            not isinstance(items, list)
            or not items
            or len(items) > 256
            or any(not isinstance(item, str) for item in items)
        ):
            raise EngineeringError("Preparation scope handoff is invalid.")
        try:
            identifiers = [_assurance_id(item, f"scope handoff {key}") for item in items]
        except EngineeringError as error:
            raise EngineeringError("Preparation scope handoff is invalid.") from error
        if len(set(identifiers)) != len(identifiers):
            raise EngineeringError("Preparation scope handoff is invalid.")
        normalized[key] = sorted(identifiers)
    artifacts = value["result_artifacts"]
    if (
        not isinstance(artifacts, list)
        or not artifacts
        or len(artifacts) > 256
        or any(not isinstance(item, str) or not item for item in artifacts)
        or any(Path(item).is_absolute() or ".." in Path(item).parts for item in artifacts)
        or any(_contains_credential(item) for item in artifacts)
    ):
        raise EngineeringError("Preparation scope handoff result artifacts are invalid.")
    normalized_artifacts = [item.replace("\\", "/") for item in artifacts]
    if len(set(normalized_artifacts)) != len(normalized_artifacts):
        raise EngineeringError("Preparation scope handoff result artifacts are invalid.")
    normalized["result_artifacts"] = sorted(normalized_artifacts)
    seed = set(normalized["seed_evidence"])
    reconstructed = set(normalized["reconstructed_scope"])
    architect = set(normalized["architect_scope"])
    result = set(normalized["result_scope"])
    if not seed.issubset(reconstructed):
        raise EngineeringError("Preparation scope handoff did not reconstruct seed evidence.")
    if reconstructed != architect:
        raise EngineeringError("Preparation scope handoff is not architect-approved.")
    if result != architect:
        raise EngineeringError("Preparation scope handoff is narrow or incomplete.")
    if "outcome_survival" in value:
        survival = value["outcome_survival"]
        if isinstance(survival, dict) and survival.get("schema") == OUTCOME_SURVIVAL_V2_SCHEMA:
            input_keys = {
                "schema",
                "owner_intent_id",
                "owner_intent_digest",
                "mappings",
            }
            controller_keys = input_keys | {"baseline_ids", "mapping_digest"}
            permitted = (
                {frozenset(input_keys)}
                if not allow_controller_baseline
                else {frozenset(input_keys), frozenset(controller_keys)}
            )
            if frozenset(survival) not in permitted:
                raise EngineeringError("Preparation owner-intent outcome survival is invalid.")
            # Root-bound validation and controller baseline injection occur at
            # the scope authority boundary, never from candidate input alone.
            normalized["outcome_survival"] = dict(survival)
        else:
            normalized["outcome_survival"] = _outcome_survival(
                survival, normalized["architect_scope"]
            )
    if require_approval:
        approval_id = value["approval_id"]
        if (
            not isinstance(approval_id, str)
            or not re.fullmatch(r"attestation-[0-9a-f]{32}", approval_id)
        ):
            raise EngineeringError("Preparation scope handoff approval is invalid.")
        try:
            normalized["decision_id"] = _assurance_id(
                value["decision_id"], "scope handoff decision"
            )
        except EngineeringError as error:
            raise EngineeringError("Preparation scope handoff decision is invalid.") from error
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value["decision_digest"])):
            raise EngineeringError("Preparation scope handoff decision digest is invalid.")
        normalized["approval_id"] = approval_id
        normalized["decision_digest"] = value["decision_digest"]
    return normalized


def _bind_owner_intent_handoff(root: Path, handoff: dict) -> dict:
    """Compile a v2 survival mapping against the active private owner intent."""
    normalized = dict(handoff)
    survival = normalized.get("outcome_survival")
    if not isinstance(survival, dict) or survival.get("schema") != OUTCOME_SURVIVAL_V2_SCHEMA:
        return normalized
    intent = _active_owner_intent(
        root,
        survival.get("owner_intent_id"),
        survival.get("owner_intent_digest"),
    )
    normalized["outcome_survival"] = _outcome_survival_v2(
        survival,
        intent,
        root=root,
        architect_scope=normalized["architect_scope"],
        allow_controller_baseline="baseline_ids" in survival,
    )
    return normalized


def _scope_result(value: object) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > 256
        or any(not isinstance(item, str) for item in value)
    ):
        raise EngineeringError("Engineering completion result scope is invalid.")
    try:
        identifiers = [_assurance_id(item, "completion result scope") for item in value]
    except EngineeringError as error:
        raise EngineeringError("Engineering completion result scope is invalid.") from error
    if len(set(identifiers)) != len(identifiers):
        raise EngineeringError("Engineering completion result scope is invalid.")
    return sorted(identifiers)


def _material_change_class(intent: str, scope: dict) -> str | None:
    explicit = scope.get("change_class")
    if explicit is not None:
        if explicit not in MATERIAL_CHANGE_CLASSES:
            raise EngineeringError("Preparation material change class is invalid.")
        return explicit
    lowered = intent.casefold()
    for change_class, terms in (
        ("capability_deletion", ("delete capability", "remove capability")),
        ("replacement", ("replace", "replacement")),
        ("redesign", ("redesign", "re-design")),
        ("simplification", ("simplify", "simplification")),
    ):
        if any(term in lowered for term in terms):
            return change_class
    return None


def _scope_envelope(scope: dict) -> dict[str, object]:
    if not isinstance(scope, dict):
        raise EngineeringError("Preparation scope must be an object.")
    result: dict[str, object] = {}
    for key in ("scope", "forbidden"):
        value = scope.get(key, [])
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
        ):
            raise EngineeringError(f"Preparation {key} must be an array of strings.")
        if len(value) > 256 or any(len(item) > 512 for item in value):
            raise EngineeringError(f"Preparation {key} exceeds its bounded size.")
        if any(_contains_credential(item) for item in value):
            raise EngineeringError(
                f"Preparation {key} must not contain credential-shaped values."
            )
        result[key] = list(dict.fromkeys(item.replace("\\", "/") for item in value))
    if any(Path(item).is_absolute() or ".." in Path(item).parts for item in result["scope"]):
        raise EngineeringError("Preparation scope paths must stay inside the project.")
    deterministic_only = scope.get("deterministic_only_approved", False)
    if not isinstance(deterministic_only, bool):
        raise EngineeringError("deterministic_only_approved must be boolean.")
    # Compatibility only: task authority, not this caller-supplied flag, permits
    # degraded deterministic work when graph context is unavailable.
    result["legacy_deterministic_only_approved"] = deterministic_only
    approval = scope.get("contract_approval_id")
    if approval is not None:
        result["contract_approval_id"] = _assurance_id(approval, "contract approval")
    if "task_authority" in scope:
        if not isinstance(scope["task_authority"], dict):
            raise EngineeringError("Preparation task authority must be an object.")
        result["task_authority"] = scope["task_authority"]
    if "scope_handoff" in scope:
        result["scope_handoff"] = _scope_handoff(
            scope["scope_handoff"], allow_controller_baseline=True
        )
    if "change_class" in scope:
        change_class = scope["change_class"]
        if change_class not in MATERIAL_CHANGE_CLASSES:
            raise EngineeringError("Preparation material change class is invalid.")
        result["change_class"] = change_class
    return result


def _explicit_context_ids(intent: str, scope: dict, nodes: dict[str, dict]) -> tuple[list[str], list[str]]:
    candidates: list[str] = []
    for key in ("context_ids", "required_context_ids", "requirement_ids", "decision_ids", "ids"):
        value = scope.get(key, [])
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item for item in value
        ):
            raise EngineeringError(f"Preparation {key} must be an array of strings.")
        if any(_contains_credential(item) for item in value):
            raise EngineeringError("Preparation context IDs must not contain credentials.")
        candidates.extend(value)
    positions = sorted(
        (match.start(), identifier)
        for identifier in nodes
        if nodes[identifier].get("type") in EXPLICIT_INTENT_CONTEXT_NODE_TYPES
        for match in [re.search(rf"(?<![\w-]){re.escape(identifier)}(?![\w-])", intent)]
        if match
    )
    candidates.extend(identifier for _, identifier in positions)
    referenced = re.findall(r"\b(?:REQ|DEC)-[A-Za-z0-9][A-Za-z0-9._-]*\b", intent)
    candidates.extend(referenced)
    unique = list(dict.fromkeys(candidates))
    return [item for item in unique if item in nodes], [item for item in unique if item not in nodes]


def _graphify_query_context(
    intent: str, checkpoint_path: Path, token_budget: int
) -> dict:
    """Select bounded code-graph context deterministically; never call an LLM CLI."""
    graph_path = checkpoint_path.parent / "graph.json"
    if not graph_path.is_file():
        return {"status": "unavailable", "context": [], "reason": "graph_missing"}
    try:
        graph = _read_base_graph(graph_path)
    except EngineeringError:
        return {"status": "invalid", "context": [], "reason": "invalid_graph"}
    if token_budget <= 0:
        return {
            "status": "unavailable",
            "context": [],
            "reason": "token_budget_not_configured",
        }
    terms = {term for term in re.findall(r"[a-z0-9_]{3,}", intent.lower())}
    selected, used = [], 0
    for node in sorted(graph["nodes"], key=lambda item: str(item["id"])):
        identifier = str(node["id"])
        label = str(node.get("label", identifier)).lower()
        if not terms.intersection(re.findall(r"[a-z0-9_]{3,}", f"{identifier} {label}".lower())):
            continue
        if _contains_credential(identifier):
            return {"status": "invalid", "context": [], "reason": "credential_query_id"}
        cost = max(1, (len(identifier) + 3) // 4)
        if used + cost > token_budget:
            continue
        selected.append({"id": identifier, "provenance": "derived"})
        used += cost
    return {"status": "success" if selected else "empty", "context": selected}


def _merge_context(items: list[dict]) -> list[dict]:
    strength = {"ambiguous": 0, "inferred": 1, "derived": 2, "direct": 3}
    merged: dict[str, dict] = {}
    for item in items:
        identifier, provenance = item["id"], item["provenance"]
        current = merged.get(identifier)
        if current is None or strength[provenance] > strength[current["provenance"]]:
            merged[identifier] = {"id": identifier, "provenance": provenance}
    return list(merged.values())


def _exact_context_neighbours(checkpoint: dict, identifiers: list[str]) -> list[dict]:
    provenance = {identifier: "direct" for identifier in identifiers}
    order: list[str] = []
    queue = deque(identifiers)
    edges = sorted(_exact_edges(checkpoint), key=lambda item: item["id"])
    while queue:
        current = queue.popleft()
        for edge in edges:
            target = (
                edge["to"] if edge["from"] == current
                else edge["from"] if edge["to"] == current
                else None
            )
            if target is None:
                continue
            candidate = (
                "derived"
                if provenance[current] == "derived"
                or edge["provenance"] == "derived"
                else "direct"
            )
            if target not in provenance:
                provenance[target] = candidate
                order.append(target)
                queue.append(target)
            elif provenance[target] == "derived" and candidate == "direct":
                provenance[target] = "direct"
                queue.append(target)
    return [
        {"id": identifier, "provenance": provenance[identifier]}
        for identifier in order
    ]


def _context_impact(checkpoint: dict, identifiers: list[str]) -> list[dict]:
    nodes = {node["id"]: node for node in checkpoint["nodes"]}
    adjacency: dict[str, list[dict]] = {}
    for edge in sorted(_exact_edges(checkpoint), key=lambda item: item["id"]):
        adjacency.setdefault(edge["from"], []).append(edge)
    result: dict[str, dict] = {}
    for origin in identifiers:
        if origin not in nodes:
            continue
        provenance = {origin: "direct"}
        queue = deque([origin])
        while queue:
            current = queue.popleft()
            for edge in adjacency.get(current, []):
                target = edge["to"]
                candidate = (
                    "derived"
                    if provenance[current] == "derived"
                    or edge["provenance"] == "derived"
                    else "direct"
                )
                if target not in provenance or (
                    provenance[target] == "derived" and candidate == "direct"
                ):
                    provenance[target] = candidate
                    queue.append(target)
        for identifier, item_provenance in provenance.items():
            node = nodes[identifier]
            source = node.get("source", {})
            path = source.get("path") if isinstance(source, dict) else None
            if not isinstance(path, str):
                continue
            path = path.replace("\\", "/")
            types = {
                "contract": "changes contract for",
                "code_symbol": "implements",
                "test": "verifies",
                "evaluation": "verifies",
                "verification_receipt": "verifies",
                "decision": "decides",
            }
            item = {
                "id": path,
                "reason": f"{types.get(node['type'], 'relates to')} {origin}",
                "provenance": item_provenance,
            }
            if path not in result or (
                result[path]["provenance"] == "derived"
                and item_provenance == "direct"
            ):
                result[path] = item
    return [result[key] for key in sorted(result)]


def _intent_impacting(
    checkpoint: dict,
    selected_ids: list[str],
    change_class: str | None,
    scope_handoff: object,
    *,
    artifact_paths: object = (),
) -> bool:
    """Conservatively identify intent scope from exact graph connectivity.

    A declared material class or an outcome-survival handoff is always
    intent-impacting. For otherwise routine work, the controller follows only
    exact edges from the selected nodes and detects contact with an explicit
    capability or assurance/obligation node. Inferred links
    never establish this gate, so ordinary legacy requirement links remain
    readable history rather than being silently upgraded into new owner intent.
    """
    if change_class in MATERIAL_CHANGE_CLASSES or (
        isinstance(scope_handoff, dict) and "outcome_survival" in scope_handoff
    ):
        return True
    if not isinstance(checkpoint, dict) or not isinstance(selected_ids, list):
        return False
    raw_nodes = checkpoint.get("nodes")
    if not isinstance(raw_nodes, list):
        return False
    nodes = {
        item.get("id"): item
        for item in raw_nodes
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    artifact_ids: list[str] = []
    if isinstance(artifact_paths, (list, tuple, set, frozenset)):
        normalized_paths = {
            item.replace("\\", "/")
            for item in artifact_paths
            if isinstance(item, str)
            and item
            and not Path(item).is_absolute()
            and ".." not in Path(item).parts
        }
        artifact_ids = [
            identifier
            for identifier, node in nodes.items()
            if isinstance(node.get("source"), dict)
            and isinstance(node["source"].get("path"), str)
            and node["source"]["path"].replace("\\", "/") in normalized_paths
        ]
    queue = deque(
        dict.fromkeys(
            identifier
            for identifier in [*selected_ids, *artifact_ids]
            if identifier in nodes
        )
    )
    seen = set(queue)
    while queue:
        current = queue.popleft()
        if nodes[current].get("type") in INTENT_IMPACT_GRAPH_NODE_TYPES:
            return True
        for edge in _exact_edges(checkpoint):
            if edge["from"] == current:
                target = edge["to"]
            elif edge["to"] == current:
                target = edge["from"]
            else:
                continue
            if target in nodes and target not in seen:
                seen.add(target)
                queue.append(target)
    return False


def _checkpoint_source_paths(checkpoint: dict) -> set[str]:
    """Return the normalized artifact paths represented by one exact checkpoint."""
    if not isinstance(checkpoint, dict) or not isinstance(checkpoint.get("nodes"), list):
        return set()
    return {
        source["path"].replace("\\", "/")
        for node in checkpoint["nodes"]
        if isinstance(node, dict)
        and isinstance(node.get("source"), dict)
        and isinstance((source := node["source"]).get("path"), str)
        and source["path"]
        and not Path(source["path"]).is_absolute()
        and ".." not in Path(source["path"]).parts
    }


def _owner_commitment_path(path: str) -> bool:
    """Fail closed when a safe changed path lacks an exact owner-neutral proof."""
    normalized = path.replace("\\", "/")
    return bool(normalized)


def _unrepresented_owner_commitment_paths(
    checkpoint: dict, artifact_paths: object
) -> set[str]:
    """Return safe repository paths not represented by the exact base graph."""
    if not isinstance(artifact_paths, (list, tuple, set, frozenset)):
        return set()
    known = _checkpoint_source_paths(checkpoint)
    return {
        normalized
        for path in artifact_paths
        if isinstance(path, str)
        and path
        and not Path(path).is_absolute()
        and ".." not in Path(path).parts
        and (normalized := path.replace("\\", "/")) not in known
        and _owner_commitment_path(normalized)
    }


def _path_exists_at_commit(root: Path, commit: str, path: str) -> bool:
    """Check a bounded repository-relative path without interpreting it as an argument."""
    if (
        not isinstance(path, str)
        or not path
        or Path(path).is_absolute()
        or ".." in Path(path).parts
    ):
        return False
    return (
        subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{commit}:{path}"],
            capture_output=True,
            text=True,
            env=_controller_git_environment(),
        ).returncode
        == 0
    )


def _requires_refreshed_intent_checkpoint(
    root: Path,
    preparation_commit: str,
    base: dict,
    changed: list[str],
) -> bool:
    """Return whether base evidence cannot safely cover the exact result.

    A result checkpoint is mandatory when the result introduces an artifact
    which the preparation checkpoint could not have represented, including
    README, documentation, and test commitments, or when it alters the
    traceability mapping itself.  The refreshed graph decides whether a new
    artifact is capability-linked; absence of that exact evidence fails closed.
    """
    known = _checkpoint_source_paths(base)
    unrepresented_commitments = _unrepresented_owner_commitment_paths(base, changed)
    for path in changed:
        normalized = path.replace("\\", "/")
        if normalized == "docs/engineering-traceability/links.json":
            return True
        if normalized in known:
            continue
        if normalized in unrepresented_commitments:
            return True
        if _path_exists_at_commit(root, preparation_commit, normalized):
            continue
        return True
    return False


def _completion_intent_impact(
    root: Path,
    preparation_commit: str,
    head: str,
    dirty: bool,
    changed: list[str],
    authorization: dict,
    scope_handoff: object,
    checkpoint_status: dict,
) -> bool:
    """Assess both the preparation and exact result graph before completion.

    The preparation graph is retained for historical links and dirty-overlay
    continuity.  An exact result checkpoint is mandatory when the result adds
    an artifact that base evidence cannot safely classify, or changes the
    traceability mapping itself.  This blocks a newly introduced capability
    path from evading the owner-intent fence while preserving ordinary
    documentation/test follow-ups and their existing scope/contract checks.
    """
    base = _load_checkpoint(root, preparation_commit)
    base_impact = _intent_impacting(
        base,
        [],
        authorization.get("change_class"),
        scope_handoff,
        artifact_paths=changed,
    ) or bool(_unrepresented_owner_commitment_paths(base, changed))
    requires_refreshed = _requires_refreshed_intent_checkpoint(
        root, preparation_commit, base, changed
    )
    if dirty:
        if base_impact:
            return True
        if requires_refreshed:
            raise EngineeringError(
                "Engineering completion cannot assess new result artifacts without a refreshed exact checkpoint."
            )
        return False
    if (
        not isinstance(checkpoint_status, dict)
        or checkpoint_status.get("ready") is not True
        or checkpoint_status.get("commit") != head
    ):
        if requires_refreshed:
            raise EngineeringError("Engineering feature checkpoint refresh failed.")
        return base_impact
    try:
        current = _load_checkpoint(root, head)
    except (EngineeringError, TraceabilityError) as error:
        if requires_refreshed:
            raise EngineeringError(
                "Engineering completion cannot assess result artifacts: refreshed exact checkpoint is unavailable."
            ) from error
        return base_impact
    return base_impact or _intent_impacting(
        current,
        [],
        authorization.get("change_class"),
        scope_handoff,
        artifact_paths=changed,
    )


def _require_completion_owner_intent(
    root: Path, preparation: dict, scope_handoff: object
) -> None:
    """Require the externally bound intent and survival baseline for impact."""
    bound_owner_intent = _bound_preparation_owner_intent(preparation)
    survival = (
        scope_handoff.get("outcome_survival")
        if isinstance(scope_handoff, dict)
        else None
    )
    if (
        bound_owner_intent is None
        or not isinstance(survival, dict)
        or survival.get("schema") != OUTCOME_SURVIVAL_V2_SCHEMA
    ):
        raise EngineeringError(
            "Engineering completion detected unbound intent impact from actual artifacts."
        )
    _active_owner_intent(
        root,
        bound_owner_intent["intent_id"],
        bound_owner_intent["owner_intent_digest"],
    )


def _dirty_paths(root: Path) -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "-z", "--untracked-files=all"],
        capture_output=True,
        check=True,
        env=_controller_git_environment(),
    ).stdout.decode("utf-8", errors="strict")
    fields = [field for field in output.split("\0") if field]
    paths: list[str] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        status, path = record[:2], record[3:]
        paths.append(path.replace("\\", "/"))
        index += 1
        if status[0] in "RC" or status[1] in "RC":
            if index < len(fields):
                paths.append(fields[index].replace("\\", "/"))
                index += 1
    return list(dict.fromkeys(paths))


def _maintenance_pending(root: Path) -> bool:
    return bool(_load_maintenance(root)["items"])


def _maintenance_blocks_preparation(
    item: dict, *, required_sources: set[str], impact: list[dict]
) -> bool:
    """Return whether queued maintenance can invalidate this graph-dependent run.

    Queued work is normally advisory: the repository operation lock already
    serializes writers, and a queued artifact is not by itself conflicting
    authority. Only an unsafe checkpoint repair, explicitly required current
    contract evidence, or an artifact on the selected graph/release impact
    path can block preparation.
    """
    if item.get("safe"):
        return False
    artifact = item.get("artifact")
    if not isinstance(artifact, str):
        return False
    artifact = artifact.replace("\\", "/")
    if item.get("kind") == "checkpoint_stale" and artifact == "checkpoint":
        return True
    if artifact in required_sources:
        return True
    return artifact in {
        entry.get("id")
        for entry in impact
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }


def _maintenance_path(root: Path) -> Path:
    return _common_graph_dir(root) / "state" / "maintenance.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _maintenance_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise EngineeringError("Engineering maintenance timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EngineeringError("Engineering maintenance timestamp is invalid.") from error
    if parsed.tzinfo is None:
        raise EngineeringError("Engineering maintenance timestamp is invalid.")
    return parsed.astimezone(timezone.utc)


def _validate_maintenance_times(item: dict) -> tuple[str, str, str | None]:
    created_at = item.get("created_at", _utc_now())
    last_seen_at = item.get("last_seen_at", created_at)
    escalated_at = item.get("escalated_at")
    created = _maintenance_time(created_at)
    last_seen = _maintenance_time(last_seen_at)
    escalated = (
        _maintenance_time(escalated_at) if escalated_at is not None else None
    )
    future_limit = datetime.now(timezone.utc) + timedelta(minutes=5)
    if (
        created > future_limit
        or last_seen > future_limit
        or last_seen < created
        or (escalated is not None and (escalated > future_limit or escalated < created))
    ):
        raise EngineeringError("Engineering maintenance timestamp is invalid.")
    return created_at, last_seen_at, escalated_at


def _bounded_maintenance_artifact(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 512:
        return None
    artifact = value.replace("\\", "/")
    if artifact in {"checkpoint", "legacy-graph-output"}:
        return artifact
    if (
        any(ord(character) < 32 or ord(character) == 127 for character in artifact)
        or ":" in artifact
        or "?" in artifact
        or "#" in artifact
        or "=" in artifact
        or _contains_credential(artifact)
    ):
        return None
    path = PurePosixPath(artifact)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def _checkpoint_target(root: Path, operation: dict, commit: str | None = None) -> dict:
    origin_commit = commit or operation.get("commit")
    if not isinstance(origin_commit, str) or not re.fullmatch(
        r"[0-9a-f]{40}", origin_commit
    ):
        origin_commit = git(root, "rev-parse", "HEAD")
    branch = operation.get("branch")
    if not isinstance(branch, str) or not branch:
        try:
            branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        except EngineeringError:
            branch = f"detached/{origin_commit}"
    branch = branch.replace("\\", "/").strip("/")
    if not branch:
        raise EngineeringError("Engineering checkpoint maintenance target is invalid.")
    repository = str(_trusted_common_dirs(root)[1])
    lineage = hashlib.sha256(
        json.dumps([repository, branch], separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    run_identity = operation.get("run_id")
    if not isinstance(run_identity, str) or not run_identity:
        run_identity = f"checkpoint/{origin_commit}"
    origin_run = hashlib.sha256(
        json.dumps([lineage, run_identity], separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "lineage": f"lineage-{lineage}",
        "origin_commit": origin_commit,
        "origin_run": f"origin-{origin_run}",
    }


def _normalize_maintenance_target(value: object) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "lineage",
        "origin_commit",
        "origin_run",
    }:
        raise EngineeringError("Engineering checkpoint maintenance target is invalid.")
    if (
        not isinstance(value["lineage"], str)
        or not re.fullmatch(r"lineage-[0-9a-f]{24}", value["lineage"])
        or not isinstance(value["origin_commit"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", value["origin_commit"])
        or not isinstance(value["origin_run"], str)
        or not re.fullmatch(r"origin-[0-9a-f]{24}", value["origin_run"])
    ):
        raise EngineeringError("Engineering checkpoint maintenance target is invalid.")
    return dict(value)


def _target_maintenance_item(root: Path, item: dict, operation: dict) -> dict:
    if not isinstance(item, dict):
        raise EngineeringError("Engineering maintenance item is invalid.")
    targeted = dict(item)
    is_checkpoint = (
        targeted.get("kind", "stale_artifact") == "checkpoint_stale"
        and targeted.get("artifact") == "checkpoint"
    )
    if is_checkpoint and "target" not in targeted:
        targeted["target"] = _checkpoint_target(root, operation)
    elif not is_checkpoint and targeted.get("target") is not None:
        raise EngineeringError("Engineering maintenance item target is invalid.")
    return targeted


def _is_ancestor_or_equal(
    root: Path, ancestor: object, descendant: object
) -> bool:
    if (
        not isinstance(ancestor, str)
        or not re.fullmatch(r"[0-9a-f]{40}", ancestor)
        or not isinstance(descendant, str)
        or not re.fullmatch(r"[0-9a-f]{40}", descendant)
    ):
        return False
    return (
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
            ],
            capture_output=True,
            text=True,
            env=_controller_git_environment(),
        ).returncode
        == 0
    )


def _maintenance_identity(item: dict) -> str:
    return "maintenance-" + hashlib.sha256(
        json.dumps(
            [item["kind"], item["area"], item["artifact"], item["target"]],
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]


def _normalize_maintenance_item(item: dict) -> dict:
    if not isinstance(item, dict):
        raise EngineeringError("Engineering maintenance item is invalid.")
    area = item.get("area")
    artifact = _bounded_maintenance_artifact(item.get("artifact"))
    kind = item.get("kind", "stale_artifact")
    impact = item.get("impact", "routine")
    if (
        not isinstance(area, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", area)
        or ".." in Path(area).parts
        or artifact is None
        or not isinstance(kind, str)
        or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", kind)
        or impact not in MAINTENANCE_IMPACT
        or any(_contains_credential(value) for value in (area, artifact, kind))
    ):
        raise EngineeringError("Engineering maintenance item is invalid.")
    created_at, last_seen_at, escalated_at = _validate_maintenance_times(item)
    target = _normalize_maintenance_target(item.get("target"))
    is_checkpoint = kind == "checkpoint_stale" and artifact == "checkpoint"
    if not is_checkpoint and target is not None:
        raise EngineeringError("Engineering maintenance item target is invalid.")
    mechanically_safe = (
        is_checkpoint and target is not None
    ) or (
        kind == "legacy_graph_generated"
        and Path(artifact).name == "graphify-out"
    )
    normalized = {
        "id": "",
        "area": area,
        "artifact": artifact,
        "kind": kind,
        "impact": impact,
        "safe": mechanically_safe and impact == "routine",
        "target": target,
        "created_at": created_at,
        "last_seen_at": last_seen_at,
        "escalated_at": escalated_at,
    }
    normalized["id"] = _maintenance_identity(normalized)
    if item.get("id") not in (None, normalized["id"]):
        raise EngineeringError("Engineering maintenance item identity is invalid.")
    return normalized


def _load_maintenance(root: Path) -> dict:
    path = _maintenance_path(root)
    if not path.is_file():
        return {"schema": "engineering.maintenance.v1", "items": [], "history": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering maintenance state is invalid.") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "items", "history"}
        or payload.get("schema") != "engineering.maintenance.v1"
        or not isinstance(payload.get("items"), list)
        or not isinstance(payload.get("history"), list)
    ):
        raise EngineeringError("Engineering maintenance state is invalid.")
    item_keys = {
        "id",
        "area",
        "artifact",
        "kind",
        "impact",
        "safe",
        "target",
        "created_at",
        "last_seen_at",
        "escalated_at",
    }
    if any(
        not isinstance(item, dict)
        or set(item) != item_keys
        or not isinstance(item.get("safe"), bool)
        for item in payload["items"]
    ):
        raise EngineeringError("Engineering maintenance state is invalid.")
    try:
        items = [_normalize_maintenance_item(item) for item in payload["items"]]
    except EngineeringError as error:
        raise EngineeringError("Engineering maintenance state is invalid.") from error
    if any(
        raw["safe"] != normalized["safe"]
        for raw, normalized in zip(payload["items"], items, strict=True)
    ):
        raise EngineeringError("Engineering maintenance state is invalid.")
    if len({item["id"] for item in items}) != len(items):
        raise EngineeringError("Engineering maintenance state has duplicate items.")
    history = payload["history"]
    if any(
        not isinstance(entry, dict)
        or set(entry) != {"id", "completed_at"}
        or not isinstance(entry["id"], str)
        or not re.fullmatch(r"maintenance-[0-9a-f]{12}", entry["id"])
        for entry in history
    ):
        raise EngineeringError("Engineering maintenance history is invalid.")
    for entry in history:
        completed = _maintenance_time(entry["completed_at"])
        if completed > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise EngineeringError("Engineering maintenance history is invalid.")
    return {"schema": payload["schema"], "items": items, "history": history}


def _write_maintenance(root: Path, payload: dict) -> None:
    path = _maintenance_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_text(path, json.dumps(payload, indent=2) + "\n")


def _assert_maintenance_lock(root: Path, operation: dict) -> None:
    owner = _lock_owner(operation)
    if owner is None or (
        owner.get("operation_id") != operation.get("operation_id")
        or owner.get("lock_token") != operation.get("lock_token")
    ):
        raise EngineeringError("Engineering maintenance requires the repository lock.")


def _queue_maintenance_locked(
    root: Path, items: list[dict], operation: dict
) -> list[dict]:
    return _mutate_maintenance_locked(root, items, operation)["queued"]


def _mutate_maintenance_locked(
    root: Path,
    items: list[dict],
    operation: dict,
    *,
    resolved_checkpoint: str | None = None,
) -> dict:
    project_root = resolve_project_root(str(root))
    _assert_maintenance_lock(project_root, operation)
    candidates = [
        _normalize_maintenance_item(
            _target_maintenance_item(project_root, item, operation)
        )
        for item in items
    ]
    payload = _load_maintenance(project_root)
    by_id = {entry["id"]: entry for entry in payload["items"]}
    rank = {"routine": 0, "blocking": 1, "ambiguous": 2, "consequential": 3}
    changed = False
    results = []
    for candidate in candidates:
        current = by_id.get(candidate["id"])
        if current is None:
            payload["items"].append(candidate)
            by_id[candidate["id"]] = candidate
            current = candidate
            changed = True
        elif rank[candidate["impact"]] > rank[current["impact"]]:
            current.update(
                impact=candidate["impact"],
                last_seen_at=candidate["last_seen_at"],
            )
            current["safe"] = _normalize_maintenance_item(current)["safe"]
            changed = True
        results.append(dict(current))
    resolved = []
    if resolved_checkpoint is not None:
        checkpoint = _checkpoint_path(project_root, resolved_checkpoint)
        if not validate_checkpoint(project_root, checkpoint, resolved_checkpoint)["valid"]:
            raise EngineeringError(
                "Engineering checkpoint maintenance resolution lacks exact evidence."
            )
        publication = _checkpoint_target(
            project_root, operation, resolved_checkpoint
        )
        remaining = []
        for current in payload["items"]:
            target = current.get("target")
            resolves = (
                current["kind"] == "checkpoint_stale"
                and current["artifact"] == "checkpoint"
                and isinstance(target, dict)
                and target.get("lineage") == publication["lineage"]
                and _is_ancestor_or_equal(
                    project_root,
                    target.get("origin_commit"),
                    resolved_checkpoint,
                )
            )
            if resolves:
                resolved.append(current["id"])
                payload["history"].append(
                    {"id": current["id"], "completed_at": _utc_now()}
                )
                changed = True
            else:
                remaining.append(current)
        payload["items"] = remaining
        payload["history"] = payload["history"][-100:]
    if changed:
        payload["items"].sort(key=lambda entry: entry["id"])
        _write_maintenance(project_root, payload)
    return {"queued": results, "resolved": sorted(resolved)}


def _prospective_maintenance_ids(
    root: Path, items: list[dict], operation: dict
) -> list[str]:
    return sorted(
        {
            _normalize_maintenance_item(
                _target_maintenance_item(root, item, operation)
            )["id"]
            for item in items
        }
    )


def _maintenance_snapshot(root: Path) -> bytes | None:
    path = _maintenance_path(root)
    return path.read_bytes() if path.is_file() else None


def _restore_maintenance(root: Path, snapshot: bytes | None) -> None:
    path = _maintenance_path(root)
    if snapshot is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_bytes(path, snapshot)


def queue_maintenance(root: Path, item: dict) -> dict:
    project_root = resolve_project_root(str(root))
    operation = _begin_completion(project_root, "maintenance-queue")
    try:
        return _queue_maintenance_locked(project_root, [item], operation)[0]
    finally:
        _end_completion(project_root, operation)


def _maintenance_age_days(item: dict, now: datetime) -> int:
    return max(0, (now - _maintenance_time(item["created_at"])).days)


def _maintenance_summary(payload: dict, newly_escalated: int = 0) -> dict:
    now = datetime.now(timezone.utc)
    items = []
    groups: dict[str, dict] = {}
    rank = {"routine": 0, "blocking": 1, "ambiguous": 2, "consequential": 3}
    for item in payload["items"]:
        age = _maintenance_age_days(item, now)
        items.append(
            {
                key: item[key]
                for key in ("id", "area", "artifact", "kind", "impact", "safe")
            }
            | {"age_days": age}
        )
        group = groups.setdefault(
            item["area"],
            {
                "area": item["area"],
                "pending": 0,
                "safe": 0,
                "blocked": 0,
                "aged": 0,
                "oldest_days": 0,
                "highest_impact": "routine",
            },
        )
        group["pending"] += 1
        group["safe" if item["safe"] else "blocked"] += 1
        group["aged"] += int(age >= MAINTENANCE_AGING_DAYS)
        group["oldest_days"] = max(group["oldest_days"], age)
        if rank[item["impact"]] > rank[group["highest_impact"]]:
            group["highest_impact"] = item["impact"]
    counts = {
        "pending": len(items),
        "safe": sum(item["safe"] for item in items),
        "blocked": sum(not item["safe"] for item in items),
        "aged": sum(item["age_days"] >= MAINTENANCE_AGING_DAYS for item in items),
        "consequential": sum(item["impact"] == "consequential" for item in items),
        "ambiguous": sum(item["impact"] == "ambiguous" for item in items),
    }
    return {
        "schema": "engineering.maintenance.status.v1",
        "counts": counts,
        "groups": [groups[key] for key in sorted(groups)],
        "items": sorted(items, key=lambda item: item["id"]),
        "newly_escalated": newly_escalated,
        "background": False,
        "message": (
            f"Engineering maintenance: {counts['pending']} queued artifact(s). "
            "Run `engineering maintain` once to repair safe items; blocked items "
            "still require review. The command does not change autonomy."
            if items
            else "Engineering maintenance: no queued artifacts."
        ),
    }


def maintenance_status(root: Path) -> dict:
    project_root = resolve_project_root(str(root))
    payload = _load_maintenance(project_root)
    now = datetime.now(timezone.utc)
    if not any(
        _maintenance_age_days(item, now) >= MAINTENANCE_AGING_DAYS
        and item["escalated_at"] is None
        for item in payload["items"]
    ):
        return _maintenance_summary(payload)
    operation = _begin_completion(project_root, "maintenance-status")
    try:
        payload = _load_maintenance(project_root)
        now = datetime.now(timezone.utc)
        newly_escalated = 0
        for item in payload["items"]:
            if (
                _maintenance_age_days(item, now) >= MAINTENANCE_AGING_DAYS
                and item["escalated_at"] is None
            ):
                item["escalated_at"] = _utc_now()
                newly_escalated += 1
        if newly_escalated:
            _write_maintenance(project_root, payload)
        return _maintenance_summary(payload, newly_escalated)
    finally:
        _end_completion(project_root, operation)


def _process_safe_maintenance(
    root: Path, item: dict, operation: dict
) -> bool | None:
    if item["kind"] == "checkpoint_stale" and item["artifact"] == "checkpoint":
        target = item.get("target")
        publication = _checkpoint_target(root, operation)
        if (
            not isinstance(target, dict)
            or target.get("lineage") != publication["lineage"]
            or not _is_ancestor_or_equal(
                root,
                target.get("origin_commit"),
                publication["origin_commit"],
            )
        ):
            return None
        return check_merge_readiness(root)["ready"]
    if item["kind"] == "legacy_graph_generated":
        return clean_legacy_output(root, root / item["artifact"])
    return False


def run_maintenance(root: Path, area: str | None = None) -> dict:
    project_root = resolve_project_root(str(root))
    if area is not None and (
        not isinstance(area, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", area)
        or ".." in Path(area).parts
    ):
        raise EngineeringError("Engineering maintenance area is invalid.")
    operation = _begin_completion(project_root, "maintenance-run")
    try:
        payload = _load_maintenance(project_root)
        remaining = []
        processed = []
        blocked = 0
        for item in payload["items"]:
            if area is not None and item["area"] != area:
                remaining.append(item)
                continue
            if not item["safe"]:
                blocked += 1
                remaining.append(item)
                continue
            processed_item = _process_safe_maintenance(
                project_root, item, operation
            )
            if processed_item is None:
                blocked += 1
                remaining.append(item)
                continue
            if not processed_item:
                item.update(impact="blocking", safe=False, last_seen_at=_utc_now())
                blocked += 1
                remaining.append(item)
                continue
            processed.append(item["id"])
            payload["history"].append(
                {"id": item["id"], "completed_at": _utc_now()}
            )
        payload["items"] = remaining
        payload["history"] = payload["history"][-100:]
        _write_maintenance(project_root, payload)
        return {
            "schema": "engineering.maintenance.run.v1",
            "area": area,
            "processed": len(processed),
            "processed_ids": sorted(processed),
            "blocked": blocked,
            "remaining": len(remaining),
            "background": False,
            "autonomy": get_autonomy(project_root),
        }
    finally:
        _end_completion(project_root, operation)


def _contract_change_approved(root: Path, commit: str, manifest: dict, scope: dict) -> bool:
    """A caller boolean never approves a persisted contract; its ledger remains authority."""
    approval = scope.get("contract_approval_id")
    if not isinstance(approval, str):
        return False
    decisions = _ledger_decisions(root, commit, manifest)
    line = decisions.get(approval)
    if line is None:
        return False
    ledger = _text_at(root, commit, decision_ledger_path(root, manifest)).splitlines()
    selected = ledger[line - 1]
    if selected.lstrip().startswith("|"):
        cells = [cell.strip().strip("*") for cell in selected.strip().strip("|").split("|")]
        block_start = line - 1
        while block_start > 0 and ledger[block_start - 1].lstrip().startswith("|"):
            block_start -= 1
        block = ledger[block_start:]
        if len(block) < 2:
            return False
        headers = [cell.strip().strip("*").casefold() for cell in block[0].strip().strip("|").split("|")]
        separator = [cell.strip() for cell in block[1].strip().strip("|").split("|")]
        if len(separator) != len(headers) or any(
            re.fullmatch(r":?-{3,}:?", cell) is None for cell in separator
        ) or headers.count("status") != 1:
            return False
        status_index = headers.index("status")
        return (
            cells[0] == approval
            and status_index < len(cells)
            and cells[status_index].casefold() == "approved"
        )
    entry = ledger[line - 1 :]
    for index, candidate in enumerate(entry[1:], start=1):
        if re.match(r"^#{1,6}\s+[A-Z][A-Z0-9_-]*-DEC-\d+\b", candidate):
            entry = entry[:index]
            break
    status = re.compile(
        r"(?i)^\s*(?:[-*]\s*)?(?:\*\*)?status(?:\*\*)?\s*:\s*(.*?)\s*$"
    )
    values = [
        match.group(1).rstrip(".").strip().casefold()
        for candidate in entry
        if (match := status.fullmatch(candidate))
    ]
    return values == ["approved"]


def _recover_initial_checkpoint(project: ProjectIdentity) -> dict:
    """Build canonical first, then an isolated feature checkpoint when needed."""
    try:
        canonical = bootstrap_graph(
            project.root,
            setup_authorized=True,
            graphify_python=sys.executable,
            recovery_timeout_seconds=DEFAULT_INITIAL_CHECKPOINT_RECOVERY_SECONDS,
        )
        if canonical.get("state") != "current" or not canonical.get("checkpoint"):
            return {"recovered": False, "reason": str(canonical.get("reason", "checkpoint_pending"))}
        if project.branch == project.default_branch:
            return {"recovered": True, "checkpoint": canonical["checkpoint"]}
        result = rebuild(project.root, sys.executable, target_commit=project.commit)
    except EngineeringError as error:
        return {"recovered": False, "reason": str(error)[:160]}
    if result.get("freshness") == "current" and result.get("checkpoint"):
        return {"recovered": True, "checkpoint": result.get("checkpoint")}
    return {"recovered": False, "reason": str(result.get("reason", "checkpoint_pending"))}


def _unmanaged_preparation(root: Path, intent: str, scope: dict, override: str | None) -> dict:
    """Give adoptable projects a no-write readiness result, never a fake run."""
    project_root = resolve_project_root(str(root))
    authorization = _scope_envelope(scope)
    change_class = _material_change_class(intent, scope)
    if change_class is not None:
        authorization["change_class"] = change_class
    if "scope_handoff" in authorization:
        raise EngineeringError(
            "Preparation scope handoff requires an adopted project decision ledger."
        )
    autonomy = override or DEFAULT_AUTONOMY
    if autonomy not in AUTONOMY_LEVELS:
        raise EngineeringError(f"Invalid Engineering autonomy: {autonomy}")
    checks = discover_checks(project_root)
    check_authority = None
    advisories = [
        "Engineering controls are not tracked in this checkout; traceability and capability status are unknown.",
        "Setup remains a separate approved project-control action; no files or controller state were written.",
    ]
    if checks and "task_authority" in authorization:
        check_authority = validate_task_check_authority(
            project_root, authorization["task_authority"], _check_capability_claims(project_root, checks)
        )
    elif checks:
        advisories.append("Project-native check authority remains outside Engineering until controls are adopted.")
    return {
        "schema": "engineering.prepare.v1",
        "run_id": None,
        "project": {"commit": git(project_root, "rev-parse", "HEAD"), "traceability": "unknown"},
        "intent": _intent_projection(_bounded_intent(intent)),
        "authorization": authorization,
        "autonomy": autonomy,
        "readiness": "advisory",
        "blockers": [],
        "advisories": advisories,
        "context": [],
        "impact": [],
        "required_checks": checks,
        "check_authority": check_authority,
        "completion_available": False,
        "outcome_survival": {
            "state": "unknown",
            "boundary": "unmanaged_project",
            "accepted": False,
            "implementation_ready": False,
            "missing_baseline_mappings": (
                ["canonical_baseline_unavailable"] if change_class is not None else []
            ),
            "approval_boundary": "adopted_decision_ledger_and_checkpoint_required",
        },
    }


def prepare(
    root: Path, intent: str, scope: dict, override: str | None = None
) -> dict:
    if _tracked_manifest_name(resolve_project_root(str(root))) is None:
        return _unmanaged_preparation(root, intent, scope, override)
    project = resolve_project(Path(root))
    bounded_intent = _bounded_intent(intent)
    authorization = _scope_envelope(scope)
    change_class = _material_change_class(intent, scope)
    if change_class is not None:
        authorization["change_class"] = change_class
    config = load_project_config(project.root)
    if "scope_handoff" in authorization:
        authorization["scope_handoff"] = _validate_scope_handoff_authority(
            project.root, project.commit, config, authorization["scope_handoff"]
        )
    saved_autonomy = get_autonomy(project.root)
    autonomy = override or saved_autonomy
    if autonomy not in AUTONOMY_LEVELS:
        raise EngineeringError(f"Invalid Engineering autonomy: {autonomy}")

    if autonomy == "steward" and _maintenance_pending(project.root):
        run_maintenance(project.root, None)

    required_checks = discover_checks(project.root)
    blocker_codes: list[str] = []
    advisory_codes: list[str] = []
    checkpoint: dict = {"nodes": [], "edges": []}
    checkpoint_path: Path | None = None
    readiness = check_merge_readiness(project.root)
    if readiness["ready"]:
        checkpoint_path = Path(readiness["checkpoint"])
        checkpoint = _load_checkpoint(project.root, project.commit)
    else:
        recovered = _recover_initial_checkpoint(project)
        readiness = check_merge_readiness(project.root)
        if readiness["ready"]:
            checkpoint_path = Path(readiness["checkpoint"])
            checkpoint = _load_checkpoint(project.root, project.commit)
            advisory_codes.append("checkpoint_recovered")
        else:
            blocker_codes.append("checkpoint_pending")

    scope_handoff = authorization.get("scope_handoff")
    survival_mapping = (
        scope_handoff.get("outcome_survival")
        if isinstance(scope_handoff, dict)
        else None
    )
    if change_class is not None and survival_mapping is None:
        blocker_codes.append("outcome_survival_incomplete")

    nodes = {node["id"]: node for node in checkpoint["nodes"]}
    matrix_issues = _semantic_matrix_issues(config, checkpoint["nodes"], set(authorization["scope"]))
    if matrix_issues:
        blocker_codes.append("semantic_matrix_incomplete")
    explicit, missing = _explicit_context_ids(bounded_intent, scope, nodes)
    if missing:
        blocker_codes.append("missing_required_source")
    context = [{"id": identifier, "provenance": "direct"} for identifier in explicit]
    context_config = config.get("context")
    token_budget = (
        context_config.get("token_budget")
        if isinstance(context_config, dict) and "token_budget" in context_config
        else DEFAULT_CONTEXT_TOKEN_BUDGET
    )
    if isinstance(token_budget, bool) or not isinstance(token_budget, int) or token_budget < 0 or token_budget > 4096:
        raise EngineeringError("Engineering context.token_budget must be an integer from 0 to 4096.")
    query_outcome = (
        _graphify_query_context(bounded_intent, checkpoint_path, token_budget)
        if checkpoint_path is not None
        else {"status": "unavailable", "context": [], "reason": "checkpoint_unavailable"}
    )
    task_check_authority = None
    if "task_authority" in authorization:
        task_check_authority = validate_task_check_authority(
            project.root, authorization["task_authority"],
            _check_capability_claims(project.root, required_checks),
        )
    if query_outcome["status"] in {"unavailable", "invalid"} and task_check_authority is None:
        blocker_codes.append("missing_required_source")
    query_ids = [item["id"] for item in query_outcome["context"]]
    selected_ids = list(dict.fromkeys([*explicit, *query_ids]))
    context.extend(query_outcome["context"])
    context.extend(
        {"id": identifier, "provenance": "direct"}
        for identifier in query_ids
        if identifier in nodes
    )
    context.extend(_exact_context_neighbours(checkpoint, selected_ids))
    context = _merge_context(context)

    impact = _context_impact(checkpoint, selected_ids)
    intent_artifact_paths = list(authorization["scope"])
    if isinstance(scope_handoff, dict):
        intent_artifact_paths.extend(scope_handoff["result_artifacts"])
    intent_impact = _intent_impacting(
        checkpoint,
        selected_ids,
        change_class,
        scope_handoff,
        artifact_paths=intent_artifact_paths,
    )
    owner_intent_projection = None
    if intent_impact:
        try:
            status = owner_intent_status(project.root)
            handoff_survival = (
                scope_handoff.get("outcome_survival")
                if isinstance(scope_handoff, dict)
                else None
            )
            bound_to_handoff = bool(
                isinstance(handoff_survival, dict)
                and handoff_survival.get("schema") == OUTCOME_SURVIVAL_V2_SCHEMA
                and status["state"] == "bound"
                and handoff_survival.get("owner_intent_id") == status["intent_id"]
                and handoff_survival.get("owner_intent_digest")
                == status["owner_intent_digest"]
            )
            owner_intent_projection = {
                **status,
                "intent_impacting": True,
                "bound_to_scope_handoff": bound_to_handoff,
            }
        except EngineeringError:
            owner_intent_projection = {
                "schema": OWNER_INTENT_STATUS_SCHEMA,
                "state": "owner_intent_unknown",
                "intent_id": None,
                "owner_intent_digest": None,
                "authority_epoch": None,
                "core_outcome_count": 0,
                "intent_impacting": True,
                "bound_to_scope_handoff": False,
            }
        if not owner_intent_projection["bound_to_scope_handoff"]:
            blocker_codes.append("owner_intent_required")
    contract_impact = any(
        item["provenance"] in EXACT_PROVENANCE
        and nodes.get(item["id"], {}).get("type") == "contract"
        for item in context
    )
    required_sources = scope.get("required_sources", [])
    if not isinstance(required_sources, list) or any(
        not isinstance(path, str)
        or Path(path).is_absolute()
        or ".." in Path(path).parts
        or not (project.root / path).is_file()
        for path in required_sources
    ):
        blocker_codes.append("missing_required_source")
    required_source_paths = (
        {
            path.replace("\\", "/")
            for path in required_sources
            if isinstance(path, str)
        }
        if isinstance(required_sources, list)
        else set()
    )
    exact_node_ids = {
        endpoint
        for edge in _exact_edges(checkpoint)
        for endpoint in (edge["from"], edge["to"])
    }
    selected_overlay_ids = [identifier for identifier in selected_ids if identifier in nodes]
    if any(identifier not in exact_node_ids for identifier in selected_overlay_ids):
        blocker_codes.append("missing_required_source")
    if query_ids and not selected_overlay_ids:
        blocker_codes.append("missing_required_source")
    if not any(item["provenance"] in EXACT_PROVENANCE for item in context) and not impact:
        blocker_codes.append("missing_required_source")
    dirty = _dirty_paths(project.root)
    if any(path not in authorization["scope"] for path in dirty):
        blocker_codes.append("conflicting_authority")
    if contract_impact and not _contract_change_approved(project.root, project.commit, config, scope):
        blocker_codes.append("unapproved_contract_change")
    if any(
        re.search(rf"\b{re.escape(action)}\b", bounded_intent, re.IGNORECASE)
        for action in authorization["forbidden"]
    ):
        blocker_codes.append("conflicting_authority")
    check_authority = task_check_authority
    if required_checks:
        try:
            claims = _check_capability_claims(project.root, required_checks)
            if task_check_authority is not None:
                check_authority = task_check_authority
            else:
                _require_attestation(
                    _project_controller_dir(project.root), "check_capability", claims
                )
                check_authority = {"mode": "legacy_attestation", "commands_digest": claims["commands_digest"]}
        except EngineeringError:
            if "task_authority" in authorization:
                raise
            blocker_codes.append("unapproved_check_capability")

    try:
        authority = _canonical_authority_details(project.root, refresh_remote=False)
        if authority["freshness"] == "unknown":
            advisory_codes.append("remote_freshness_unknown")
    except EngineeringError:
        blocker_codes.append("ambiguous_project")
    baseline = config.get("baseline")
    if isinstance(baseline, dict) and baseline.get("accepted") is False:
        advisory_codes.append("historical_gap_before_baseline_acceptance")
    maintenance = (
        maintenance_status(project.root)
        if _maintenance_pending(project.root)
        else None
    )
    if maintenance is not None and maintenance["counts"]["pending"]:
        advisory_codes.append("unrelated_maintenance")
        if any(
            _maintenance_blocks_preparation(
                item,
                required_sources=required_source_paths,
                impact=impact,
            )
            for item in maintenance["items"]
        ):
            blocker_codes.append("conflicting_authority")

    blocker_codes = list(dict.fromkeys(blocker_codes))
    advisory_codes = list(dict.fromkeys(advisory_codes))
    applied_practices, practice_status = _practice_projection("preparation")
    completion_practices, completion_practice_status = _practice_projection("completion")
    outcome_projection = None
    if change_class is not None:
        if survival_mapping is None:
            outcome_projection = {
                "state": "blocked",
                "boundary": "baseline_outcome_mapping_missing",
                "accepted": False,
                "implementation_ready": False,
                "missing_baseline_mappings": ["baseline_reconstruction_required"],
                "approval_boundary": "signed_scope_handoff_required",
            }
        elif checkpoint_path is None:
            outcome_projection = {
                "state": "unknown",
                "boundary": "canonical_checkpoint_unavailable",
                "accepted": False,
                "implementation_ready": False,
                "missing_baseline_mappings": survival_mapping["baseline_ids"],
                "approval_boundary": "current_checkpoint_required",
                "mappings": survival_mapping["mappings"],
            }
        elif any(
            code in blocker_codes
            for code in (
                "ambiguous_project",
                "conflicting_authority",
                "missing_required_source",
                "checkpoint_pending",
            )
        ):
            boundary = next(
                code
                for code in (
                    "ambiguous_project",
                    "conflicting_authority",
                    "missing_required_source",
                    "checkpoint_pending",
                )
                if code in blocker_codes
            )
            outcome_projection = {
                "state": "unknown",
                "boundary": boundary,
                "accepted": False,
                "implementation_ready": False,
                "missing_baseline_mappings": [],
                "approval_boundary": "current_traceability_required",
                "mappings": survival_mapping["mappings"],
            }
        else:
            outcome_projection = {
                "state": "mapped",
                "boundary": "independent_outcome_acceptance_required",
                "accepted": False,
                "implementation_ready": not blocker_codes,
                "missing_baseline_mappings": [],
                "approval_boundary": "signed_scope_handoff_verified",
                "mappings": survival_mapping["mappings"],
            }
    if (
        intent_impact
        and owner_intent_projection is not None
        and not owner_intent_projection["bound_to_scope_handoff"]
    ):
        outcome_projection = {
            "state": "unknown",
            "boundary": "owner_intent_unknown",
            "accepted": False,
            "implementation_ready": False,
            "missing_baseline_mappings": [],
            "approval_boundary": "external_owner_intent_required",
            "mappings": (
                survival_mapping.get("mappings", [])
                if isinstance(survival_mapping, dict)
                else []
            ),
        }
    result = {
        "schema": "engineering.prepare.v1",
        "run_id": "",
        "project": {
            "root_digest": f"sha256:{checkpoint_identity(project.root, project.commit)}",
            "branch": project.branch,
            "commit": project.commit,
        },
        "intent": _intent_projection(bounded_intent),
        "authorization": authorization,
        "autonomy": autonomy,
        "readiness": (
            "blocked"
            if blocker_codes
            else "ready_with_advisories" if advisory_codes else "ready"
        ),
        "blockers": [PREPARATION_BLOCKERS[code] for code in blocker_codes],
        "advisories": [
            (
                maintenance["message"]
                if code == "unrelated_maintenance"
                and autonomy == "collaborative"
                and maintenance is not None
                else PREPARATION_ADVISORIES[code]
            )
            for code in advisory_codes
        ],
        "context": context,
        "impact": impact,
        "required_checks": required_checks,
        "check_authority": check_authority,
    }
    if outcome_projection is not None:
        result["outcome_survival"] = outcome_projection
    if owner_intent_projection is not None:
        result["owner_intent"] = owner_intent_projection
    if applied_practices:
        result["applied_practices"] = applied_practices
    if practice_status is not None:
        result["practice_status"] = practice_status
    if completion_practices:
        result["completion_applied_practices"] = completion_practices
    if completion_practice_status is not None:
        result["completion_practice_status"] = completion_practice_status
    digest_input = {key: value for key, value in result.items() if key != "run_id"}
    result["run_id"] = "run-" + hashlib.sha256(
        json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:6]
    path = _common_graph_dir(project.root) / "runs" / result["run_id"] / "preparation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != result:
                raise EngineeringError("Preparation run identifier collision.")
            return existing
        except json.JSONDecodeError as error:
            raise EngineeringError("Invalid retained preparation metadata.") from error
    _atomic_text(path, json.dumps(result, indent=2) + "\n")
    return result


def _check_identity(argv: list[str]) -> str:
    if not isinstance(argv, list) or not argv or any(
        not isinstance(argument, str) or not argument for argument in argv
    ):
        raise EngineeringError("Engineering check argv is invalid.")
    return "sha256:" + hashlib.sha256(
        json.dumps(argv, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _contains_inline_code(argv: list[str]) -> bool:
    executable = Path(argv[0]).name.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if executable.endswith(suffix):
            executable = executable[: -len(suffix)]
            break
    arguments = argv[1:]
    lowered = [argument.lower() for argument in arguments]
    current_python = Path(sys.executable).stem.lower()
    python_family = executable == "py" or bool(
        re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", executable)
    ) or executable == current_python
    if python_family:
        mode = list(lowered)
        if executable == "py" and mode and re.fullmatch(r"-\d+(?:\.\d+)?", mode[0]):
            mode = mode[1:]
        if not mode:
            raise EngineeringError("Engineering Python check uses an unclassified interpreter mode.")
        first = mode[0]
        if first == "-c" or first.startswith("-c"):
            return True
        if first in {"-v", "--version", "-h", "--help"}:
            return False
        if first == "-m" and len(mode) > 1:
            return False
        if not first.startswith("-"):
            return False
        raise EngineeringError("Engineering Python check uses an unclassified interpreter mode.")
    if re.fullmatch(r"node(?:\d+(?:\.\d+)*)?", executable):
        if not lowered:
            raise EngineeringError("Engineering Node check uses an unclassified interpreter mode.")
        first = lowered[0]
        inline = ("-e", "--eval", "-p", "--print")
        if any(
            first == prefix
            or first.startswith(prefix + "=")
            or (prefix in {"-e", "-p"} and first.startswith(prefix) and first != prefix)
            for prefix in inline
        ):
            return True
        if first in {"-v", "--version", "-h", "--help", "--test"}:
            return False
        if not first.startswith("-"):
            return False
        raise EngineeringError("Engineering Node check uses an unclassified interpreter mode.")
    if re.fullmatch(r"(?:powershell|pwsh)(?:\d+(?:\.\d+)*)?", executable):
        if not lowered:
            raise EngineeringError("Engineering PowerShell check uses an unclassified interpreter mode.")
        inline = ("-command", "-c", "-encodedcommand", "-enc")
        if any(
            argument == prefix
            or argument.startswith(prefix + "=")
            or argument.startswith(prefix + ":")
            or (prefix in {"-c", "-enc"} and argument.startswith(prefix) and argument != prefix)
            for argument in lowered
            for prefix in inline
        ):
            return True
        if any(
            argument in {"-file", "-f"} and index + 1 < len(lowered)
            for index, argument in enumerate(lowered)
        ):
            return False
        if lowered[0] in {"-v", "--version", "-h", "--help", "-help"}:
            return False
        raise EngineeringError("Engineering PowerShell check uses an unclassified interpreter mode.")
    if executable == "cmd":
        if lowered and (lowered[0].startswith("/c") or lowered[0].startswith("/k")):
            return True
        if lowered and lowered[0] in {"/?", "--help"}:
            return False
        raise EngineeringError("Engineering cmd check uses an unclassified interpreter mode.")
    if re.fullmatch(r"(?:sh|bash|zsh|ksh|dash)(?:\d+(?:\.\d+)*)?", executable):
        if not lowered:
            raise EngineeringError("Engineering shell check uses an unclassified interpreter mode.")
        first = lowered[0]
        if first == "-c" or first.startswith("-c"):
            return True
        if first in {"--version", "--help"} or not first.startswith("-"):
            return False
        raise EngineeringError("Engineering shell check uses an unclassified interpreter mode.")
    if re.fullmatch(r"(?:ruby|perl)(?:\d+(?:\.\d+)*)?", executable):
        if not lowered:
            raise EngineeringError("Engineering Ruby/Perl check uses an unclassified interpreter mode.")
        first = lowered[0]
        inline_flags = ("-e",) if executable.startswith("ruby") else ("-e", "-E")
        if any(first == flag.lower() or first.startswith(flag.lower()) for flag in inline_flags):
            return True
        if first in {"-v", "--version", "-h", "--help"} or not first.startswith("-"):
            return False
        raise EngineeringError("Engineering Ruby/Perl check uses an unclassified interpreter mode.")
    return False


def _check_capability_claims(root: Path, checks: list[list[str]]) -> dict:
    if any(_contains_credential(argument) for argv in checks for argument in argv):
        raise EngineeringError("Engineering check capability contains credential-shaped data.")
    identities = [_check_identity(argv) for argv in checks]
    inline_code = any(_contains_inline_code(argv) for argv in checks)
    shell = any(
        re.fullmatch(
            r"(?:sh|bash|zsh|ksh|dash|cmd|powershell|pwsh)(?:\d+(?:\.\d+)*)?",
            Path(argv[0]).stem.lower(),
        )
        for argv in checks
    )
    claims = {
        "repository_id": _project_contribution_digest(root),
        "commands_digest": _json_digest(identities),
        "inline_code": inline_code,
        "shell_free": not shell,
        "allow_inline_code": inline_code,
    }
    return claims


def approve_checks(root: Path, *, allow_inline_code: bool = False) -> dict:
    project = resolve_project(Path(root))
    checks = discover_checks(project.root)
    if not checks:
        raise EngineeringError("Engineering project has no checks to approve.")
    claims = _check_capability_claims(project.root, checks)
    if claims["inline_code"] and not allow_inline_code:
        raise EngineeringError(
            "Engineering inline interpreter or shell code requires separate explicit approval."
        )
    operation = _begin_completion(
        project.root, "approve-checks-" + claims["commands_digest"].removeprefix("sha256:")[:12]
    )
    try:
        controller = _project_controller_dir(project.root)
        registry, attestation, new_key = _append_attestation(
            controller, "check_capability", claims
        )
        _transactional_json_documents(
            [(_attestation_path(controller), registry)],
            [(_controller_key_path(controller), new_key)] if new_key else None,
        )
        return {
            "approval_id": attestation["id"],
            "commands_digest": claims["commands_digest"],
            "commands": checks,
            "inline_code_approved": claims["allow_inline_code"],
        }
    finally:
        _end_completion(project.root, operation)


def _scope_handoff_claims(
    root: Path, commit: str, manifest: dict, handoff: dict
) -> dict:
    normalized = _bind_owner_intent_handoff(
        root, _scope_handoff(handoff, allow_controller_baseline=True)
    )
    decision_digest = _decision_artifact_digest(
        root, commit, manifest, normalized["decision_id"]
    )
    if normalized["decision_digest"] != decision_digest:
        raise EngineeringError("Engineering scope approval decision artifact changed.")
    claims = {
        "repository_id": _project_contribution_digest(root),
        "commit": commit,
        "decision_id": normalized["decision_id"],
        "decision_digest": normalized["decision_digest"],
        "seed_evidence": normalized["seed_evidence"],
        "reconstructed_scope": normalized["reconstructed_scope"],
        "architect_scope": normalized["architect_scope"],
        "result_scope": normalized["result_scope"],
        "result_artifacts": normalized["result_artifacts"],
    }
    if "outcome_survival" in normalized:
        claims["outcome_survival"] = normalized["outcome_survival"]
    return claims


def approve_scope_handoff(
    root: Path,
    decision_id: str,
    handoff: dict,
    *,
    owner_intent_id: str | None = None,
) -> dict:
    """Issue one signed, commit-bound approval for a reconstructed scope handoff."""
    project = resolve_project(Path(root))
    manifest = load_project_config(project.root)
    decision_id = _assurance_id(decision_id, "scope handoff decision")
    normalized = _bind_owner_intent_handoff(
        project.root, _scope_handoff(handoff, require_approval=False)
    )
    survival = normalized.get("outcome_survival")
    if isinstance(survival, dict) and survival.get("schema") == OUTCOME_SURVIVAL_V2_SCHEMA:
        if owner_intent_id is None:
            raise EngineeringError(
                "Engineering owner-intent scope approval requires the exact owner intent ID."
            )
        if _assurance_id(owner_intent_id, "scope approval owner intent") != survival[
            "owner_intent_id"
        ]:
            raise EngineeringError("Engineering owner-intent scope approval is mismatched.")
    elif owner_intent_id is not None:
        raise EngineeringError("Engineering legacy scope approval has no owner intent binding.")
    decision_digest = _decision_artifact_digest(
        project.root, project.commit, manifest, decision_id
    )
    approved = {
        **normalized,
        "decision_id": decision_id,
        "decision_digest": decision_digest,
    }
    claims = _scope_handoff_claims(project.root, project.commit, manifest, {
        **approved,
        "approval_id": "attestation-" + "0" * 32,
    })
    operation = _begin_completion(
        project.root,
        "approve-scope-" + decision_digest.removeprefix("sha256:")[:12],
    )
    try:
        controller = _project_controller_dir(project.root)
        registry, attestation, new_key = _append_attestation(
            controller, "scope_handoff", claims
        )
        _transactional_json_documents(
            [(_attestation_path(controller), registry)],
            [(_controller_key_path(controller), new_key)] if new_key else None,
        )
        approved["approval_id"] = attestation["id"]
        return {"scope_handoff": approved, "approval_id": attestation["id"]}
    finally:
        _end_completion(project.root, operation)


def _validate_scope_handoff_authority(
    root: Path, commit: str, manifest: dict, handoff: object
) -> dict:
    normalized = _bind_owner_intent_handoff(
        root, _scope_handoff(handoff, allow_controller_baseline=True)
    )
    claims = _scope_handoff_claims(root, commit, manifest, normalized)
    attestation = _require_attestation(
        _project_controller_dir(root), "scope_handoff", claims
    )
    if attestation["id"] != normalized["approval_id"]:
        raise EngineeringError("Engineering scope approval attestation is mismatched.")
    return normalized


def _check_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _execute_check(
    argv: list[str], *, timeout_seconds: float, cwd: Path | None = None
) -> dict:
    command_id = _check_identity(argv)
    started = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            shell=False,
            timeout=timeout_seconds,
            env=_check_environment(),
        )
    except subprocess.TimeoutExpired as error:
        raise EngineeringError(f"Engineering check timed out: {command_id}") from error
    duration = time.monotonic() - started
    stdout = result.stdout if isinstance(result.stdout, bytes) else str(result.stdout).encode()
    stderr = result.stderr if isinstance(result.stderr, bytes) else str(result.stderr).encode()
    return {
        "schema": "engineering.check.v1",
        "command_id": command_id,
        "exit_code": result.returncode,
        "duration_seconds": round(duration, 6),
        "output_digest": "sha256:" + hashlib.sha256(stdout + b"\0" + stderr).hexdigest(),
    }


def _git_bytes(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        shell=False,
        env=_controller_git_environment(),
    )
    if result.returncode != 0:
        raise EngineeringError("Engineering could not inspect the Git working state.")
    return result.stdout


def _name_status_paths(output: bytes) -> list[str]:
    fields = output.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    paths: list[str] = []
    index = 0
    try:
        while index < len(fields):
            status = fields[index].decode("ascii")
            index += 1
            count = 2 if status[:1] in {"R", "C"} else 1
            if not status or index + count > len(fields):
                raise ValueError
            for field in fields[index : index + count]:
                paths.append(field.decode("utf-8").replace("\\", "/"))
            index += count
    except (UnicodeDecodeError, ValueError) as error:
        raise EngineeringError("Engineering Git path metadata is invalid.") from error
    return paths


def _tracked_blob_sources(root: Path, commit: str) -> dict[str, set[str]]:
    sources: dict[str, set[str]] = {}

    def add(oid: str, path: bytes) -> None:
        try:
            decoded = path.decode("utf-8").replace("\\", "/")
        except UnicodeDecodeError as error:
            raise EngineeringError("Engineering Git path metadata is invalid.") from error
        sources.setdefault(oid, set()).add(decoded)

    for record in _git_bytes(root, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not record:
            continue
        try:
            metadata, path = record.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split(" ")
        except (UnicodeDecodeError, ValueError) as error:
            raise EngineeringError("Engineering tracked-blob metadata is invalid.") from error
        valid_oid = re.fullmatch(r"[0-9a-f]{40,64}", oid) is not None
        if kind == "blob" and mode in {"100644", "100755"} and valid_oid:
            add(oid, path)
        elif not (kind == "blob" and mode == "120000" and valid_oid) and not (
            kind in {"tree", "commit"} and valid_oid
        ):
            raise EngineeringError("Engineering tracked-blob metadata is invalid.")

    for record in _git_bytes(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        try:
            metadata, path = record.split(b"\t", 1)
            mode, oid, stage = metadata.decode("ascii").split(" ")
        except (UnicodeDecodeError, ValueError) as error:
            raise EngineeringError("Engineering index-blob metadata is invalid.") from error
        if stage != "0":
            raise EngineeringError("Engineering index provenance is ambiguous.")
        valid_oid = re.fullmatch(r"[0-9a-f]{40,64}", oid) is not None
        if mode in {"100644", "100755"} and valid_oid:
            add(oid, path)
        elif not (mode in {"120000", "160000", "040000"} and valid_oid):
            raise EngineeringError("Engineering index-blob metadata is invalid.")
    return sources


def _untracked_copy_sources(
    root: Path, commit: str, untracked: list[str]
) -> set[str]:
    if not untracked:
        return set()
    tracked = _tracked_blob_sources(root, commit)
    result: set[str] = set()
    for path in untracked:
        candidate = root / path
        try:
            metadata = candidate.lstat()
        except OSError as error:
            raise EngineeringError("Engineering untracked-copy provenance changed.") from error
        if not stat.S_ISREG(metadata.st_mode):
            continue
        oid = _git_bytes(root, "hash-object", "--path", path, "--", path).decode(
            "ascii"
        ).strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", oid):
            raise EngineeringError("Engineering untracked-copy provenance is invalid.")
        result.update(tracked.get(oid, set()))
    return result


def _changed_paths_since(root: Path, commit: str) -> list[str]:
    changed = _name_status_paths(
        _git_bytes(
            root,
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            "--find-copies",
            "--find-copies-harder",
            commit,
            "--",
        )
    )
    try:
        untracked = [
            item.decode("utf-8").replace("\\", "/")
            for item in _git_bytes(
                root, "ls-files", "--others", "--exclude-standard", "-z"
            ).split(b"\0")
            if item
        ]
    except UnicodeDecodeError as error:
        raise EngineeringError("Engineering Git path metadata is invalid.") from error
    paths = changed + untracked + sorted(
        _untracked_copy_sources(root, commit, untracked)
    )
    paths = sorted(dict.fromkeys(paths))
    if len(paths) > 512 or any(len(path) > 512 or _contains_credential(path) for path in paths):
        raise EngineeringError("Engineering changed-artifact set is not privacy-safe and bounded.")
    return paths


def _working_state_identity(root: Path) -> dict:
    head = git(root, "rev-parse", "HEAD")
    paths = _changed_paths_since(root, head)
    digest = hashlib.sha256()
    digest.update(head.encode("ascii") + b"\0")
    digest.update(_git_bytes(root, "write-tree") + b"\0")
    digest.update(
        _git_bytes(
            root,
            "diff",
            "--raw",
            "-z",
            "--find-renames",
            "--find-copies",
            "--find-copies-harder",
            "--no-ext-diff",
        )
        + b"\0"
    )
    for path in paths:
        digest.update(path.encode("utf-8") + b"\0")
        candidate = root / path
        if candidate.is_symlink() or (
            candidate.exists() and _is_reparse_point(candidate)
        ):
            raise EngineeringError("Engineering dirty artifact is a reparse point.")
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            digest.update(b"deleted")
            continue
        except OSError as error:
            raise EngineeringError("Engineering dirty artifact metadata is invalid.") from error
        file_type = stat.S_IFMT(metadata.st_mode)
        executable = stat.S_IMODE(metadata.st_mode) & 0o111
        digest.update(f"type:{file_type};exec:{executable}".encode("ascii") + b"\0")
        if stat.S_ISREG(metadata.st_mode):
            content = hashlib.sha256()
            with candidate.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    content.update(chunk)
            digest.update(content.digest())
        elif stat.S_ISDIR(metadata.st_mode):
            digest.update(b"directory")
        else:
            raise EngineeringError("Engineering dirty artifact type is unsupported.")
    if (root / ".gitmodules").is_file():
        digest.update(_git_bytes(root, "submodule", "status", "--recursive"))
    return {"head": head, "digest": "sha256:" + digest.hexdigest()}


def _stable_completion_snapshot(root: Path, commit: str) -> tuple[list[str], dict]:
    before = _working_state_identity(root)
    changed = _changed_paths_since(root, commit)
    after = _working_state_identity(root)
    if before != after:
        raise EngineeringError("Engineering initial working state changed during capture.")
    return changed, after


def _discard_unlocked_operation(root: Path, operation_id: str) -> None:
    record = _read_operation(root, operation_id)
    paths = _validated_operation_paths(root, operation_id)
    owner = _lock_owner(record)
    if owner is not None and (
        owner.get("operation_id") == operation_id
        and owner.get("lock_token") == record.get("lock_token")
    ):
        raise EngineeringError("Engineering repository lock ownership is ambiguous.")
    if any(paths[key].exists() for key in ("worktree_path", "staging_path", "result_path")):
        raise EngineeringError("Engineering completion operation has unexpected resources.")
    paths["record_path"].unlink()
    paths["operation_root"].rmdir()


def _begin_completion(root: Path, run_id: str) -> dict:
    orphan = reconcile_orphaned_operations(root, timeout_seconds=10)
    if orphan["unresolved"] or orphan["live"]:
        raise EngineeringError("Engineering repository lock is unavailable.")
    operation = register_hook_operation(root)
    record = _read_operation(root, operation["operation_id"])
    record.update({"kind": "completion", "run_id": run_id})
    _write_operation(record)
    deadline = time.monotonic() + 0.5
    while not _acquire_repository_lock(record):
        if time.monotonic() >= deadline:
            _discard_unlocked_operation(root, record["operation_id"])
            raise EngineeringError("Engineering repository lock timed out.")
        time.sleep(0.01)
    return _read_operation(root, record["operation_id"])


def _end_completion(root: Path, record: dict) -> None:
    current = _read_operation(root, record["operation_id"])
    current.update(
        phase="orphaned",
        worker_process_tree_dead=True,
        controller_owned_completion=True,
    )
    _write_operation(current)
    # Completion/maintenance operations are owned by this controller process.
    # Release that exact lock before the orphan cleanup guard checks for live
    # owners; worker-operation cleanup must still refuse any live owner.
    if not _release_failed_start_lock(current):
        raise EngineeringError("Engineering completion lock ownership is ambiguous.")
    result = cleanup_hook_operation(
        root,
        current["operation_id"],
        timeout_seconds=30,
        allow_replaced_completion_lock=True,
    )
    if not result["completed"]:
        raise EngineeringError(f"Engineering completion cleanup failed: {result['reason']}")


def _load_preparation(root: Path, run_id: str) -> dict:
    if not re.fullmatch(r"run-[0-9a-f]{6}", run_id):
        raise EngineeringError("Engineering run identifier is invalid.")
    path = _common_graph_dir(root) / "runs" / run_id / "preparation.json"
    try:
        preparation = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering preparation is missing or invalid.") from error
    if (
        not isinstance(preparation, dict)
        or preparation.get("schema") != "engineering.prepare.v1"
        or preparation.get("run_id") != run_id
        or preparation.get("readiness") == "blocked"
    ):
        raise EngineeringError("Engineering preparation is not completion-ready.")
    return preparation


def _contract_paths_at(root: Path, revision: str) -> set[str]:
    manifests = [
        name for name in (V1_CONFIG, V2_CONFIG) if _exists_at(root, revision, name)
    ]
    if len(manifests) != 1:
        raise EngineeringError(
            "Engineering completion requires exactly one valid overlay manifest."
        )
    manifest_name = manifests[0]
    _, links_path, _, _ = _project_paths_for_manifest(manifest_name)
    manifest = _json_at(root, revision, manifest_name)
    links = _json_at(root, revision, links_path)
    nodes, _, _ = _validate_overlay(
        root, revision, manifest, links, manifest_name=manifest_name
    )
    return {
        node["source"]["path"].replace("\\", "/")
        for node in nodes
        if node.get("type") == "contract"
        and isinstance(node.get("source"), dict)
        and isinstance(node["source"].get("path"), str)
    }


def _successful_check_evidence(required: list[list[str]], checks: object) -> bool:
    if not isinstance(checks, list) or len(checks) != len(required):
        return False
    expected_keys = {
        "schema",
        "command_id",
        "exit_code",
        "duration_seconds",
        "output_digest",
    }
    for argv, receipt in zip(required, checks, strict=True):
        if not isinstance(receipt, dict) or set(receipt) != expected_keys:
            return False
        duration = receipt.get("duration_seconds")
        if not (
            receipt.get("schema") == "engineering.check.v1"
            and receipt.get("command_id") == _check_identity(argv)
            and receipt.get("exit_code") == 0
            and not isinstance(receipt.get("exit_code"), bool)
            and isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and math.isfinite(duration)
            and 0 <= duration <= 86_400
            and isinstance(receipt.get("output_digest"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", receipt["output_digest"])
        ):
            return False
    return True


def _bound_preparation_owner_intent(preparation: object) -> dict | None:
    if not isinstance(preparation, dict):
        raise EngineeringError("Engineering preparation owner intent is invalid.")
    owner_intent = preparation.get("owner_intent")
    if owner_intent is None:
        return None
    expected = {
        "schema",
        "state",
        "intent_id",
        "owner_intent_digest",
        "authority_epoch",
        "core_outcome_count",
        "intent_impacting",
        "bound_to_scope_handoff",
    }
    if (
        not isinstance(owner_intent, dict)
        or set(owner_intent) != expected
        or owner_intent.get("schema") != OWNER_INTENT_STATUS_SCHEMA
        or owner_intent.get("state") != "bound"
        or owner_intent.get("intent_impacting") is not True
        or owner_intent.get("bound_to_scope_handoff") is not True
    ):
        raise EngineeringError("Engineering preparation owner intent is unknown or unbound.")
    try:
        normalized = {
            "intent_id": _assurance_id(owner_intent["intent_id"], "preparation owner intent"),
            "owner_intent_digest": owner_intent["owner_intent_digest"],
            "authority_epoch": _assurance_id(owner_intent["authority_epoch"], "preparation owner intent epoch"),
        }
    except EngineeringError as error:
        raise EngineeringError("Engineering preparation owner intent is invalid.") from error
    if not re.fullmatch(
        r"sha256:[0-9a-f]{64}", normalized["owner_intent_digest"]
    ):
        raise EngineeringError("Engineering preparation owner intent is invalid.")
    return normalized


def _completion_payload(
    preparation: dict,
    changed: list[str],
    result_identity: dict,
    checkpoint_status: dict,
    dirty: bool,
    checks: list[dict],
    maintenance_ids: list[str],
    scope_result: list[str] | None = None,
    scope_result_artifacts: list[str] | None = None,
) -> dict:
    predicted_paths = {item["id"] for item in preparation["impact"]}
    safe_additional = [
        path
        for path in changed
        if path not in set(preparation["authorization"]["scope"])
        and (path.startswith("tests/") or path.startswith("docs/"))
    ]
    payload = {
        "schema": "engineering.complete.v1",
        "run_id": preparation["run_id"],
        "project": preparation["project"],
        "intent": preparation["intent"],
        "authorization": preparation["authorization"],
        "autonomy": preparation["autonomy"],
        "context": preparation["context"],
        "changed_artifacts": changed,
        "predicted_impact": preparation["impact"],
        "actual_impact": [
            {
                "id": path,
                "provenance": "direct" if path in predicted_paths else "derived",
            }
            for path in changed
        ],
        "traceability": {"added": [], "changed": [], "removed": []},
        "checks": checks,
        "advisories": (
            [{"code": "safe_additional_artifacts", "paths": safe_additional}]
            if safe_additional
            else []
        ),
        "maintenance": sorted(maintenance_ids),
        "checkpoint": {
            "commit": checkpoint_status["commit"],
            "status": (
                "current"
                if checkpoint_status["ready"] and not dirty
                else "pending_commit"
            ),
        },
        "result_identity": result_identity,
    }
    if preparation.get("completion_applied_practices"):
        payload["applied_practices"] = preparation["completion_applied_practices"]
    if preparation.get("completion_practice_status") is not None:
        payload["practice_status"] = preparation["completion_practice_status"]
    if scope_result is not None:
        payload["scope_result"] = scope_result
    if scope_result_artifacts is not None:
        payload["scope_result_artifacts"] = scope_result_artifacts
    handoff = preparation["authorization"].get("scope_handoff")
    if isinstance(handoff, dict) and "outcome_survival" in handoff:
        payload["outcome_survival"] = handoff["outcome_survival"]
    owner_intent = _bound_preparation_owner_intent(preparation)
    if owner_intent is not None:
        payload["owner_intent"] = owner_intent
    return payload


def complete(
    root: Path,
    run_id: str,
    receipts: list[dict],
    *,
    result_scope: list[str] | None = None,
) -> dict:
    if receipts != []:
        raise EngineeringError("Engineering caller-supplied check receipts are not accepted.")
    project = resolve_project(Path(root))
    preparation = _load_preparation(project.root, run_id)
    if preparation["project"].get("root_digest") != (
        "sha256:" + checkpoint_identity(project.root, preparation["project"]["commit"])
    ):
        raise EngineeringError("Engineering preparation project identity changed.")

    initial_head = git(project.root, "rev-parse", "HEAD")
    initial_dirty = bool(_dirty_paths(project.root))
    if (
        not initial_dirty
        and initial_head != preparation["project"]["commit"]
        and not check_merge_readiness(project.root)["ready"]
    ):
        rebuild(project.root, initial_head, sys.executable)

    operation = _begin_completion(project.root, run_id)
    try:
        manifest_path = _common_graph_dir(project.root) / "runs" / run_id / "completion.json"
        changed, initial_state = _stable_completion_snapshot(
            project.root, preparation["project"]["commit"]
        )
        dirty = bool(_dirty_paths(project.root))
        head = git(project.root, "rev-parse", "HEAD")
        if head != initial_head or dirty != initial_dirty or initial_state["head"] != head:
            raise EngineeringError("Engineering completion authority changed during refresh.")
        result_identity = {
            "commit": None if dirty else head,
            "dirty_tree_digest": initial_state["digest"] if dirty else None,
        }
        authorization = preparation["authorization"]
        scope_handoff = authorization.get("scope_handoff")
        checkpoint_status = check_merge_readiness(project.root)
        base_checkpoint = _load_checkpoint(
            project.root, preparation["project"]["commit"]
        )
        if _intent_impacting(
            base_checkpoint,
            [],
            authorization.get("change_class"),
            scope_handoff,
            artifact_paths=changed,
        ):
            _require_completion_owner_intent(
                project.root, preparation, scope_handoff
            )
        if authorization.get("change_class") in MATERIAL_CHANGE_CLASSES and (
            not isinstance(scope_handoff, dict)
            or "outcome_survival" not in scope_handoff
        ):
            raise EngineeringError(
                "Engineering completion blocks material change without baseline outcome survival."
            )
        scope_result = _scope_result(result_scope) if result_scope is not None else None
        scope_result_artifacts = None
        if scope_handoff is not None:
            _validate_scope_handoff_authority(
                project.root,
                preparation["project"]["commit"],
                load_project_config(project.root),
                scope_handoff,
            )
            if scope_result is None and not manifest_path.is_file():
                raise EngineeringError(
                    "Engineering completion requires an actual scope result for the approved handoff."
                )
            if scope_result is not None and scope_result != scope_handoff["architect_scope"]:
                raise EngineeringError(
                    "Engineering completion result scope is narrow or outside the approved scope."
                )
            scope_result_artifacts = sorted(
                path.replace("\\", "/") for path in changed
            )
            if scope_result_artifacts != scope_handoff["result_artifacts"]:
                raise EngineeringError(
                    "Engineering completion result artifacts are incomplete or outside the approved scope."
                )
        elif scope_result is not None:
            raise EngineeringError("Engineering completion result scope has no approved handoff.")
        scope = set(authorization["scope"])
        safe_additional = [
            path
            for path in changed
            if path not in scope and (path.startswith("tests/") or path.startswith("docs/"))
        ]
        expanded = [
            path for path in changed if path not in scope and path not in safe_additional
        ]
        if expanded:
            raise EngineeringError("Engineering completion detected scope expansion.")
        maintenance_observations = []
        if dirty or not checkpoint_status["ready"]:
            maintenance_observations.append(
                {
                    "area": "graph",
                    "artifact": "checkpoint",
                    "kind": "checkpoint_stale",
                    "impact": "routine",
                }
            )
        maintenance_observations.extend(
            {
                "area": path.split("/", 1)[0],
                "artifact": path,
                "kind": "stale_artifact",
                "impact": "routine",
            }
            for path in safe_additional
        )
        maintenance_ids = _prospective_maintenance_ids(
            project.root, maintenance_observations, operation
        )
        if manifest_path.is_file():
            try:
                retained = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise EngineeringError("Engineering completion manifest is invalid.") from error
            if not isinstance(retained, dict) or not _successful_check_evidence(
                preparation["required_checks"], retained.get("checks")
            ):
                raise EngineeringError("Engineering completion manifest is invalid.")
            if retained.get("result_identity") != result_identity:
                raise EngineeringError(
                    "Engineering completion replay conflicts with current tree."
                )
            if scope_handoff is not None and scope_result is None:
                scope_result = _scope_result(retained.get("scope_result"))
                if scope_result != scope_handoff["architect_scope"]:
                    raise EngineeringError(
                        "Engineering completion manifest has a mismatched scope result."
                    )
            expected = _completion_payload(
                preparation,
                changed,
                result_identity,
                checkpoint_status,
                dirty,
                retained["checks"],
                maintenance_ids,
                scope_result,
                scope_result_artifacts,
            )
            if retained != expected:
                raise EngineeringError("Engineering completion manifest is invalid.")
            _require_attestation(
                _project_controller_dir(project.root),
                "completion",
                _completion_attestation_claims(project.root, retained),
            )
            if _working_state_identity(project.root) != initial_state:
                raise EngineeringError("Engineering completion replay conflicts with current tree.")
            return {**retained, "manifest": str(manifest_path)}

        checkpoint = _load_checkpoint(
            project.root,
            preparation["project"]["commit"] if dirty else head,
        )
        predicted_paths = {item["id"] for item in preparation["impact"]}
        contract_paths = {
            node["source"]["path"].replace("\\", "/")
            for node in checkpoint["nodes"]
            if node.get("type") == "contract"
            and isinstance(node.get("source"), dict)
            and isinstance(node["source"].get("path"), str)
        }
        if dirty:
            contract_paths.update(_contract_paths_at(project.root, "INDEX"))
            contract_paths.update(_contract_paths_at(project.root, "WORKTREE"))
        if any(path in contract_paths and path not in predicted_paths for path in changed):
            raise EngineeringError("Engineering completion detected unpredicted public contract impact.")

        actual_intent_impact = _completion_intent_impact(
            project.root,
            preparation["project"]["commit"],
            head,
            dirty,
            changed,
            authorization,
            scope_handoff,
            checkpoint_status,
        )
        if actual_intent_impact:
            _require_completion_owner_intent(
                project.root, preparation, scope_handoff
            )

        required = preparation["required_checks"]
        if discover_checks(project.root) != required:
            raise EngineeringError("Engineering project check capability changed after preparation.")
        if required:
            claims = _check_capability_claims(project.root, required)
            task_authority = authorization.get("task_authority")
            if task_authority is not None:
                validated_authority = validate_task_check_authority(project.root, task_authority, claims)
                if preparation.get("check_authority") != validated_authority:
                    raise EngineeringError("Engineering task check authority changed after preparation.")
            else:
                _require_attestation(
                    _project_controller_dir(project.root), "check_capability", claims
                )
        checks: list[dict] = []
        for argv in required:
            command_id = _check_identity(argv)
            receipt = _execute_check(argv, timeout_seconds=600, cwd=project.root)
            if receipt["exit_code"] != 0:
                raise EngineeringError(f"Engineering check failed: {command_id}")
            checks.append(receipt)
        if _working_state_identity(project.root) != initial_state:
            raise EngineeringError("Engineering working state changed during checks.")

        payload = _completion_payload(
            preparation,
            changed,
            result_identity,
            checkpoint_status,
            dirty,
            checks,
            maintenance_ids,
            scope_result,
            scope_result_artifacts,
        )
        if _working_state_identity(project.root) != initial_state:
            raise EngineeringError("Engineering working state changed before publication.")
        prior_maintenance = _maintenance_snapshot(project.root)
        try:
            mutation = _mutate_maintenance_locked(
                project.root,
                maintenance_observations,
                operation,
                resolved_checkpoint=(
                    head if checkpoint_status["ready"] and not dirty else None
                ),
            )
            if sorted(item["id"] for item in mutation["queued"]) != maintenance_ids:
                raise EngineeringError("Engineering maintenance publication changed identity.")
            controller = _project_controller_dir(project.root)
            attestations, _, new_key = _append_attestation(
                controller,
                "completion",
                _completion_attestation_claims(project.root, payload),
            )
            _transactional_json_documents(
                [
                    (manifest_path, payload),
                    (
                        _attestation_path(controller),
                        attestations,
                    ),
                ],
                [(_controller_key_path(controller), new_key)] if new_key else None,
            )
        except Exception:
            manifest_path.unlink(missing_ok=True)
            _restore_maintenance(project.root, prior_maintenance)
            raise
        return {**payload, "manifest": str(manifest_path)}
    finally:
        _end_completion(project.root, operation)


def compare_checkpoints(first: dict, second: dict) -> dict:
    def changes(kind: str) -> dict:
        before = {item["id"]: item for item in first[kind]}
        after = {item["id"]: item for item in second[kind]}
        return {
            "added": sorted(after.keys() - before.keys()),
            "removed": sorted(before.keys() - after.keys()),
            "changed": sorted(key for key in before.keys() & after.keys() if before[key] != after[key]),
        }

    first_coverage = {item["requirement"]: item["covered"] for item in coverage(first)}
    second_coverage = {item["requirement"]: item["covered"] for item in coverage(second)}
    return {
        "from": first["metadata"]["commit"],
        "to": second["metadata"]["commit"],
        "integrity": {"from": first["integrity"], "to": second["integrity"]},
        "nodes": changes("nodes"),
        "edges": changes("edges"),
        "coverage": {
            "newly_uncovered": sorted(
                key for key, covered in second_coverage.items()
                if not covered and first_coverage.get(key, True)
            ),
            "newly_covered": sorted(
                key for key, covered in second_coverage.items()
                if covered and not first_coverage.get(key, False)
            ),
        },
    }


def _exists_at(root: Path, revision: str, path: str) -> bool:
    if revision == "WORKTREE":
        return (root / path).is_file()
    try:
        object_name = f":{path}" if revision == "INDEX" else f"{revision}:{path}"
        git(root, "cat-file", "-e", object_name)
        return True
    except TraceabilityError:
        return False


def _validate_project_controls(
    root: Path, revision: str, manifest_name: str
) -> str:
    config_path, links_path, ledger_path, readme_path = (
        _project_paths_for_manifest(manifest_name)
    )
    if not _exists_at(root, revision, config_path):
        raise EngineeringError(f"invalid_manifest: {config_path} is not available")
    try:
        manifest = _json_at(root, revision, config_path)
    except TraceabilityError as error:
        raise EngineeringError(f"invalid_manifest: {config_path}") from error
    expected_version = 1 if manifest_name == V1_CONFIG else 2
    inputs = manifest.get("inputs")
    if (
        manifest.get("version") != expected_version
        or not isinstance(inputs, list)
        or links_path not in inputs
        or any(
            not isinstance(path, str)
            or not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            for path in inputs
        )
    ):
        raise EngineeringError(f"invalid_manifest: {config_path}")
    project = manifest.get("project")
    configured_default = (
        project.get("default_branch") if isinstance(project, dict) else None
    )
    if (
        not isinstance(configured_default, str)
        or not configured_default.strip()
    ):
        raise EngineeringError(
            f"invalid_manifest: project.default_branch in {config_path}"
        )

    missing = []
    if not _exists_at(root, revision, ledger_path):
        missing.append(f"missing_ledger: {ledger_path}")
    if not _exists_at(root, revision, links_path):
        missing.append(f"missing_links: {links_path}")
    if not _exists_at(root, revision, readme_path):
        missing.append(f"missing_governed_artifact: {readme_path}")
    if missing:
        raise EngineeringError("; ".join(missing))
    ledger = _text_at(root, revision, ledger_path)
    if not ledger.lstrip().startswith("#"):
        raise EngineeringError(f"invalid_ledger: {ledger_path}")
    try:
        links = _json_at(root, revision, links_path)
    except TraceabilityError as error:
        raise EngineeringError(f"invalid_links: {links_path}") from error
    try:
        _validate_overlay(
            root,
            revision,
            manifest,
            links,
            manifest_name=manifest_name,
        )
    except TraceabilityError as error:
        message = str(error)
        if "Missing source at commit" in message:
            code = "missing_governed_artifact"
        elif "source line" in message or "Input path must stay" in message:
            code = "invalid_governed_artifact"
        else:
            code = "invalid_links"
        raise EngineeringError(f"{code}: {message}") from error
    return configured_default


def _validate_staged_overlay(root: Path, manifest_name: str | None = None) -> None:
    selected = manifest_name or _tracked_manifest_name(root)
    if selected is None:
        return
    _validate_project_controls(root, "INDEX", selected)


def _validate_push_checkpoint(
    root: Path, manifest_name: str | None = None
) -> dict:
    commit = git(root, "rev-parse", "HEAD")
    try:
        checkpoint = _load_checkpoint(root, commit)
    except TraceabilityError as error:
        raise TraceabilityError(
            f"No commit-bound graph for {commit}; run rebuild before push."
        ) from error
    config_path, links_path, _, _ = (
        _project_paths_for_manifest(manifest_name)
        if manifest_name is not None
        else _project_paths(root)
    )
    manifest = _json_at(root, commit, config_path)
    links = _json_at(root, commit, links_path)
    _, _, integrity = _validate_overlay(
        root, commit, manifest, links, manifest_name=config_path
    )
    if integrity["input_digest"] != checkpoint["metadata"]["input_digest"]:
        raise TraceabilityError(
            f"Commit-bound graph for {commit} is stale; run rebuild before push."
        )
    if not (_checkpoint_path(root, commit).parent / "graph.json").is_file():
        raise TraceabilityError(
            f"Commit-bound graph for {commit} has no Graphify output."
        )
    if manifest.get("baseline", {}).get("accepted"):
        missing = [
            item["requirement"]
            for item in coverage(checkpoint)
            if not item["covered"]
        ]
        if missing:
            raise TraceabilityError(
                "Accepted baseline has uncovered requirements: "
                + ", ".join(missing)
            )
    return checkpoint


def _hook_budget(
    root: Path, manifest_name: str, explicit: float | None
) -> float:
    if explicit is not None:
        return explicit
    manifest = _json_at(root, "INDEX", manifest_name)
    graphify = manifest.get("graphify")
    configured = (
        graphify.get("hook_budget_seconds")
        if isinstance(graphify, dict)
        else None
    )
    if configured is None:
        return 0.0
    if (
        isinstance(configured, bool)
        or not isinstance(configured, (int, float))
        or configured <= 0
    ):
        raise EngineeringError(
            "invalid_manifest: graphify.hook_budget_seconds must be positive"
        )
    return float(configured)


def dispatch_hook(
    root: Path,
    event: str,
    *,
    graphify_python: str = sys.executable,
    hook_budget_seconds: float | None = None,
    cleanup_timeout_seconds: float = 5.0,
    identity_clock: object | None = None,
) -> dict:
    clock = identity_clock if callable(identity_clock) else time.monotonic
    started = clock()
    project = resolve_hook_project(root)
    if project is None:
        return {"event": event, "action": "no_op", "reason": "manifest_not_tracked"}
    manifest_name = _tracked_manifest_name(root)
    configured_default = _validate_project_controls(root, "INDEX", manifest_name)
    budget = _hook_budget(root, manifest_name, hook_budget_seconds)
    if event == "pre-commit":
        return {"event": event, "action": "validate"}
    if event == "post-checkout":
        commit = git(root, "rev-parse", "HEAD")
        try:
            checkpoint = _load_checkpoint(root, commit)
        except EngineeringError:
            return {"event": event, "action": "select", "selected": False}
        return {
            "event": event,
            "action": "select",
            "selected": True,
            "checkpoint": str(_checkpoint_path(root, commit)),
            "kind": checkpoint["metadata"]["kind"],
        }
    if event == "pre-push":
        readiness = check_merge_readiness(root)
        if not readiness["ready"]:
            raise EngineeringError(
                f"{readiness['reason']}: exact current checkpoint required before push"
            )
        return {
            "event": event,
            "action": "validate",
            "checkpoint": readiness["checkpoint"],
        }
    if event == "post-merge":
        branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        if branch != configured_default:
            return {"event": event, "action": "skip", "reason": "not-default-branch"}
        result = reconcile_canonical(
            root,
            refresh_remote=False,
            graphify_python=graphify_python,
            hook_budget_seconds=max(0.0, budget - (clock() - started)),
        )
    else:
        remaining = budget - (clock() - started)
        if remaining <= 0:
            commit = git(root, "rev-parse", "HEAD")
            result = _stale_result(
                root,
                commit,
                "hook_budget_exceeded",
                _compatible_ancestor(root, commit, GRAPHIFY_VERSION),
            )
            result["changed_paths"] = []
        else:
            result = rebuild(
                root,
                graphify_python,
                manifest_name=manifest_name,
                hook_budget_seconds=remaining,
                cleanup_timeout_seconds=cleanup_timeout_seconds,
            )
    if result.get("reason") == "semantic_completion_required":
        result["reason"] = "semantic_update_deferred"
        _record_stale(root, result["commit"], result["reason"])
    return {
        "event": event,
        "action": "stale" if result["freshness"] == "stale" else "rebuild",
        **result,
    }


def handle_hook(
    event: str, root: Path, graphify_python: str
) -> dict:
    return dispatch_hook(root, event, graphify_python=graphify_python)


def _worktree_roots(root: Path) -> list[Path]:
    output = git(root, "worktree", "list", "--porcelain")
    return [
        Path(line.removeprefix("worktree ")).resolve()
        for line in output.splitlines()
        if line.startswith("worktree ")
    ]


def _is_reparse_point(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        if os.name != "nt":
            return False
        return bool(
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    except OSError:
        return True


def _engineering_user_home() -> Path:
    configured = os.environ.get("ENGINEERING_USER_HOME")
    home = _expand_install_path(configured) if configured else Path.home()
    if not home.is_absolute():
        raise EngineeringError("Engineering user home must be absolute.")
    if str(home).startswith("\\\\"):
        raise EngineeringError("Engineering controller storage on UNC paths is unsupported.")
    _reject_reparse_ancestors(home.absolute())
    return home.resolve()


def _contribution_queue_path() -> Path:
    path = _engineering_user_home() / ".agents" / "engineering" / "contribution-queue.json"
    _reject_reparse_ancestors(path)
    return path


def _applied_practices_path() -> Path:
    path = _engineering_user_home() / ".agents" / "engineering" / "applied-practices.json"
    _reject_reparse_ancestors(path)
    return path


def _contribution_lock_path() -> Path:
    path = _engineering_user_home() / ".agents" / "engineering" / "contribution.lock"
    _reject_reparse_ancestors(path)
    return path


def _promotion_controller_dir() -> Path:
    path = _engineering_user_home() / ".agents" / "engineering" / "controller"
    _reject_reparse_ancestors(path)
    return path


def _promotion_attestation_path() -> Path:
    return _promotion_controller_dir() / "attestations.json"


def _project_controller_dir(root: Path) -> Path:
    path = _common_graph_dir(root) / "controller"
    _reject_reparse_ancestors(path)
    return path


_WINDOWS_PRIVATE_ACL = r"""
& {
param(
    [Parameter(Mandatory=$true)][string]$path,
    [Parameter(Mandatory=$true)][ValidateSet('0','1')][string]$enforceFlag,
    [Parameter(Mandatory=$true)][ValidateSet('0','1')][string]$directoryFlag
)
$ErrorActionPreference = 'Stop'
$enforce = $enforceFlag -eq '1'
$directory = $directoryFlag -eq '1'
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = if ($directory) {
    [System.IO.DirectoryInfo]::new($path).GetAccessControl()
} else {
    [System.IO.FileInfo]::new($path).GetAccessControl()
}
$ownerSid = (New-Object System.Security.Principal.NTAccount($acl.Owner)).Translate(
    [System.Security.Principal.SecurityIdentifier]
).Value
$expectedInheritance = if ($directory) { 'ContainerInherit, ObjectInherit' } else { 'None' }
$privateAccess = @($acl.Access | Where-Object {
    $entrySid = $_.IdentityReference.Translate(
        [System.Security.Principal.SecurityIdentifier]
    ).Value
    ($entrySid -eq $sid.Value -or $entrySid -eq 'S-1-5-18') -and
        $_.AccessControlType.ToString() -eq 'Allow' -and
        -not $_.IsInherited -and
        $_.InheritanceFlags.ToString() -eq $expectedInheritance -and
        $_.PropagationFlags.ToString() -eq 'None'
})
$alreadyPrivate = $acl.AreAccessRulesProtected -and $ownerSid -eq $sid.Value -and
    $privateAccess.Count -gt 0 -and $privateAccess.Count -eq @($acl.Access).Count
if ($enforce -and -not $alreadyPrivate) {
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRuleSpecific($rule) }
    if ($directory) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
                [System.Security.AccessControl.InheritanceFlags]::ObjectInherit,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
    } else {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
    }
    $ownerSid = (New-Object System.Security.Principal.NTAccount($acl.Owner)).Translate(
        [System.Security.Principal.SecurityIdentifier]
    ).Value
    if ($ownerSid -ne $sid.Value) { $acl.SetOwner($sid) }
    $acl.AddAccessRule($rule)
    if ($directory) {
        [System.IO.DirectoryInfo]::new($path).SetAccessControl($acl)
    } else {
        [System.IO.FileInfo]::new($path).SetAccessControl($acl)
    }
}
$verified = if ($directory) {
    [System.IO.DirectoryInfo]::new($path).GetAccessControl()
} else {
    [System.IO.FileInfo]::new($path).GetAccessControl()
}
$entries = @($verified.Access | ForEach-Object {
    $entrySid = $_.IdentityReference.Translate(
        [System.Security.Principal.SecurityIdentifier]
    ).Value
    @{
        sid = $entrySid
        type = $_.AccessControlType.ToString()
        inherited = $_.IsInherited
        inheritance = $_.InheritanceFlags.ToString()
        propagation = $_.PropagationFlags.ToString()
    }
})
$ownerSid = (New-Object System.Security.Principal.NTAccount($verified.Owner)).Translate(
    [System.Security.Principal.SecurityIdentifier]
).Value
$result = @{
    protected = $verified.AreAccessRulesProtected
    owner_sid = $ownerSid
    current_sid = $sid.Value
    access = $entries
} | ConvertTo-Json -Compress -Depth 4
[Console]::Out.WriteLine('ENGINEERING_ACL_RESULT:' + $result)
}
""".strip()


def _windows_owner_private(path: Path, *, enforce: bool) -> None:
    directory = path.is_dir()
    try:
        executable = _shared_native_powershell()
        environment = _shared_native_powershell_environment(executable)
    except (HostBoundaryError, OSError) as error:
        raise EngineeringError(
            "Engineering controller owner-private ACL verification failed."
        ) from error
    result = subprocess.run(
        [
            str(executable),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _WINDOWS_PRIVATE_ACL,
            str(path),
            "1" if enforce else "0",
            "1" if directory else "0",
        ],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise EngineeringError("Engineering controller owner-private ACL verification failed.")
    records = [
        line.removeprefix("ENGINEERING_ACL_RESULT:")
        for line in result.stdout.splitlines()
        if line.startswith("ENGINEERING_ACL_RESULT:")
    ]
    if len(records) != 1:
        raise EngineeringError("Engineering controller owner-private ACL verification failed.")
    try:
        payload = json.loads(records[0])
    except json.JSONDecodeError as error:
        raise EngineeringError("Engineering controller owner-private ACL verification failed.") from error
    if not isinstance(payload, dict):
        raise EngineeringError("Engineering controller owner-private ACL verification failed.")
    current_sid = payload.get("current_sid")
    access = payload.get("access")
    if (
        payload.get("protected") is not True
        or payload.get("owner_sid") != payload.get("current_sid")
        or not isinstance(access, list)
        or not access
        or any(
            not isinstance(item, dict)
            or item.get("sid") not in {current_sid, "S-1-5-18"}
            or item.get("type") != "Allow"
            or item.get("inherited") is not False
            or item.get("inheritance")
            != ("ContainerInherit, ObjectInherit" if directory else "None")
            or item.get("propagation") != "None"
            for item in access
        )
        or not any(item.get("sid") == current_sid for item in access)
    ):
        raise EngineeringError("Engineering controller file is not owner-private.")


def _enforce_owner_private(path: Path) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise EngineeringError("Engineering controller file is not owner-private.")
        return
    _windows_owner_private(path, enforce=True)


def _verify_owner_private(path: Path, *, directory: bool) -> None:
    if not path.is_dir() if directory else not path.is_file():
        raise EngineeringError("Engineering controller owner-private path is unavailable.")
    if os.name != "nt":
        expected = 0o700 if directory else 0o600
        retained = path.stat()
        if stat.S_IMODE(retained.st_mode) != expected or (
            hasattr(os, "geteuid") and retained.st_uid != os.geteuid()
        ):
            raise EngineeringError("Engineering controller file is not owner-private.")
        return
    _windows_owner_private(path, enforce=False)


def _enforce_install_private(path: Path) -> None:
    """Keep POSIX test doubles from invoking Windows ACL behavior."""
    if os.name == "nt" and sys.platform != "win32":
        return
    _enforce_owner_private(path)


def _private_atomic_bytes(path: Path, content: bytes) -> None:
    _reject_reparse_ancestors(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _enforce_install_private(path.parent)
    _reject_reparse_ancestors(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        _enforce_install_private(temporary)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _json_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _assurance_id(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value)
        or _contains_credential(value)
    ):
        raise EngineeringError(f"Engineering assurance {label} is invalid.")
    return value


def _traceability_identity(value: object, label: str) -> str:
    """Validate receipt identity values, allowing ordinary slash branches."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or "\\" in value
        or ".." in PurePosixPath(value).parts
        or value.startswith("/")
        or _contains_credential(value)
    ):
        raise EngineeringError(f"Engineering traceability {label} is invalid.")
    return value


def _assurance_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise EngineeringError("Engineering assurance timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EngineeringError("Engineering assurance timestamp is invalid.") from error
    if parsed.tzinfo is None:
        raise EngineeringError("Engineering assurance timestamp is invalid.")
    return parsed.astimezone(timezone.utc)


def validate_assurance_manifest(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {
        "schema", "capabilities", "cells", "obligations"
    } or value.get("schema") != ASSURANCE_SCHEMA:
        raise EngineeringError("Engineering capability assurance manifest is invalid.")
    capabilities = value.get("capabilities")
    cells = value.get("cells")
    obligations = value.get("obligations")
    if (
        not isinstance(capabilities, list)
        or not isinstance(cells, list)
        or not isinstance(obligations, list)
        or len(capabilities) > 256
        or len(cells) > 256
        or len(obligations) > 512
    ):
        raise EngineeringError("Engineering capability assurance manifest is invalid.")
    normalized_cells = []
    for cell in cells:
        if not isinstance(cell, dict) or set(cell) != {"id", "production"}:
            raise EngineeringError("Engineering capability assurance cell is invalid.")
        if not isinstance(cell["production"], bool):
            raise EngineeringError("Engineering capability assurance cell is invalid.")
        normalized_cells.append({"id": _assurance_id(cell["id"], "cell"), "production": cell["production"]})
    cell_ids = {item["id"] for item in normalized_cells}
    if len(cell_ids) != len(normalized_cells):
        raise EngineeringError("Engineering capability assurance cell is invalid.")
    normalized_capabilities = []
    for capability in capabilities:
        base_fields = {"id", "criticality", "required_cells", "required_interfaces", "required_roles"}
        if not isinstance(capability, dict) or set(capability) not in (base_fields, base_fields | {"topology"}):
            raise EngineeringError("Engineering capability assurance capability is invalid.")
        if capability["criticality"] not in {"routine", "material", "critical"}:
            raise EngineeringError("Engineering capability assurance capability is invalid.")
        normalized = {
            "id": _assurance_id(capability["id"], "capability"),
            "criticality": capability["criticality"],
        }
        for field in ("required_cells", "required_interfaces", "required_roles"):
            items = capability[field]
            if not isinstance(items, list) or len(items) > 64:
                raise EngineeringError("Engineering capability assurance capability is invalid.")
            normalized[field] = [_assurance_id(item, field) for item in items]
            if len(set(normalized[field])) != len(normalized[field]):
                raise EngineeringError("Engineering capability assurance capability is invalid.")
        if not normalized["required_cells"] or not normalized["required_interfaces"]:
            raise EngineeringError("Engineering capability assurance capability is invalid.")
        if not set(normalized["required_cells"]).issubset(cell_ids):
            raise EngineeringError("Engineering capability assurance capability is invalid.")
        topology_declared = "topology" in capability
        topology = capability.get("topology", {"artifacts_or_configurations": [], "routes": [], "schedules": []})
        if not isinstance(topology, dict) or set(topology) != {"artifacts_or_configurations", "routes", "schedules"}:
            raise EngineeringError("Engineering capability assurance capability is invalid.")
        normalized["topology"] = {}
        for field in ("artifacts_or_configurations", "routes", "schedules"):
            items = topology[field]
            if not isinstance(items, list) or len(items) > 64:
                raise EngineeringError("Engineering capability assurance capability is invalid.")
            normalized["topology"][field] = [_assurance_id(item, field) for item in items]
            if len(set(normalized["topology"][field])) != len(normalized["topology"][field]):
                raise EngineeringError("Engineering capability assurance capability is invalid.")
        normalized_capabilities.append(normalized)
    capability_ids = {item["id"] for item in normalized_capabilities}
    if len(capability_ids) != len(normalized_capabilities):
        raise EngineeringError("Engineering capability assurance capability is invalid.")
    remediation = {
        "route_observability": "observability",
        "release_identity": "release_evidence",
        "incident_mapping": "incident_mapping",
        "feedback_route": "feedback_route",
    }
    normalized_obligations = []
    for obligation in obligations:
        if not isinstance(obligation, dict) or set(obligation) != {"id", "capability_id", "kind"}:
            raise EngineeringError("Engineering capability assurance obligation is invalid.")
        if obligation["kind"] not in remediation:
            raise EngineeringError("Engineering capability assurance obligation is invalid.")
        normalized = {
            "id": _assurance_id(obligation["id"], "obligation"),
            "capability_id": _assurance_id(obligation["capability_id"], "capability"),
            "kind": obligation["kind"],
        }
        if normalized["capability_id"] not in capability_ids:
            raise EngineeringError("Engineering capability assurance obligation is invalid.")
        normalized_obligations.append(normalized)
    if len({item["id"] for item in normalized_obligations}) != len(normalized_obligations):
        raise EngineeringError("Engineering capability assurance obligation is invalid.")
    return {
        "schema": ASSURANCE_SCHEMA,
        "capabilities": normalized_capabilities,
        "cells": normalized_cells,
        "obligations": normalized_obligations,
    }


def _validated_assurance_observations(observations: object, now: datetime) -> list[dict]:
    if not isinstance(observations, list) or len(observations) > 2048:
        raise EngineeringError("Engineering assurance observations are invalid.")
    normalized = []
    for observation in observations:
        if not isinstance(observation, dict) or not set(observation).issubset(
            {"kind", "result", "severity", "release", "interface", "observed_at", "valid_until", "role", "obligation_id"}
        ):
            raise EngineeringError("Engineering assurance observation is invalid.")
        kind = observation.get("kind")
        if kind not in ASSURANCE_EVIDENCE_KINDS:
            raise EngineeringError("Engineering assurance observation is invalid.")
        if kind == "missing":
            if set(observation) != {"kind", "obligation_id"}:
                raise EngineeringError("Engineering assurance observation is invalid.")
            normalized.append({"kind": "missing", "obligation_id": _assurance_id(observation["obligation_id"], "obligation")})
            continue
        required = {"kind", "result", "release", "interface", "observed_at", "valid_until"}
        if not required.issubset(observation) or observation["result"] not in {"passed", "failed", "accepted", "rejected"}:
            raise EngineeringError("Engineering assurance observation is invalid.")
        normalized_item = {key: observation[key] for key in required}
        normalized_item["release"] = _assurance_id(normalized_item["release"], "release")
        normalized_item["interface"] = _assurance_id(normalized_item["interface"], "interface")
        observed_at = _assurance_timestamp(normalized_item["observed_at"])
        valid_until = _assurance_timestamp(normalized_item["valid_until"])
        if valid_until < observed_at or observed_at > now + timedelta(minutes=5):
            raise EngineeringError("Engineering assurance observation is invalid.")
        for optional in ("severity", "role"):
            if optional in observation:
                normalized_item[optional] = _assurance_id(observation[optional], optional)
        normalized.append(normalized_item)
    return normalized


def reduce_assurance_status(
    manifest: object, capability_id: str, cell_id: str, observations: object, as_of: str
) -> dict:
    assurance = validate_assurance_manifest(manifest)
    capability = next((item for item in assurance["capabilities"] if item["id"] == capability_id), None)
    if capability is None or cell_id not in capability["required_cells"]:
        raise EngineeringError("Engineering assurance capability or cell is invalid.")
    now = _assurance_timestamp(as_of)
    items = _validated_assurance_observations(observations, now)
    current = [item for item in items if item["kind"] != "missing" and _assurance_timestamp(item["valid_until"]) >= now]
    stale = [item for item in items if item["kind"] != "missing" and item not in current]
    interfaces = set(capability["required_interfaces"])
    deployed = {item["interface"] for item in current if item["kind"] == "deployment" and item["result"] == "passed"}
    synthetic = {item["interface"] for item in current if item["kind"] == "synthetic" and item["result"] == "passed"}
    failed = [item for item in current if item["result"] in {"failed", "rejected"}]
    severe = any(item["kind"] == "incident" and item.get("severity") == "severe" for item in failed)
    feedback_roles = {item.get("role") for item in current if item["kind"] == "feedback" and item["result"] == "accepted"}
    deployment = "present" if interfaces.issubset(deployed) else "partial" if deployed else "unknown"
    verification = "failed" if failed else "passed" if interfaces.issubset(synthetic) else "unknown"
    availability = "unavailable" if severe else "healthy" if any(item["kind"] == "availability" and item["result"] == "passed" for item in current) else "unknown"
    acceptance = (
        "not_required" if not capability["required_roles"]
        else "accepted" if set(capability["required_roles"]).issubset(feedback_roles)
        else "pending"
    )
    confidence = "conflicting" if severe or (failed and (deployed or synthetic)) else "strong" if current else "unknown"
    freshness = "current" if current and not stale else "stale" if stale else "unknown"
    lifecycle = "implemented" if any(item["kind"] == "implementation" and item["result"] == "passed" for item in current) else "unknown"
    if severe or verification == "failed" or availability == "unavailable":
        summary = "not_live"
    elif not current:
        summary = "unknown"
    elif deployment == "present" and verification == "passed" and availability == "healthy" and acceptance in {"accepted", "not_required"} and freshness == "current":
        summary = "fully_live"
    else:
        summary = "partially_live"
    return {
        "schema": "engineering.capability-status.v1",
        "capability_id": capability_id,
        "cell_id": cell_id,
        "lifecycle": lifecycle,
        "deployment": deployment,
        "availability": availability,
        "verification": verification,
        "acceptance": acceptance,
        "confidence": confidence,
        "freshness": freshness,
        "summary": summary,
    }


def assurance_recommendations(manifest: object, observations: object) -> dict:
    assurance = validate_assurance_manifest(manifest)
    items = _validated_assurance_observations(observations, datetime.now(timezone.utc))
    obligations = {item["id"]: item for item in assurance["obligations"]}
    remediation = {
        "route_observability": "observability",
        "release_identity": "release_evidence",
        "incident_mapping": "incident_mapping",
        "feedback_route": "feedback_route",
    }
    recommendations = []
    for observation in items:
        if observation["kind"] != "missing" or observation["obligation_id"] not in obligations:
            continue
        obligation = obligations[observation["obligation_id"]]
        recommendations.append(
            {
                "obligation_id": obligation["id"],
                "capability_id": obligation["capability_id"],
                "remediation_class": remediation[obligation["kind"]],
                "title": f"Provide {obligation['kind'].replace('_', ' ')} evidence",
            }
        )
    return {"status": "recommendation", "items": recommendations} if recommendations else {"status": "unknown", "items": []}


def assurance_feedback_request(
    manifest: object, capability_id: str, cell_id: str, observations: object, as_of: str
) -> dict:
    """Produce a role-only request contract; this function never contacts anyone."""
    assurance = validate_assurance_manifest(manifest)
    capability = next((item for item in assurance["capabilities"] if item["id"] == capability_id), None)
    if capability is None:
        raise EngineeringError("Engineering assurance capability or cell is invalid.")
    status = reduce_assurance_status(assurance, capability_id, cell_id, observations, as_of)
    if (
        not capability["required_roles"]
        or status["deployment"] != "present"
        or status["verification"] != "passed"
        or status["acceptance"] != "pending"
    ):
        return {"status": "unknown", "capability_status": status}
    return {
        "schema": "engineering.assurance-feedback.v1",
        "status": "requested",
        "capability_id": capability_id,
        "cell_id": cell_id,
        "roles": sorted(capability["required_roles"]),
        "reason": "declared_role_acceptance_missing",
        "capability_status": status,
    }


def assurance_reaction(status: object) -> dict:
    if not isinstance(status, dict) or status.get("schema") != "engineering.capability-status.v1":
        raise EngineeringError("Engineering capability status is invalid.")
    summary = status.get("summary")
    if summary not in {"fully_live", "partially_live", "not_live", "unknown"}:
        raise EngineeringError("Engineering capability status is invalid.")
    if summary == "fully_live":
        return {"status": "none"}
    action = (
        "owner_decision" if summary == "not_live"
        else "await_feedback" if status.get("acceptance") == "pending"
        else "recheck_evidence"
    )
    identity = {
        "capability_id": status.get("capability_id"),
        "cell_id": status.get("cell_id"),
        "summary": summary,
        "action": action,
    }
    return {"status": "pending", "action": action, "dedupe_key": _json_digest(identity)}


def _assurance_overlay_path(root: Path) -> Path:
    return _project_controller_dir(root) / "assurance-overlay.json"


def _load_assurance_overlay(root: Path) -> list[dict]:
    path = _assurance_overlay_path(root)
    if not path.is_file():
        return []
    _verify_owner_private(path, directory=False)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering assurance overlay is invalid.") from error
    if not isinstance(payload, dict) or set(payload) != {"schema", "observations"} or payload.get("schema") != "engineering.assurance-overlay.v1":
        raise EngineeringError("Engineering assurance overlay is invalid.")
    return payload["observations"]


def assurance_status(root: Path, capability_id: str, cell_id: str, as_of: str | None = None) -> dict:
    project_root = resolve_project_root(str(root))
    declared = load_project_config(project_root).get("assurance")
    if declared is None:
        return {"schema": "engineering.capability-status.v1", "summary": "unknown", "reason": "assurance_not_declared"}
    return reduce_assurance_status(
        declared,
        capability_id,
        cell_id,
        _load_assurance_overlay(project_root),
        as_of or _utc_now(),
    )


def _traceability_receipt(value: object, now: datetime) -> dict:
    """Validate one bounded, non-secret receipt without trusting its live claim."""
    trusted = isinstance(value, dict) and value.get("_traceability_trust_token") is _TRACEABILITY_TRUST_TOKEN
    if trusted:
        value = {key: item for key, item in value.items() if key != "_traceability_trust_token"}
    allowed = {
        "receipt_id", "project_id", "worktree_id", "commit", "checkpoint", "kind", "result", "capability_id", "cell_id", "release", "interface",
        "artifact", "configuration", "route", "schedule", "observed_at", "valid_until",
        "role", "severity", "obligation_id", "admission", "claimed_state", "legacy",
    }
    if not isinstance(value, dict) or not set(value).issubset(allowed):
        raise EngineeringError("Engineering traceability receipt is invalid.")
    if value.get("kind") == "missing":
        obligation = value.get("obligation_id")
        return {"kind": "missing", "obligation_id": _assurance_id(obligation, "obligation"), "admission": "unadmitted", "legacy": True}
    required = {"kind", "result", "release", "interface", "observed_at", "valid_until"}
    if not required.issubset(value):
        raise EngineeringError("Engineering traceability receipt is invalid.")
    if value["kind"] not in ASSURANCE_EVIDENCE_KINDS - {"missing"} or value["result"] not in {"passed", "failed", "accepted", "rejected"}:
        raise EngineeringError("Engineering traceability receipt is invalid.")
    identity_fields = {"receipt_id", "project_id", "worktree_id", "commit", "checkpoint", "capability_id", "cell_id"}
    present_identity_fields = identity_fields.intersection(value)
    legacy = not present_identity_fields
    if present_identity_fields and present_identity_fields != identity_fields:
        raise EngineeringError("Engineering traceability receipt is invalid.")
    if not legacy and not {"route", "schedule"}.issubset(value):
        raise EngineeringError("Engineering traceability receipt is invalid.")
    normalized = {key: value[key] for key in required}
    for key in ("release", "interface"):
        normalized[key] = _assurance_id(normalized[key], key)
    for key in ("receipt_id", "project_id", "checkpoint", "capability_id", "cell_id", "role", "severity", "route", "schedule"):
        if key in value:
            normalized[key] = _assurance_id(value[key], key)
    if "worktree_id" in value:
        normalized["worktree_id"] = _traceability_identity(value["worktree_id"], "worktree_id")
    artifact = value.get("artifact")
    configuration = value.get("configuration")
    if not legacy:
        if bool(artifact) == bool(configuration):
            raise EngineeringError("Engineering traceability receipt is invalid.")
        normalized["artifact" if artifact else "configuration"] = _assurance_id(
            artifact if artifact else configuration, "artifact or configuration"
        )
    observed_at = _assurance_timestamp(normalized["observed_at"])
    valid_until = _assurance_timestamp(normalized["valid_until"])
    if valid_until < observed_at or observed_at > now + timedelta(minutes=5):
        raise EngineeringError("Engineering traceability receipt is invalid.")
    if not legacy:
        commit = value.get("commit")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise EngineeringError("Engineering traceability receipt is invalid.")
        normalized["commit"] = commit
    # Caller labels are non-authoritative. Only the signed-loader path upgrades this.
    normalized["admission"] = "host_attested" if trusted else "unadmitted"
    normalized["legacy"] = legacy
    return normalized


def reduce_traceability_receipts(
    manifest: object, capability_id: str, cell_id: str, receipts: object, as_of: str,
    *, identity: dict | None = None,
) -> dict:
    """Pure, scope-isolated v2 reducer.  It never widens legacy evidence."""
    assurance = validate_assurance_manifest(manifest)
    capability = next((item for item in assurance["capabilities"] if item["id"] == capability_id), None)
    if capability is None or cell_id not in capability["required_cells"]:
        raise EngineeringError("Engineering assurance capability or cell is invalid.")
    now = _assurance_timestamp(as_of)
    if not isinstance(receipts, list) or len(receipts) > 2048:
        raise EngineeringError("Engineering traceability receipts are invalid.")
    normalized = []
    for item in receipts:
        normalized.append(_traceability_receipt(item, now))
    scoped = [item for item in normalized if item.get("capability_id") == capability_id and item.get("cell_id") == cell_id]
    if identity is not None:
        expected = {key: identity.get(key) for key in ("project_id", "worktree_id", "commit", "checkpoint")}
        scoped = [item for item in scoped if all(item.get(key) == value for key, value in expected.items())]
    legacy = [item for item in normalized if "capability_id" not in item or "cell_id" not in item]
    # Select one complete deployment scope.  Interface is deliberately not a
    # grouping key: a capability declaring api + admin must aggregate both
    # interfaces within the same release/artifact/route/schedule scope rather
    # than silently selecting whichever interface was observed most recently.
    def scope_key(item: dict) -> tuple[str, str, str, str]:
        return (
            item["release"], item.get("artifact", item.get("configuration", "")),
            item.get("route", ""), item.get("schedule", ""),
        )
    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    for item in scoped:
        groups.setdefault(scope_key(item), []).append(item)
    selected_key = max(
        groups,
        key=lambda key: (max(_assurance_timestamp(item["observed_at"]) for item in groups[key]), key),
    ) if groups else None
    scoped = groups.get(selected_key, [])
    release = selected_key[0] if selected_key else None
    latest_by_scope: dict[tuple[str, str, str | None], dict] = {}
    for item in scoped:
        key = (
            item["kind"],
            item["interface"],
            item.get("role") if item["kind"] == "feedback" else None,
        )
        prior = latest_by_scope.get(key)
        if prior is None or _assurance_timestamp(item["observed_at"]) > _assurance_timestamp(prior["observed_at"]):
            latest_by_scope[key] = item
    current_by_scope = {
        key: item for key, item in latest_by_scope.items()
        if _assurance_timestamp(item["valid_until"]) >= now
    }
    # Keep the legacy-friendly kind keyed receipt summary while reducing over
    # the full per-interface set above.
    latest: dict[str, dict] = {}
    for item in latest_by_scope.values():
        prior = latest.get(item["kind"])
        if prior is None or _assurance_timestamp(item["observed_at"]) > _assurance_timestamp(prior["observed_at"]):
            latest[item["kind"]] = item
    current = {
        kind: item for kind, item in latest.items()
        if _assurance_timestamp(item["valid_until"]) >= now
    }
    expired = bool(latest_by_scope) and not current_by_scope
    interfaces = set(capability["required_interfaces"])
    topology = capability["topology"]
    required_stages = (
        "intent", "requirement", "decision", "plan", "implementation", "code", "test",
        "artifact", "release", "installation", "configuration", "route", "schedule",
        "interface", "runtime", "deployment", "synthetic", "availability", "feedback",
    )
    gaps = []
    if legacy:
        gaps.append("legacy_unscoped_evidence")
    if any(item["admission"] != "host_attested" for item in current_by_scope.values()):
        gaps.append("authority")
        gaps.append("unadmitted_evidence")
    stale_evidence = expired or any(item not in current_by_scope.values() for item in latest_by_scope.values())
    if stale_evidence:
        gaps.append("freshness")
    artifact_or_configuration = selected_key[1] if selected_key else ""
    if not selected_key or artifact_or_configuration not in topology["artifacts_or_configurations"] or selected_key[2] not in topology["routes"] or selected_key[3] not in topology["schedules"]:
        gaps.append("topology")
    lifecycle_gaps = []
    for stage in required_stages:
        expected = "accepted" if stage == "feedback" else "passed"
        if any(
            not any(
                item["result"] == expected
                for (kind, item_interface, _role), item in current_by_scope.items()
                if kind == stage and item_interface == interface
            )
            for interface in interfaces
        ):
            lifecycle_gaps.append(stage)
    feedback = [item for (kind, _, _), item in current_by_scope.items() if kind == "feedback"]
    feedback_roles = {item.get("role") for item in feedback}
    if capability["required_roles"] and not set(capability["required_roles"]).issubset(feedback_roles):
        gaps.append("acceptance")
    current_interfaces = {item.get("interface") for item in current_by_scope.values()}
    if current_interfaces != interfaces:
        gaps.append("interfaces")
    if capability["required_roles"] and not set(capability["required_roles"]).issubset(feedback_roles):
        gaps.append("roles")
    if lifecycle_gaps:
        gaps.extend(lifecycle_gaps)
    failed = any(item["result"] in {"failed", "rejected"} for item in current_by_scope.values())
    admissible = bool(current_by_scope) and all(item["admission"] == "host_attested" for item in current_by_scope.values())
    ready = not gaps and not lifecycle_gaps and admissible
    state = "not_live" if failed else "verified_live" if ready and admissible else "unknown"
    return {
        "capability_id": capability_id,
        "cell_id": cell_id,
        "release": release,
        "state": state,
        "freshness": "stale" if stale_evidence else "current" if current_by_scope else "unknown",
        "receipts": latest,
        "gaps": sorted(set(gaps)),
        "lifecycle_gaps": lifecycle_gaps,
        "provenance": "host_attested" if admissible else "legacy_or_unadmitted",
    }


def compose_traceability_view(
    manifest: object, receipts: object, context: object, as_of: str
) -> dict:
    """Compose the machine view once; both the CLI and HTML consume its digest."""
    assurance = validate_assurance_manifest(manifest)
    if not isinstance(context, dict) or not isinstance(context.get("commit"), str):
        raise EngineeringError("Engineering traceability view context is invalid.")
    identity = context.get("identity")
    trusted_input = isinstance(receipts, list) and any(
        isinstance(item, dict) and item.get("_traceability_trust_token") is _TRACEABILITY_TRUST_TOKEN
        for item in receipts
    )
    if trusted_input and (
        not isinstance(identity, dict) or any(
            not isinstance(identity.get(key), str) or not identity.get(key)
            for key in ("project_id", "worktree_id", "commit", "checkpoint")
        )
    ):
        raise EngineeringError("Engineering traceability view identity is required for trusted evidence.")
    cells = {item["id"]: item for item in assurance["cells"]}
    capabilities = []
    for capability in assurance["capabilities"]:
        states = [reduce_traceability_receipts(assurance, capability["id"], cell_id, receipts, as_of, identity=identity) for cell_id in capability["required_cells"]]
        verified = [item for item in states if item["state"] == "verified_live"]
        aggregate = {
            "state": "not_live" if any(item["state"] == "not_live" for item in states) else "verified_live" if len(verified) == len(states) else "partial" if verified else "unknown",
            "required_cells": [item["cell_id"] for item in states],
            "missing_required_cells": [item["cell_id"] for item in states if item["state"] != "verified_live"],
            "lifecycle_gaps": sorted({gap for item in states for gap in item["lifecycle_gaps"]}),
        }
        capabilities.append({
            "id": capability["id"], "criticality": capability["criticality"],
            "required_cells": list(capability["required_cells"]),
            "required_interfaces": list(capability["required_interfaces"]),
            "required_roles": list(capability["required_roles"]),
            "topology": capability["topology"],
            "cells": [{**item, "production": cells[item["cell_id"]]["production"]} for item in states],
            "aggregate": aggregate,
        })
    paths = context.get("paths", [])
    if not isinstance(paths, list) or any(
        not isinstance(path, str) or not path or Path(path).is_absolute() or "\\" in path
        or ".." in PurePosixPath(path).parts or re.search(r"(?i)(?:^|/)(?:users|home)(?:/|$)", path)
        for path in paths
    ):
        raise EngineeringError("Engineering traceability view paths are invalid.")
    relationships = context.get("relationships", [])
    if not isinstance(relationships, list) or len(relationships) > 4096:
        raise EngineeringError("Engineering traceability relationships are invalid.")
    for relationship in relationships:
        if not isinstance(relationship, dict) or set(relationship) != {"from", "type", "to", "provenance"}:
            raise EngineeringError("Engineering traceability relationships are invalid.")
        for key in ("from", "type", "provenance"):
            value = relationship[key]
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 256
                or "\\" in value
                or Path(value).is_absolute()
                or ".." in PurePosixPath(value).parts
            ):
                raise EngineeringError("Engineering traceability relationships are invalid.")
        target = relationship["to"]
        if target is not None and (
            not isinstance(target, str)
            or not target
            or len(target) > 256
            or "\\" in target
            or Path(target).is_absolute()
            or ".." in PurePosixPath(target).parts
        ):
            raise EngineeringError("Engineering traceability relationships are invalid.")
    envelope = {
        "project": context.get("project", {}), "worktree": context.get("worktree", {}),
        "commit": context["commit"], "checkpoint": context.get("checkpoint", {}),
        "graphify": context.get("graphify", {"commit": GRAPHIFY_COMMIT}),
        "overlay": context.get("overlay", {"digest": "unknown"}),
        "assurance": context.get("assurance", {"digest": _json_digest(assurance)}),
        "dirty_coverage": context.get("dirty_coverage", "unknown"),
        "authority": context.get("authority", "unknown"),
        "freshness": context.get("freshness", "unknown"),
        "paths": paths, "gaps": context.get("gaps", []),
        "stage_gaps": sorted({gap for capability in capabilities for gap in capability["aggregate"]["lifecycle_gaps"]}),
        "relationships": relationships,
        "focus": context.get("focus", "all"), "aggregate": context.get("aggregate", False),
        "provenance": "deterministic_composition",
    }
    unsigned = {"schema": TRACEABILITY_VIEW_SCHEMA, "as_of": as_of, "envelope": envelope, "capabilities": capabilities}
    return {**unsigned, "digest": _json_digest(unsigned)}


def render_traceability_view_html(view: object) -> str:
    if not isinstance(view, dict) or view.get("schema") != TRACEABILITY_VIEW_SCHEMA or view.get("digest") != _json_digest({key: value for key, value in view.items() if key != "digest"}):
        raise EngineeringError("Engineering traceability view is invalid.")
    rows = "".join(
        f"<tr><th scope='row'>{html.escape(capability['id'])}</th><td>{html.escape(cell['cell_id'])}</td><td>{html.escape(cell['state'])}</td><td>{html.escape(cell['provenance'])}</td><td>{html.escape(', '.join(cell['receipts']) or 'Unknown')}</td><td>{html.escape(', '.join(cell['gaps']) or 'none')}</td></tr>"
        for capability in view["capabilities"] for cell in capability["cells"]
    ) or "<tr><td colspan='6'>No declared capabilities.</td></tr>"
    relationship_rows = "".join(
        f"<tr><td>{html.escape(str(item['from']))}</td><td>{html.escape(str(item['type']))}</td><td>{html.escape(str(item['to']) if item['to'] is not None else 'Unknown')}</td><td>{html.escape(str(item['provenance']))}</td></tr>"
        for item in view["envelope"].get("relationships", [])
    ) or "<tr><td colspan='4'>No declared relationships.</td></tr>"
    authority = view["envelope"]["authority"]
    authority_state = authority.get("state", authority) if isinstance(authority, dict) else authority
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'><title>Engineering traceability</title>"
        "<main><h1>Engineering traceability</h1>"
        f"<p>View digest <code>{html.escape(view['digest'])}</code></p>"
        f"<section aria-label='Evidence banner'><p>Authority: {html.escape(str(authority_state))}</p>"
        f"<p>Freshness: {html.escape(str(view['envelope']['freshness']))}</p></section>"
        "<h2>Lifecycle matrix</h2><table><caption>Capability lifecycle evidence</caption><thead><tr><th>Capability</th><th>Cell</th><th>State</th><th>Provenance</th><th>Receipts</th><th>Gaps</th></tr></thead>"
        f"<tbody>{rows}</tbody></table><h2>Envelope</h2><dl><dt>Checkpoint</dt><dd>{html.escape(str(view['envelope']['checkpoint']))}</dd><dt>Graphify</dt><dd>{html.escape(str(view['envelope']['graphify']))}</dd><dt>Overlay</dt><dd>{html.escape(str(view['envelope']['overlay']))}</dd><dt>Dirty coverage</dt><dd>{html.escape(str(view['envelope']['dirty_coverage']))}</dd></dl>"
        f"<h2>Relationships</h2><table><caption>From, type, to, and provenance</caption><thead><tr><th>From</th><th>Type</th><th>To</th><th>Provenance</th></tr></thead><tbody>{relationship_rows}</tbody></table>"
        f"<h2>Relationship paths</h2><p>Focused upstream/downstream paths: {html.escape(', '.join(view['envelope']['paths']) or 'Unknown')}</p><p>Focus: {html.escape(str(view['envelope'].get('focus', 'all')))}; aggregate: {html.escape(str(view['envelope'].get('aggregate', False)))}</p>"
        f"<h2>Unknowns and gaps</h2><p>{html.escape(', '.join(view['envelope']['gaps']) or 'Unknown')}</p></main></html>"
    )


def _traceability_receipts_path(root: Path) -> Path:
    return _project_controller_dir(root) / "traceability-receipts.json"


def _receipt_admission_material(receipt: object) -> bytes:
    if not isinstance(receipt, dict):
        raise EngineeringError("Engineering traceability receipt is invalid.")
    unsigned = {key: value for key, value in receipt.items() if key not in {"admission", "claimed_state"}}
    return _canonical_json({"schema": "engineering.traceability-receipt-admission.v1", "receipt_digest": _json_digest(unsigned)})


def _traceability_host_claims(receipt: dict) -> dict:
    """Build the exact detached claims a trusted runtime host must sign."""
    return {
        "receipt_digest": _json_digest(receipt),
        "project_id": receipt.get("project_id"),
        "worktree_id": receipt.get("worktree_id"),
        "commit": receipt.get("commit"),
        "checkpoint": receipt.get("checkpoint"),
    }


def _verify_traceability_host_attestation(root: Path, receipt: dict, approval: object) -> str:
    """Verify a new host attestation against the host-owned trust boundary."""
    reference, _ = _verify_host_owned_signature(
        root,
        approval,
        approval_schema=TRACEABILITY_HOST_ATTESTATION_SCHEMA,
        claims_schema="engineering.traceability-host-claims.v3",
        claims=_traceability_host_claims(receipt),
        namespace="engineering-traceability",
        label="Engineering traceability host attestation",
        reference_prefix="traceability-host-attestation-",
        contract="engineering.traceability-host-attestation.v2",
        authority_epoch=None,
    )
    return reference


def _legacy_traceability_host_attestation(value: object) -> bool:
    """Keep v1 receipts readable without admitting their candidate-controlled proof."""
    return isinstance(value, dict) and value.get("schema") == "engineering.traceability-host-attestation.v1"


def _signed_traceability_receipt_payload(
    receipts: object, key: bytes, *, host_attestations: dict[str, dict] | None = None
) -> dict:
    if not isinstance(receipts, list) or len(receipts) > 256:
        raise EngineeringError("Engineering traceability receipt ingestion is invalid.")
    normalized = [
        _traceability_receipt(item, _assurance_timestamp(item["observed_at"]) + timedelta(minutes=5))
        for item in receipts
        if isinstance(item, dict) and isinstance(item.get("observed_at"), str)
    ]
    if len(normalized) != len(receipts):
        raise EngineeringError("Engineering traceability receipt ingestion is invalid.")
    signed = []
    for receipt in normalized:
        material = _receipt_admission_material(receipt)
        digest = json.loads(material.decode("utf-8"))["receipt_digest"]
        admission = {
            "schema": "engineering.traceability-receipt-admission.v1",
            "receipt_digest": digest,
            "signature": "hmac-sha256:" + hmac.new(key, material, hashlib.sha256).hexdigest(),
        }
        if host_attestations and digest in host_attestations:
            admission["host_attestation"] = host_attestations[digest]
        signed.append({
            "receipt": receipt,
            "admission": admission,
        })
    return {"schema": TRACEABILITY_RECEIPTS_SCHEMA, "receipts": signed}


def _load_signed_traceability_receipts_payload(
    payload: object, key: bytes, *, root: Path | None = None
) -> list[dict]:
    if not isinstance(payload, dict) or set(payload) != {"schema", "receipts"} or payload.get("schema") != TRACEABILITY_RECEIPTS_SCHEMA or not isinstance(payload["receipts"], list) or len(payload["receipts"]) > 256:
        raise EngineeringError("Engineering traceability receipts are invalid.")
    retained = []
    for item in payload["receipts"]:
        if not isinstance(item, dict) or set(item) != {"receipt", "admission"} or not isinstance(item["admission"], dict):
            raise EngineeringError("Engineering traceability receipt admission is invalid.")
        if not isinstance(item["receipt"], dict) or not isinstance(item["receipt"].get("observed_at"), str):
            raise EngineeringError("Engineering traceability receipts are invalid.")
        receipt = _traceability_receipt(item["receipt"], _assurance_timestamp(item["receipt"]["observed_at"]) + timedelta(minutes=5))
        material = _receipt_admission_material(receipt)
        admission = item["admission"]
        expected = "hmac-sha256:" + hmac.new(key, material, hashlib.sha256).hexdigest()
        if (
            set(admission) - {"schema", "receipt_digest", "signature", "host_attestation"}
            or admission.get("schema") != "engineering.traceability-receipt-admission.v1"
            or admission.get("receipt_digest") != json.loads(material.decode("utf-8"))["receipt_digest"]
            or not isinstance(admission.get("signature"), str)
            or not hmac.compare_digest(admission["signature"], expected)
        ):
            raise EngineeringError("Engineering traceability receipt admission is invalid.")
        # Controller HMAC protects local storage integrity only. A detached
        # host/adapter proof is required before this process-local token is
        # attached and the receipt can participate in verified-live reduction.
        host_attestation = admission.get("host_attestation")
        if _legacy_traceability_host_attestation(host_attestation):
            # Historical v1 evidence remains inspectable, but it was bound to
            # candidate HEAD and therefore cannot establish present trust.
            pass
        elif host_attestation is not None:
            if root is None:
                raise EngineeringError("Engineering traceability host attestation requires a project root.")
            _verify_traceability_host_attestation(root, receipt, host_attestation)
            receipt["_traceability_trust_token"] = _TRACEABILITY_TRUST_TOKEN
        retained.append(receipt)
    return retained


def issue_traceability_receipt_admission(
    root: Path, receipt: object, host_attestation: object | None = None
) -> dict:
    """Bind storage integrity to a detached, trusted host/adapter signature.

    This helper deliberately does not mint host authority.  The detached
    signature must already be produced through the host-owned authority
    boundary outside the candidate repository.
    """
    project_root = resolve_project_root(str(root))
    normalized = _traceability_receipt(receipt, datetime.now(timezone.utc))
    if host_attestation is None:
        raise EngineeringError("Engineering traceability host attestation is required.")
    _verify_traceability_host_attestation(project_root, normalized, host_attestation)
    key = _controller_key(_project_controller_dir(project_root), required=True)
    assert key is not None
    material = _receipt_admission_material(normalized)
    return {
        "schema": "engineering.traceability-receipt-admission.v1",
        "receipt_digest": json.loads(material.decode("utf-8"))["receipt_digest"],
        "signature": "hmac-sha256:" + hmac.new(key, material, hashlib.sha256).hexdigest(),
        "host_attestation": host_attestation,
    }


def ingest_traceability_receipts(root: Path, receipts: object, admissions: object) -> dict:
    """Persist only bounded host-attested receipts; caller status labels are ignored."""
    project_root = resolve_project_root(str(root))
    if not isinstance(receipts, list) or not isinstance(admissions, list) or len(receipts) > 256 or len(admissions) > 256:
        raise EngineeringError("Engineering traceability receipt ingestion is invalid.")
    key = _controller_key(_project_controller_dir(project_root), required=True)
    assert key is not None
    admissions_by_digest: dict[str, dict] = {}
    for admission in admissions:
        if (
            not isinstance(admission, dict)
            or set(admission) - {"schema", "receipt_digest", "signature", "host_attestation"}
            or admission.get("schema") != "engineering.traceability-receipt-admission.v1"
            or not isinstance(admission.get("receipt_digest"), str)
            or not isinstance(admission.get("signature"), str)
        ):
            raise EngineeringError("Engineering traceability receipt admission is invalid.")
        admissions_by_digest[admission["receipt_digest"]] = admission
    normalized = []
    host_attestations: dict[str, dict] = {}
    now = datetime.now(timezone.utc)
    for raw in receipts:
        receipt = _traceability_receipt(raw, now)
        material = _receipt_admission_material(receipt)
        digest = json.loads(material.decode("utf-8"))["receipt_digest"]
        admission = admissions_by_digest.get(digest)
        expected = "hmac-sha256:" + hmac.new(key, material, hashlib.sha256).hexdigest()
        if admission is None or not hmac.compare_digest(admission.get("signature", ""), expected):
            raise EngineeringError("Engineering traceability receipt admission is invalid.")
        host_attestation = admission.get("host_attestation")
        if host_attestation is not None:
            _verify_traceability_host_attestation(project_root, receipt, host_attestation)
            host_attestations[digest] = host_attestation
        normalized.append(receipt)
    payload = _signed_traceability_receipt_payload(normalized, key, host_attestations=host_attestations)
    path = _traceability_receipts_path(project_root)
    _private_atomic_bytes(path, _canonical_json(payload))
    return {"schema": TRACEABILITY_RECEIPTS_SCHEMA, "accepted": len(normalized), "digest": _json_digest(payload)}


def _load_traceability_receipts(root: Path) -> list[dict]:
    path = _traceability_receipts_path(root)
    if not path.is_file():
        return []
    _verify_owner_private(path, directory=False)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering traceability receipts are invalid.") from error
    key = _controller_key(_project_controller_dir(root), required=True)
    assert key is not None
    return _load_signed_traceability_receipts_payload(payload, key, root=root)


def traceability_view(
    root: Path,
    *,
    as_of: str | None = None,
    focus: str | None = None,
    commit: str | None = None,
) -> dict:
    """Return the canonical v2 machine view without changing project state."""
    project_root = resolve_project_root(str(root))
    target_commit = git(project_root, "rev-parse", commit or "HEAD")
    if commit is None:
        # Preserve the established live-worktree path for compatibility with
        # legacy map/status callers; an explicit --commit is the historical
        # revision path and resolves its manifest from that revision.
        config = load_project_config(project_root)
    else:
        manifest_name = _tracked_manifest_name_at(project_root, target_commit)
        if manifest_name is None:
            raise EngineeringError("manifest_not_tracked")
        config = _json_at(project_root, target_commit, manifest_name)
        config["source_path"] = Path(manifest_name)
    declared = config.get("assurance")
    if declared is None:
        declared = {"schema": ASSURANCE_SCHEMA, "capabilities": [], "cells": [], "obligations": []}
    checkpoint = _load_checkpoint(project_root, target_commit)
    current_status = status(project_root, target_commit=target_commit)
    metadata = checkpoint.get("metadata", {})
    assurance_digest = _json_digest(declared)
    status_lines = git(project_root, "status", "--porcelain", "--untracked-files=all").splitlines()
    dirty_paths = []
    for line in status_lines[:256]:
        path = line[3:] if len(line) >= 4 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        dirty_paths.append(path.replace("\\", "/"))
    context = {
        "project": {"identity": metadata.get("project_identity", metadata.get("project", "unknown"))},
        "worktree": {"branch": metadata.get("branch", "unknown")},
        "commit": target_commit,
        "checkpoint": {"kind": metadata.get("kind", "unknown"), "digest": metadata.get("graph_digest", "unknown")},
        "graphify": {"version": GRAPHIFY_VERSION, "commit": GRAPHIFY_COMMIT, "status": "pinned"},
        "overlay": {"digest": metadata.get("input_digest", "unknown")},
        "assurance": {"digest": assurance_digest},
        "dirty_coverage": {"state": "dirty" if status_lines else "clean", "count": len(status_lines), "paths": dirty_paths, "truncated": len(status_lines) > len(dirty_paths)},
        "authority": {"state": "unknown", "reasons": ["query_does_not_grant_live_authority"]},
        "freshness": current_status.get("freshness", "unknown"),
        "paths": [str(config["source_path"].name).replace("\\", "/")],
        "gaps": [] if current_status.get("freshness") == "current" else ["checkpoint_freshness"],
        "provenance": "local_deterministic_query",
    }
    relationships, focused_paths = _traceability_relationships(checkpoint, focus)
    context["relationships"] = relationships
    context["focus"] = focus or "all"
    context["aggregate"] = focus is None
    if focus:
        context["paths"] = focused_paths
    # v2.2.4 observations remain readable but have no capability/cell scope and
    # therefore cannot establish the v2 verified-live state.
    receipts = _load_traceability_receipts(project_root) + _load_assurance_overlay(project_root)
    context["identity"] = {"project_id": context["project"]["identity"], "worktree_id": context["worktree"]["branch"], "commit": target_commit, "checkpoint": context["checkpoint"]["digest"]}
    return compose_traceability_view(declared, receipts, context, as_of or _utc_now())


def write_traceability_view_html(root: Path, view: object) -> dict:
    project_root = resolve_project_root(str(root))
    document = render_traceability_view_html(view)
    destination = _common_graph_dir(project_root) / "traceability-views" / view["digest"].replace(":", "-") / "index.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    _atomic_text(destination, document)
    return {"output": str(destination), "digest": view["digest"]}


def build_execution_context(
    preparation: object, *, assertions: object = (), forbidden_ids: object = ()
) -> dict:
    if not isinstance(preparation, dict) or preparation.get("schema") != "engineering.prepare.v1":
        raise EngineeringError("Engineering preparation context is invalid.")
    project = preparation.get("project")
    authorization = preparation.get("authorization")
    context = preparation.get("context")
    if not isinstance(project, dict) or not isinstance(authorization, dict) or not isinstance(context, list):
        raise EngineeringError("Engineering preparation context is invalid.")
    if not isinstance(forbidden_ids, (set, list, tuple)) or any(not isinstance(item, str) for item in forbidden_ids):
        raise EngineeringError("Engineering execution context exclusions are invalid.")
    forbidden = sorted(set(forbidden_ids))
    selected = [
        {"id": _assurance_id(item.get("id"), "context identifier"), "provenance": item.get("provenance")}
        for item in context
        if isinstance(item, dict) and item.get("provenance") in EXACT_PROVENANCE and item.get("id") not in forbidden
    ]
    if any(item["provenance"] not in EXACT_PROVENANCE for item in selected):
        raise EngineeringError("Engineering execution context provenance is invalid.")
    selected = list({item["id"]: item for item in selected}.values())[:128]
    if not isinstance(assertions, (list, tuple)) or len(assertions) > 32:
        raise EngineeringError("Engineering execution context assertions are invalid.")
    selected_ids = {item["id"] for item in selected}
    normalized_assertions = []
    for item in assertions:
        if not isinstance(item, dict) or set(item) != {"id", "text"} or item["id"] not in selected_ids:
            raise EngineeringError("Engineering execution context assertions are invalid.")
        text = item["text"]
        if not isinstance(text, str) or not text or len(text) > 256:
            raise EngineeringError("Engineering execution context assertions are invalid.")
        normalized_assertions.append({"id": item["id"], "text": _redact_credentials(text)})
    scope = authorization.get("scope")
    if not isinstance(scope, list) or any(not isinstance(item, str) for item in scope):
        raise EngineeringError("Engineering execution context scope is invalid.")
    bundle = {
        "schema": EXECUTION_CONTEXT_SCHEMA,
        "run_id": _assurance_id(preparation.get("run_id"), "run"),
        "project": {"root_digest": project.get("root_digest"), "commit": project.get("commit")},
        "scope": list(scope),
        "context": selected,
        "assertions": normalized_assertions,
        "forbidden_ids": forbidden,
    }
    owner_intent = preparation.get("owner_intent")
    if owner_intent is not None:
        expected_owner_intent = {
            "schema",
            "state",
            "intent_id",
            "owner_intent_digest",
            "authority_epoch",
            "core_outcome_count",
            "intent_impacting",
            "bound_to_scope_handoff",
        }
        if (
            not isinstance(owner_intent, dict)
            or set(owner_intent) != expected_owner_intent
            or owner_intent.get("schema") != OWNER_INTENT_STATUS_SCHEMA
            or owner_intent.get("state") != "bound"
            or owner_intent.get("intent_impacting") is not True
            or owner_intent.get("bound_to_scope_handoff") is not True
        ):
            raise EngineeringError(
                "Engineering execution context owner intent is unknown or unbound."
            )
        try:
            bundle["owner_intent"] = {
                "intent_id": _assurance_id(owner_intent["intent_id"], "execution owner intent"),
                "owner_intent_digest": owner_intent["owner_intent_digest"],
                "authority_epoch": _assurance_id(owner_intent["authority_epoch"], "execution owner intent epoch"),
            }
        except EngineeringError as error:
            raise EngineeringError("Engineering execution context owner intent is invalid.") from error
        if not re.fullmatch(
            r"sha256:[0-9a-f]{64}", bundle["owner_intent"]["owner_intent_digest"]
        ):
            raise EngineeringError("Engineering execution context owner intent is invalid.")
    if not isinstance(bundle["project"]["root_digest"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", bundle["project"]["root_digest"]) or not isinstance(bundle["project"]["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", bundle["project"]["commit"]):
        raise EngineeringError("Engineering execution context project is invalid.")
    return {**bundle, "digest": _json_digest(bundle)}


def validate_execution_context(bundle: object, preparation: object, *, runner_enforces_boundary: bool) -> dict:
    required = {
        "schema", "run_id", "project", "scope", "context", "assertions", "forbidden_ids", "digest"
    }
    allowed = {frozenset(required), frozenset(required | {"owner_intent"})}
    if (
        not isinstance(bundle, dict)
        or frozenset(bundle) not in allowed
        or bundle.get("schema") != EXECUTION_CONTEXT_SCHEMA
    ):
        raise EngineeringError("Engineering execution context is invalid.")
    unsigned = {key: value for key, value in bundle.items() if key != "digest"}
    if bundle.get("digest") != _json_digest(unsigned):
        raise EngineeringError("Engineering execution context digest is invalid.")
    expected = build_execution_context(
        preparation,
        assertions=bundle["assertions"],
        forbidden_ids=set(bundle["forbidden_ids"]),
    )
    if expected != bundle:
        raise EngineeringError("Engineering execution context scope or provenance changed.")
    if not isinstance(runner_enforces_boundary, bool):
        raise EngineeringError("Engineering runner boundary mode is invalid.")
    return {"schema": EXECUTION_CONTEXT_SCHEMA, "mode": "enforced" if runner_enforces_boundary else "advisory", "bundle": bundle}


def _task_authority_signature(key: bytes, authority: dict) -> str:
    material = {
        name: authority[name]
        for name in (
            "schema",
            "task_id",
            "repository_id",
            "commit",
            "commands_digest",
            "effects",
            "issued_at",
            "valid_until",
        )
    }
    return "hmac-sha256:" + hmac.new(key, _canonical_json(material), hashlib.sha256).hexdigest()


def issue_task_check_authority(root: Path, task_id: str) -> dict:
    """The trusted host calls this after task approval; the CLI never invents it."""
    project = resolve_project(root)
    claims = _check_capability_claims(project.root, discover_checks(project.root))
    issued = datetime.now(timezone.utc)
    authority = {
        "schema": TASK_AUTHORITY_SCHEMA,
        "task_id": _assurance_id(task_id, "task authority"),
        "repository_id": claims["repository_id"],
        "commit": project.commit,
        "commands_digest": claims["commands_digest"],
        "effects": {name: False for name in sorted(TASK_CHECK_EFFECTS)},
        "issued_at": issued.isoformat(),
        "valid_until": (issued + timedelta(hours=1)).isoformat(),
    }
    key = _controller_key(_project_controller_dir(project.root), required=True)
    assert key is not None
    authority["signature"] = _task_authority_signature(key, authority)
    return authority


def validate_task_check_authority(root: Path, authority: object, claims: object) -> dict:
    if not isinstance(authority, dict) or set(authority) != {
        "schema",
        "task_id",
        "repository_id",
        "commit",
        "commands_digest",
        "effects",
        "issued_at",
        "valid_until",
        "signature",
    }:
        raise EngineeringError("Engineering routine check authority is invalid.")
    if authority.get("schema") != TASK_AUTHORITY_SCHEMA or not isinstance(claims, dict):
        raise EngineeringError("Engineering routine check authority is invalid.")
    task_id = _assurance_id(authority.get("task_id"), "task authority")
    project = resolve_project(root)
    digest = authority.get("commands_digest")
    effects = authority.get("effects")
    issued = _assurance_timestamp(authority.get("issued_at"))
    valid_until = _assurance_timestamp(authority.get("valid_until"))
    now = datetime.now(timezone.utc)
    if (
        not isinstance(digest, str)
        or digest != claims.get("commands_digest")
        or authority.get("repository_id") != claims.get("repository_id")
        or authority.get("commit") != project.commit
        or valid_until < now
        or issued > now + timedelta(minutes=5)
        or valid_until - issued > timedelta(hours=1)
        or claims.get("inline_code") is not False
        or claims.get("shell_free") is not True
        or not isinstance(effects, dict)
        or set(effects) != TASK_CHECK_EFFECTS
        or any(value is not False for value in effects.values())
    ):
        raise EngineeringError("Engineering routine check authority is invalid.")
    key = _controller_key(_project_controller_dir(project.root), required=True)
    assert key is not None
    if not hmac.compare_digest(str(authority["signature"]), _task_authority_signature(key, authority)):
        raise EngineeringError("Engineering routine check authority is invalid.")
    return {
        "schema": TASK_AUTHORITY_SCHEMA,
        "task_id": task_id,
        "repository_id": authority["repository_id"],
        "commit": authority["commit"],
        "commands_digest": digest,
        "valid_until": authority["valid_until"],
    }


def _scoped_authority_path(root: Path) -> Path:
    path = _project_controller_dir(root) / "authority-ledger.json"
    _reject_reparse_ancestors(path)
    return path


def _scoped_authority_values(
    value: object, field: str, *, paths: bool = False, allow_empty: bool = False
) -> list[str]:
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or len(value) > 256
        or any(not isinstance(item, str) or not item or len(item) > 512 for item in value)
    ):
        raise EngineeringError(f"Engineering scoped authority {field} is invalid.")
    normalized = []
    for item in value:
        if _contains_credential(item):
            raise EngineeringError(f"Engineering scoped authority {field} is invalid.")
        candidate = item.replace("\\", "/") if paths else _assurance_id(item, field)
        if paths and (Path(candidate).is_absolute() or ".." in Path(candidate).parts):
            raise EngineeringError(f"Engineering scoped authority {field} is invalid.")
        normalized.append(candidate)
    return sorted(set(normalized))


def _scoped_authority_binding(root: Path, binding: object) -> dict:
    expected = {
        "authority_epoch",
        "target",
        "action_class",
        "scope",
        "safeguards",
        "native_requirements",
        "issued_at",
        "expires_at",
    }
    if not isinstance(binding, dict) or set(binding) != expected:
        raise EngineeringError("Engineering scoped authority binding is invalid.")
    issued = _assurance_timestamp(binding.get("issued_at"))
    expires = _assurance_timestamp(binding.get("expires_at"))
    now = datetime.now(timezone.utc)
    if (
        issued > now + timedelta(minutes=5)
        or expires <= issued
        or expires - issued > timedelta(days=30)
    ):
        raise EngineeringError("Engineering scoped authority lifetime is invalid.")
    native = _scoped_authority_values(
        binding.get("native_requirements"), "native requirements", allow_empty=True
    )
    action_class = _assurance_id(binding.get("action_class"), "authority action class")
    if action_class in NATIVE_APPROVAL_REQUIREMENTS:
        native = sorted(set(native) | {action_class})
    if any(item not in NATIVE_APPROVAL_REQUIREMENTS for item in native):
        raise EngineeringError("Engineering scoped authority native requirements are invalid.")
    return {
        "repository_id": _project_contribution_digest(resolve_project_root(str(root))),
        "authority_epoch": _assurance_id(binding.get("authority_epoch"), "authority epoch"),
        "target": _assurance_id(binding.get("target"), "authority target"),
        "action_class": action_class,
        "scope": _scoped_authority_values(binding.get("scope"), "scope", paths=True),
        "safeguards": _scoped_authority_values(binding.get("safeguards"), "safeguards"),
        "native_requirements": native,
        "issued_at": issued.isoformat(),
        "expires_at": expires.isoformat(),
    }


def _scoped_authority_signature(key: bytes, record: dict) -> str:
    material = {name: record[name] for name in record if name != "signature"}
    return "hmac-sha256:" + hmac.new(
        key, _canonical_json(material), hashlib.sha256
    ).hexdigest()


def _authority_audit_signature(key: bytes, event: dict) -> str:
    material = {name: event[name] for name in event if name != "signature"}
    return "hmac-sha256:" + hmac.new(
        key, _canonical_json(material), hashlib.sha256
    ).hexdigest()


def _load_scoped_authorities(root: Path) -> dict:
    path = _scoped_authority_path(root)
    if not path.exists():
        return {"schema": AUTHORITY_LEDGER_SCHEMA, "authorities": [], "audits": []}
    controller = path.parent
    key = _controller_key(controller, required=True)
    assert key is not None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering scoped authority ledger is invalid.") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "authorities", "audits"}
        or payload.get("schema") != AUTHORITY_LEDGER_SCHEMA
        or not isinstance(payload.get("authorities"), list)
        or not isinstance(payload.get("audits"), list)
        or len(payload["authorities"]) > MAX_SCOPED_AUTHORITIES
        or len(payload["audits"]) > MAX_AUTHORITY_AUDITS
    ):
        raise EngineeringError("Engineering scoped authority ledger is invalid.")
    authority_ids: set[str] = set()
    legacy_authority_fields = {
        "schema",
        "authority_id",
        "repository_id",
        "authority_epoch",
        "target",
        "action_class",
        "scope",
        "safeguards",
        "native_requirements",
        "approval_reference",
        "parent_authority_id",
        "issued_at",
        "expires_at",
        "status",
        "transitioned_at",
        "signature",
    }
    authority_fields = legacy_authority_fields | {"approval_trust_anchor"}
    for record in payload["authorities"]:
        if (
            not isinstance(record, dict)
            or frozenset(record) not in {
                frozenset(legacy_authority_fields),
                frozenset(authority_fields),
            }
            or record.get("schema") != SCOPED_AUTHORITY_SCHEMA
            or not re.fullmatch(r"authority-[0-9a-f]{32}", str(record.get("authority_id", "")))
            or record["authority_id"] in authority_ids
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(record.get("repository_id", "")))
            or record.get("status") not in {"active", "revoked", "consumed"}
            or (record.get("status") == "active") != (record.get("transitioned_at") is None)
            or not hmac.compare_digest(
                str(record.get("signature", "")), _scoped_authority_signature(key, record)
            )
        ):
            raise EngineeringError("Engineering scoped authority ledger is invalid.")
        try:
            _assurance_id(record["authority_epoch"], "authority epoch")
            _assurance_id(record["target"], "authority target")
            _assurance_id(record["action_class"], "authority action class")
            _assurance_id(record["approval_reference"], "authority approval reference")
            if "approval_trust_anchor" in record:
                _host_trust_anchor(record["approval_trust_anchor"])
            native = _scoped_authority_values(
                record["native_requirements"], "native requirements", allow_empty=True
            )
            _scoped_authority_values(record["scope"], "scope", paths=True)
            _scoped_authority_values(record["safeguards"], "safeguards")
            issued = _assurance_timestamp(record["issued_at"])
            expires = _assurance_timestamp(record["expires_at"])
            transitioned = (
                _assurance_timestamp(record["transitioned_at"])
                if record["transitioned_at"] is not None
                else None
            )
        except EngineeringError as error:
            raise EngineeringError("Engineering scoped authority ledger is invalid.") from error
        if native != record["native_requirements"] or any(
            item not in NATIVE_APPROVAL_REQUIREMENTS for item in native
        ) or expires <= issued or expires - issued > timedelta(days=30) or (
            transitioned is not None and transitioned < issued
        ):
            raise EngineeringError("Engineering scoped authority ledger is invalid.")
        parent = record.get("parent_authority_id")
        if parent is not None and not re.fullmatch(r"authority-[0-9a-f]{32}", str(parent)):
            raise EngineeringError("Engineering scoped authority ledger is invalid.")
        authority_ids.add(record["authority_id"])
    audit_ids: set[str] = set()
    audit_fields = {
        "schema",
        "event_id",
        "authority_id",
        "artifact_digest",
        "auditor_ref",
        "verdict",
        "observed_at",
        "signature",
    }
    for event in payload["audits"]:
        if (
            not isinstance(event, dict)
            or set(event) != audit_fields
            or event.get("schema") != AUTHORITY_AUDIT_SCHEMA
            or not re.fullmatch(r"audit-[0-9a-f]{32}", str(event.get("event_id", "")))
            or event["event_id"] in audit_ids
            or event.get("authority_id") not in authority_ids
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(event.get("artifact_digest", "")))
            or event.get("verdict") not in {"accepted", "rejected"}
            or not hmac.compare_digest(
                str(event.get("signature", "")), _authority_audit_signature(key, event)
            )
        ):
            raise EngineeringError("Engineering scoped authority ledger is invalid.")
        _assurance_id(event.get("auditor_ref"), "authority auditor reference")
        _assurance_timestamp(event.get("observed_at"))
        audit_ids.add(event["event_id"])
    if any(
        record["parent_authority_id"] is not None
        and record["parent_authority_id"] not in authority_ids
        for record in payload["authorities"]
    ):
        raise EngineeringError("Engineering scoped authority ledger is invalid.")
    return payload


def _publish_scoped_authorities(root: Path, ledger: dict, key_bytes: bytes | None) -> None:
    path = _scoped_authority_path(root)
    controller = path.parent
    if (
        len(ledger.get("authorities", [])) > MAX_SCOPED_AUTHORITIES
        or len(ledger.get("audits", [])) > MAX_AUTHORITY_AUDITS
        or len(json.dumps(ledger).encode("utf-8")) > 1024 * 1024
    ):
        raise EngineeringError("Engineering scoped authority ledger exceeds its bounded size.")
    controller.mkdir(parents=True, exist_ok=True)
    _enforce_owner_private(controller)
    encoded_key = key_bytes.hex().encode("ascii") + b"\n" if key_bytes is not None else None
    _transactional_json_documents(
        [(path, ledger)],
        [(_controller_key_path(controller), encoded_key)] if encoded_key is not None else None,
    )


def _begin_authority_mutation(root: Path, kind: str) -> dict:
    """Acquire the shared repository lock without performing unrelated graph recovery."""
    operation = register_hook_operation(root)
    record = _read_operation(root, operation["operation_id"])
    record["kind"] = kind
    _write_operation(record)
    deadline = time.monotonic() + 2.0
    while not _acquire_repository_lock(record):
        if time.monotonic() >= deadline:
            _discard_unlocked_operation(root, record["operation_id"])
            raise EngineeringError("Engineering scoped authority repository lock timed out.")
        time.sleep(0.01)
    return _read_operation(root, record["operation_id"])


def _verify_host_authority_approval(root: Path, normalized: dict, approval: object) -> tuple[str, dict]:
    return _verify_host_owned_signature(
        root,
        approval,
        approval_schema=HOST_AUTHORITY_APPROVAL_SCHEMA,
        claims_schema="engineering.host-authority-claims.v3",
        claims=normalized,
        namespace="engineering-authority",
        label="Engineering scoped authority host approval",
        reference_prefix="approval-",
        contract=SCOPED_AUTHORITY_SCHEMA,
        authority_epoch=normalized["authority_epoch"],
    )
def _owner_intent_path(root: Path) -> Path:
    path = _project_controller_dir(root) / "owner-intents.json"
    _reject_reparse_ancestors(path)
    return path


def _owner_intent_predecessor(value: object) -> dict:
    """Normalize an explicit owner-approved transition from the active baseline."""
    if (
        isinstance(value, dict)
        and set(value) == {"schema", "state"}
        and value.get("schema") == OWNER_INTENT_PREDECESSOR_SCHEMA
        and value.get("state") == "none"
    ):
        return {"schema": OWNER_INTENT_PREDECESSOR_SCHEMA, "state": "none"}
    expected = {
        "schema",
        "state",
        "intent_id",
        "owner_intent_digest",
        "dispositions",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != OWNER_INTENT_PREDECESSOR_SCHEMA
        or value.get("state") != "successor"
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", str(value.get("owner_intent_digest", ""))
        )
        or not isinstance(value.get("dispositions"), list)
        or not value["dispositions"]
        or len(value["dispositions"]) > MAX_OWNER_INTENT_OUTCOMES
    ):
        raise EngineeringError("Engineering owner intent predecessor is invalid.")
    dispositions = []
    outcome_ids: set[str] = set()
    successor_ids: set[str] = set()
    for item in value["dispositions"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"outcome_id", "disposition", "successor_outcome_id"}
            or item.get("disposition") not in OWNER_INTENT_PREDECESSOR_DISPOSITIONS
        ):
            raise EngineeringError("Engineering owner intent predecessor disposition is invalid.")
        outcome_id = _assurance_id(item.get("outcome_id"), "owner intent predecessor outcome")
        successor = item.get("successor_outcome_id")
        if successor is not None:
            successor = _assurance_id(
                successor, "owner intent predecessor successor outcome"
            )
        disposition = item["disposition"]
        if (
            outcome_id in outcome_ids
            or (successor is not None and successor in successor_ids)
            or (disposition == "CARRIED_FORWARD" and successor != outcome_id)
            or (disposition == "REPLACED" and (successor is None or successor == outcome_id))
            or (disposition in {"DEFERRED", "EXCLUDED"} and successor is not None)
        ):
            raise EngineeringError("Engineering owner intent predecessor disposition is invalid.")
        outcome_ids.add(outcome_id)
        if successor is not None:
            successor_ids.add(successor)
        dispositions.append(
            {
                "outcome_id": outcome_id,
                "disposition": disposition,
                "successor_outcome_id": successor,
            }
        )
    return {
        "schema": OWNER_INTENT_PREDECESSOR_SCHEMA,
        "state": "successor",
        "intent_id": _assurance_id(value.get("intent_id"), "owner intent predecessor"),
        "owner_intent_digest": value["owner_intent_digest"],
        "dispositions": sorted(dispositions, key=lambda item: item["outcome_id"]),
    }


def _owner_intent_binding(root: Path, value: object) -> dict:
    legacy_expected = {
        "schema",
        "intent_id",
        "repository_id",
        "authority_epoch",
        "source_evidence",
        "outcomes",
    }
    expected = legacy_expected | {"predecessor"}
    if (
        not isinstance(value, dict)
        or set(value) not in (legacy_expected, expected)
        or value.get("schema") != OWNER_INTENT_SCHEMA
    ):
        raise EngineeringError("Engineering owner intent binding is invalid.")
    repository_id = value.get("repository_id")
    expected_repository = _project_contribution_digest(resolve_project_root(str(root)))
    if repository_id != expected_repository:
        raise EngineeringError("Engineering owner intent repository binding is invalid.")
    source_evidence = value.get("source_evidence")
    outcomes = value.get("outcomes")
    if (
        not isinstance(source_evidence, list)
        or not source_evidence
        or len(source_evidence) > MAX_OWNER_INTENT_EVIDENCE
        or not isinstance(outcomes, list)
        or not outcomes
        or len(outcomes) > MAX_OWNER_INTENT_OUTCOMES
    ):
        raise EngineeringError("Engineering owner intent binding is invalid.")
    normalized_sources = []
    source_ids: set[str] = set()
    for source in source_evidence:
        if (
            not isinstance(source, dict)
            or set(source) != {"identity", "digest"}
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(source.get("digest", "")))
        ):
            raise EngineeringError("Engineering owner intent source evidence is invalid.")
        identity = _assurance_id(source.get("identity"), "owner intent source evidence")
        if identity in source_ids:
            raise EngineeringError("Engineering owner intent source evidence is duplicated.")
        source_ids.add(identity)
        normalized_sources.append({"identity": identity, "digest": source["digest"]})
    normalized_outcomes = []
    outcome_ids: set[str] = set()
    for outcome in outcomes:
        if (
            not isinstance(outcome, dict)
            or set(outcome) != {"id", "criticality", "statement_digest", "required_evidence"}
            or outcome.get("criticality") not in OWNER_INTENT_CRITICALITIES
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(outcome.get("statement_digest", "")))
            or not isinstance(outcome.get("required_evidence"), list)
            or not outcome["required_evidence"]
            or len(outcome["required_evidence"]) > 16
        ):
            raise EngineeringError("Engineering owner intent outcome is invalid.")
        outcome_id = _assurance_id(outcome.get("id"), "owner intent outcome")
        if outcome_id in outcome_ids:
            raise EngineeringError("Engineering owner intent outcome is duplicated.")
        outcome_ids.add(outcome_id)
        requirements = []
        requirement_keys: set[tuple[str, str, str]] = set()
        for requirement in outcome["required_evidence"]:
            if (
                not isinstance(requirement, dict)
                or set(requirement) != {"class", "interface", "environment"}
                or requirement.get("class") not in OUTCOME_EVIDENCE_CLASSES
            ):
                raise EngineeringError("Engineering owner intent evidence requirement is invalid.")
            interface = _assurance_id(requirement.get("interface"), "owner intent evidence interface")
            environment = _assurance_id(requirement.get("environment"), "owner intent evidence environment")
            key = (requirement["class"], interface, environment)
            if key in requirement_keys:
                raise EngineeringError("Engineering owner intent evidence requirement is duplicated.")
            requirement_keys.add(key)
            requirements.append(
                {
                    "class": requirement["class"],
                    "interface": interface,
                    "environment": environment,
                }
            )
        normalized_outcomes.append(
            {
                "id": outcome_id,
                "criticality": outcome["criticality"],
                "statement_digest": outcome["statement_digest"],
                "required_evidence": sorted(
                    requirements,
                    key=lambda item: (item["class"], item["interface"], item["environment"]),
                ),
            }
        )
    normalized = {
        "schema": OWNER_INTENT_SCHEMA,
        "intent_id": _assurance_id(value.get("intent_id"), "owner intent"),
        "repository_id": repository_id,
        "authority_epoch": _assurance_id(value.get("authority_epoch"), "owner intent authority epoch"),
        "source_evidence": sorted(normalized_sources, key=lambda item: item["identity"]),
        "outcomes": sorted(normalized_outcomes, key=lambda item: item["id"]),
    }
    if "predecessor" in value:
        normalized["predecessor"] = _owner_intent_predecessor(value["predecessor"])
    return normalized


def _owner_intent_signature(key: bytes, record: dict) -> str:
    material = {name: value for name, value in record.items() if name != "signature"}
    return "hmac-sha256:" + hmac.new(key, _canonical_json(material), hashlib.sha256).hexdigest()


def _load_owner_intents(root: Path) -> dict:
    path = _owner_intent_path(root)
    if not path.exists():
        return {"schema": OWNER_INTENT_LEDGER_SCHEMA, "intents": []}
    _verify_owner_private(path, directory=False)
    key = _controller_key(_project_controller_dir(root), required=True)
    assert key is not None
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering owner intent ledger is invalid.") from error
    if (
        not isinstance(ledger, dict)
        or set(ledger) != {"schema", "intents"}
        or ledger.get("schema") != OWNER_INTENT_LEDGER_SCHEMA
        or not isinstance(ledger.get("intents"), list)
        or len(ledger["intents"]) > MAX_OWNER_INTENTS
    ):
        raise EngineeringError("Engineering owner intent ledger is invalid.")
    active = 0
    digests: set[str] = set()
    for record in ledger["intents"]:
        legacy_binding_fields = {
            "schema",
            "intent_id",
            "repository_id",
            "authority_epoch",
            "source_evidence",
            "outcomes",
        }
        binding_fields = legacy_binding_fields | {"predecessor"}
        receipt_fields = {
            "owner_intent_digest",
            "approval_reference",
            "bound_at",
            "status",
            "signature",
        }
        expected_records = (
            legacy_binding_fields | receipt_fields,
            legacy_binding_fields | receipt_fields | {"approval_trust_anchor"},
            binding_fields | receipt_fields,
            binding_fields | receipt_fields | {"approval_trust_anchor"},
        )
        if not isinstance(record, dict) or set(record) not in expected_records:
            raise EngineeringError("Engineering owner intent ledger is invalid.")
        binding = {
            name: record[name]
            for name in (
                "schema",
                "intent_id",
                "repository_id",
                "authority_epoch",
                "source_evidence",
                "outcomes",
                "predecessor",
            )
            if name in record
        }
        try:
            normalized = _owner_intent_binding(root, binding)
            _assurance_id(record["approval_reference"], "owner intent approval reference")
            _assurance_timestamp(record["bound_at"])
            if "approval_trust_anchor" in record:
                _host_trust_anchor(record["approval_trust_anchor"])
        except EngineeringError as error:
            raise EngineeringError("Engineering owner intent ledger is invalid.") from error
        if (
            normalized != binding
            or record.get("status") not in {"active", "superseded"}
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(record.get("owner_intent_digest", "")))
            or record["owner_intent_digest"] != _json_digest(binding)
            or record["owner_intent_digest"] in digests
            or not hmac.compare_digest(str(record.get("signature", "")), _owner_intent_signature(key, record))
        ):
            raise EngineeringError("Engineering owner intent ledger is invalid.")
        digests.add(record["owner_intent_digest"])
        active += int(record["status"] == "active")
    if active > 1:
        raise EngineeringError("Engineering owner intent ledger is ambiguous.")
    return ledger


def _publish_owner_intents(root: Path, ledger: dict, new_key: bytes | None) -> None:
    if (
        len(ledger.get("intents", [])) > MAX_OWNER_INTENTS
        or len(json.dumps(ledger).encode("utf-8")) > 1024 * 1024
    ):
        raise EngineeringError("Engineering owner intent ledger exceeds its bounded size.")
    controller = _project_controller_dir(root)
    controller.mkdir(parents=True, exist_ok=True)
    _enforce_owner_private(controller)
    binary = (
        [(_controller_key_path(controller), new_key.hex().encode("ascii") + b"\n")]
        if new_key is not None
        else None
    )
    _transactional_json_documents([(_owner_intent_path(root), ledger)], binary)


def _validate_owner_intent_predecessor_transition(ledger: dict, normalized: dict) -> None:
    """Require a signed successor to account for every active approved outcome."""
    predecessor = normalized.get("predecessor")
    if not isinstance(predecessor, dict):
        raise EngineeringError(
            "Engineering new owner intent requires explicit predecessor dispositions."
        )
    active = [record for record in ledger["intents"] if record["status"] == "active"]
    if len(active) > 1:
        raise EngineeringError("Engineering owner intent ledger is ambiguous.")
    if not active:
        if predecessor != {
            "schema": OWNER_INTENT_PREDECESSOR_SCHEMA,
            "state": "none",
        }:
            raise EngineeringError(
                "Engineering first owner intent predecessor must declare no active baseline."
            )
        return
    prior = active[0]
    if (
        predecessor.get("state") != "successor"
        or predecessor.get("intent_id") != prior["intent_id"]
        or predecessor.get("owner_intent_digest") != prior["owner_intent_digest"]
    ):
        raise EngineeringError(
            "Engineering owner intent predecessor does not bind the active baseline."
        )
    prior_outcomes = {item["id"]: item for item in prior["outcomes"]}
    next_outcomes = {item["id"]: item for item in normalized["outcomes"]}
    dispositions = predecessor.get("dispositions")
    if not isinstance(dispositions, list):
        raise EngineeringError("Engineering owner intent predecessor dispositions are invalid.")
    by_outcome = {item.get("outcome_id"): item for item in dispositions}
    if len(by_outcome) != len(dispositions) or set(by_outcome) != set(prior_outcomes):
        raise EngineeringError(
            "Engineering owner intent predecessor dispositions are incomplete."
        )
    for outcome_id, item in by_outcome.items():
        disposition = item["disposition"]
        successor_id = item["successor_outcome_id"]
        if disposition == "CARRIED_FORWARD":
            if (
                successor_id != outcome_id
                or next_outcomes.get(outcome_id) != prior_outcomes[outcome_id]
            ):
                raise EngineeringError(
                    "Engineering owner intent predecessor carry-forward is mismatched."
                )
        elif disposition == "REPLACED":
            if successor_id not in next_outcomes or successor_id == outcome_id:
                raise EngineeringError(
                    "Engineering owner intent predecessor replacement is mismatched."
                )
        elif disposition in {"DEFERRED", "EXCLUDED"}:
            if successor_id is not None or outcome_id in next_outcomes:
                raise EngineeringError(
                    "Engineering owner intent predecessor disposition is mismatched."
                )
        else:
            raise EngineeringError("Engineering owner intent predecessor disposition is invalid.")


def _verify_host_owner_intent_approval(root: Path, normalized: dict, approval: object) -> tuple[str, dict]:
    return _verify_host_owned_signature(
        root,
        approval,
        approval_schema=HOST_OWNER_INTENT_APPROVAL_SCHEMA,
        claims_schema="engineering.host-owner-intent-claims.v3",
        claims=normalized,
        namespace="engineering-owner-intent",
        label="Engineering owner intent host approval",
        reference_prefix="owner-intent-approval-",
        contract=OWNER_INTENT_SCHEMA,
        authority_epoch=normalized["authority_epoch"],
    )
def bind_owner_intent(root: Path, binding: object, approval: object) -> dict:
    """Persist a host-approved owner baseline; callers cannot self-approve it."""
    project_root = resolve_project_root(str(root))
    normalized = _owner_intent_binding(project_root, binding)
    if "predecessor" not in normalized:
        raise EngineeringError(
            "Engineering new owner intent requires explicit predecessor dispositions."
        )
    approval_reference, approval_trust_anchor = _verify_host_owner_intent_approval(
        project_root, normalized, approval
    )
    operation = _begin_authority_mutation(project_root, "owner-intent-bind")
    try:
        ledger = _load_owner_intents(project_root)
        digest = _json_digest(normalized)
        matches = [
            record
            for record in ledger["intents"]
            if record["owner_intent_digest"] == digest
        ]
        if matches:
            if (
                len(matches) != 1
                or matches[0]["approval_reference"] != approval_reference
                or matches[0].get("approval_trust_anchor") != approval_trust_anchor
            ):
                raise EngineeringError("Engineering owner intent replay conflicts with retained state.")
            return dict(matches[0])
        _validate_owner_intent_predecessor_transition(ledger, normalized)
        controller = _project_controller_dir(project_root)
        key = _controller_key(controller, required=False)
        new_key = os.urandom(32) if key is None else None
        key = key or new_key
        assert key is not None
        for existing in ledger["intents"]:
            if existing["status"] == "active":
                existing["status"] = "superseded"
                existing["signature"] = _owner_intent_signature(key, existing)
        record = {
            **normalized,
            "owner_intent_digest": digest,
            "approval_reference": approval_reference,
            "approval_trust_anchor": approval_trust_anchor,
            "bound_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        }
        record["signature"] = _owner_intent_signature(key, record)
        ledger["intents"].append(record)
        ledger["intents"].sort(key=lambda item: item["owner_intent_digest"])
        _publish_owner_intents(project_root, ledger, new_key)
        return dict(record)
    finally:
        _end_completion(project_root, operation)


def owner_intent_status(root: Path, authority_id: str | None = None) -> dict:
    project_root = resolve_project_root(str(root))
    if authority_id is not None:
        authority_id = _assurance_id(authority_id, "owner intent")
    ledger = _load_owner_intents(project_root)
    candidates = [
        record
        for record in ledger["intents"]
        if authority_id is None or record["intent_id"] == authority_id
    ]
    active = [record for record in candidates if record["status"] == "active"]
    if len(active) > 1:
        raise EngineeringError("Engineering owner intent status is ambiguous.")
    record = (
        active[0]
        if active
        and isinstance(active[0].get("approval_trust_anchor"), dict)
        and active[0]["approval_trust_anchor"].get("schema") == HOST_TRUST_ANCHOR_SCHEMA
        else None
    )
    return {
        "schema": OWNER_INTENT_STATUS_SCHEMA,
        "state": "bound" if record is not None else "owner_intent_unknown",
        "intent_id": record["intent_id"] if record is not None else authority_id,
        "owner_intent_digest": record["owner_intent_digest"] if record is not None else None,
        "authority_epoch": record["authority_epoch"] if record is not None else None,
        "core_outcome_count": sum(
            item["criticality"] == "core" for item in record["outcomes"]
        ) if record is not None else 0,
        "post_activation_import_state": (
            "complete"
            if record is not None and _active_owner_intent_import(project_root, record) is not None
            else "required"
            if record is not None
            else "unknown"
        ),
    }


def _owner_intent_import_path(root: Path) -> Path:
    path = _project_controller_dir(root) / "owner-intent-imports.json"
    _reject_reparse_ancestors(path)
    return path


def _retained_owner_intent(root: Path, intent_id: str, intent_digest: str) -> dict:
    matches = [
        record
        for record in _load_owner_intents(root)["intents"]
        if record["intent_id"] == intent_id
        and record["owner_intent_digest"] == intent_digest
    ]
    if len(matches) != 1:
        raise EngineeringError("Engineering owner intent import owner intent is unavailable.")
    return dict(matches[0])


def _owner_mapping_reference(
    root: Path, commit: str, reference: dict, *, kind: str
) -> None:
    """Resolve one semantic mapping reference from the exact committed artifact."""
    path = reference["path"]
    try:
        content = _git_blob_bytes(root, commit, path)
        text = content.decode("utf-8")
    except (EngineeringError, UnicodeDecodeError) as error:
        raise EngineeringError(
            "Engineering owner intent import mapping reference is unavailable."
        ) from error
    if kind == "design":
        section = reference["section"].strip()
        if not any(
            re.fullmatch(rf"#{{1,6}}\s+{re.escape(section)}\s*", line.strip())
            for line in text.splitlines()
        ):
            raise EngineeringError(
                "Engineering owner intent import mapping design reference is invalid."
            )
        return
    if kind == "contract":
        interface = reference["interface"].strip()
        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            raise EngineeringError(
                "Engineering owner intent import mapping contract reference is invalid."
            ) from error

        def contains(value: object) -> bool:
            if isinstance(value, dict):
                return any(contains(item) for item in value.values())
            if isinstance(value, list):
                return any(contains(item) for item in value)
            return value == interface

        if not contains(document):
            raise EngineeringError(
                "Engineering owner intent import mapping contract reference is invalid."
            )
        return
    selector = reference["selector"].strip().split(".")[-1]
    try:
        parsed = ast.parse(text, filename=path)
    except SyntaxError as error:
        raise EngineeringError(
            "Engineering owner intent import mapping test reference is invalid."
        ) from error
    if not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == selector
        for node in ast.walk(parsed)
    ):
        raise EngineeringError(
            "Engineering owner intent import mapping test reference is invalid."
        )


def _owner_intent_import(
    root: Path, value: object, *, allow_historical_intent: bool = False
) -> dict:
    """Validate an exact host-recorded completeness import after activation."""
    legacy = isinstance(value, dict) and value.get("schema") == LEGACY_OWNER_INTENT_IMPORT_SCHEMA
    expected = {
        "schema",
        "import_id",
        "repository_id",
        "authority_epoch",
        "owner_intent_id",
        "owner_intent_digest",
        "outcome_ids",
        "coverage_scopes",
    }
    if not legacy:
        expected |= {"outcome_mappings", "outcome_mapping_digest"}
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema")
        not in {OWNER_INTENT_IMPORT_SCHEMA, LEGACY_OWNER_INTENT_IMPORT_SCHEMA}
        or (legacy and not allow_historical_intent)
        or value.get("repository_id") != _project_contribution_digest(root)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("owner_intent_digest", "")))
        or not isinstance(value.get("outcome_ids"), list)
        or not isinstance(value.get("coverage_scopes"), list)
        or any(not isinstance(item, str) for item in value["coverage_scopes"])
    ):
        raise EngineeringError("Engineering owner intent import is invalid.")
    try:
        import_id = _assurance_id(value.get("import_id"), "owner intent import")
        intent_id = _assurance_id(value.get("owner_intent_id"), "owner intent import owner intent")
        authority_epoch = _assurance_id(
            value.get("authority_epoch"), "owner intent import authority epoch"
        )
        outcome_ids = sorted(
            _assurance_id(item, "owner intent import outcome") for item in value["outcome_ids"]
        )
    except EngineeringError as error:
        raise EngineeringError("Engineering owner intent import is invalid.") from error
    if (
        not outcome_ids
        or len(outcome_ids) != len(set(outcome_ids))
        or sorted(value["coverage_scopes"]) != sorted(POST_ACTIVATION_IMPORT_SCOPES)
        or len(value["coverage_scopes"]) != len(set(value["coverage_scopes"]))
    ):
        raise EngineeringError("Engineering owner intent import completeness is invalid.")
    intent = (
        _retained_owner_intent(root, intent_id, value["owner_intent_digest"])
        if allow_historical_intent
        else _active_owner_intent(root, intent_id, value["owner_intent_digest"])
    )
    expected_outcomes = sorted(item["id"] for item in intent["outcomes"])
    if (
        value["repository_id"] != intent["repository_id"]
        or authority_epoch != intent["authority_epoch"]
        or outcome_ids != expected_outcomes
    ):
        raise EngineeringError("Engineering owner intent import is incomplete or mismatched.")
    normalized = {
        "schema": value["schema"],
        "import_id": import_id,
        "repository_id": intent["repository_id"],
        "authority_epoch": intent["authority_epoch"],
        "owner_intent_id": intent["intent_id"],
        "owner_intent_digest": intent["owner_intent_digest"],
        "outcome_ids": expected_outcomes,
        "coverage_scopes": sorted(POST_ACTIVATION_IMPORT_SCOPES),
    }
    if legacy:
        return normalized
    mappings = value.get("outcome_mappings")
    if (
        not isinstance(mappings, list)
        or not mappings
        or value.get("outcome_mapping_digest") != _json_digest(mappings)
    ):
        raise EngineeringError("Engineering owner intent import outcome mapping is invalid.")
    normalized_mappings = []
    mapped_ids: set[str] = set()
    mapping_expected = {
        "outcome_id",
        "outcome_statement_digest",
        "lifecycle_state",
        "design",
        "contract",
        "runtime_behavior",
        "negative_test",
        "required_evidence",
        "exact_artifact",
    }
    current_commit = _identity_git(root, "rev-parse", "HEAD")
    current_tree = _identity_git(root, "rev-parse", "HEAD^{tree}")
    outcomes_by_id = {item["id"]: item for item in intent["outcomes"]}
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) != mapping_expected:
            raise EngineeringError("Engineering owner intent import outcome mapping is invalid.")
        outcome_id = mapping.get("outcome_id")
        design = mapping.get("design")
        contract = mapping.get("contract")
        negative_test = mapping.get("negative_test")
        evidence = mapping.get("required_evidence")
        artifact = mapping.get("exact_artifact")
        runtime_behavior = mapping.get("runtime_behavior")
        outcome = outcomes_by_id.get(outcome_id)
        path_fields = (
            (design, {"path", "section"}),
            (contract, {"path", "interface"}),
            (negative_test, {"path", "selector"}),
        )
        if (
            not isinstance(outcome_id, str)
            or outcome_id not in expected_outcomes
            or outcome_id in mapped_ids
            or not isinstance(outcome, dict)
            or mapping.get("outcome_statement_digest") != outcome.get("statement_digest")
            or mapping.get("lifecycle_state") != "DESIGN_MAPPED"
            or any(
                not isinstance(item, dict)
                or set(item) != names
                or any(
                    not isinstance(item[name], str)
                    or not item[name].strip()
                    or item[name].strip().lower() == "unknown"
                    for name in names
                )
                for item, names in path_fields
            )
            or any(
                PurePosixPath(item["path"]).is_absolute()
                or ".." in PurePosixPath(item["path"]).parts
                for item, _ in path_fields
            )
            or not isinstance(runtime_behavior, str)
            or not runtime_behavior.strip()
            or runtime_behavior.strip().lower() == "unknown"
            or not isinstance(evidence, dict)
            or set(evidence) != {"class", "interface", "environment"}
            or evidence.get("class") not in {"end_to_end", "real_outcome"}
            or evidence not in outcome.get("required_evidence", [])
            or any(
                not isinstance(evidence.get(name), str)
                or not evidence[name].strip()
                or evidence[name].strip().lower() in {"unknown", "proxy"}
                for name in ("interface", "environment")
            )
            or not isinstance(artifact, dict)
            or set(artifact) != {"repository_id", "commit", "tree", "digest"}
            or artifact.get("repository_id") != intent["repository_id"]
            or artifact.get("commit") != current_commit
            or artifact.get("tree") != current_tree
            or artifact.get("digest")
            != _json_digest(
                {
                    "repository_id": artifact.get("repository_id"),
                    "commit": artifact.get("commit"),
                    "tree": artifact.get("tree"),
                }
            )
        ):
            raise EngineeringError("Engineering owner intent import outcome mapping is invalid.")
        _owner_mapping_reference(root, current_commit, design, kind="design")
        _owner_mapping_reference(root, current_commit, contract, kind="contract")
        _owner_mapping_reference(root, current_commit, negative_test, kind="test")
        mapped_ids.add(outcome_id)
        normalized_mappings.append(dict(mapping))
    normalized_mappings.sort(key=lambda item: item["outcome_id"])
    if sorted(mapped_ids) != expected_outcomes or mappings != normalized_mappings:
        raise EngineeringError("Engineering owner intent import outcome mapping is incomplete.")
    normalized["outcome_mappings"] = normalized_mappings
    normalized["outcome_mapping_digest"] = _json_digest(normalized_mappings)
    return normalized


def _owner_intent_import_signature(key: bytes, record: dict) -> str:
    material = {name: value for name, value in record.items() if name != "signature"}
    return "hmac-sha256:" + hmac.new(key, _canonical_json(material), hashlib.sha256).hexdigest()


def _load_owner_intent_imports(root: Path) -> dict:
    path = _owner_intent_import_path(root)
    if not path.exists():
        return {"schema": OWNER_INTENT_IMPORT_LEDGER_SCHEMA, "imports": []}
    _verify_owner_private(path, directory=False)
    key = _controller_key(_project_controller_dir(root), required=True)
    assert key is not None
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering owner intent import ledger is invalid.") from error
    if (
        not isinstance(ledger, dict)
        or set(ledger) != {"schema", "imports"}
        or ledger.get("schema") != OWNER_INTENT_IMPORT_LEDGER_SCHEMA
        or not isinstance(ledger.get("imports"), list)
        or len(ledger["imports"]) > MAX_OWNER_INTENTS
    ):
        raise EngineeringError("Engineering owner intent import ledger is invalid.")
    import_ids: set[str] = set()
    for record in ledger["imports"]:
        expected = {
            "import",
            "import_digest",
            "approval_reference",
            "approval_trust_anchor",
            "approval_host_receipt",
            "imported_at",
            "signature",
        }
        if not isinstance(record, dict) or set(record) != expected:
            raise EngineeringError("Engineering owner intent import ledger is invalid.")
        try:
            normalized = _owner_intent_import(
                root, record["import"], allow_historical_intent=True
            )
            _assurance_id(record["approval_reference"], "owner intent import approval reference")
            _host_trust_anchor(record["approval_trust_anchor"])
            _assurance_timestamp(record["imported_at"])
        except EngineeringError as error:
            raise EngineeringError("Engineering owner intent import ledger is invalid.") from error
        if (
            normalized != record["import"]
            or record["approval_trust_anchor"].get("schema") != HOST_TRUST_ANCHOR_SCHEMA
            or not isinstance(record["approval_host_receipt"], dict)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(record.get("import_digest", "")))
            or record["import_digest"] != _json_digest(normalized)
            or normalized["import_id"] in import_ids
            or not hmac.compare_digest(
                str(record.get("signature", "")), _owner_intent_import_signature(key, record)
            )
        ):
            raise EngineeringError("Engineering owner intent import ledger is invalid.")
        import_ids.add(normalized["import_id"])
    return ledger


def _publish_owner_intent_imports(root: Path, ledger: dict) -> None:
    if (
        len(ledger.get("imports", [])) > MAX_OWNER_INTENTS
        or len(json.dumps(ledger).encode("utf-8")) > 1024 * 1024
    ):
        raise EngineeringError("Engineering owner intent import ledger exceeds its bounded size.")
    controller = _project_controller_dir(root)
    controller.mkdir(parents=True, exist_ok=True)
    _enforce_owner_private(controller)
    _transactional_json_documents([(_owner_intent_import_path(root), ledger)])


def _active_owner_intent_import(root: Path, intent: dict) -> dict | None:
    matches = [
        record
        for record in _load_owner_intent_imports(root)["imports"]
        if record["import"].get("schema") == OWNER_INTENT_IMPORT_SCHEMA
        and record["import"]["owner_intent_id"] == intent["intent_id"]
        and record["import"]["owner_intent_digest"] == intent["owner_intent_digest"]
    ]
    if len(matches) > 1:
        raise EngineeringError("Engineering owner intent import is ambiguous.")
    return dict(matches[0]) if matches else None


def import_owner_intent(root: Path, imported: object, approval: object) -> dict:
    """Retain the host proof that activation imported every recorded owner outcome."""
    project_root = resolve_project_root(str(root))
    normalized = _owner_intent_import(project_root, imported)
    approval_reference, approval_anchor = _verify_host_owned_signature(
        project_root,
        approval,
        approval_schema="engineering.host-owner-intent-import-approval.v2",
        claims_schema="engineering.host-owner-intent-import-claims.v2",
        claims=normalized,
        namespace="engineering-owner-intent-import",
        label="Engineering owner intent import host approval",
        reference_prefix="owner-intent-import-approval-",
        contract=OWNER_INTENT_IMPORT_SCHEMA,
        authority_epoch=normalized["authority_epoch"],
    )
    operation = _begin_authority_mutation(project_root, "owner-intent-import")
    try:
        ledger = _load_owner_intent_imports(project_root)
        digest = _json_digest(normalized)
        for retained in ledger["imports"]:
            if retained["import"]["import_id"] != normalized["import_id"]:
                continue
            if (
                retained["import_digest"] != digest
                or retained["approval_reference"] != approval_reference
                or retained["approval_trust_anchor"] != approval_anchor
                or retained["approval_host_receipt"] != approval["host_receipt"]
            ):
                raise EngineeringError("Engineering owner intent import replay conflicts with retained state.")
            return {**normalized, "import_digest": digest}
        controller = _project_controller_dir(project_root)
        key = _controller_key(controller, required=True)
        assert key is not None
        record = {
            "import": normalized,
            "import_digest": digest,
            "approval_reference": approval_reference,
            "approval_trust_anchor": approval_anchor,
            "approval_host_receipt": approval["host_receipt"],
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }
        record["signature"] = _owner_intent_import_signature(key, record)
        ledger["imports"].append(record)
        ledger["imports"].sort(key=lambda item: item["import"]["import_id"])
        _publish_owner_intent_imports(project_root, ledger)
        return {**normalized, "import_digest": digest}
    finally:
        _end_completion(project_root, operation)


def dependent_dispatch_status(root: Path, scope: str) -> dict:
    """Return a non-authorizing downstream admission fact after complete import."""
    project_root = resolve_project_root(str(root))
    if scope not in POST_ACTIVATION_IMPORT_SCOPES:
        raise EngineeringError("Engineering dependent dispatch scope is invalid.")
    intent = _active_owner_intent(project_root)
    imported = _active_owner_intent_import(project_root, intent)
    if imported is None:
        raise EngineeringError(
            "Engineering post-activation owner intent import is required before dependent dispatch."
        )
    return {
        "schema": "engineering.dependent-dispatch-status.v1",
        "state": "admitted",
        "scope": scope,
        "owner_intent_id": intent["intent_id"],
        "owner_intent_digest": intent["owner_intent_digest"],
        "import_digest": imported["import_digest"],
        "outcome_mapping_digest": imported["import"]["outcome_mapping_digest"],
        "dispatch_performed": False,
        "native_approval_required": True,
    }


def _completion_artifact_digest(completion: object, completion_digest: object) -> str:
    """Bind a token to the exact terminal completion and its immutable artifact identity."""
    if (
        not isinstance(completion, dict)
        or completion.get("schema") != "engineering.complete.v1"
        or not isinstance(completion.get("run_id"), str)
        or not re.fullmatch(r"run-[0-9a-f]{6}", completion["run_id"])
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(completion_digest))
        or not isinstance(completion.get("result_identity"), dict)
        or set(completion["result_identity"]) != {"commit", "dirty_tree_digest"}
        or not isinstance(completion.get("changed_artifacts"), list)
        or any(not isinstance(path, str) for path in completion["changed_artifacts"])
    ):
        raise EngineeringError("Engineering terminal completion artifact identity is invalid.")
    return _json_digest(
        {
            "completion_digest": completion_digest,
            "result_identity": completion["result_identity"],
            "changed_artifacts": sorted(completion["changed_artifacts"]),
            "scope_result_artifacts": sorted(
                completion.get("scope_result_artifacts", [])
            ),
        }
    )


def _outcome_acceptance_path(root: Path) -> Path:
    path = _project_controller_dir(root) / "outcome-acceptances.json"
    _reject_reparse_ancestors(path)
    return path


def _outcome_audit_claims(value: object) -> dict:
    """Return the minimum exact claims an independent auditor must sign."""
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("roles"), dict)
        or not isinstance(value.get("outcomes"), list)
    ):
        raise EngineeringError("Engineering independent outcome audit is invalid.")
    roles = value["roles"]
    expected_roles = {"architect_id", "implementer_id", "writer_id", "auditor_id"}
    if set(roles) != expected_roles or any(
        not isinstance(roles[name], str) for name in expected_roles
    ):
        raise EngineeringError("Engineering independent outcome audit is invalid.")
    states = []
    for outcome in value["outcomes"]:
        if (
            not isinstance(outcome, dict)
            or set(outcome) != {"outcome_id", "state", "evidence"}
            or not isinstance(outcome.get("outcome_id"), str)
            or outcome.get("state") not in OUTCOME_ACCEPTANCE_STATES
        ):
            raise EngineeringError("Engineering independent outcome audit is invalid.")
        states.append(
            {"outcome_id": outcome["outcome_id"], "state": outcome["state"]}
        )
    if len({item["outcome_id"] for item in states}) != len(states):
        raise EngineeringError("Engineering independent outcome audit is invalid.")
    return {
        "schema": "engineering.independent-outcome-audit-claims.v2",
        "acceptance_id": value.get("acceptance_id"),
        "completion_digest": value.get("completion_digest"),
        "artifact_digest": value.get("artifact_digest"),
        "owner_intent_id": value.get("owner_intent_id"),
        "owner_intent_digest": value.get("owner_intent_digest"),
        "mapping_digest": value.get("mapping_digest"),
        "evidence_digest": value.get("evidence_digest"),
        "roles": {name: roles[name] for name in sorted(expected_roles)},
        "outcome_states": sorted(states, key=lambda item: item["outcome_id"]),
        "original_owner_intent_compared": True,
    }


def _verify_independent_outcome_audit(root: Path, value: dict) -> dict:
    attestation = value.get("audit_attestation")
    claims = _outcome_audit_claims(value)
    try:
        auditor_id = _assurance_id(
            value["roles"]["auditor_id"], "independent outcome audit auditor"
        )
    except EngineeringError as error:
        raise EngineeringError("Engineering independent outcome audit is invalid.") from error
    try:
        owner_intent = _active_owner_intent(
            root, value.get("owner_intent_id"), value.get("owner_intent_digest")
        )
    except EngineeringError as error:
        raise EngineeringError("Engineering independent outcome audit is invalid.") from error
    _verify_host_owned_signature(
        root,
        attestation,
        approval_schema=INDEPENDENT_OUTCOME_AUDIT_SCHEMA,
        claims_schema="engineering.independent-outcome-audit-claims.v3",
        claims=claims,
        namespace="engineering-independent-audit",
        label="Engineering independent outcome audit",
        reference_prefix="independent-outcome-audit-",
        contract=OUTCOME_ACCEPTANCE_SCHEMA,
        authority_epoch=owner_intent["authority_epoch"],
        required_principal=auditor_id,
    )
    return {
        "schema": INDEPENDENT_OUTCOME_AUDIT_SCHEMA,
        "approver": auditor_id,
        "claims": claims,
        "host_receipt": attestation["host_receipt"],
        "signature": attestation["signature"],
    }


def _outcome_evidence(value: object) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_OWNER_INTENT_EVIDENCE:
        raise EngineeringError("Engineering outcome acceptance evidence is invalid.")
    normalized = []
    identities: set[str] = set()
    for evidence in value:
        expected = {
            "evidence_id",
            "evidence_digest",
            "class",
            "interface",
            "environment",
            "producer_role",
        }
        if (
            not isinstance(evidence, dict)
            or set(evidence) != expected
            or evidence.get("class") not in OUTCOME_EVIDENCE_CLASSES
            or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(evidence.get("evidence_digest", ""))
            )
        ):
            raise EngineeringError("Engineering outcome acceptance evidence is invalid.")
        try:
            normalized_evidence = {
                "evidence_id": _assurance_id(evidence["evidence_id"], "outcome evidence"),
                "evidence_digest": evidence["evidence_digest"],
                "class": evidence["class"],
                "interface": _assurance_id(evidence["interface"], "outcome evidence interface"),
                "environment": _assurance_id(evidence["environment"], "outcome evidence environment"),
                "producer_role": _assurance_id(evidence["producer_role"], "outcome evidence producer role"),
            }
        except EngineeringError as error:
            raise EngineeringError("Engineering outcome acceptance evidence is invalid.") from error
        identity = normalized_evidence["evidence_id"]
        if identity in identities:
            raise EngineeringError("Engineering outcome acceptance evidence is duplicated.")
        identities.add(identity)
        normalized.append(normalized_evidence)
    return sorted(normalized, key=lambda item: item["evidence_id"])


def _outcome_evidence_matrix_digest(outcomes: object) -> str:
    """Digest the declared outcome/evidence matrix independent of presentation order."""
    if not isinstance(outcomes, list) or len(outcomes) > MAX_OWNER_INTENT_OUTCOMES:
        raise EngineeringError("Engineering outcome acceptance evidence matrix is invalid.")
    matrix = []
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            raise EngineeringError("Engineering outcome acceptance evidence matrix is invalid.")
        outcome_id = outcome.get("outcome_id")
        evidence = outcome.get("evidence")
        if not isinstance(outcome_id, str) or not isinstance(evidence, list):
            raise EngineeringError("Engineering outcome acceptance evidence matrix is invalid.")
        if any(not isinstance(item, dict) for item in evidence):
            raise EngineeringError("Engineering outcome acceptance evidence matrix is invalid.")
        matrix.append(
            {
                "outcome_id": outcome_id,
                "evidence": sorted(evidence, key=lambda item: str(item.get("evidence_id", ""))),
            }
        )
    if len({item["outcome_id"] for item in matrix}) != len(matrix):
        raise EngineeringError("Engineering outcome acceptance evidence matrix is invalid.")
    return _json_digest(sorted(matrix, key=lambda item: item["outcome_id"]))


def _evidence_satisfies_requirements(
    evidence: list[dict], requirements: list[dict]
) -> bool:
    for required in requirements:
        required_order = OUTCOME_EVIDENCE_CLASS_ORDER[required["class"]]
        if not any(
            OUTCOME_EVIDENCE_CLASS_ORDER[item["class"]] >= required_order
            and item["interface"] == required["interface"]
            and item["environment"] == required["environment"]
            for item in evidence
        ):
            return False
    return True


def _outcome_acceptance(
    root: Path, completion_id: str, value: object
) -> dict:
    expected = {
        "schema",
        "acceptance_id",
        "completion_digest",
        "artifact_digest",
        "owner_intent_id",
        "owner_intent_digest",
        "mapping_digest",
        "evidence_digest",
        "roles",
        "audit_attestation",
        "outcomes",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != OUTCOME_ACCEPTANCE_SCHEMA
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("completion_digest", "")))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("artifact_digest", "")))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("mapping_digest", "")))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("evidence_digest", "")))
    ):
        raise EngineeringError("Engineering outcome acceptance is invalid.")
    try:
        acceptance_id = _assurance_id(value["acceptance_id"], "outcome acceptance")
        completion, completion_digest = _terminal_completion(root, completion_id)
        artifact_digest = _completion_artifact_digest(completion, completion_digest)
    except EngineeringError as error:
        raise EngineeringError("Engineering outcome acceptance terminal completion is invalid.") from error
    if value["completion_digest"] != completion_digest or value["artifact_digest"] != artifact_digest:
        raise EngineeringError("Engineering outcome acceptance exact artifact is mismatched.")
    authorization = completion.get("authorization")
    handoff = authorization.get("scope_handoff") if isinstance(authorization, dict) else None
    survival = handoff.get("outcome_survival") if isinstance(handoff, dict) else None
    if not isinstance(survival, dict) or survival.get("schema") != OUTCOME_SURVIVAL_V2_SCHEMA:
        raise EngineeringError("Engineering outcome acceptance owner intent is unknown for this completion.")
    try:
        intent = _active_owner_intent(
            root, value["owner_intent_id"], value["owner_intent_digest"]
        )
        compiled_survival = _outcome_survival_v2(
            survival,
            intent,
            root=root,
            allow_controller_baseline=True,
        )
    except EngineeringError as error:
        raise EngineeringError("Engineering outcome acceptance owner intent is invalid.") from error
    completion_owner_intent = completion.get("owner_intent")
    expected_completion_owner_intent = {
        "intent_id": intent["intent_id"],
        "owner_intent_digest": intent["owner_intent_digest"],
        "authority_epoch": intent["authority_epoch"],
    }
    if completion_owner_intent != expected_completion_owner_intent:
        raise EngineeringError("Engineering outcome acceptance completion owner intent is mismatched.")
    if value["mapping_digest"] != compiled_survival["mapping_digest"]:
        raise EngineeringError("Engineering outcome acceptance mapping is mismatched.")
    roles = value["roles"]
    expected_roles = {"architect_id", "implementer_id", "writer_id", "auditor_id"}
    if not isinstance(roles, dict) or set(roles) != expected_roles:
        raise EngineeringError("Engineering outcome acceptance roles are invalid.")
    try:
        normalized_roles = {
            name: _assurance_id(roles[name], f"outcome acceptance {name}")
            for name in sorted(expected_roles)
        }
    except EngineeringError as error:
        raise EngineeringError("Engineering outcome acceptance roles are invalid.") from error
    if normalized_roles["auditor_id"] in {
        normalized_roles["architect_id"],
        normalized_roles["implementer_id"],
        normalized_roles["writer_id"],
    }:
        raise EngineeringError("Engineering outcome acceptance auditor is not independent.")
    audit_input = {**value, "roles": normalized_roles}
    audit_attestation = _verify_independent_outcome_audit(root, audit_input)
    outcomes = value["outcomes"]
    if (
        not isinstance(outcomes, list)
        or not outcomes
        or len(outcomes) > MAX_OWNER_INTENT_OUTCOMES
    ):
        raise EngineeringError("Engineering outcome acceptance outcomes are invalid.")
    required_by_id = {item["id"]: item for item in intent["outcomes"]}
    dispositions = {
        item["outcome_id"]: item["disposition"]
        for item in compiled_survival["mappings"]
    }
    mappings_by_id = {
        item["outcome_id"]: item
        for item in compiled_survival["mappings"]
    }
    normalized_outcomes = []
    for outcome in outcomes:
        expected_outcome = {"outcome_id", "state", "evidence"}
        if (
            not isinstance(outcome, dict)
            or set(outcome) != expected_outcome
            or outcome.get("state") not in OUTCOME_ACCEPTANCE_STATES
        ):
            raise EngineeringError("Engineering outcome acceptance outcomes are invalid.")
        try:
            outcome_id = _assurance_id(outcome["outcome_id"], "accepted owner outcome")
        except EngineeringError as error:
            raise EngineeringError("Engineering outcome acceptance outcomes are invalid.") from error
        evidence = _outcome_evidence(outcome["evidence"])
        if outcome_id not in required_by_id:
            raise EngineeringError("Engineering outcome acceptance includes an unknown owner outcome.")
        if outcome["state"] == "accepted":
            if dispositions.get(outcome_id) not in {"INCLUDED", "REPLACED"}:
                raise EngineeringError("Engineering outcome acceptance cannot accept deferred or excluded core outcome.")
            if not _evidence_satisfies_requirements(
                evidence, required_by_id[outcome_id]["required_evidence"]
            ):
                raise EngineeringError(
                    "Engineering outcome acceptance required evidence is not satisfied."
                )
            mapped = mappings_by_id[outcome_id]
            required_evidence_ids = set(mapped["verification_ids"])
            if mapped["equivalence"] is not None:
                required_evidence_ids.add(mapped["equivalence"]["evidence_id"])
            retained_evidence_ids = {item["evidence_id"] for item in evidence}
            if not required_evidence_ids.issubset(retained_evidence_ids):
                raise EngineeringError(
                    "Engineering outcome acceptance does not retain mapped verification evidence."
                )
        normalized_outcomes.append(
            {"outcome_id": outcome_id, "state": outcome["state"], "evidence": evidence}
        )
    outcome_ids = [item["outcome_id"] for item in normalized_outcomes]
    if len(set(outcome_ids)) != len(outcome_ids):
        raise EngineeringError("Engineering outcome acceptance outcomes are duplicated.")
    evidence_digest = _outcome_evidence_matrix_digest(normalized_outcomes)
    if value["evidence_digest"] != evidence_digest:
        raise EngineeringError("Engineering outcome acceptance evidence matrix is mismatched.")
    core_ids = {
        item["id"] for item in intent["outcomes"] if item["criticality"] == "core"
    }
    missing_core = sorted(core_ids - set(outcome_ids))
    if missing_core:
        raise EngineeringError(
            "Engineering outcome acceptance lacks core outcome states: "
            + ", ".join(missing_core)
        )
    return {
        "schema": OUTCOME_ACCEPTANCE_SCHEMA,
        "acceptance_id": acceptance_id,
        "completion_id": completion_id,
        "completion_digest": completion_digest,
        "artifact_digest": artifact_digest,
        "owner_intent_id": intent["intent_id"],
        "owner_intent_digest": intent["owner_intent_digest"],
        "mapping_digest": compiled_survival["mapping_digest"],
        "evidence_digest": evidence_digest,
        "roles": normalized_roles,
        "audit_attestation": audit_attestation,
        "outcomes": sorted(normalized_outcomes, key=lambda item: item["outcome_id"]),
    }


def _outcome_acceptance_signature(key: bytes, record: dict) -> str:
    material = {name: value for name, value in record.items() if name != "signature"}
    return "hmac-sha256:" + hmac.new(key, _canonical_json(material), hashlib.sha256).hexdigest()


def _load_outcome_acceptances(root: Path) -> dict:
    path = _outcome_acceptance_path(root)
    if not path.exists():
        return {"schema": OUTCOME_ACCEPTANCE_LEDGER_SCHEMA, "acceptances": []}
    _verify_owner_private(path, directory=False)
    key = _controller_key(_project_controller_dir(root), required=True)
    assert key is not None
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering outcome acceptance ledger is invalid.") from error
    if (
        not isinstance(ledger, dict)
        or set(ledger) != {"schema", "acceptances"}
        or ledger.get("schema") != OUTCOME_ACCEPTANCE_LEDGER_SCHEMA
        or not isinstance(ledger.get("acceptances"), list)
        or len(ledger["acceptances"]) > MAX_OUTCOME_ACCEPTANCES
    ):
        raise EngineeringError("Engineering outcome acceptance ledger is invalid.")
    identities: set[str] = set()
    for record in ledger["acceptances"]:
        expected = {
            "acceptance",
            "acceptance_digest",
            "recorded_at",
            "signature",
        }
        if (
            not isinstance(record, dict)
            or set(record) != expected
            or not isinstance(record.get("acceptance"), dict)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(record.get("acceptance_digest", "")))
            or record["acceptance_digest"] != _json_digest(record["acceptance"])
            or not hmac.compare_digest(
                str(record.get("signature", "")), _outcome_acceptance_signature(key, record)
            )
        ):
            raise EngineeringError("Engineering outcome acceptance ledger is invalid.")
        try:
            acceptance_id = _assurance_id(
                record["acceptance"].get("acceptance_id"), "retained outcome acceptance"
            )
            _assurance_timestamp(record["recorded_at"])
        except EngineeringError as error:
            raise EngineeringError("Engineering outcome acceptance ledger is invalid.") from error
        if acceptance_id in identities:
            raise EngineeringError("Engineering outcome acceptance ledger is ambiguous.")
        identities.add(acceptance_id)
    return ledger


def _publish_outcome_acceptances(
    root: Path, ledger: dict, new_key: bytes | None
) -> None:
    if (
        len(ledger.get("acceptances", [])) > MAX_OUTCOME_ACCEPTANCES
        or len(json.dumps(ledger).encode("utf-8")) > 1024 * 1024
    ):
        raise EngineeringError("Engineering outcome acceptance ledger exceeds its bounded size.")
    controller = _project_controller_dir(root)
    controller.mkdir(parents=True, exist_ok=True)
    _enforce_owner_private(controller)
    binary = (
        [(_controller_key_path(controller), new_key.hex().encode("ascii") + b"\n")]
        if new_key is not None
        else None
    )
    _transactional_json_documents([(_outcome_acceptance_path(root), ledger)], binary)


def record_outcome_acceptance(
    root: Path, completion_id: str, value: object
) -> dict:
    """Retain independently audited evidence for one exact terminal artifact."""
    project_root = resolve_project_root(str(root))
    normalized = _outcome_acceptance(project_root, completion_id, value)
    operation = _begin_authority_mutation(project_root, "outcome-accept")
    try:
        ledger = _load_outcome_acceptances(project_root)
        digest = _json_digest(normalized)
        for retained in ledger["acceptances"]:
            prior = retained["acceptance"]
            if prior["acceptance_id"] != normalized["acceptance_id"]:
                continue
            if retained["acceptance_digest"] != digest:
                raise EngineeringError("Engineering outcome acceptance replay conflicts with retained state.")
            return {**prior, "acceptance_digest": retained["acceptance_digest"]}
        controller = _project_controller_dir(project_root)
        key = _controller_key(controller, required=False)
        new_key = os.urandom(32) if key is None else None
        key = key or new_key
        assert key is not None
        record = {
            "acceptance": normalized,
            "acceptance_digest": digest,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        record["signature"] = _outcome_acceptance_signature(key, record)
        ledger["acceptances"].append(record)
        ledger["acceptances"].sort(
            key=lambda item: item["acceptance"]["acceptance_id"]
        )
        _publish_outcome_acceptances(project_root, ledger, new_key)
        return {**normalized, "acceptance_digest": digest}
    finally:
        _end_completion(project_root, operation)


def _release_token_path(root: Path) -> Path:
    path = _project_controller_dir(root) / "release-tokens.json"
    _reject_reparse_ancestors(path)
    return path


def _release_token_signature(key: bytes, record: dict) -> str:
    material = {name: value for name, value in record.items() if name != "signature"}
    return "hmac-sha256:" + hmac.new(key, _canonical_json(material), hashlib.sha256).hexdigest()


def _load_release_tokens(root: Path) -> dict:
    path = _release_token_path(root)
    if not path.exists():
        return {"schema": RELEASE_TOKEN_LEDGER_SCHEMA, "tokens": []}
    _verify_owner_private(path, directory=False)
    key = _controller_key(_project_controller_dir(root), required=True)
    assert key is not None
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering release token ledger is invalid.") from error
    if (
        not isinstance(ledger, dict)
        or set(ledger) != {"schema", "tokens"}
        or ledger.get("schema") != RELEASE_TOKEN_LEDGER_SCHEMA
        or not isinstance(ledger.get("tokens"), list)
        or len(ledger["tokens"]) > MAX_RELEASE_TOKENS
    ):
        raise EngineeringError("Engineering release token ledger is invalid.")
    identities: set[str] = set()
    for record in ledger["tokens"]:
        expected = {"token", "issued_at", "signature"}
        token = record.get("token") if isinstance(record, dict) else None
        legacy_token_keys = {
            "schema",
            "token_id",
            "completion_id",
            "completion_digest",
            "artifact_digest",
            "owner_intent_id",
            "owner_intent_digest",
            "mapping_digest",
            "evidence_digest",
            "acceptance_id",
            "acceptance_digest",
            "actions",
        }
        token_keys = legacy_token_keys | {"install_source_bundle"}
        source_bundle = (
            token.get("install_source_bundle") if isinstance(token, dict) else None
        )
        valid_source_bundle = (
            isinstance(source_bundle, dict)
            and set(source_bundle)
            == {
                "source_git_commit",
                "source_git_tree",
                "source_digest",
                "skill_version",
            }
            and re.fullmatch(
                r"[0-9a-f]{40}", str(source_bundle.get("source_git_commit", ""))
            )
            and re.fullmatch(
                r"[0-9a-f]{40}", str(source_bundle.get("source_git_tree", ""))
            )
            and re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(source_bundle.get("source_digest", ""))
            )
            and re.fullmatch(
                r"[0-9]+\.[0-9]+\.[0-9]+", str(source_bundle.get("skill_version", ""))
            )
        )
        valid_legacy = (
            isinstance(token, dict)
            and set(token) == legacy_token_keys
            and token.get("schema") == LEGACY_RELEASE_TOKEN_SCHEMA
            and token.get("actions") == sorted(RELEASE_TOKEN_ACTIONS)
        )
        valid_current = (
            isinstance(token, dict)
            and set(token) == token_keys
            and token.get("schema") == RELEASE_TOKEN_SCHEMA
            and isinstance(token.get("actions"), list)
            and (
                (
                    source_bundle is None
                    and token["actions"]
                    == sorted(RELEASE_TOKEN_ACTIONS - {"install"})
                )
                or (
                    valid_source_bundle
                    and token["actions"] == sorted(RELEASE_TOKEN_ACTIONS)
                )
            )
        )
        if (
            not isinstance(record, dict)
            or set(record) != expected
            or not isinstance(token, dict)
            or not (valid_legacy or valid_current)
            or any(
                not re.fullmatch(r"sha256:[0-9a-f]{64}", str(token.get(name, "")))
                for name in (
                    "completion_digest",
                    "artifact_digest",
                    "owner_intent_digest",
                    "mapping_digest",
                    "evidence_digest",
                    "acceptance_digest",
                )
            )
            or not hmac.compare_digest(
                str(record.get("signature", "")), _release_token_signature(key, record)
            )
        ):
            raise EngineeringError("Engineering release token ledger is invalid.")
        try:
            token_id = _assurance_id(token.get("token_id"), "release token")
            _assurance_id(token.get("completion_id"), "release completion")
            _assurance_id(token.get("owner_intent_id"), "release owner intent")
            _assurance_id(token.get("acceptance_id"), "release outcome acceptance")
            _assurance_timestamp(record["issued_at"])
        except EngineeringError as error:
            raise EngineeringError("Engineering release token ledger is invalid.") from error
        if token_id in identities:
            raise EngineeringError("Engineering release token ledger is ambiguous.")
        identities.add(token_id)
    return ledger


def _publish_release_tokens(root: Path, ledger: dict, new_key: bytes | None) -> None:
    if (
        len(ledger.get("tokens", [])) > MAX_RELEASE_TOKENS
        or len(json.dumps(ledger).encode("utf-8")) > 1024 * 1024
    ):
        raise EngineeringError("Engineering release token ledger exceeds its bounded size.")
    controller = _project_controller_dir(root)
    controller.mkdir(parents=True, exist_ok=True)
    _enforce_owner_private(controller)
    binary = (
        [(_controller_key_path(controller), new_key.hex().encode("ascii") + b"\n")]
        if new_key is not None
        else None
    )
    _transactional_json_documents([(_release_token_path(root), ledger)], binary)


def _retained_outcome_acceptance(root: Path, acceptance_id: str) -> tuple[dict, str]:
    acceptance_id = _assurance_id(acceptance_id, "outcome acceptance")
    matches = [
        record
        for record in _load_outcome_acceptances(root)["acceptances"]
        if record["acceptance"].get("acceptance_id") == acceptance_id
    ]
    if len(matches) != 1:
        raise EngineeringError("Engineering outcome acceptance is unavailable.")
    return matches[0]["acceptance"], matches[0]["acceptance_digest"]


def _release_gate_acceptance(
    root: Path, completion_id: str, acceptance_id: str
) -> tuple[dict, dict, str]:
    completion, completion_digest = _terminal_completion(root, completion_id)
    artifact_digest = _completion_artifact_digest(completion, completion_digest)
    acceptance, acceptance_digest = _retained_outcome_acceptance(root, acceptance_id)
    if (
        acceptance.get("completion_id") != completion_id
        or acceptance.get("completion_digest") != completion_digest
        or acceptance.get("artifact_digest") != artifact_digest
    ):
        raise EngineeringError("Engineering release gate exact artifact acceptance is mismatched.")
    authorization = completion.get("authorization")
    handoff = authorization.get("scope_handoff") if isinstance(authorization, dict) else None
    survival = handoff.get("outcome_survival") if isinstance(handoff, dict) else None
    if not isinstance(survival, dict) or survival.get("schema") != OUTCOME_SURVIVAL_V2_SCHEMA:
        raise EngineeringError("Engineering release gate owner intent is unknown for this completion.")
    intent = _active_owner_intent(
        root, acceptance.get("owner_intent_id"), acceptance.get("owner_intent_digest")
    )
    if completion.get("owner_intent") != {
        "intent_id": intent["intent_id"],
        "owner_intent_digest": intent["owner_intent_digest"],
        "authority_epoch": intent["authority_epoch"],
    }:
        raise EngineeringError("Engineering release gate completion owner intent is mismatched.")
    compiled_survival = _outcome_survival_v2(
        survival,
        intent,
        root=root,
        allow_controller_baseline=True,
    )
    if acceptance.get("mapping_digest") != compiled_survival["mapping_digest"]:
        raise EngineeringError("Engineering release gate outcome mapping is mismatched.")
    if (
        not re.fullmatch(r"sha256:[0-9a-f]{64}", str(acceptance.get("evidence_digest", "")))
        or acceptance["evidence_digest"]
        != _outcome_evidence_matrix_digest(acceptance.get("outcomes"))
    ):
        raise EngineeringError("Engineering release gate evidence matrix is mismatched.")
    _verify_independent_outcome_audit(root, acceptance)
    outcomes = acceptance.get("outcomes")
    if not isinstance(outcomes, list):
        raise EngineeringError("Engineering release gate acceptance is invalid.")
    outcomes_by_id = {
        item.get("outcome_id"): item for item in outcomes if isinstance(item, dict)
    }
    if len(outcomes_by_id) != len(outcomes):
        raise EngineeringError("Engineering release gate acceptance is invalid.")
    dispositions = {
        item["outcome_id"]: item["disposition"]
        for item in compiled_survival["mappings"]
    }
    for requirement in intent["outcomes"]:
        if requirement["criticality"] != "core":
            continue
        outcome = outcomes_by_id.get(requirement["id"])
        if (
            not isinstance(outcome, dict)
            or outcome.get("state") != "accepted"
            or dispositions.get(requirement["id"]) not in {"INCLUDED", "REPLACED"}
            or not isinstance(outcome.get("evidence"), list)
            or not _evidence_satisfies_requirements(
                outcome["evidence"], requirement["required_evidence"]
            )
        ):
            raise EngineeringError(
                "Engineering release gate core outcome is not independently accepted."
            )
    return acceptance, intent, acceptance_digest


def _release_install_source_bundle(
    project_root: Path, completion_id: str, install_source: Path | str | None
) -> dict | None:
    """Resolve the only clean bundle an install-capable release token may name."""
    if install_source is None:
        return None
    source = _expand_install_path(install_source)
    try:
        source_repository = Path(
            _identity_git(source, "rev-parse", "--show-toplevel")
        ).resolve()
    except (EngineeringError, OSError) as error:
        raise EngineeringError("Engineering release install source is unavailable.") from error
    if source_repository != project_root.resolve():
        raise EngineeringError(
            "Engineering release install source is not the accepted project repository."
        )
    _, manifest, source_commit, source_digest = _bundle_files(source)
    source_git_tree = _bundle_git_tree(source, source_commit)
    completion, completion_digest = _terminal_completion(project_root, completion_id)
    _completion_artifact_digest(completion, completion_digest)
    result_identity = completion.get("result_identity")
    accepted_commit = (
        result_identity.get("commit") if isinstance(result_identity, dict) else None
    )
    if source_commit != accepted_commit:
        raise EngineeringError(
            "Engineering release install source is not the exact accepted commit."
        )
    return {
        "source_git_commit": source_commit,
        "source_git_tree": source_git_tree,
        "source_digest": source_digest,
        "skill_version": manifest["version"],
    }


def release_gate(
    root: Path,
    completion_id: str,
    acceptance_id: str,
    *,
    install_source: Path | str | None = None,
) -> dict:
    """Issue an opaque exact-artifact token only after every core owner outcome passes."""
    project_root = resolve_project_root(str(root))
    acceptance, intent, acceptance_digest = _release_gate_acceptance(
        project_root, completion_id, acceptance_id
    )
    install_source_bundle = _release_install_source_bundle(
        project_root, completion_id, install_source
    )
    actions = sorted(
        RELEASE_TOKEN_ACTIONS
        if install_source_bundle is not None
        else RELEASE_TOKEN_ACTIONS - {"install"}
    )
    token_seed = {
        "completion_id": completion_id,
        "completion_digest": acceptance["completion_digest"],
        "artifact_digest": acceptance["artifact_digest"],
        "owner_intent_digest": intent["owner_intent_digest"],
        "mapping_digest": acceptance["mapping_digest"],
        "evidence_digest": acceptance["evidence_digest"],
        "acceptance_digest": acceptance_digest,
        "install_source_bundle": install_source_bundle,
        "actions": actions,
    }
    token_id = "release-token-" + hashlib.sha256(_canonical_json(token_seed)).hexdigest()[:32]
    token = {
        "schema": RELEASE_TOKEN_SCHEMA,
        "token_id": token_id,
        "completion_id": completion_id,
        "completion_digest": acceptance["completion_digest"],
        "artifact_digest": acceptance["artifact_digest"],
        "owner_intent_id": intent["intent_id"],
        "owner_intent_digest": intent["owner_intent_digest"],
        "mapping_digest": acceptance["mapping_digest"],
        "evidence_digest": acceptance["evidence_digest"],
        "acceptance_id": acceptance["acceptance_id"],
        "acceptance_digest": acceptance_digest,
        "install_source_bundle": install_source_bundle,
        "actions": actions,
    }
    operation = _begin_authority_mutation(project_root, "release-gate")
    try:
        ledger = _load_release_tokens(project_root)
        matches = [
            record for record in ledger["tokens"] if record["token"]["token_id"] == token_id
        ]
        if matches:
            if len(matches) != 1 or matches[0]["token"] != token:
                raise EngineeringError("Engineering release token replay conflicts with retained state.")
            return dict(token)
        controller = _project_controller_dir(project_root)
        key = _controller_key(controller, required=False)
        new_key = os.urandom(32) if key is None else None
        key = key or new_key
        assert key is not None
        record = {"token": token, "issued_at": datetime.now(timezone.utc).isoformat()}
        record["signature"] = _release_token_signature(key, record)
        ledger["tokens"].append(record)
        ledger["tokens"].sort(key=lambda item: item["token"]["token_id"])
        _publish_release_tokens(project_root, ledger, new_key)
        return dict(token)
    finally:
        _end_completion(project_root, operation)


def verify_release_token(
    root: Path, token_id: str, artifact_digest: str, action: str
) -> dict:
    """Check a token at a native merge/install/activation boundary; never perform it."""
    project_root = resolve_project_root(str(root))
    token_id = _assurance_id(token_id, "release token")
    if (
        not re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact_digest))
        or action not in RELEASE_TOKEN_ACTIONS
    ):
        raise EngineeringError("Engineering release token verification is invalid.")
    matches = [
        record for record in _load_release_tokens(project_root)["tokens"]
        if record["token"]["token_id"] == token_id
    ]
    if len(matches) != 1:
        raise EngineeringError("Engineering release token is unavailable.")
    token = matches[0]["token"]
    if token["artifact_digest"] != artifact_digest or action not in token["actions"]:
        raise EngineeringError("Engineering release token does not authorize this exact artifact action.")
    source_bundle = token.get("install_source_bundle")
    if action == "install" and (
        token.get("schema") != RELEASE_TOKEN_SCHEMA
        or not isinstance(source_bundle, dict)
    ):
        raise EngineeringError(
            "Engineering release token does not authorize an exact install source bundle."
        )
    _active_owner_intent(
        project_root, token["owner_intent_id"], token["owner_intent_digest"]
    )
    return {
        "schema": token["schema"],
        "token_id": token_id,
        "token_digest": _json_digest(token),
        "artifact_digest": artifact_digest,
        "action": action,
        "acceptance_id": token["acceptance_id"],
        "owner_intent_digest": token["owner_intent_digest"],
        "source_bundle": source_bundle,
        "native_approval_required": True,
    }


def persist_scoped_authority(root: Path, binding: object, approval: object) -> dict:
    """Persist exact business authority from a retained host approval attestation."""
    project_root = resolve_project_root(str(root))
    normalized = _scoped_authority_binding(project_root, binding)
    approval_id, approval_trust_anchor = _verify_host_authority_approval(
        project_root, normalized, approval
    )
    operation = _begin_authority_mutation(project_root, "authority-persist")
    try:
        controller = _project_controller_dir(project_root)
        ledger = _load_scoped_authorities(project_root)
        comparable = {
            **normalized,
            "approval_reference": approval_id,
            "approval_trust_anchor": approval_trust_anchor,
            "parent_authority_id": None,
        }
        for retained in ledger["authorities"]:
            if all(retained.get(name) == value for name, value in comparable.items()):
                return dict(retained)
        key = _controller_key(controller, required=False)
        new_key = os.urandom(32) if key is None else None
        key = key or new_key
        assert key is not None
        record = {
            "schema": SCOPED_AUTHORITY_SCHEMA,
            "authority_id": "authority-" + uuid.uuid4().hex,
            **normalized,
            "approval_reference": approval_id,
            "approval_trust_anchor": approval_trust_anchor,
            "parent_authority_id": None,
            "status": "active",
            "transitioned_at": None,
        }
        record["signature"] = _scoped_authority_signature(key, record)
        ledger["authorities"].append(record)
        ledger["authorities"].sort(key=lambda item: item["authority_id"])
        _publish_scoped_authorities(project_root, ledger, new_key)
        return dict(record)
    finally:
        _end_completion(project_root, operation)


def _scoped_authority_request(root: Path, request: object) -> dict:
    required = {
        "authority_id",
        "authority_epoch",
        "target",
        "action_class",
        "scope",
        "safeguards",
        "permission_mode",
        "native_requirements",
        "continuation",
    }
    if not isinstance(request, dict) or set(request) != required:
        raise EngineeringError("Engineering scoped authority request is invalid.")
    authority_id = request.get("authority_id")
    if authority_id is not None and not re.fullmatch(r"authority-[0-9a-f]{32}", str(authority_id)):
        raise EngineeringError("Engineering scoped authority request is invalid.")
    permission = request.get("permission_mode")
    if permission not in {"full_access", "sandboxed", "unknown"}:
        raise EngineeringError("Engineering scoped authority request is invalid.")
    native = request.get("native_requirements")
    if (
        not isinstance(native, list)
        or len(native) > len(NATIVE_APPROVAL_REQUIREMENTS)
        or any(item not in NATIVE_APPROVAL_REQUIREMENTS for item in native)
    ):
        raise EngineeringError("Engineering scoped authority request is invalid.")
    continuation = request.get("continuation")
    if not isinstance(continuation, dict) or len(continuation) > 8 or any(
        not isinstance(name, str)
        or not isinstance(value, (str, int, bool))
        or isinstance(value, str)
        and (len(value) > 128 or _contains_credential(value))
        for name, value in continuation.items()
    ):
        raise EngineeringError("Engineering scoped authority continuation is invalid.")
    return {
        "authority_id": authority_id,
        "repository_id": _project_contribution_digest(resolve_project_root(str(root))),
        "authority_epoch": _assurance_id(request.get("authority_epoch"), "authority epoch"),
        "target": _assurance_id(request.get("target"), "authority target"),
        "action_class": _assurance_id(request.get("action_class"), "authority action class"),
        "scope": _scoped_authority_values(request.get("scope"), "scope", paths=True),
        "safeguards": _scoped_authority_values(request.get("safeguards"), "safeguards"),
        "permission_mode": permission,
        "native_requirements": sorted(set(native)),
    }


def _authority_resolution(request: dict, *, reason: str, record: dict | None = None) -> dict:
    present = record is not None and reason == "authorized"
    native = (
        sorted(set(request["native_requirements"]) | set(record["native_requirements"]))
        if present and record is not None
        else []
    )
    decision = "pending_native_approval" if native else "authorized" if present else "request_required"
    binding = {
        name: request[name]
        for name in (
            "repository_id",
            "authority_epoch",
            "target",
            "action_class",
            "scope",
            "safeguards",
        )
    }
    return {
        "schema": AUTHORITY_RESOLUTION_SCHEMA,
        "decision": decision,
        "reason": "native_approval_required" if native else reason,
        "authority_id": record["authority_id"] if record is not None else request["authority_id"],
        "binding_digest": _json_digest(binding),
        "business_authority_present": present,
        "request_business_approval": not present,
        "permission_mode": request["permission_mode"],
        "native_approval_required": native,
    }


def resolve_scoped_authority(root: Path, request: object) -> dict:
    project_root = resolve_project_root(str(root))
    normalized = _scoped_authority_request(project_root, request)
    if normalized["authority_id"] is None:
        return _authority_resolution(normalized, reason="missing_authority")
    ledger = _load_scoped_authorities(project_root)
    matches = [
        item
        for item in ledger["authorities"]
        if item["authority_id"] == normalized["authority_id"]
    ]
    if len(matches) != 1:
        return _authority_resolution(normalized, reason="missing_authority")
    record = matches[0]
    if "approval_trust_anchor" not in record:
        return _authority_resolution(normalized, reason="historical_unanchored")
    if record["status"] != "active":
        return _authority_resolution(normalized, reason=record["status"])
    if _assurance_timestamp(record["expires_at"]) <= datetime.now(timezone.utc):
        return _authority_resolution(normalized, reason="expired")
    retained = {item["authority_id"]: item for item in ledger["authorities"]}
    ancestor_id = record["parent_authority_id"]
    visited = {record["authority_id"]}
    while ancestor_id is not None:
        if ancestor_id in visited or ancestor_id not in retained:
            raise EngineeringError("Engineering scoped authority ancestry is invalid.")
        visited.add(ancestor_id)
        ancestor = retained[ancestor_id]
        if ancestor["status"] != "active":
            return _authority_resolution(
                normalized, reason=f"ancestor_{ancestor['status']}"
            )
        if _assurance_timestamp(ancestor["expires_at"]) <= datetime.now(timezone.utc):
            return _authority_resolution(normalized, reason="ancestor_expired")
        ancestor_id = ancestor["parent_authority_id"]
    for field in (
        "repository_id",
        "authority_epoch",
        "target",
        "action_class",
        "scope",
        "safeguards",
    ):
        if record[field] != normalized[field]:
            return _authority_resolution(normalized, reason=f"changed_{field}")
    return _authority_resolution(normalized, reason="authorized", record=record)


def _delegate_scoped_authority_unlocked(root: Path, parent_id: str, binding: object) -> dict:
    project_root = resolve_project_root(str(root))
    if not re.fullmatch(r"authority-[0-9a-f]{32}", str(parent_id)):
        raise EngineeringError("Engineering scoped authority parent is invalid.")
    normalized = _scoped_authority_binding(project_root, binding)
    ledger = _load_scoped_authorities(project_root)
    matches = [item for item in ledger["authorities"] if item["authority_id"] == parent_id]
    if len(matches) != 1:
        raise EngineeringError("Engineering scoped authority parent is missing.")
    parent = matches[0]
    if "approval_trust_anchor" not in parent:
        raise EngineeringError(
            "Engineering scoped authority parent is historical and cannot delegate new work."
        )
    if parent["status"] != "active" or _assurance_timestamp(parent["expires_at"]) <= datetime.now(timezone.utc):
        raise EngineeringError("Engineering scoped authority parent is not active.")
    for field in (
        "repository_id",
        "authority_epoch",
        "target",
        "action_class",
        "safeguards",
        "native_requirements",
    ):
        if normalized[field] != parent[field]:
            raise EngineeringError("Engineering scoped authority delegation would broaden or change authority.")
    if not set(normalized["scope"]).issubset(parent["scope"]) or _assurance_timestamp(
        normalized["expires_at"]
    ) > _assurance_timestamp(parent["expires_at"]) or _assurance_timestamp(
        normalized["issued_at"]
    ) < _assurance_timestamp(parent["issued_at"]):
        raise EngineeringError("Engineering scoped authority delegation would broaden authority.")
    comparable = {
        **normalized,
        "approval_reference": parent["approval_reference"],
        "approval_trust_anchor": parent["approval_trust_anchor"],
        "parent_authority_id": parent_id,
    }
    for retained in ledger["authorities"]:
        if all(retained.get(name) == value for name, value in comparable.items()):
            return dict(retained)
    controller = _project_controller_dir(project_root)
    key = _controller_key(controller, required=True)
    assert key is not None
    record = {
        "schema": SCOPED_AUTHORITY_SCHEMA,
        "authority_id": "authority-" + uuid.uuid4().hex,
        **normalized,
        "approval_reference": parent["approval_reference"],
        "approval_trust_anchor": parent["approval_trust_anchor"],
        "parent_authority_id": parent_id,
        "status": "active",
        "transitioned_at": None,
    }
    record["signature"] = _scoped_authority_signature(key, record)
    ledger["authorities"].append(record)
    ledger["authorities"].sort(key=lambda item: item["authority_id"])
    _publish_scoped_authorities(project_root, ledger, None)
    return dict(record)


def delegate_scoped_authority(root: Path, parent_id: str, binding: object) -> dict:
    project_root = resolve_project_root(str(root))
    operation = _begin_authority_mutation(project_root, "authority-delegate")
    try:
        return _delegate_scoped_authority_unlocked(project_root, parent_id, binding)
    finally:
        _end_completion(project_root, operation)


def _transition_scoped_authority_unlocked(
    root: Path, authority_id: str, transition: str, at: str
) -> dict:
    project_root = resolve_project_root(str(root))
    if transition not in {"revoked", "consumed"}:
        raise EngineeringError("Engineering scoped authority transition is invalid.")
    changed_at = _assurance_timestamp(at).isoformat()
    ledger = _load_scoped_authorities(project_root)
    matches = [item for item in ledger["authorities"] if item["authority_id"] == authority_id]
    if len(matches) != 1:
        raise EngineeringError("Engineering scoped authority is missing.")
    record = matches[0]
    if record["status"] != "active":
        if record["status"] == transition and record["transitioned_at"] == changed_at:
            return dict(record)
        raise EngineeringError("Engineering scoped authority is already terminal.")
    if _assurance_timestamp(changed_at) < _assurance_timestamp(record["issued_at"]):
        raise EngineeringError("Engineering scoped authority transition is invalid.")
    key = _controller_key(_project_controller_dir(project_root), required=True)
    assert key is not None
    record["status"] = transition
    record["transitioned_at"] = changed_at
    record["signature"] = _scoped_authority_signature(key, record)
    _publish_scoped_authorities(project_root, ledger, None)
    return dict(record)


def transition_scoped_authority(
    root: Path, authority_id: str, transition: str, at: str
) -> dict:
    project_root = resolve_project_root(str(root))
    operation = _begin_authority_mutation(project_root, "authority-transition")
    try:
        return _transition_scoped_authority_unlocked(
            project_root, authority_id, transition, at
        )
    finally:
        _end_completion(project_root, operation)


def _record_authority_audit_unlocked(
    root: Path,
    authority_id: str,
    artifact_digest: str,
    auditor_ref: str,
    verdict: str,
    observed_at: str,
) -> dict:
    project_root = resolve_project_root(str(root))
    ledger = _load_scoped_authorities(project_root)
    if authority_id not in {item["authority_id"] for item in ledger["authorities"]}:
        raise EngineeringError("Engineering scoped authority is missing.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact_digest)) or verdict not in {
        "accepted",
        "rejected",
    }:
        raise EngineeringError("Engineering authority audit is invalid.")
    auditor = _assurance_id(auditor_ref, "authority auditor reference")
    observed = _assurance_timestamp(observed_at).isoformat()
    identity = {
        "authority_id": authority_id,
        "artifact_digest": artifact_digest,
        "auditor_ref": auditor,
    }
    event_id = "audit-" + hashlib.sha256(_canonical_json(identity)).hexdigest()[:32]
    matches = [item for item in ledger["audits"] if item["event_id"] == event_id]
    if matches:
        if (
            len(matches) == 1
            and matches[0]["verdict"] == verdict
            and matches[0]["observed_at"] == observed
        ):
            return dict(matches[0])
        raise EngineeringError("Engineering authority audit replay conflicts with retained evidence.")
    key = _controller_key(_project_controller_dir(project_root), required=True)
    assert key is not None
    event = {
        "schema": AUTHORITY_AUDIT_SCHEMA,
        "event_id": event_id,
        **identity,
        "verdict": verdict,
        "observed_at": observed,
    }
    event["signature"] = _authority_audit_signature(key, event)
    ledger["audits"].append(event)
    ledger["audits"].sort(key=lambda item: item["event_id"])
    _publish_scoped_authorities(project_root, ledger, None)
    return dict(event)


def record_authority_audit(
    root: Path,
    authority_id: str,
    artifact_digest: str,
    auditor_ref: str,
    verdict: str,
    observed_at: str,
) -> dict:
    project_root = resolve_project_root(str(root))
    operation = _begin_authority_mutation(project_root, "authority-audit")
    try:
        return _record_authority_audit_unlocked(
            project_root,
            authority_id,
            artifact_digest,
            auditor_ref,
            verdict,
            observed_at,
        )
    finally:
        _end_completion(project_root, operation)


def _validate_practice(practice: object) -> dict:
    if not isinstance(practice, dict) or set(practice) != PRACTICE_KEYS:
        raise EngineeringError("Engineering learning practice is invalid.")
    if practice.get("schema") != "engineering.practice.v1" or practice.get("sanitized") is not True:
        raise EngineeringError("Engineering learning practice is invalid.")
    normalized: dict[str, object] = {
        "schema": "engineering.practice.v1",
        "title": practice.get("title"),
        "instruction": practice.get("instruction"),
        "applies_to": practice.get("applies_to"),
        "verification": practice.get("verification"),
        "sanitized": True,
    }
    for field, limit in PRACTICE_TEXT_LIMITS.items():
        value = normalized[field]
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > limit
            or any(ord(character) < 32 and character not in "\t" for character in value)
            or PRACTICE_UNSAFE.search(value)
        ):
            raise EngineeringError("Engineering learning practice is invalid.")
    modules = normalized["applies_to"]
    if (
        not isinstance(modules, list)
        or not 1 <= len(modules) <= 4
        or any(not isinstance(module, str) or module not in ALLOWED_PRACTICE_MODULES for module in modules)
        or len(set(modules)) != len(modules)
        or modules != sorted(modules)
    ):
        raise EngineeringError("Engineering learning practice is invalid.")
    return json.loads(json.dumps(normalized))


def _practice_digest(practice: object) -> str:
    return _json_digest(_validate_practice(practice))


def _skill_version() -> str:
    try:
        payload = json.loads((Path(__file__).resolve().parents[1] / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering skill manifest is invalid.") from error
    version = payload.get("version")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(version or "")):
        raise EngineeringError("Engineering skill manifest is invalid.")
    return str(version)


def _applied_practice_signature(key: bytes, item: dict) -> str:
    material = {name: item[name] for name in item if name != "signature"}
    return "hmac-sha256:" + hmac.new(key, _canonical_json(material), hashlib.sha256).hexdigest()


def _valid_applied_practice(item: object, key: bytes) -> bool:
    if not isinstance(item, dict) or set(item) != {
        "candidate_id",
        "practice_digest",
        "practice",
        "state",
        "skill_version",
        "disabled_reason",
        "signature",
    }:
        return False
    try:
        practice_digest = _practice_digest(item.get("practice"))
    except EngineeringError:
        return False
    return (
        re.fullmatch(r"candidate-[0-9a-f]{12}", str(item.get("candidate_id", ""))) is not None
        and item.get("practice_digest") == practice_digest
        and item.get("state") in {"active", "disabled"}
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(item.get("skill_version", ""))) is not None
        and (
            item.get("disabled_reason") is None
            if item.get("state") == "active"
            else item.get("disabled_reason") == "owner_disabled"
        )
        and hmac.compare_digest(
            str(item.get("signature", "")), _applied_practice_signature(key, item)
        )
    )


def _load_applied_practices() -> dict:
    path = _applied_practices_path()
    if not path.exists():
        return {"schema": "engineering.applied-practices.v1", "items": []}
    if path.stat().st_size > MAX_APPLIED_LEDGER_BYTES:
        raise EngineeringError("Engineering applied-practice ledger exceeds its size limit.")
    _verify_owner_private(path, directory=False)
    key = _controller_key(_promotion_controller_dir(), required=True)
    assert key is not None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering applied-practice ledger is invalid.") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "items"}
        or payload.get("schema") != "engineering.applied-practices.v1"
        or not isinstance(payload.get("items"), list)
        or len([item for item in payload["items"] if isinstance(item, dict) and item.get("state") == "active"])
        > MAX_ACTIVE_PRACTICES
        or len(_canonical_json(payload)) > MAX_APPLIED_LEDGER_BYTES
    ):
        raise EngineeringError("Engineering applied-practice ledger is invalid.")
    identifiers: set[str] = set()
    for item in payload["items"]:
        if (
            not _valid_applied_practice(item, key)
            or item["candidate_id"] in identifiers
        ):
            raise EngineeringError("Engineering applied-practice ledger is invalid.")
        identifiers.add(item["candidate_id"])
    return payload


def _validate_applied_ledger(payload: dict, key: bytes) -> None:
    encoded = json.dumps(payload, indent=2).encode("utf-8") + b"\n"
    if len(encoded) > MAX_APPLIED_LEDGER_BYTES:
        raise EngineeringError("Engineering applied-practice ledger exceeds its size limit.")
    if len([item for item in payload["items"] if item["state"] == "active"]) > MAX_ACTIVE_PRACTICES:
        raise EngineeringError("Engineering applied-practice ledger exceeds its active limit.")
    identifiers = [item.get("candidate_id") for item in payload["items"] if isinstance(item, dict)]
    if (
        len(identifiers) != len(payload["items"])
        or len(set(identifiers)) != len(identifiers)
        or any(not _valid_applied_practice(item, key) for item in payload["items"])
    ):
        raise EngineeringError("Engineering applied-practice ledger is invalid.")


def applicable_practices(module: str, *, manifest_version: str) -> list[dict]:
    if module not in ALLOWED_PRACTICE_MODULES:
        raise EngineeringError("Engineering practice module is invalid.")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest_version):
        raise EngineeringError("Engineering practice manifest version is invalid.")
    selected: list[dict] = []
    for item in _load_applied_practices()["items"]:
        if item["state"] != "active" or module not in item["practice"]["applies_to"]:
            continue
        if item["skill_version"].split(".", 1)[0] != manifest_version.split(".", 1)[0]:
            raise EngineeringError("Engineering applied practice is incompatible with this version.")
        selected.append(
            {
                "candidate_id": item["candidate_id"],
                "title": item["practice"]["title"],
                "instruction": item["practice"]["instruction"],
                "verification": item["practice"]["verification"],
                "reason": f"applies_to:{module}",
            }
        )
    return sorted(selected, key=lambda item: item["candidate_id"])


def _practice_projection(module: str) -> tuple[list[dict], dict | None]:
    try:
        practices = applicable_practices(module, manifest_version=_skill_version())
    except EngineeringError:
        return [], {"status": "blocked", "reason": "applied_practices_unavailable"}
    return practices, ({"status": "active", "count": len(practices)} if practices else None)


def _controller_key_path(controller: Path) -> Path:
    path = controller / "attestation.key"
    _reject_reparse_ancestors(path)
    return path


def _controller_key(controller: Path, *, required: bool) -> bytes | None:
    path = _controller_key_path(controller)
    if not path.exists() and not required:
        return None
    _verify_owner_private(controller, directory=True)
    _verify_owner_private(path, directory=False)
    try:
        raw = path.read_text(encoding="ascii").strip()
    except OSError as error:
        raise EngineeringError("Engineering controller attestation key is unavailable.") from error
    if not re.fullmatch(r"[0-9a-f]{64}", raw):
        raise EngineeringError("Engineering controller attestation key is invalid.")
    return bytes.fromhex(raw)


def _attestation_path(controller: Path) -> Path:
    path = controller / "attestations.json"
    _reject_reparse_ancestors(path)
    return path


def _attestation_signature(key: bytes, record: dict) -> str:
    material = {name: record[name] for name in ("id", "kind", "nonce", "claims")}
    return "hmac-sha256:" + hmac.new(key, _canonical_json(material), hashlib.sha256).hexdigest()


def _load_attestations(controller: Path) -> dict:
    path = _attestation_path(controller)
    if not path.exists():
        return {"schema": "engineering.controller-attestations.v1", "items": []}
    key = _controller_key(controller, required=True)
    assert key is not None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering controller attestation registry is invalid.") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "items"}
        or payload.get("schema") != "engineering.controller-attestations.v1"
        or not isinstance(payload.get("items"), list)
    ):
        raise EngineeringError("Engineering controller attestation registry is invalid.")
    identifiers: set[str] = set()
    for record in payload["items"]:
        if (
            not isinstance(record, dict)
            or set(record) != {"id", "kind", "nonce", "claims", "signature"}
            or not re.fullmatch(r"attestation-[0-9a-f]{32}", str(record.get("id", "")))
            or record.get("kind")
            not in {
                "check_capability",
                "completion",
                "promotion",
                "setup",
                "scope_handoff",
            }
            or not re.fullmatch(r"[0-9a-f]{32}", str(record.get("nonce", "")))
            or not isinstance(record.get("claims"), dict)
            or record["id"] in identifiers
            or not hmac.compare_digest(
                str(record.get("signature", "")), _attestation_signature(key, record)
            )
        ):
            raise EngineeringError("Engineering controller attestation registry is invalid.")
        identifiers.add(record["id"])
    return payload


def _append_attestation(
    controller: Path, kind: str, claims: dict
) -> tuple[dict, dict, bytes | None]:
    registry = _load_attestations(controller)
    existing = [
        item
        for item in registry["items"]
        if item["kind"] == kind and _attestation_claims_match(kind, item["claims"], claims)
    ]
    if len(existing) == 1:
        return registry, existing[0], None
    if existing:
        raise EngineeringError("Engineering controller attestation registry is ambiguous.")
    key = _controller_key(controller, required=False)
    new_key = os.urandom(32) if key is None else None
    key = key or new_key
    assert key is not None
    record = {
        "id": "attestation-" + uuid.uuid4().hex,
        "kind": kind,
        "nonce": uuid.uuid4().hex,
        "claims": claims,
    }
    record["signature"] = _attestation_signature(key, record)
    registry["items"].append(record)
    registry["items"].sort(key=lambda item: item["id"])
    return registry, record, (new_key.hex().encode("ascii") + b"\n" if new_key else None)


def _attestation_claims_match(kind: str, retained: dict, expected: dict) -> bool:
    if retained == expected:
        return True
    if kind != "check_capability" or expected.get("allow_inline_code") is not False:
        return False
    legacy = dict(expected)
    legacy.pop("allow_inline_code", None)
    return retained == legacy


def _require_attestation(controller: Path, kind: str, claims: dict) -> dict:
    matches = [
        item
        for item in _load_attestations(controller)["items"]
        if item["kind"] == kind and _attestation_claims_match(kind, item["claims"], claims)
    ]
    if len(matches) != 1:
        raise EngineeringError("Engineering controller attestation is missing or mismatched.")
    return matches[0]


def _transactional_documents(documents: list[tuple[Path, bytes]]) -> None:
    token = uuid.uuid4().hex
    replacements: list[tuple[Path, Path]] = []
    try:
        for path, content in documents:
            _reject_reparse_ancestors(path)
            stage = path.with_name(f".{path.name}.stage-{token}")
            _private_atomic_bytes(stage, content)
            replacements.append((stage, path))
        _transactional_replace(replacements, token)
    finally:
        for stage, _ in replacements:
            stage.unlink(missing_ok=True)


def _transactional_json_documents(
    documents: list[tuple[Path, dict]],
    binary_documents: list[tuple[Path, bytes]] | None = None,
) -> None:
    encoded = [
        (path, json.dumps(payload, indent=2).encode("utf-8") + b"\n")
        for path, payload in documents
    ]
    _transactional_documents([*encoded, *(binary_documents or [])])


def _contribution_index_path() -> Path:
    path = _promotion_controller_dir() / "contribution-index.json"
    _reject_reparse_ancestors(path)
    return path


def _contribution_index_signature(key: bytes, item: dict) -> str:
    material = {
        name: item[name]
        for name in ("candidate_id", "project_digest", "common_graph_dir", "local_record")
    }
    return "hmac-sha256:" + hmac.new(key, _canonical_json(material), hashlib.sha256).hexdigest()


def _load_contribution_index() -> dict:
    path = _contribution_index_path()
    if not path.exists():
        return {"schema": "engineering.contribution-index.v1", "items": []}
    key = _controller_key(_promotion_controller_dir(), required=True)
    assert key is not None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering contribution index is invalid.") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "items"}
        or payload.get("schema") != "engineering.contribution-index.v1"
        or not isinstance(payload.get("items"), list)
    ):
        raise EngineeringError("Engineering contribution index is invalid.")
    identifiers: set[str] = set()
    for item in payload["items"]:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "candidate_id",
                "project_digest",
                "common_graph_dir",
                "local_record",
                "signature",
            }
            or not re.fullmatch(r"candidate-[0-9a-f]{12}", str(item.get("candidate_id", "")))
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(item.get("project_digest", "")))
            or not isinstance(item.get("common_graph_dir"), str)
            or not Path(item["common_graph_dir"]).is_absolute()
            or not isinstance(item.get("local_record"), str)
            or not Path(item["local_record"]).is_absolute()
            or item["candidate_id"] in identifiers
            or not hmac.compare_digest(
                str(item.get("signature", "")), _contribution_index_signature(key, item)
            )
        ):
            raise EngineeringError("Engineering contribution index is invalid.")
        common = Path(item["common_graph_dir"])
        local = Path(item["local_record"])
        _reject_reparse_ancestors(common)
        _reject_reparse_ancestors(local)
        expected = common / "contributions" / f"{item['candidate_id']}.json"
        if (
            common.name != "engineering-graphs"
            or os.path.normcase(str(local.absolute()))
            != os.path.normcase(str(expected.absolute()))
        ):
            raise EngineeringError("Engineering contribution index is invalid.")
        identifiers.add(item["candidate_id"])
    return payload


def _indexed_local_contribution(candidate: dict, index: dict | None = None) -> Path:
    index = index or _load_contribution_index()
    matches = [
        item
        for item in index["items"]
        if item["candidate_id"] == candidate["id"]
        and item["project_digest"] == candidate["project_digest"]
    ]
    if len(matches) != 1:
        raise EngineeringError("Engineering project contribution pointer is missing or mismatched.")
    path = Path(matches[0]["local_record"])
    common = Path(matches[0]["common_graph_dir"])
    _reject_reparse_ancestors(path)
    expected = common / "contributions" / f"{candidate['id']}.json"
    if os.path.normcase(str(path.absolute())) != os.path.normcase(str(expected.absolute())):
        raise EngineeringError("Engineering project contribution pointer is invalid.")
    return path


def _publish_contribution_transition(
    queue: dict,
    candidate: dict,
    *,
    attestation_registry: dict | None = None,
    attestation_key: bytes | None = None,
    applied_ledger: dict | None = None,
) -> None:
    local = _indexed_local_contribution(candidate)
    try:
        retained = json.loads(local.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering project contribution is invalid.") from error
    previous_states = {
        "evaluating": {"proposed"},
        "approved_for_promotion": {"evaluating"},
        "promoted": {"approved_for_promotion"},
        "promoted_applied": {"evaluating", "approved_for_promotion"},
        "rejected": {"proposed"},
    }
    if retained.get("state") not in previous_states.get(candidate["state"], set()):
        raise EngineeringError("Engineering project contribution conflicts with controller state.")
    documents = [(_contribution_queue_path(), queue), (local, candidate)]
    if attestation_registry is not None:
        documents.append((_promotion_attestation_path(), attestation_registry))
    if applied_ledger is not None:
        documents.append((_applied_practices_path(), applied_ledger))
    _transactional_json_documents(
        documents,
        [(_controller_key_path(_promotion_controller_dir()), attestation_key)]
        if attestation_key
        else None,
    )


def _acquire_directory_lock(path: Path, message: str) -> dict:
    home = _engineering_user_home()
    expected_parent = home / ".agents" / "engineering"
    if path.name not in {"install.lock", "contribution.lock"} or os.path.normcase(
        str(path.parent.resolve())
    ) != os.path.normcase(str(expected_parent.resolve())):
        raise EngineeringError("Engineering directory lock is outside its managed boundary.")
    _reject_reparse_ancestors(path, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_reparse_ancestors(path, home)
    owner = {
        "schema": "engineering.directory-lock.v1",
        "owner_pid": os.getpid(),
        "created_at": _utc_now(),
        "operation_id": "operation-" + uuid.uuid4().hex,
        "token": uuid.uuid4().hex,
    }
    for _ in range(2):
        stage = path.with_name(f".{path.name}.stage-{owner['token']}")
        try:
            stage.mkdir()
            _atomic_text(stage / "owner.json", json.dumps(owner, indent=2) + "\n")
            _reject_reparse_ancestors(path, home)
            os.replace(stage, path)
            return owner
        except OSError as error:
            if stage.exists():
                _reject_reparse_ancestors(stage, home)
                (stage / "owner.json").unlink(missing_ok=True)
                stage.rmdir()
            if not path.exists():
                raise
            _reject_reparse_ancestors(path, home)
            if _is_reparse_point(path):
                raise EngineeringError("Engineering directory lock is a reparse point.") from error
            owner_path = path / "owner.json"
            try:
                _reject_reparse_ancestors(owner_path, home)
                before = owner_path.read_bytes()
                retained = json.loads(before)
                created = _maintenance_time(retained["created_at"])
                valid = (
                    set(retained) == {
                        "schema", "owner_pid", "created_at", "operation_id", "token"
                    }
                    and retained["schema"] == "engineering.directory-lock.v1"
                    and isinstance(retained["owner_pid"], int)
                    and re.fullmatch(r"operation-[0-9a-f]{32}", retained["operation_id"])
                    and re.fullmatch(r"[0-9a-f]{32}", retained["token"])
                )
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                valid = False
            if (
                not valid
                or _process_alive(retained["owner_pid"])
                or datetime.now(timezone.utc) - created < timedelta(seconds=30)
            ):
                raise EngineeringError(message) from error
            _reject_reparse_ancestors(owner_path, home)
            if _is_reparse_point(path) or _is_reparse_point(owner_path):
                raise EngineeringError("Engineering directory lock is a reparse point.") from error
            if owner_path.read_bytes() != before:
                raise EngineeringError(message) from error
            quarantine = path.with_name(f".{path.name}.reclaim-{owner['token']}")
            try:
                os.replace(path, quarantine)
            except OSError as race:
                raise EngineeringError(message) from race
            try:
                _reject_reparse_ancestors(quarantine, home)
                quarantine_owner = quarantine / "owner.json"
                if _is_reparse_point(quarantine) or _is_reparse_point(quarantine_owner):
                    raise EngineeringError("Engineering directory lock is a reparse point.")
                if quarantine_owner.read_bytes() != before:
                    raise EngineeringError(message)
                quarantine_owner.unlink()
                quarantine.rmdir()
            except Exception:
                if quarantine.exists() and not path.exists():
                    try:
                        os.replace(quarantine, path)
                    except OSError:
                        pass
                raise
    raise EngineeringError(message)


def _release_directory_lock(path: Path, owner: dict) -> None:
    try:
        home = _engineering_user_home()
        expected_parent = home / ".agents" / "engineering"
        if path.name not in {"install.lock", "contribution.lock"} or os.path.normcase(
            str(path.parent.resolve())
        ) != os.path.normcase(str(expected_parent.resolve())):
            raise EngineeringError("Engineering directory lock is outside its managed boundary.")
        _reject_reparse_ancestors(path, home)
        if _is_reparse_point(path):
            raise EngineeringError("Engineering directory lock is a reparse point.")
        owner_path = path / "owner.json"
        _reject_reparse_ancestors(owner_path, home)
        if _is_reparse_point(owner_path):
            raise EngineeringError("Engineering directory lock is a reparse point.")
        retained = json.loads(owner_path.read_text(encoding="utf-8"))
        if retained != owner:
            raise EngineeringError("Engineering directory lock ownership changed.")
        _reject_reparse_ancestors(owner_path, home)
        owner_path.unlink()
        path.rmdir()
    except FileNotFoundError:
        pass


def _load_contribution_queue() -> dict:
    path = _contribution_queue_path()
    if not path.exists():
        return {"schema": "engineering.contribution-queue.v1", "items": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering contribution queue is invalid.") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "items"}
        or payload.get("schema") != "engineering.contribution-queue.v1"
        or not isinstance(payload.get("items"), list)
    ):
        raise EngineeringError("Engineering contribution queue is invalid.")
    identifiers: set[str] = set()
    for item in payload["items"]:
        if not _valid_contribution_item(item) or item["id"] in identifiers:
            raise EngineeringError("Engineering contribution queue is invalid.")
        identifiers.add(item["id"])
    return payload


def _lifecycle_record(identifier: str, state: str) -> dict:
    return {
        "id": "transition-"
        + hashlib.sha256(f"{identifier}\0{state}".encode("utf-8")).hexdigest()[:12],
        "state": state,
    }


def _candidate_identifier(
    project_digest: str,
    source_digest: str,
    kind: str,
    practice_digest: str | None = None,
) -> str:
    material = f"{project_digest}\0{source_digest}\0{kind}"
    if practice_digest is not None:
        material += f"\0{practice_digest}"
    return "candidate-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _learning_candidate_projection(candidate: dict) -> dict:
    practice = _validate_practice(candidate.get("practice"))
    actions = {
        "proposed": ["keep", "inspect", "dismiss"],
        "evaluating": ["inspect"],
        "approved_for_promotion": ["inspect", "promote_and_apply"],
        "promoted_applied": ["inspect", "disable", "source_improvement"],
        "rejected": ["inspect"],
    }.get(candidate["state"], ["inspect"])
    return {
        "candidate_id": candidate["id"],
        "title": practice["title"],
        "kind": candidate["kind"],
        "modules": list(practice["applies_to"]),
        "state": candidate["state"],
        "actions": actions,
    }


def _valid_contribution_item(item: object) -> bool:
    legacy_keys = {
        "id",
        "project_digest",
        "source_reference",
        "source_digest",
        "kind",
        "state",
        "evidence",
        "review",
        "history",
    }
    if not isinstance(item, dict):
        return False
    item_keys = frozenset(item)
    if item_keys not in {
        frozenset(legacy_keys),
        frozenset({*legacy_keys, "practice", "practice_digest"}),
    }:
        return False
    identifier = item.get("id")
    state = item.get("state")
    if not (
        re.fullmatch(r"candidate-[0-9a-f]{12}", str(identifier or ""))
        and state in CONTRIBUTION_STATES
        and item.get("kind") in CONTRIBUTION_KINDS
        and re.fullmatch(r"sha256:[0-9a-f]{64}", str(item.get("project_digest", "")))
        and re.fullmatch(r"sha256:[0-9a-f]{64}", str(item.get("source_digest", "")))
        and re.fullmatch(r"completion:run-[0-9a-f]{6}", str(item.get("source_reference", "")))
        and isinstance(item.get("evidence"), list)
        and isinstance(item.get("review"), dict)
        and isinstance(item.get("history"), list)
    ):
        return False
    practice_digest = item.get("practice_digest")
    if practice_digest is not None:
        try:
            if practice_digest != _practice_digest(item.get("practice")):
                return False
        except EngineeringError:
            return False
    expected_identifier = _candidate_identifier(
        item["project_digest"], item["source_digest"], item["kind"], practice_digest
    )
    if identifier != expected_identifier:
        return False
    expected_states = {
        "proposed": ["proposed"],
        "evaluating": ["proposed", "evaluating"],
        "approved_for_promotion": ["proposed", "evaluating", "approved_for_promotion"],
        "promoted": ["proposed", "evaluating", "approved_for_promotion", "promoted"],
        "promoted_applied": ["proposed", "evaluating", "promoted_applied"],
        "rejected": ["proposed", "rejected"],
    }[state]
    expected_history = [_lifecycle_record(identifier, value) for value in expected_states]
    if state == "promoted_applied":
        migrated_history = [
            _lifecycle_record(identifier, value)
            for value in (
                "proposed",
                "evaluating",
                "approved_for_promotion",
                "promoted_applied",
            )
        ]
        if item["history"] != expected_history and item["history"] != migrated_history:
            return False
    elif item["history"] != expected_history:
        return False
    evaluation_ids: set[str] = set()
    for evidence in item["evidence"]:
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {
                "id",
                "project_digest",
                "source_reference",
                "source_digest",
                "result",
            }
            or not re.fullmatch(r"evaluation-[0-9a-f]{12}", str(evidence.get("id", "")))
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(evidence.get("project_digest", "")))
            or evidence.get("project_digest") == item["project_digest"]
            or not re.fullmatch(r"completion:run-[0-9a-f]{6}", str(evidence.get("source_reference", "")))
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(evidence.get("source_digest", "")))
            or evidence.get("result") != "passed"
            or evidence["id"] in evaluation_ids
        ):
            return False
        expected_evaluation = "evaluation-" + hashlib.sha256(
            f"{identifier}\0{evidence['project_digest']}\0{evidence['source_digest']}".encode("utf-8")
        ).hexdigest()[:12]
        if evidence["id"] != expected_evaluation:
            return False
        evaluation_ids.add(evidence["id"])
    if state == "proposed":
        return not item["evidence"] and item["review"] == {}
    if state == "evaluating":
        return bool(item["evidence"]) and item["review"] == {}
    if state in {"approved_for_promotion", "promoted", "promoted_applied"}:
        approval = item["review"].get("approval")
        return (
            bool(item["evidence"])
            and set(item["review"]) == {"approval"}
            and isinstance(approval, dict)
            and approval == {
                "id": "approval-"
                + hashlib.sha256(f"{identifier}\0approved".encode("utf-8")).hexdigest()[:12],
                "decision": "approved",
            }
        )
    rejection = item["review"].get("rejection")
    return (
        not item["evidence"]
        and set(item["review"]) == {"rejection"}
        and isinstance(rejection, dict)
        and rejection.get("decision") == "rejected"
    )


def _project_contribution_digest(root: Path) -> str:
    root = Path(root).resolve()
    top = Path(_identity_git(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise EngineeringError("Engineering project Git root is ambiguous.")
    common_raw = _identity_git(root, "rev-parse", "--git-common-dir")
    common = Path(common_raw)
    if not common.is_absolute():
        common = root / common
    _reject_reparse_ancestors(common.absolute())
    common = common.resolve()
    if not common.is_dir() or _is_reparse_point(common):
        raise EngineeringError("Engineering project Git common directory is invalid.")
    if _identity_git(root, "rev-parse", "--is-shallow-repository") != "false":
        raise EngineeringError("Engineering project Git lineage is shallow or ambiguous.")
    if _identity_git(root, "for-each-ref", "--format=%(refname)", "refs/replace").strip():
        raise EngineeringError("Engineering project Git lineage contains replace state.")
    graft = Path(_identity_git(root, "rev-parse", "--git-path", "info/grafts"))
    if not graft.is_absolute():
        graft = root / graft
    _reject_reparse_ancestors(graft.absolute())
    if graft.is_file() and graft.stat().st_size:
        raise EngineeringError("Engineering project Git lineage contains graft state.")
    roots = _identity_git(root, "rev-list", "--max-parents=0", "HEAD").splitlines()
    common_after_raw = _identity_git(root, "rev-parse", "--git-common-dir")
    common_after = Path(common_after_raw)
    if not common_after.is_absolute():
        common_after = root / common_after
    if common_after.resolve() != common:
        raise EngineeringError("Engineering project Git common directory changed during validation.")
    if len(roots) != 1 or not re.fullmatch(r"[0-9a-f]{40,64}", roots[0]):
        raise EngineeringError("Engineering project Git lineage is ambiguous.")
    return "sha256:" + hashlib.sha256(f"git-root\0{roots[0]}".encode("ascii")).hexdigest()


def _completion_attestation_claims(root: Path, completion: dict) -> dict:
    return {
        "run_id": completion["run_id"],
        "completion_digest": _json_digest(completion),
        "repository_id": _project_contribution_digest(root),
    }


def _terminal_completion(root: Path, completion_id: str) -> tuple[dict, str]:
    if not re.fullmatch(r"run-[0-9a-f]{6}", completion_id):
        raise EngineeringError("Engineering learning requires terminal verified completion evidence.")
    path = _common_graph_dir(root) / "runs" / completion_id / "completion.json"
    try:
        raw = path.read_bytes()
        completion = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EngineeringError(
            "Engineering learning requires terminal verified completion evidence."
        ) from error
    try:
        preparation = _load_preparation(root, completion_id)
        if "scope_handoff" in preparation["authorization"]:
            _validate_scope_handoff_authority(
                root,
                preparation["project"]["commit"],
                load_project_config(root),
                preparation["authorization"]["scope_handoff"],
            )
        checks = completion["checks"]
        result = completion["result_identity"]
        checkpoint = completion["checkpoint"]
        expected = _completion_payload(
            preparation,
            completion["changed_artifacts"],
            result,
            {"commit": checkpoint["commit"], "ready": True},
            False,
            checks,
            completion["maintenance"],
            completion.get("scope_result"),
            completion.get("scope_result_artifacts"),
        )
        _load_checkpoint(root, checkpoint["commit"])
        valid = (
            completion == expected
            and _successful_check_evidence(preparation["required_checks"], checks)
            and checkpoint["status"] == "current"
            and result == {"commit": checkpoint["commit"], "dirty_tree_digest": None}
            and preparation["project"]["root_digest"]
            == "sha256:" + checkpoint_identity(root, preparation["project"]["commit"])
        )
    except (EngineeringError, KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise EngineeringError(
            "Engineering learning requires terminal verified completion evidence."
        )
    try:
        _require_attestation(
            _project_controller_dir(root),
            "completion",
            _completion_attestation_claims(root, completion),
        )
    except EngineeringError as error:
        raise EngineeringError(
            "Engineering learning requires terminal verified completion attestation."
        ) from error
    return completion, "sha256:" + hashlib.sha256(raw).hexdigest()


_DELIVERY_METRICS = (
    "duration_seconds",
    "critical_path_seconds",
    "coordination_cost_seconds",
    "terminal_to_reconciliation_seconds",
    "feedback_iterations",
    "invalidated_evidence",
    "rework",
    "escaped_defects",
    "false_blockers",
    "missed_escalations",
    "unnecessary_orchestrator_intervention",
    "unconsumed_terminal_event",
    "proxy_pass_outcome_fail",
    "audit_false_positive",
)
_DELIVERY_EVALUATION_MAX_ITEMS = 365
_DELIVERY_EVALUATION_MAX_BYTES = 1_048_576


def _delivery_evaluation_path() -> Path:
    path = _promotion_controller_dir() / "delivery-evaluations.json"
    _reject_reparse_ancestors(path)
    return path


def _delivery_label(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", value)
        or _contains_credential(value)
    ):
        raise EngineeringError(f"Engineering delivery evaluation {label} is invalid.")
    return value


def _delivery_count(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= 604800:
        raise EngineeringError(f"Engineering delivery evaluation {label} is invalid.")
    return value


def _delivery_routing_fact(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise EngineeringError("Engineering delivery evaluation routing is invalid.")
    if set(value) == {"state"} and value.get("state") == "unknown":
        return {"state": "unknown"}
    if set(value) == {"state", "value"} and value.get("state") == "recorded":
        return {
            "state": "recorded",
            "value": _delivery_label(value["value"], f"routing {label}"),
        }
    raise EngineeringError("Engineering delivery evaluation routing is invalid.")


def _delivery_routing(value: object) -> dict:
    names = {"reasoning", "owner_override", "execution_target", "scope"}
    if not isinstance(value, dict) or set(value) != names:
        raise EngineeringError("Engineering delivery evaluation routing is invalid.")
    return {name: _delivery_routing_fact(value[name], name) for name in sorted(names)}


def _validate_delivery_evaluation(
    value: object,
    *,
    bound_terminal_evidence: set[str] | None = None,
    bound_acceptance_evidence: set[str] | None = None,
    allow_legacy_terminal: bool = False,
    allow_legacy_routing: bool = False,
) -> dict:
    legacy_required = {
        "task_id", "dod_id", "artifact_digest", "verdict", "trigger", "model", "lanes",
        "terminal", "acceptance", *_DELIVERY_METRICS, "auditor_coverage", "non_applicable"
    }
    required = legacy_required | {"routing"}
    if not isinstance(value, dict):
        raise EngineeringError("Engineering delivery evaluation input is invalid.")
    keys = set(value)
    legacy_routing = keys == legacy_required
    if legacy_routing and not allow_legacy_routing:
        raise EngineeringError("Engineering delivery evaluation routing is required.")
    if keys != required and not (allow_legacy_routing and legacy_routing):
        raise EngineeringError("Engineering delivery evaluation input is invalid.")
    non_applicable = value["non_applicable"]
    permitted_reasons = {*_DELIVERY_METRICS, "model.fallback"}
    if (
        not isinstance(non_applicable, dict)
        or not set(non_applicable).issubset(permitted_reasons)
    ):
        raise EngineeringError("Engineering delivery evaluation non-applicable reasons are invalid.")
    reasons = {
        name: _delivery_label(reason, "non-applicable reason")
        for name, reason in non_applicable.items()
    }
    model = value["model"]
    lanes = value["lanes"]
    coverage = value["auditor_coverage"]
    acceptance = value["acceptance"]
    terminal = value["terminal"]
    routing = None if legacy_routing else _delivery_routing(value["routing"])
    terminal_keys = {
        "artifact_identity",
        "acceptance_state",
        "current_gate",
        "next_action",
        "reconciliation_digest",
    }
    legacy_terminal_keys = terminal_keys - {"reconciliation_digest"}
    valid_terminal_shape = (
        isinstance(terminal, dict)
        and (
            set(terminal) == terminal_keys
            or (allow_legacy_terminal and set(terminal) == legacy_terminal_keys)
        )
    )
    if (
        not isinstance(model, dict)
        or set(model) != {"requested", "actual", "fallback"}
        or not isinstance(lanes, dict)
        or set(lanes) != {"dependencies", "parallelism"}
        or not isinstance(coverage, dict)
        or set(coverage) != {"planned", "completed"}
        or not valid_terminal_shape
        or not isinstance(acceptance, dict)
        or set(acceptance) != {
            "technical", "domain", "outcome", "operating_interface", "operating_environment",
            "representative_data", "outcome_evidence_digest", "representative_data_evidence_digest", "gate"
        }
    ):
        raise EngineeringError("Engineering delivery evaluation input is invalid.")
    fallback = model["fallback"]
    if fallback is None:
        if "model.fallback" not in reasons:
            raise EngineeringError("Engineering delivery evaluation fallback reason is required.")
    elif "model.fallback" in reasons:
        raise EngineeringError("Engineering delivery evaluation fallback reason is invalid.")
    else:
        fallback = _delivery_label(fallback, "fallback model")
    normalized_terminal = {
        "artifact_identity": terminal["artifact_identity"],
        "acceptance_state": _delivery_label(terminal["acceptance_state"], "terminal acceptance state"),
        "current_gate": _delivery_label(terminal["current_gate"], "terminal current gate"),
        "next_action": _delivery_label(terminal["next_action"], "terminal next action"),
    }
    if "reconciliation_digest" in terminal:
        normalized_terminal["reconciliation_digest"] = terminal["reconciliation_digest"]
    normalized = {
        "task_id": _delivery_label(value["task_id"], "task identity"),
        "dod_id": _delivery_label(value["dod_id"], "DoD identity"),
        "artifact_digest": value["artifact_digest"],
        "verdict": value["verdict"],
        "trigger": _delivery_label(value["trigger"], "trigger"),
        "model": {
            "requested": _delivery_label(model["requested"], "requested model"),
            "actual": _delivery_label(model["actual"], "actual model"),
            "fallback": fallback,
        },
        "terminal": normalized_terminal,
        "acceptance": {
            "technical": _delivery_label(acceptance["technical"], "technical acceptance"),
            "domain": _delivery_label(acceptance["domain"], "domain acceptance"),
            "outcome": _delivery_label(acceptance["outcome"], "outcome acceptance"),
            "operating_interface": _delivery_label(acceptance["operating_interface"], "operating interface"),
            "operating_environment": _delivery_label(acceptance["operating_environment"], "operating environment"),
            "representative_data": _delivery_label(acceptance["representative_data"], "representative data"),
            "outcome_evidence_digest": acceptance["outcome_evidence_digest"],
            "representative_data_evidence_digest": acceptance["representative_data_evidence_digest"],
            "gate": _delivery_label(acceptance["gate"], "acceptance gate"),
        },
        "lanes": {
            "dependencies": _delivery_count(lanes["dependencies"], "lane dependencies"),
            "parallelism": _delivery_count(lanes["parallelism"], "lane parallelism", minimum=1),
        },
        "auditor_coverage": {
            "planned": _delivery_count(coverage["planned"], "auditor coverage"),
            "completed": _delivery_count(coverage["completed"], "auditor coverage"),
        },
        "non_applicable": dict(sorted(reasons.items())),
    }
    if routing is not None:
        normalized["routing"] = routing
    if (
        not re.fullmatch(r"sha256:[0-9a-f]{64}", str(normalized["artifact_digest"]))
        or normalized["verdict"] != "accepted_exact_artifact"
        or normalized["terminal"]["artifact_identity"] != normalized["artifact_digest"]
        or normalized["terminal"]["acceptance_state"] != normalized["verdict"]
        or (
            "reconciliation_digest" in normalized["terminal"]
            and not re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                str(normalized["terminal"]["reconciliation_digest"]),
            )
        )
    ):
        raise EngineeringError("Engineering delivery evaluation identity is invalid.")
    if normalized["auditor_coverage"]["completed"] > normalized["auditor_coverage"]["planned"]:
        raise EngineeringError("Engineering delivery evaluation auditor coverage is invalid.")
    if (
        any(normalized["acceptance"][name] not in {"passed", "failed", "unknown"} for name in ("technical", "domain", "outcome"))
        or normalized["acceptance"]["operating_interface"] not in {"ui", "cli", "api", "file", "service", "device", "workflow"}
        or normalized["acceptance"]["operating_environment"] not in {"local", "staging", "production", "user_environment"}
        or normalized["acceptance"]["representative_data"] not in {"verified", "missing", "unknown"}
        or normalized["acceptance"]["gate"] not in {"accepted", "failed"}
        or (
            normalized["acceptance"]["outcome"] == "passed"
            and normalized["acceptance"]["representative_data"] != "verified"
        )
    ):
        raise EngineeringError("Engineering delivery evaluation acceptance is invalid.")
    for name in ("outcome_evidence_digest", "representative_data_evidence_digest"):
        evidence = normalized["acceptance"][name]
        if evidence is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(evidence)):
            raise EngineeringError("Engineering delivery evaluation acceptance evidence is invalid.")
    if (
        (normalized["acceptance"]["outcome"] == "unknown")
        != (normalized["acceptance"]["outcome_evidence_digest"] is None)
        or (normalized["acceptance"]["representative_data"] == "verified")
        != (normalized["acceptance"]["representative_data_evidence_digest"] is not None)
    ):
        raise EngineeringError("Engineering delivery evaluation acceptance evidence is invalid.")
    if bound_terminal_evidence is not None or bound_acceptance_evidence is not None:
        if (
            "reconciliation_digest" not in normalized["terminal"]
            or bound_terminal_evidence is None
            or normalized["terminal"]["reconciliation_digest"] not in bound_terminal_evidence
        ):
            raise EngineeringError(
                "Engineering delivery evaluation terminal evidence is not controller-bound."
            )
        for name in ("outcome_evidence_digest", "representative_data_evidence_digest"):
            evidence = normalized["acceptance"][name]
            if (
                evidence is not None
                and (
                    bound_acceptance_evidence is None
                    or evidence not in bound_acceptance_evidence
                )
            ):
                raise EngineeringError(
                    "Engineering delivery evaluation acceptance evidence is not controller-bound."
                )
    accepted = all(normalized["acceptance"][name] == "passed" for name in ("technical", "domain", "outcome")) and normalized["acceptance"]["representative_data"] == "verified"
    if normalized["acceptance"]["gate"] != ("accepted" if accepted else "failed"):
        raise EngineeringError("Engineering delivery evaluation acceptance gate is invalid.")
    for name in _DELIVERY_METRICS:
        item = value[name]
        if item is None:
            if name not in reasons:
                raise EngineeringError("Engineering delivery evaluation non-applicable reason is required.")
            normalized[name] = None
        elif name in reasons:
            raise EngineeringError("Engineering delivery evaluation non-applicable reason is invalid.")
        else:
            normalized[name] = _delivery_count(item, name)
    if normalized["unconsumed_terminal_event"] not in {0, 1}:
        raise EngineeringError("Engineering delivery evaluation terminal event is invalid.")
    expected_proxy_failure = int(
        normalized["acceptance"]["technical"] == "passed"
        and normalized["acceptance"]["outcome"] == "failed"
    )
    expected_audit_false_positive = int(
        expected_proxy_failure
        and normalized["acceptance"]["domain"] == "passed"
    )
    if (
        normalized["proxy_pass_outcome_fail"] != expected_proxy_failure
        or normalized["audit_false_positive"] != expected_audit_false_positive
        or (
            normalized["audit_false_positive"]
            and normalized["auditor_coverage"]["completed"] == 0
        )
    ):
        raise EngineeringError("Engineering delivery evaluation proxy signal is invalid.")
    if normalized["critical_path_seconds"] is not None and normalized["duration_seconds"] is not None and normalized["critical_path_seconds"] > normalized["duration_seconds"]:
        raise EngineeringError("Engineering delivery evaluation critical path is invalid.")
    if normalized["coordination_cost_seconds"] is not None and normalized["duration_seconds"] is not None and normalized["coordination_cost_seconds"] > normalized["duration_seconds"]:
        raise EngineeringError("Engineering delivery evaluation coordination cost is invalid.")
    return normalized


def _delivery_artifact_digest(completion: dict) -> str:
    try:
        return _json_digest({
            "changed_artifacts": completion["changed_artifacts"],
            "result_identity": completion["result_identity"],
        })
    except (KeyError, TypeError):
        raise EngineeringError("Engineering delivery evaluation exact artifact is unavailable.") from None


def _delivery_evaluation_signature(key: bytes, record: dict) -> str:
    material = {name: value for name, value in record.items() if name != "signature"}
    return "hmac-sha256:" + hmac.new(key, _canonical_json(material), hashlib.sha256).hexdigest()


def _delivery_evaluation_bytes(payload: dict) -> int:
    return len(json.dumps(payload, indent=2).encode("utf-8") + b"\n")


def _load_delivery_evaluations() -> dict:
    path = _delivery_evaluation_path()
    if not path.exists():
        return {
            "schema": "engineering.delivery-evaluations.v1",
            "items": [],
            "sequences": {},
            "next_sequence": 1,
        }
    _verify_owner_private(path, directory=False)
    if path.stat().st_size > _DELIVERY_EVALUATION_MAX_BYTES:
        raise EngineeringError("Engineering delivery evaluation ledger exceeds its bounded size.")
    key = _controller_key(_promotion_controller_dir(), required=True)
    assert key is not None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering delivery evaluation ledger is invalid.") from error
    identifiers: set[str] = set()
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "items", "sequences", "next_sequence"}
        or payload["schema"] != "engineering.delivery-evaluations.v1"
        or not isinstance(payload["items"], list)
        or not isinstance(payload["sequences"], dict)
        or isinstance(payload["next_sequence"], bool)
        or not isinstance(payload["next_sequence"], int)
    ):
        raise EngineeringError("Engineering delivery evaluation ledger is invalid.")
    for record in payload["items"]:
        try:
            valid = (
                isinstance(record, dict)
                and set(record) == {"schema", "id", "project_digest", "completion_id", "completion_digest", "input", "signature"}
                and record["schema"] == "engineering.delivery-evaluation.v1"
                and re.fullmatch(r"delivery-eval-[0-9a-f]{12}", str(record["id"]))
                and re.fullmatch(r"sha256:[0-9a-f]{64}", str(record["project_digest"]))
                and re.fullmatch(r"run-[0-9a-f]{6}", str(record["completion_id"]))
                and re.fullmatch(r"sha256:[0-9a-f]{64}", str(record["completion_digest"]))
                and _validate_delivery_evaluation(
                    record["input"],
                    allow_legacy_terminal=True,
                    allow_legacy_routing=True,
                ) == record["input"]
                and record["id"] not in identifiers
                and hmac.compare_digest(str(record["signature"]), _delivery_evaluation_signature(key, record))
            )
        except (KeyError, TypeError, EngineeringError):
            valid = False
        if not valid:
            raise EngineeringError("Engineering delivery evaluation ledger is invalid.")
        identifiers.add(record["id"])
    if (
        set(payload["sequences"]) != identifiers
        or any(
            isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1
            for sequence in payload["sequences"].values()
        )
        or len(set(payload["sequences"].values())) != len(identifiers)
        or payload["next_sequence"] <= max(payload["sequences"].values(), default=0)
        or len(payload["items"]) > _DELIVERY_EVALUATION_MAX_ITEMS
        or _delivery_evaluation_bytes(payload) > _DELIVERY_EVALUATION_MAX_BYTES
    ):
        raise EngineeringError("Engineering delivery evaluation ledger exceeds its bounded limits.")
    return payload


def record_delivery_evaluation(root: Path, completion_id: str, value: object) -> dict:
    project = resolve_project(Path(root))
    completion, completion_digest = _terminal_completion(project.root, completion_id)
    project_digest = _project_contribution_digest(project.root)
    bound_acceptance_evidence = {
        receipt["output_digest"]
        for receipt in completion.get("checks", [])
        if isinstance(receipt, dict)
        and isinstance(receipt.get("output_digest"), str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", receipt["output_digest"])
    }
    normalized = _validate_delivery_evaluation(
        value,
        bound_terminal_evidence={completion_digest},
        bound_acceptance_evidence=bound_acceptance_evidence,
    )
    if normalized["terminal"]["reconciliation_digest"] != completion_digest:
        raise EngineeringError(
            "Engineering delivery evaluation terminal evidence is not controller-bound."
        )
    if normalized["artifact_digest"] != _delivery_artifact_digest(completion):
        raise EngineeringError("Engineering delivery evaluation exact artifact is invalid.")
    identifier = "delivery-eval-" + hashlib.sha256(
        f"{project_digest}\0{completion_id}\0{completion_digest}".encode("ascii")
    ).hexdigest()[:12]
    record = {
        "schema": "engineering.delivery-evaluation.v1",
        "id": identifier,
        "project_digest": project_digest,
        "completion_id": completion_id,
        "completion_digest": completion_digest,
        "input": normalized,
    }
    lock = _contribution_lock_path()
    lock_owner = _acquire_directory_lock(lock, "Engineering delivery evaluation update is already in progress.")
    try:
        ledger = _load_delivery_evaluations()
        existing = next((item for item in ledger["items"] if item["id"] == identifier), None)
        if existing is not None:
            if {name: item for name, item in existing.items() if name != "signature"} != record:
                raise EngineeringError("Engineering delivery evaluation replay conflicts with retained state.")
            return dict(existing)
        controller = _promotion_controller_dir()
        key = _controller_key(controller, required=False)
        new_key = os.urandom(32) if key is None else None
        key = key or new_key
        assert key is not None
        record["signature"] = _delivery_evaluation_signature(key, record)
        ledger["items"].append(record)
        ledger["sequences"][record["id"]] = ledger["next_sequence"]
        ledger["next_sequence"] += 1
        ledger["items"].sort(key=lambda item: ledger["sequences"][item["id"]])
        while (
            len(ledger["items"]) > _DELIVERY_EVALUATION_MAX_ITEMS
            or _delivery_evaluation_bytes(ledger) > _DELIVERY_EVALUATION_MAX_BYTES
        ):
            if len(ledger["items"]) == 1:
                raise EngineeringError("Engineering delivery evaluation exceeds its bounded size.")
            removed = ledger["items"].pop(0)
            del ledger["sequences"][removed["id"]]
        _transactional_json_documents(
            [(_delivery_evaluation_path(), ledger)],
            [(_controller_key_path(controller), new_key.hex().encode("ascii") + b"\n")]
            if new_key else None,
        )
        return dict(record)
    finally:
        _release_directory_lock(lock, lock_owner)


def delivery_trends(window: int = 30) -> dict:
    if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 365:
        raise EngineeringError("Engineering delivery trend window is invalid.")
    ledger = _load_delivery_evaluations()
    ordered = sorted(ledger["items"], key=lambda item: ledger["sequences"][item["id"]])
    verified_ordered = [
        record
        for record in ordered
        if "reconciliation_digest" in record["input"].get("terminal", {})
    ]
    legacy_record_count = len(ordered) - len(verified_ordered)
    latest = verified_ordered[-1] if verified_ordered else None
    cohort = (
        {"task_id": latest["input"]["task_id"], "dod_id": latest["input"]["dod_id"]}
        if latest is not None else None
    )
    records = [
        record for record in verified_ordered
        if cohort is not None
        and record["input"]["task_id"] == cohort["task_id"]
        and record["input"]["dod_id"] == cohort["dod_id"]
    ][-window:]
    metric_names = (*_DELIVERY_METRICS, "lane_dependencies", "lane_parallelism", "auditors_planned", "auditors_completed")
    values = {name: [] for name in metric_names}
    models: dict[str, int] = {}
    for record in records:
        value = record["input"]
        for name in _DELIVERY_METRICS:
            if value[name] is not None:
                values[name].append(value[name])
        values["lane_dependencies"].append(value["lanes"]["dependencies"])
        values["lane_parallelism"].append(value["lanes"]["parallelism"])
        values["auditors_planned"].append(value["auditor_coverage"]["planned"])
        values["auditors_completed"].append(value["auditor_coverage"]["completed"])
        models[value["model"]["actual"]] = models.get(value["model"]["actual"], 0) + 1
    return {
        "schema": "engineering.delivery-trends.v1",
        "window": window,
        "status": "ready" if len(records) >= 2 else "insufficient_sample",
        "cohort": cohort,
        "record_count": len(records),
        "legacy_record_count": legacy_record_count,
        "models": [{"actual": name, "count": models[name]} for name in sorted(models)],
        "metrics": {
            name: {"count": len(items), "sum": sum(items), "average": (sum(items) / len(items) if items else None)}
            for name, items in values.items()
        },
        "rates": {
            name: (sum(values[name]) / len(values[name]) if values[name] else None)
            for name in ("proxy_pass_outcome_fail", "audit_false_positive")
        },
    }


def propose_learning(
    root: Path,
    completion_id: str,
    kind: str,
    practice: dict | None = None,
) -> dict:
    project = resolve_project(Path(root))
    if kind not in CONTRIBUTION_KINDS:
        raise EngineeringError("Engineering learning kind is invalid.")
    _, source_digest = _terminal_completion(project.root, completion_id)
    project_digest = _project_contribution_digest(project.root)
    normalized_practice = _validate_practice(practice) if practice is not None else None
    practice_digest = _practice_digest(normalized_practice) if normalized_practice else None
    identifier = _candidate_identifier(project_digest, source_digest, kind, practice_digest)
    candidate = {
        "id": identifier,
        "project_digest": project_digest,
        "source_reference": f"completion:{completion_id}",
        "source_digest": source_digest,
        "kind": kind,
        "state": "proposed",
        "evidence": [],
        "review": {},
        "history": [_lifecycle_record(identifier, "proposed")],
    }
    if normalized_practice is not None:
        candidate["practice"] = normalized_practice
        candidate["practice_digest"] = practice_digest
    local = _common_graph_dir(project.root) / "contributions" / f"{identifier}.json"
    lock = _contribution_lock_path()
    lock_owner = _acquire_directory_lock(lock, "Engineering contribution update is already in progress.")
    try:
        queue = _load_contribution_queue()
        index = _load_contribution_index()
        existing = next((item for item in queue["items"] if item["id"] == identifier), None)
        if existing is None and practice_digest is not None:
            existing = next(
                (
                    item
                    for item in queue["items"]
                    if item.get("practice_digest") == practice_digest and item["kind"] == kind
                ),
                None,
            )
        if existing is not None:
            identity_keys = {
                "id",
                "project_digest",
                "source_reference",
                "source_digest",
                "kind",
            }
            if existing.get("practice_digest") == practice_digest and practice_digest is not None:
                return dict(existing)
            if any(existing[key] != candidate[key] for key in identity_keys):
                raise EngineeringError("Engineering contribution replay conflicts with retained state.")
            retained_local = _indexed_local_contribution(existing, index)
            try:
                retained = json.loads(retained_local.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise EngineeringError("Engineering project contribution is invalid.") from error
            if retained != existing:
                raise EngineeringError("Engineering project contribution conflicts with controller state.")
            return dict(existing)
        if local.exists():
            try:
                retained = json.loads(local.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise EngineeringError("Engineering project contribution is invalid.") from error
            if retained != candidate:
                raise EngineeringError("Engineering contribution replay conflicts with retained state.")
        if any(item["candidate_id"] == identifier for item in index["items"]):
            raise EngineeringError("Engineering contribution index conflicts with retained state.")
        controller = _promotion_controller_dir()
        key = _controller_key(controller, required=False)
        new_key = os.urandom(32) if key is None else None
        key = key or new_key
        assert key is not None
        index_entry = {
            "candidate_id": identifier,
            "project_digest": project_digest,
            "common_graph_dir": str(_common_graph_dir(project.root).absolute()),
            "local_record": str(local.absolute()),
        }
        index_entry["signature"] = _contribution_index_signature(key, index_entry)
        index["items"].append(index_entry)
        index["items"].sort(key=lambda item: item["candidate_id"])
        queue["items"].append(candidate)
        queue["items"].sort(key=lambda item: item["id"])
        _transactional_json_documents(
            [
                (_contribution_queue_path(), queue),
                (local, candidate),
                (_contribution_index_path(), index),
            ],
            [(_controller_key_path(controller), new_key.hex().encode("ascii") + b"\n")]
            if new_key
            else None,
        )
        return dict(candidate)
    finally:
        _release_directory_lock(lock, lock_owner)


def _candidate(queue: dict, candidate_id: str) -> dict:
    candidate = next((item for item in queue["items"] if item["id"] == candidate_id), None)
    if candidate is None:
        raise EngineeringError("Engineering contribution candidate is unknown.")
    return candidate


def evaluate_learning(candidate_id: str, root: Path, completion_id: str) -> dict:
    project = resolve_project(Path(root))
    _, source_digest = _terminal_completion(project.root, completion_id)
    project_digest = _project_contribution_digest(project.root)
    lock = _contribution_lock_path()
    lock_owner = _acquire_directory_lock(lock, "Engineering contribution update is already in progress.")
    try:
        queue = _load_contribution_queue()
        candidate = _candidate(queue, candidate_id)
        if project_digest == candidate["project_digest"]:
            raise EngineeringError("Engineering evaluation requires a distinct second project.")
        evaluation = {
            "id": "evaluation-" + hashlib.sha256(
                f"{candidate_id}\0{project_digest}\0{source_digest}".encode("utf-8")
            ).hexdigest()[:12],
            "project_digest": project_digest,
            "source_reference": f"completion:{completion_id}",
            "source_digest": source_digest,
            "result": "passed",
        }
        if candidate["state"] == "evaluating" and evaluation in candidate["evidence"]:
            return dict(evaluation)
        if candidate["state"] != "proposed":
            raise EngineeringError("Engineering contribution is not open for evaluation.")
        candidate["state"] = "evaluating"
        candidate["evidence"] = [evaluation]
        candidate["history"].append(_lifecycle_record(candidate_id, "evaluating"))
        if not _valid_contribution_item(candidate):
            raise EngineeringError("Engineering evaluation record is invalid.")
        _publish_contribution_transition(queue, candidate)
        return dict(evaluation)
    finally:
        _release_directory_lock(lock, lock_owner)


def record_learning_approval(candidate_id: str, approved: bool) -> dict:
    lock = _contribution_lock_path()
    lock_owner = _acquire_directory_lock(lock, "Engineering contribution update is already in progress.")
    try:
        queue = _load_contribution_queue()
        candidate = _candidate(queue, candidate_id)
        if approved is not True:
            raise EngineeringError("Engineering promotion requires explicit approval.")
        approval = {
            "id": "approval-"
            + hashlib.sha256(f"{candidate_id}\0approved".encode("utf-8")).hexdigest()[:12],
            "decision": "approved",
        }
        if candidate["state"] == "approved_for_promotion" and candidate["review"] == {"approval": approval}:
            return dict(approval)
        if candidate["state"] != "evaluating" or not candidate["evidence"]:
            raise EngineeringError("Engineering approval requires a validated evaluation record.")
        candidate["state"] = "approved_for_promotion"
        candidate["review"] = {"approval": approval}
        candidate["history"].append(_lifecycle_record(candidate_id, "approved_for_promotion"))
        if not _valid_contribution_item(candidate):
            raise EngineeringError("Engineering approval record is invalid.")
        _publish_contribution_transition(queue, candidate)
        return dict(approval)
    finally:
        _release_directory_lock(lock, lock_owner)


def _promotion_attestation_claims(candidate: dict) -> dict:
    return {
        "candidate_id": candidate["id"],
        "candidate_digest": _json_digest(candidate),
        "lifecycle_ids": [item["id"] for item in candidate["history"]],
        "evaluation_ids": sorted(item["id"] for item in candidate["evidence"]),
        "approval_id": candidate["review"]["approval"]["id"],
        "source_project_ids": sorted(
            [candidate["project_digest"]]
            + [item["project_digest"] for item in candidate["evidence"]]
        ),
    }


def _require_promotion_attestation(candidate: dict) -> dict:
    return _require_attestation(
        _promotion_controller_dir(),
        "promotion",
        _promotion_attestation_claims(candidate),
    )


def promote_and_apply(
    candidate_id: str,
    evaluation_ids: list[str],
    approved: bool,
) -> dict:
    if not re.fullmatch(r"candidate-[0-9a-f]{12}", candidate_id):
        raise EngineeringError("Engineering contribution identifier is invalid.")
    lock = _contribution_lock_path()
    lock_owner = _acquire_directory_lock(
        lock, "Engineering contribution update is already in progress."
    )
    try:
        queue = _load_contribution_queue()
        candidate = _candidate(queue, candidate_id)
        if "practice" not in candidate:
            raise EngineeringError("Engineering application requires a validated practice.")
        practice = _validate_practice(candidate["practice"])
        if candidate.get("practice_digest") != _practice_digest(practice):
            raise EngineeringError("Engineering application requires a validated practice.")
        if (
            not isinstance(evaluation_ids, list)
            or not evaluation_ids
            or any(
                not isinstance(identifier, str)
                or not re.fullmatch(r"evaluation-[0-9a-f]{12}", identifier)
                for identifier in evaluation_ids
            )
            or sorted(evaluation_ids)
            != sorted(item["id"] for item in candidate["evidence"])
        ):
            raise EngineeringError("Engineering application requires validated evaluation records.")
        if approved is not True:
            raise EngineeringError("Engineering promotion and application require explicit approval.")
        ledger = _load_applied_practices()
        retained_entries = [
            item for item in ledger["items"] if item["candidate_id"] == candidate_id
        ]
        if candidate.get("state") == "promoted_applied":
            _require_promotion_attestation(candidate)
            if len(retained_entries) != 1 or retained_entries[0]["state"] != "active":
                raise EngineeringError("Engineering applied-practice state is missing or mismatched.")
            return dict(candidate)
        if candidate.get("state") not in {"evaluating", "approved_for_promotion"} or retained_entries:
            raise EngineeringError("Engineering application requires validated evaluation state.")
        if candidate["state"] == "evaluating":
            approval = {
                "id": "approval-"
                + hashlib.sha256(f"{candidate_id}\0approved".encode("utf-8")).hexdigest()[:12],
                "decision": "approved",
            }
            candidate["review"] = {"approval": approval}
        elif "approval" not in candidate["review"]:
            raise EngineeringError("Engineering application requires a durable explicit approval record.")
        key = _controller_key(_promotion_controller_dir(), required=True)
        assert key is not None
        entry = {
            "candidate_id": candidate_id,
            "practice_digest": candidate["practice_digest"],
            "practice": practice,
            "state": "active",
            "skill_version": _skill_version(),
            "disabled_reason": None,
        }
        entry["signature"] = _applied_practice_signature(key, entry)
        ledger["items"].append(entry)
        ledger["items"].sort(key=lambda item: item["candidate_id"])
        _validate_applied_ledger(ledger, key)
        candidate["state"] = "promoted_applied"
        candidate["history"].append(_lifecycle_record(candidate_id, "promoted_applied"))
        if not _valid_contribution_item(candidate):
            raise EngineeringError("Engineering application lifecycle is invalid.")
        attestations, _, new_key = _append_attestation(
            _promotion_controller_dir(),
            "promotion",
            _promotion_attestation_claims(candidate),
        )
        if new_key is not None:
            raise EngineeringError("Engineering controller key changed during application.")
        _publish_contribution_transition(
            queue,
            candidate,
            attestation_registry=attestations,
            applied_ledger=ledger,
        )
        return dict(candidate)
    finally:
        _release_directory_lock(lock, lock_owner)


def disable_applied_practice(candidate_id: str, approved: bool) -> dict:
    if approved is not True:
        raise EngineeringError("Engineering practice disablement requires explicit approval.")
    lock = _contribution_lock_path()
    lock_owner = _acquire_directory_lock(
        lock, "Engineering contribution update is already in progress."
    )
    try:
        ledger = _load_applied_practices()
        matches = [item for item in ledger["items"] if item["candidate_id"] == candidate_id]
        if len(matches) != 1:
            raise EngineeringError("Engineering applied practice is unknown.")
        entry = matches[0]
        if entry["state"] == "disabled":
            return dict(entry)
        key = _controller_key(_promotion_controller_dir(), required=True)
        assert key is not None
        entry["state"] = "disabled"
        entry["disabled_reason"] = "owner_disabled"
        entry["signature"] = _applied_practice_signature(key, entry)
        _validate_applied_ledger(ledger, key)
        _transactional_json_documents([(_applied_practices_path(), ledger)])
        return dict(entry)
    finally:
        _release_directory_lock(lock, lock_owner)


def learning_status() -> dict:
    items = [
        _learning_candidate_projection(item)
        for item in _load_contribution_queue()["items"]
        if "practice" in item and item["state"] not in {"rejected"}
    ]
    return {
        "schema": "engineering.learning-status.v1",
        "items": sorted(items, key=lambda item: item["candidate_id"]),
    }


def inspect_learning(candidate_id: str) -> dict:
    candidate = _candidate(_load_contribution_queue(), candidate_id)
    projection = _learning_candidate_projection(candidate)
    practice = _validate_practice(candidate.get("practice"))
    return {
        **projection,
        "instruction": practice["instruction"],
        "verification": practice["verification"],
    }


def source_improvement_proposal(candidate_id: str) -> dict:
    candidate = _candidate(_load_contribution_queue(), candidate_id)
    if candidate.get("state") != "promoted_applied":
        raise EngineeringError("Engineering source improvement requires an applied practice.")
    practice = _validate_practice(candidate.get("practice"))
    if candidate.get("practice_digest") != _practice_digest(practice):
        raise EngineeringError("Engineering source improvement practice is invalid.")
    _require_promotion_attestation(candidate)
    evidence_digests = sorted(
        {
            candidate["source_digest"],
            *(item["source_digest"] for item in candidate["evidence"]),
        }
    )
    return {
        "schema": "engineering.source-improvement-proposal.v1",
        "candidate_id": candidate_id,
        "practice_digest": candidate["practice_digest"],
        "affected_contract": list(practice["applies_to"]),
        "evidence_digests": evidence_digests,
        "required_tests": [practice["verification"]],
        "authority": "proposal_only",
    }


def dismiss_learning(candidate_id: str, approved: bool) -> dict:
    if approved is not True:
        raise EngineeringError("Engineering learning dismissal requires explicit approval.")
    lock = _contribution_lock_path()
    lock_owner = _acquire_directory_lock(
        lock, "Engineering contribution update is already in progress."
    )
    try:
        queue = _load_contribution_queue()
        candidate = _candidate(queue, candidate_id)
        if "practice" not in candidate:
            raise EngineeringError("Engineering learning practice is unavailable.")
        if candidate["state"] == "rejected":
            return _learning_candidate_projection(candidate)
        if candidate["state"] != "proposed":
            raise EngineeringError("Engineering learning candidate cannot be dismissed in this state.")
        candidate["state"] = "rejected"
        candidate["review"] = {"rejection": {"decision": "rejected"}}
        candidate["history"].append(_lifecycle_record(candidate_id, "rejected"))
        if not _valid_contribution_item(candidate):
            raise EngineeringError("Engineering learning dismissal is invalid.")
        _publish_contribution_transition(queue, candidate)
        return _learning_candidate_projection(candidate)
    finally:
        _release_directory_lock(lock, lock_owner)


def promote_learning(candidate_id: str, evidence: list[dict], approved: bool) -> dict:
    queue = _load_contribution_queue()
    existing = _candidate(queue, candidate_id)
    if "practice" in existing:
        if not isinstance(evidence, list) or any(
            not isinstance(item, dict) or set(item) != {"evaluation_id"}
            for item in evidence
        ):
            raise EngineeringError("Engineering application requires validated evaluation records.")
        return promote_and_apply(
            candidate_id,
            [item["evaluation_id"] for item in evidence],
            approved,
        )
    if not re.fullmatch(r"candidate-[0-9a-f]{12}", candidate_id):
        raise EngineeringError("Engineering contribution identifier is invalid.")
    lock = _contribution_lock_path()
    lock_owner = _acquire_directory_lock(lock, "Engineering contribution update is already in progress.")
    try:
        queue = _load_contribution_queue()
        candidate = _candidate(queue, candidate_id)
        if not isinstance(evidence, list) or any(
            not isinstance(item, dict) or set(item) != {"evaluation_id"}
            for item in evidence
        ):
            raise EngineeringError("Engineering promotion requires validated evaluation records.")
        requested = sorted(item["evaluation_id"] for item in evidence)
        retained = sorted(item["id"] for item in candidate["evidence"])
        if not requested or requested != retained:
            raise EngineeringError("Engineering promotion requires validated evaluation records.")
        if approved is not True:
            raise EngineeringError("Engineering promotion requires explicit approval.")
        if candidate.get("state") == "promoted":
            _require_promotion_attestation(candidate)
            local = _indexed_local_contribution(candidate)
            try:
                retained = json.loads(local.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise EngineeringError("Engineering project contribution is invalid.") from error
            if retained != candidate:
                raise EngineeringError("Engineering project contribution conflicts with controller state.")
            return dict(candidate)
        if candidate.get("state") != "approved_for_promotion" or "approval" not in candidate["review"]:
            raise EngineeringError("Engineering promotion requires a durable explicit approval record.")
        candidate["state"] = "promoted"
        candidate["history"].append(_lifecycle_record(candidate_id, "promoted"))
        if not _valid_contribution_item(candidate):
            raise EngineeringError("Engineering promotion lifecycle is invalid.")
        attestations, _, new_key = _append_attestation(
            _promotion_controller_dir(),
            "promotion",
            _promotion_attestation_claims(candidate),
        )
        _publish_contribution_transition(
            queue,
            candidate,
            attestation_registry=attestations,
            attestation_key=new_key,
        )
        return dict(candidate)
    finally:
        _release_directory_lock(lock, lock_owner)


def discover_shared_skills() -> list[str]:
    promoted = [
        item for item in _load_contribution_queue()["items"] if item["state"] == "promoted"
    ]
    for item in promoted:
        _require_promotion_attestation(item)
        local = _indexed_local_contribution(item)
        try:
            retained = json.loads(local.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise EngineeringError("Engineering project contribution is invalid.") from error
        if retained != item:
            raise EngineeringError("Engineering project contribution conflicts with controller state.")
    return sorted(item["id"] for item in promoted)


def _reject_reparse_ancestors(path: Path, boundary: Path | None = None) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise EngineeringError("Engineering install boundary is invalid.")
    stop = boundary.parent if boundary is not None else None
    current = path
    while True:
        if current.exists() and _is_reparse_point(current):
            raise EngineeringError("Engineering install boundary contains a reparse point.")
        if current == stop or current.parent == current:
            break
        current = current.parent
    if boundary is not None:
        try:
            path.resolve().relative_to(boundary.resolve())
        except ValueError as error:
            raise EngineeringError("Engineering install target escapes its caller boundary.") from error


def _bundle_files(source: Path) -> tuple[list[Path], dict, str, str]:
    source = _expand_install_path(source)
    _reject_reparse_ancestors(source)
    source = source.resolve()
    if not source.is_dir() or _is_reparse_point(source):
        raise EngineeringError("Engineering bundle source is missing or is a link/reparse point.")
    for path in source.rglob("*"):
        if _is_reparse_point(path):
            raise EngineeringError("Engineering bundle contains a link/reparse point.")
    required = {
        PurePosixPath("SKILL.md"),
        PurePosixPath("manifest.json"),
        PurePosixPath("scripts/engineering.py"),
        PurePosixPath("references/controller-contract.md"),
    }
    try:
        repository = _expand_install_path(git(source, "rev-parse", "--show-toplevel")).resolve()
        commit = git(source, "rev-parse", "HEAD")
        relative_source = source.relative_to(repository).as_posix()
        tracked = git(repository, "ls-files", "--", relative_source).splitlines()
    except (EngineeringError, ValueError) as error:
        raise EngineeringError("Engineering bundle requires an exact Git source commit.") from error
    if git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        relative_source,
    ):
        raise EngineeringError("Engineering bundle requires an exact Git source commit.")
    files: list[Path] = []
    prefix = relative_source.rstrip("/") + "/"
    for tracked_path in tracked:
        if not tracked_path.startswith(prefix):
            continue
        relative = PurePosixPath(tracked_path.removeprefix(prefix))
        candidate = source / relative
        if not candidate.is_file() or _is_reparse_point(candidate):
            raise EngineeringError("Engineering bundle source closure is invalid.")
        files.append(relative)
    if not required <= set(files) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise EngineeringError("Engineering bundle source closure is invalid.")
    blobs = {
        relative: _git_blob_bytes(
            repository,
            commit,
            f"{relative_source.rstrip('/')}/{relative.as_posix()}",
        )
        for relative in files
    }
    try:
        manifest = json.loads(blobs[PurePosixPath("manifest.json")].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering bundle manifest is invalid.") from error
    graphify = manifest.get("graphify") if isinstance(manifest, dict) else None
    if not (
        manifest.get("name") == "engineering"
        and isinstance(manifest.get("version"), str)
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest["version"])
        and isinstance(graphify, dict)
        and graphify.get("commit") == GRAPHIFY_COMMIT
    ):
        raise EngineeringError("Engineering bundle manifest is invalid.")
    try:
        skill = blobs[PurePosixPath("SKILL.md")].decode("utf-8")
    except UnicodeDecodeError as error:
        raise EngineeringError("Engineering canonical skill metadata is invalid.") from error
    if "name: engineering" not in skill:
        raise EngineeringError("Engineering canonical skill metadata is invalid.")
    digest = hashlib.sha256()
    for relative in sorted(files, key=lambda value: value.as_posix()):
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        digest.update(blobs[relative] + b"\0")
    tree = git(repository, "rev-parse", f"{commit}^{{tree}}")
    if not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise EngineeringError("Engineering bundle Git tree is invalid.")
    return BundleSnapshot(
        files,
        manifest,
        commit,
        "sha256:" + digest.hexdigest(),
        tree,
        blobs,
    )


def _git_blob_bytes(repository: Path, commit: str, relative: str) -> bytes:
    if (
        not re.fullmatch(r"[0-9a-f]{40}", commit)
        or not relative
        or Path(relative).is_absolute()
        or ".." in PurePosixPath(relative).parts
    ):
        raise EngineeringError("Engineering Git object identity is invalid.")
    result = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "blob", f"{commit}:{relative}"],
        capture_output=True,
        env=_controller_git_environment(),
    )
    if result.returncode:
        raise EngineeringError("Engineering bundle Git object is unavailable.")
    return result.stdout


def _bundle_git_tree(source: Path, commit: str) -> str:
    repository = _expand_install_path(git(source, "rev-parse", "--show-toplevel")).resolve()
    tree = git(repository, "rev-parse", f"{commit}^{{tree}}")
    if not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise EngineeringError("Engineering bundle Git tree is invalid.")
    return tree


def _copy_bundle(
    source: Path,
    target: Path,
    files: list[Path],
    commit: str,
    blobs: dict[Path, bytes] | None = None,
) -> None:
    repository = None
    relative_source = None
    if blobs is None:
        repository = _expand_install_path(git(source, "rev-parse", "--show-toplevel")).resolve()
        relative_source = source.resolve().relative_to(repository).as_posix().rstrip("/")
    target.mkdir(parents=True)
    for relative in files:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = (
            blobs[relative]
            if blobs is not None
            else _git_blob_bytes(
                repository,
                commit,
                f"{relative_source}/{relative.as_posix()}",
            )
        )
        destination.write_bytes(content)


def _forwarder(name: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        "description: Use when Engineering is required through this compatibility surface.\n"
        "---\n\n"
        f"# {name}\n\n"
        "Read and follow the canonical `~/.agents/skills/engineering/SKILL.md`.\n"
        "This loader contains no project instructions or separate workflow.\n"
    )


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for candidate in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if _is_reparse_point(candidate):
            raise EngineeringError("Engineering installed bundle contains a link/reparse point.")
        relative_path = candidate.relative_to(path)
        if relative_path.parts[:2] == ("scripts", "__pycache__"):
            if candidate.is_dir():
                continue
            if (
                len(relative_path.parts) == 3
                and candidate.is_file()
                and re.fullmatch(
                    r"(?:engineering|engineering_host_boundary)"
                    r"(?:\.[A-Za-z0-9_-]+)?\.pyc",
                    relative_path.name,
                )
            ):
                continue
            raise EngineeringError("Engineering installed bundle has unexpected bytecode.")
        if candidate.is_file():
            relative = relative_path.as_posix()
            digest.update(relative.encode("utf-8") + b"\0")
            digest.update(candidate.read_bytes() + b"\0")
    return "sha256:" + digest.hexdigest()


def _remove_install_path(path: Path, expected_state: dict) -> None:
    """Remove only the exact lexical install object the caller observed.

    Cleanup is a destructive publication effect, not best-effort hygiene.  It
    therefore uses the same exact/absent preimage contract as replacement and
    rechecks lexical ancestors immediately before deletion.
    """
    _reject_reparse_ancestors(path)
    _verify_install_path_state(path, expected_state)
    if not expected_state.get("exists"):
        return
    _reject_reparse_ancestors(path)
    _verify_install_path_state(path, expected_state)
    if path.is_symlink() or _is_reparse_point(path):
        raise EngineeringError("Engineering install path is a link/reparse point.")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _install_paths(home: Path) -> dict[str, Path]:
    return {
        "canonical": home / ".agents" / "skills" / "engineering",
        "previous": home / ".agents" / "skills" / ".engineering.previous",
        "claude": home / ".claude" / "skills" / "engineering",
        "shim": home / ".agents" / "skills" / "engineering-traceability",
        "command": home / ".agents" / "bin",
        "receipt": home / ".agents" / "engineering" / "install-receipt.json",
        "previous_receipt": home / ".agents" / "engineering" / "previous-install-receipt.json",
        "lock": home / ".agents" / "engineering" / "install.lock",
    }


def _command_launcher_contents() -> tuple[str, str]:
    return (
        '#!/bin/sh\nexec "$(dirname "$0")/../skills/engineering/scripts/engineering" "$@"\n',
        "@echo off\n\"%~dp0..\\skills\\engineering\\scripts\\engineering.cmd\" %*\n",
    )


def _write_command_launchers(path: Path) -> None:
    portable, windows = _command_launcher_contents()
    path.mkdir(parents=True)
    (path / "engineering").write_text(portable, encoding="utf-8", newline="\n")
    (path / "engineering.cmd").write_text(windows, encoding="utf-8", newline="")


def _valid_command_launchers(path: Path) -> bool:
    portable, windows = _command_launcher_contents()
    return (
        path.is_dir()
        and not _is_reparse_point(path)
        and (path / "engineering").is_file()
        and (path / "engineering.cmd").is_file()
        and not _is_reparse_point(path / "engineering")
        and not _is_reparse_point(path / "engineering.cmd")
        and (path / "engineering").read_text(encoding="utf-8") == portable
        and (path / "engineering.cmd").read_text(encoding="utf-8") == windows
    )


def _register_windows_command_directory(install_home: Path, directory: Path) -> None:
    """Add Engineering's single managed command directory to the user PATH."""
    normalize = lambda path: os.path.normcase(os.path.normpath(str(path)))
    if normalize(install_home) != normalize(Path.home().resolve()):
        return
    import winreg

    normalized = os.path.normcase(os.path.normpath(str(directory)))
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        "Environment",
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        try:
            value, value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            value, value_type = "", winreg.REG_EXPAND_SZ
        entries = [entry for entry in str(value).split(";") if entry]
        if not any(os.path.normcase(os.path.normpath(entry)) == normalized for entry in entries):
            entries.append(str(directory))
            winreg.SetValueEx(
                key,
                "Path",
                0,
                value_type if value_type in {winreg.REG_SZ, winreg.REG_EXPAND_SZ} else winreg.REG_EXPAND_SZ,
                ";".join(entries),
            )
    current = os.environ.get("PATH", "")
    if not any(os.path.normcase(os.path.normpath(entry)) == normalized for entry in current.split(";")):
        os.environ["PATH"] = ";".join([entry for entry in (current, str(directory)) if entry])


def _install_key(home: Path) -> bytes:
    controller = home / ".agents" / "engineering" / "controller"
    key = _controller_key(controller, required=False)
    if key is None:
        _private_atomic_bytes(_controller_key_path(controller), os.urandom(32).hex().encode("ascii") + b"\n")
        key = _controller_key(controller, required=True)
    assert key is not None
    return key


def _sign_install_receipt(receipt: dict, key: bytes) -> dict:
    payload = {name: value for name, value in receipt.items() if name != "signature"}
    return {
        **payload,
        "signature": "hmac-sha256:"
        + hmac.new(key, _canonical_json(payload), hashlib.sha256).hexdigest(),
    }


def _legacy_v226_bootstrap_authorization(value: object, source_bundle: object) -> dict:
    """Read the superseded v1 bootstrap envelope for historical receipts only.

    This deliberately verifies only the exact source/artifact envelope.  The
    installed v2.2.5 controller, recorded owner approval, and independent
    audits are evaluated by the native delivery boundary before it supplies
    this receipt.  A candidate cannot mint that external decision here.
    """
    expected = {
        "schema",
        "artifact_digest",
        "source_bundle",
        "installed_v225_receipt_digest",
        "owner_approval_reference",
        "independent_audits",
        "identity",
    }
    source_expected = {"source_git_commit", "source_digest", "skill_version"}
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != LEGACY_V226_BOOTSTRAP_AUTHORIZATION_SCHEMA
        or not isinstance(source_bundle, dict)
        or set(source_bundle) != source_expected
        or value.get("source_bundle") != source_bundle
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("artifact_digest", "")))
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", str(value.get("installed_v225_receipt_digest", ""))
        )
        or value.get("identity") != {"state": "unknown"}
    ):
        raise EngineeringError("Engineering v2.2.6 bootstrap authorization is invalid.")
    if (
        not re.fullmatch(
            r"[0-9a-f]{40}", str(source_bundle.get("source_git_commit", ""))
        )
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", str(source_bundle.get("source_digest", ""))
        )
        or source_bundle.get("skill_version") != "2.2.6"
    ):
        raise EngineeringError("Engineering v2.2.6 bootstrap source bundle is invalid.")
    try:
        owner_approval_reference = _assurance_id(
            value.get("owner_approval_reference"), "v2.2.6 bootstrap owner approval"
        )
    except EngineeringError as error:
        raise EngineeringError("Engineering v2.2.6 bootstrap authorization is invalid.") from error
    audits = value.get("independent_audits")
    if not isinstance(audits, list) or not 2 <= len(audits) <= 16:
        raise EngineeringError("Engineering v2.2.6 bootstrap independent audits are invalid.")
    normalized_audits = []
    audit_ids: set[str] = set()
    for audit in audits:
        if (
            not isinstance(audit, dict)
            or set(audit) != {"audit_id", "artifact_digest"}
            or audit.get("artifact_digest") != value["artifact_digest"]
        ):
            raise EngineeringError("Engineering v2.2.6 bootstrap independent audits are invalid.")
        try:
            audit_id = _assurance_id(audit.get("audit_id"), "v2.2.6 bootstrap audit")
        except EngineeringError as error:
            raise EngineeringError("Engineering v2.2.6 bootstrap independent audits are invalid.") from error
        if audit_id in audit_ids:
            raise EngineeringError("Engineering v2.2.6 bootstrap independent audits are duplicated.")
        audit_ids.add(audit_id)
        normalized_audits.append(
            {"audit_id": audit_id, "artifact_digest": value["artifact_digest"]}
        )
    return {
        "schema": LEGACY_V226_BOOTSTRAP_AUTHORIZATION_SCHEMA,
        "artifact_digest": value["artifact_digest"],
        "source_bundle": dict(source_bundle),
        "installed_v225_receipt_digest": value["installed_v225_receipt_digest"],
        "owner_approval_reference": owner_approval_reference,
        "independent_audits": sorted(normalized_audits, key=lambda item: item["audit_id"]),
        "identity": {"state": "unknown"},
    }


def _v226_bootstrap_source_bundle(value: object) -> dict:
    expected = {
        "source_git_commit",
        "source_git_tree",
        "source_digest",
        "skill_version",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or not re.fullmatch(r"[0-9a-f]{40}", str(value.get("source_git_commit", "")))
        or not re.fullmatch(r"[0-9a-f]{40}", str(value.get("source_git_tree", "")))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("source_digest", "")))
        or value.get("skill_version") != "2.2.6"
    ):
        raise EngineeringError("Engineering v2.2.6 bootstrap source bundle is invalid.")
    return {
        "source_git_commit": value["source_git_commit"],
        "source_git_tree": value["source_git_tree"],
        "source_digest": value["source_digest"],
        "skill_version": "2.2.6",
    }


def _v226_bootstrap_authorization(value: object, source_bundle: object) -> dict:
    """Validate the caller's reference to a root-owned, post-audit record."""
    expected = {"schema", "record_id", "record_digest", "source_bundle"}
    source = _v226_bootstrap_source_bundle(source_bundle)
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != V226_BOOTSTRAP_AUTHORIZATION_SCHEMA
        or value.get("source_bundle") != source
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("record_digest", "")))
    ):
        raise EngineeringError("Engineering v2.2.6 bootstrap authorization is invalid.")
    try:
        record_id = _assurance_id(value.get("record_id"), "v2.2.6 bootstrap record")
    except EngineeringError as error:
        raise EngineeringError("Engineering v2.2.6 bootstrap authorization is invalid.") from error
    return {
        "schema": V226_BOOTSTRAP_AUTHORIZATION_SCHEMA,
        "record_id": record_id,
        "record_digest": value["record_digest"],
        "source_bundle": source,
    }


def _v226_bootstrap_candidate_artifact_digest(candidate: dict) -> str:
    return _json_digest(
        {
            name: candidate[name]
            for name in (
                "role",
                "repository_id",
                "source_git_commit",
                "source_git_tree",
                "source_digest",
                "skill_version",
                "base_commit",
            )
        }
    )


def _v226_bootstrap_candidate(value: object) -> dict:
    expected = {
        "role",
        "repository_id",
        "source_git_commit",
        "source_git_tree",
        "source_digest",
        "skill_version",
        "base_commit",
        "artifact_digest",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("role") not in {"internal", "public"}
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("repository_id", "")))
        or not re.fullmatch(r"[0-9a-f]{40}", str(value.get("source_git_commit", "")))
        or not re.fullmatch(r"[0-9a-f]{40}", str(value.get("source_git_tree", "")))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("source_digest", "")))
        or value.get("skill_version") != "2.2.6"
        or not re.fullmatch(r"[0-9a-f]{40}", str(value.get("base_commit", "")))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("artifact_digest", "")))
    ):
        raise EngineeringError("Engineering v2.2.6 bootstrap candidate is invalid.")
    normalized = {
        "role": value["role"],
        "repository_id": value["repository_id"],
        "source_git_commit": value["source_git_commit"],
        "source_git_tree": value["source_git_tree"],
        "source_digest": value["source_digest"],
        "skill_version": "2.2.6",
        "base_commit": value["base_commit"],
        "artifact_digest": value["artifact_digest"],
    }
    if normalized["artifact_digest"] != _v226_bootstrap_candidate_artifact_digest(normalized):
        raise EngineeringError("Engineering v2.2.6 bootstrap candidate artifact is mismatched.")
    return normalized


def _v226_bootstrap_pair(value: object) -> tuple[list[dict], str, str]:
    if not isinstance(value, list) or len(value) != 2:
        raise EngineeringError("Engineering v2.2.6 bootstrap candidate pair is invalid.")
    candidates = sorted(
        (_v226_bootstrap_candidate(item) for item in value), key=lambda item: item["role"]
    )
    if [item["role"] for item in candidates] != ["internal", "public"]:
        raise EngineeringError("Engineering v2.2.6 bootstrap candidate pair is invalid.")
    pair_digest = _json_digest(candidates)
    ancestry_digest = _json_digest(
        [
            {
                "role": item["role"],
                "base_commit": item["base_commit"],
                "source_git_commit": item["source_git_commit"],
            }
            for item in candidates
        ]
    )
    return candidates, pair_digest, ancestry_digest


def _v226_bootstrap_authority_dir(home: Path) -> Path:
    directory = home / ".agents" / "engineering" / "bootstrap-authority"
    _reject_reparse_ancestors(directory)
    return directory


def _v226_bootstrap_trust_anchor(value: object) -> dict:
    expected = {"schema", "anchor_id", "format_version", "signers_digest", "identity"}
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != V226_BOOTSTRAP_TRUST_ANCHOR_SCHEMA
        or value.get("format_version") != 1
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("signers_digest", "")))
        or value.get("identity") != {"state": "unknown"}
    ):
        raise EngineeringError("Engineering v2.2.6 bootstrap trust anchor is invalid.")
    try:
        anchor_id = _assurance_id(value.get("anchor_id"), "v2.2.6 bootstrap trust anchor")
    except EngineeringError as error:
        raise EngineeringError("Engineering v2.2.6 bootstrap trust anchor is invalid.") from error
    return {
        "schema": V226_BOOTSTRAP_TRUST_ANCHOR_SCHEMA,
        "anchor_id": anchor_id,
        "format_version": 1,
        "signers_digest": value["signers_digest"],
        "identity": {"state": "unknown"},
    }


def _v226_bootstrap_host_trust_anchor(source: Path, home: Path) -> tuple[dict, bytes]:
    """Read the one-time host-owned delivery anchor, never the installed gate."""
    directory = _v226_bootstrap_authority_dir(home)
    anchor_path = directory / "bootstrap-trust-anchor.json"
    signers_path = directory / "allowed-signers"
    try:
        source_root = resolve_project_root(str(source)).resolve()
        if directory.resolve().is_relative_to(source_root):
            raise EngineeringError("Engineering host bootstrap authority is inside candidate Git.")
        _reject_reparse_ancestors(directory)
        _reject_reparse_ancestors(anchor_path, directory)
        _reject_reparse_ancestors(signers_path, directory)
        _verify_owner_private(directory, directory=True)
        _verify_owner_private(anchor_path, directory=False)
        _verify_owner_private(signers_path, directory=False)
        anchor = _v226_bootstrap_trust_anchor(
            json.loads(anchor_path.read_text(encoding="utf-8"))
        )
        allowed = signers_path.read_bytes()
    except (OSError, ValueError, json.JSONDecodeError, EngineeringError) as error:
        raise EngineeringError("Engineering host bootstrap trust is unavailable.") from error
    if (
        not allowed
        or len(allowed) > 65536
        or b"\x00" in allowed
        or anchor["signers_digest"] != "sha256:" + hashlib.sha256(allowed).hexdigest()
    ):
        raise EngineeringError("Engineering host bootstrap trust is invalid.")
    return anchor, allowed


def _v226_bootstrap_host_receipt(
    source: Path,
    value: object,
    *,
    anchor: dict,
    authority_epoch: str,
    contract: str,
) -> dict:
    expected = {
        "schema",
        "receipt_id",
        "repository_id",
        "authority_epoch",
        "contract",
        "identity",
        "trust_anchor",
    }
    try:
        source_root = resolve_project_root(str(source))
        repository_id = _project_contribution_digest(source_root)
    except (OSError, EngineeringError) as error:
        raise EngineeringError("Engineering bootstrap source repository is unavailable.") from error
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != V226_BOOTSTRAP_HOST_RECEIPT_SCHEMA
        or value.get("repository_id") != repository_id
        or value.get("authority_epoch") != authority_epoch
        or value.get("contract") != contract
        or value.get("identity") != {"state": "unknown"}
        or value.get("trust_anchor") != anchor
    ):
        raise EngineeringError("Engineering bootstrap host receipt is mismatched.")
    try:
        receipt_id = _assurance_id(value.get("receipt_id"), "v2.2.6 bootstrap host receipt")
    except EngineeringError as error:
        raise EngineeringError("Engineering bootstrap host receipt is invalid.") from error
    return {
        "schema": V226_BOOTSTRAP_HOST_RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "repository_id": repository_id,
        "authority_epoch": authority_epoch,
        "contract": contract,
        "identity": {"state": "unknown"},
        "trust_anchor": anchor,
    }


def _v226_bootstrap_signer_fingerprint(allowed: bytes, principal: str) -> str:
    """Require simple, exact service-principal signer entries for distinct audits."""
    try:
        lines = allowed.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise EngineeringError("Engineering host bootstrap trust is invalid.") from error
    matches = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 3 or parts[0] != principal:
            continue
        if not re.fullmatch(r"ssh-[A-Za-z0-9@._+-]+", parts[1]) or not re.fullmatch(
            r"[A-Za-z0-9+/=]+", parts[2]
        ):
            raise EngineeringError("Engineering host bootstrap trust is invalid.")
        matches.append(parts[1] + " " + parts[2])
    if len(matches) != 1:
        raise EngineeringError("Engineering host bootstrap signer is unavailable or ambiguous.")
    return "sha256:" + hashlib.sha256(matches[0].encode("ascii")).hexdigest()


def _v226_bootstrap_timestamp(value: object, label: str) -> str:
    try:
        issued = _assurance_timestamp(value)
    except EngineeringError as error:
        raise EngineeringError(f"Engineering v2.2.6 bootstrap {label} timestamp is invalid.") from error
    now = datetime.now(timezone.utc)
    if issued > now + timedelta(minutes=5) or now - issued > V226_BOOTSTRAP_MAX_EVIDENCE_AGE:
        raise EngineeringError(f"Engineering v2.2.6 bootstrap {label} evidence is stale.")
    return value


def _v226_verify_bootstrap_signature(
    source: Path,
    home: Path,
    approval: object,
    *,
    approval_schema: str,
    claims_schema: str,
    claims: dict,
    namespace: str,
    contract: str,
    authority_epoch: str,
    label: str,
) -> tuple[str, str, str]:
    """Verify pre-activation root/audit evidence against a separate host anchor."""
    anchor, allowed = _v226_bootstrap_host_trust_anchor(source, home)
    expected = {"schema", "approver", "claims", "host_receipt", "signature"}
    if (
        not isinstance(approval, dict)
        or set(approval) != expected
        or approval.get("schema") != approval_schema
        or approval.get("claims") != claims
        or not isinstance(approval.get("signature"), str)
        or not approval["signature"].startswith("-----BEGIN SSH SIGNATURE-----\n")
        or len(approval["signature"]) > 16384
    ):
        raise EngineeringError(f"Engineering v2.2.6 bootstrap {label} is invalid.")
    try:
        approver = _assurance_id(approval.get("approver"), f"v2.2.6 bootstrap {label} approver")
    except EngineeringError as error:
        raise EngineeringError(f"Engineering v2.2.6 bootstrap {label} is invalid.") from error
    receipt = _v226_bootstrap_host_receipt(
        source,
        approval.get("host_receipt"),
        anchor=anchor,
        authority_epoch=authority_epoch,
        contract=contract,
    )
    fingerprint = _v226_bootstrap_signer_fingerprint(allowed, approver)
    material = _canonical_json(
        {"schema": claims_schema, "claims": claims, "host_receipt": receipt}
    )
    with tempfile.TemporaryDirectory(prefix="engineering-v226-bootstrap-") as temporary:
        allowed_path = Path(temporary) / "allowed_signers"
        signature_path = Path(temporary) / "approval.sig"
        allowed_path.write_bytes(allowed)
        signature_path.write_text(approval["signature"], encoding="ascii")
        try:
            verified = subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_path),
                    "-I",
                    approver,
                    "-n",
                    namespace,
                    "-s",
                    str(signature_path),
                ],
                input=material,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EngineeringError(
                f"Engineering v2.2.6 bootstrap {label} verification is unavailable."
            ) from error
    if verified.returncode != 0:
        raise EngineeringError(f"Engineering v2.2.6 bootstrap {label} signature is invalid.")
    reference = "bootstrap-" + hashlib.sha256(
        _canonical_json({"approval": approval, "host_receipt": receipt})
    ).hexdigest()[:32]
    return reference, approver, fingerprint


def _v226_bootstrap_source_candidate(source: Path, role: str, base_commit: str) -> dict:
    files, manifest, commit, source_digest = _bundle_files(source)
    del files
    try:
        repository = _expand_install_path(git(source, "rev-parse", "--show-toplevel")).resolve()
        tree = git(repository, "rev-parse", "HEAD^{tree}")
        repository_id = _project_contribution_digest(repository)
    except (OSError, EngineeringError) as error:
        raise EngineeringError("Engineering v2.2.6 bootstrap source identity is unavailable.") from error
    if not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise EngineeringError("Engineering v2.2.6 bootstrap source identity is invalid.")
    candidate = {
        "role": role,
        "repository_id": repository_id,
        "source_git_commit": commit,
        "source_git_tree": tree,
        "source_digest": source_digest,
        "skill_version": manifest["version"],
        "base_commit": base_commit,
    }
    candidate["artifact_digest"] = _v226_bootstrap_candidate_artifact_digest(candidate)
    return candidate


def _v226_bootstrap_public_source(source: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise EngineeringError("Engineering v2.2.6 bootstrap public source is invalid.")
    public_source = _expand_install_path(value)
    if not public_source.is_absolute() or str(public_source).startswith("\\\\"):
        raise EngineeringError("Engineering v2.2.6 bootstrap public source is invalid.")
    try:
        _reject_reparse_ancestors(public_source)
        source_root = resolve_project_root(str(source)).resolve()
        public_root = resolve_project_root(str(public_source)).resolve()
        if public_root == source_root or public_root.is_relative_to(source_root):
            raise EngineeringError("Engineering v2.2.6 bootstrap public source is not independent.")
    except (OSError, ValueError, EngineeringError) as error:
        raise EngineeringError("Engineering v2.2.6 bootstrap public source is unavailable.") from error
    return public_source


def _v226_installed_v225(home: Path) -> dict:
    """Resolve the actual installed v2.2.5 receipt before a first v2.2.6 copy."""
    paths = _install_paths(home)
    controller = home / ".agents" / "engineering" / "controller"
    try:
        _reject_reparse_ancestors(controller)
        _reject_reparse_ancestors(paths["receipt"])
        _verify_owner_private(controller, directory=True)
        key = _controller_key(controller, required=True)
        if key is None:
            raise EngineeringError("Engineering v2.2.5 controller key is unavailable.")
        candidates = (
            (paths["receipt"], paths["canonical"]),
            (paths["previous_receipt"], paths["previous"]),
        )
        receipt = None
        for receipt_path, bundle_path in candidates:
            if not receipt_path.is_file():
                continue
            _reject_reparse_ancestors(receipt_path)
            _verify_owner_private(receipt_path, directory=False)
            candidate = _load_install_receipt(receipt_path, key)
            if candidate is None:
                continue
            if (
                candidate.get("schema")
                in {"engineering.install.v1", "engineering.install.v5"}
                and candidate.get("status") == "installed"
                and candidate.get("skill_version") == "2.2.5"
            ):
                _validated_installed_bundle(bundle_path, candidate)
                receipt = candidate
                break
        if receipt is None:
            raise EngineeringError("Engineering v2.2.5 installed receipt is unavailable.")
    except (OSError, EngineeringError) as error:
        raise EngineeringError("Engineering v2.2.5 installed receipt is unavailable.") from error
    return {
        "receipt_digest": _json_digest(receipt),
        "skill_version": receipt["skill_version"],
        "source_git_commit": receipt["source_git_commit"],
        "source_digest": receipt["source_digest"],
    }


def _v226_bootstrap_owner_claims(
    value: object,
    *,
    repository_id: str,
    authority_epoch: str,
    pair_digest: str,
    installed_v225_digest: str,
) -> dict:
    expected = {
        "approval_id",
        "repository_id",
        "authority_epoch",
        "candidate_pair_digest",
        "installed_v225_receipt_digest",
        "decision",
        "issued_at",
        "replay_nonce",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("repository_id") != repository_id
        or value.get("authority_epoch") != authority_epoch
        or value.get("candidate_pair_digest") != pair_digest
        or value.get("installed_v225_receipt_digest") != installed_v225_digest
        or value.get("decision") != "owner_approved"
    ):
        raise EngineeringError("Engineering v2.2.6 bootstrap owner approval is mismatched.")
    try:
        approval_id = _assurance_id(value.get("approval_id"), "v2.2.6 bootstrap owner approval")
        replay_nonce = _assurance_id(value.get("replay_nonce"), "v2.2.6 bootstrap owner replay")
        issued_at = _v226_bootstrap_timestamp(value.get("issued_at"), "owner approval")
    except EngineeringError as error:
        raise EngineeringError("Engineering v2.2.6 bootstrap owner approval is invalid.") from error
    return {
        "approval_id": approval_id,
        "repository_id": repository_id,
        "authority_epoch": authority_epoch,
        "candidate_pair_digest": pair_digest,
        "installed_v225_receipt_digest": installed_v225_digest,
        "decision": "owner_approved",
        "issued_at": issued_at,
        "replay_nonce": replay_nonce,
    }


def _v226_bootstrap_audit_claims(
    value: object,
    *,
    repository_id: str,
    authority_epoch: str,
    pair_digest: str,
    ancestry_digest: str,
) -> dict:
    expected = {
        "audit_id",
        "auditor_role",
        "repository_id",
        "authority_epoch",
        "candidate_pair_digest",
        "candidate_ancestry_digest",
        "decision",
        "issued_at",
        "replay_nonce",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("repository_id") != repository_id
        or value.get("authority_epoch") != authority_epoch
        or value.get("candidate_pair_digest") != pair_digest
        or value.get("candidate_ancestry_digest") != ancestry_digest
        or value.get("decision") != "accepted"
    ):
        raise EngineeringError("Engineering v2.2.6 bootstrap audit is mismatched.")
    try:
        audit_id = _assurance_id(value.get("audit_id"), "v2.2.6 bootstrap audit")
        auditor_role = _assurance_id(value.get("auditor_role"), "v2.2.6 bootstrap auditor role")
        replay_nonce = _assurance_id(value.get("replay_nonce"), "v2.2.6 bootstrap audit replay")
        issued_at = _v226_bootstrap_timestamp(value.get("issued_at"), "audit")
    except EngineeringError as error:
        raise EngineeringError("Engineering v2.2.6 bootstrap audit is invalid.") from error
    if auditor_role not in V226_BOOTSTRAP_AUDIT_CATEGORIES:
        raise EngineeringError(
            "Engineering v2.2.6 bootstrap audit category must be semantic or technical."
        )
    return {
        "audit_id": audit_id,
        "auditor_role": auditor_role,
        "repository_id": repository_id,
        "authority_epoch": authority_epoch,
        "candidate_pair_digest": pair_digest,
        "candidate_ancestry_digest": ancestry_digest,
        "decision": "accepted",
        "issued_at": issued_at,
        "replay_nonce": replay_nonce,
    }


def _v226_bootstrap_host_record(
    source: Path, home: Path, value: object, source_bundle: dict
) -> dict:
    """Resolve the root-owned post-audit evidence record for the first delivery."""
    expected = {
        "schema",
        "record_id",
        "repository_id",
        "authority_epoch",
        "candidate_pair",
        "candidate_pair_digest",
        "installed_v225",
        "owner_approval",
        "independent_audits",
        "issued_at",
        "replay_nonce",
        "public_source",
        "identity",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != V226_BOOTSTRAP_HOST_RECORD_SCHEMA
        or value.get("identity") != {"state": "unknown"}
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("repository_id", "")))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("candidate_pair_digest", "")))
    ):
        raise EngineeringError("Engineering host bootstrap record is invalid.")
    try:
        record_id = _assurance_id(value.get("record_id"), "v2.2.6 bootstrap record")
        authority_epoch = _assurance_id(value.get("authority_epoch"), "v2.2.6 bootstrap epoch")
        record_nonce = _assurance_id(value.get("replay_nonce"), "v2.2.6 bootstrap record replay")
        issued_at = _v226_bootstrap_timestamp(value.get("issued_at"), "record")
        source_root = resolve_project_root(str(source))
        repository_id = _project_contribution_digest(source_root)
    except (OSError, EngineeringError) as error:
        raise EngineeringError("Engineering host bootstrap record is invalid.") from error
    if value["repository_id"] != repository_id:
        raise EngineeringError("Engineering host bootstrap record repository is mismatched.")
    candidates, pair_digest, ancestry_digest = _v226_bootstrap_pair(value["candidate_pair"])
    if value["candidate_pair_digest"] != pair_digest:
        raise EngineeringError("Engineering host bootstrap record artifact pair is mismatched.")
    internal, public = candidates
    actual_internal = _v226_bootstrap_source_candidate(
        source, "internal", internal["base_commit"]
    )
    public_source = _v226_bootstrap_public_source(source, value.get("public_source"))
    actual_public = _v226_bootstrap_source_candidate(
        public_source, "public", public["base_commit"]
    )
    if internal != actual_internal or public != actual_public:
        raise EngineeringError("Engineering host bootstrap record source artifact is mismatched.")
    for candidate, candidate_source in ((internal, source), (public, public_source)):
        try:
            candidate_root = resolve_project_root(str(candidate_source))
        except (OSError, EngineeringError) as error:
            raise EngineeringError("Engineering host bootstrap record ancestry is unavailable.") from error
        if not _is_ancestor_or_equal(
            candidate_root, candidate["base_commit"], candidate["source_git_commit"]
        ):
            raise EngineeringError("Engineering host bootstrap record ancestry is mismatched.")
    installed = value.get("installed_v225")
    installed_expected = {
        "receipt_digest",
        "skill_version",
        "source_git_commit",
        "source_digest",
    }
    actual_v225 = _v226_installed_v225(home)
    if (
        not isinstance(installed, dict)
        or set(installed) != installed_expected
        or installed != actual_v225
    ):
        raise EngineeringError("Engineering host bootstrap v2.2.5 receipt is mismatched.")
    owner_claims = _v226_bootstrap_owner_claims(
        value.get("owner_approval", {}).get("claims")
        if isinstance(value.get("owner_approval"), dict)
        else None,
        repository_id=repository_id,
        authority_epoch=authority_epoch,
        pair_digest=pair_digest,
        installed_v225_digest=actual_v225["receipt_digest"],
    )
    owner_reference, owner_principal, owner_fingerprint = _v226_verify_bootstrap_signature(
        source,
        home,
        value["owner_approval"],
        approval_schema=V226_BOOTSTRAP_OWNER_APPROVAL_SCHEMA,
        claims_schema="engineering.v2.2.6-bootstrap-owner-claims.v1",
        claims=owner_claims,
        namespace="engineering-v226-bootstrap-owner",
        contract=V226_BOOTSTRAP_OWNER_APPROVAL_SCHEMA,
        authority_epoch=authority_epoch,
        label="owner approval",
    )
    audits = value.get("independent_audits")
    if not isinstance(audits, list) or len(audits) != len(V226_BOOTSTRAP_AUDIT_CATEGORIES):
        raise EngineeringError("Engineering host bootstrap independent audits are invalid.")
    normalized_audits = []
    audit_ids: set[str] = set()
    audit_roles: set[str] = set()
    # Independent audit must be independent of the package approval as well
    # as the other audit.  A valid owner signature is still not audit evidence.
    audit_principals: set[str] = {owner_principal}
    audit_fingerprints: set[str] = {owner_fingerprint}
    replay_nonces = {record_nonce, owner_claims["replay_nonce"]}
    for audit in audits:
        claims = _v226_bootstrap_audit_claims(
            audit.get("claims") if isinstance(audit, dict) else None,
            repository_id=repository_id,
            authority_epoch=authority_epoch,
            pair_digest=pair_digest,
            ancestry_digest=ancestry_digest,
        )
        reference, principal, fingerprint = _v226_verify_bootstrap_signature(
            source,
            home,
            audit,
            approval_schema=V226_BOOTSTRAP_AUDIT_SCHEMA,
            claims_schema="engineering.v2.2.6-bootstrap-audit-claims.v1",
            claims=claims,
            namespace="engineering-v226-bootstrap-audit",
            contract=V226_BOOTSTRAP_AUDIT_SCHEMA,
            authority_epoch=authority_epoch,
            label="independent audit",
        )
        if (
            claims["audit_id"] in audit_ids
            or claims["auditor_role"] in audit_roles
            or principal in audit_principals
            or fingerprint in audit_fingerprints
            or claims["replay_nonce"] in replay_nonces
        ):
            raise EngineeringError("Engineering host bootstrap independent audits are not distinct.")
        audit_ids.add(claims["audit_id"])
        audit_roles.add(claims["auditor_role"])
        audit_principals.add(principal)
        audit_fingerprints.add(fingerprint)
        replay_nonces.add(claims["replay_nonce"])
        normalized_audits.append(
            {
                "audit_id": claims["audit_id"],
                "auditor_role": claims["auditor_role"],
                "reference": reference,
                "principal": principal,
                "signer_fingerprint": fingerprint,
            }
        )
    if len(replay_nonces) != len(audits) + 2:
        raise EngineeringError("Engineering host bootstrap replay evidence is duplicated.")
    if audit_roles != V226_BOOTSTRAP_AUDIT_CATEGORIES:
        raise EngineeringError(
            "Engineering host bootstrap lacks required semantic and technical audit categories."
        )
    if source_bundle != {
        name: internal[name]
        for name in (
            "source_git_commit",
            "source_git_tree",
            "source_digest",
            "skill_version",
        )
    }:
        raise EngineeringError("Engineering host bootstrap record source bundle is mismatched.")
    return {
        "schema": V226_BOOTSTRAP_AUTHORIZATION_SCHEMA,
        "record_id": record_id,
        "record_digest": _json_digest(value),
        "source_bundle": dict(source_bundle),
        "candidate_pair_digest": pair_digest,
        "installed_v225_receipt_digest": actual_v225["receipt_digest"],
        "owner_approval_id": owner_claims["approval_id"],
        "owner_approval_reference": owner_reference,
        "owner_principal": owner_principal,
        "owner_signer_fingerprint": owner_fingerprint,
        "independent_audits": sorted(normalized_audits, key=lambda item: item["audit_id"]),
        "identity": {"state": "unknown"},
        "issued_at": issued_at,
    }


def _v226_bootstrap_authorization_path(home: Path) -> Path:
    """Return the root-owned post-audit record outside candidate Git."""
    path = _v226_bootstrap_authority_dir(home) / "v2.2.6-authorization.json"
    _reject_reparse_ancestors(path)
    return path


def v226_bootstrap_handoff_status(source: Path, home: Path) -> dict:
    """Expose the non-circular bootstrap state without creating any authority.

    Before independent audits exist, this returns only deterministic exact source
    and installed-v2.2.5 evidence for root's external post-audit action.  Once
    root has written its private signed record, the same read-only function
    resolves that record before returning an install authorization reference.
    """
    source = _expand_install_path(source)
    home = _expand_install_path(home)
    if not home.is_absolute() or str(home).startswith("\\\\"):
        raise EngineeringError("Engineering bootstrap home must be absolute.")
    _, manifest, commit, source_digest = _bundle_files(source)
    source_git_tree = _bundle_git_tree(source, commit)
    source_bundle = _v226_bootstrap_source_bundle(
        {
            "source_git_commit": commit,
            "source_git_tree": source_git_tree,
            "source_digest": source_digest,
            "skill_version": manifest["version"],
        }
    )
    installed_v225 = _v226_installed_v225(home)
    path = _v226_bootstrap_authorization_path(home)
    if not path.exists():
        return {
            "schema": "engineering.v2.2.6-bootstrap-handoff.v1",
            "state": "pre_audit_capability_evidence",
            "source_bundle": source_bundle,
            "installed_v225": installed_v225,
            "required_external_evidence": [
                "installed_v225",
                "owner_approval",
                "independent_audits",
            ],
            "post_audit_authority": "root",
        }
    try:
        directory = path.parent
        source_root = resolve_project_root(str(source)).resolve()
        if directory.resolve().is_relative_to(source_root):
            raise EngineeringError("Engineering host bootstrap authority is inside candidate Git.")
        _reject_reparse_ancestors(directory)
        _reject_reparse_ancestors(path, directory)
        _verify_owner_private(directory, directory=True)
        _verify_owner_private(path, directory=False)
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, EngineeringError) as error:
        raise EngineeringError("Engineering host bootstrap authority is unavailable.") from error
    resolved = _v226_bootstrap_host_record(source, home, record, source_bundle)
    authorization = {
        name: resolved[name]
        for name in ("schema", "record_id", "record_digest", "source_bundle")
    }
    return {
        "schema": "engineering.v2.2.6-bootstrap-handoff.v1",
        "state": "post_audit_authorization_available",
        "source_bundle": source_bundle,
        "installed_v225": installed_v225,
        "bootstrap_authorization": authorization,
        "candidate_pair_digest": resolved["candidate_pair_digest"],
        "independent_audit_ids": [
            item["audit_id"] for item in resolved["independent_audits"]
        ],
        "post_audit_authority": "root",
    }


def _host_v226_bootstrap_authorization(
    source: Path, home: Path, supplied: object, source_bundle: dict
) -> dict:
    """Require a caller reference to equal the resolved root post-audit record."""
    supplied_normalized = _v226_bootstrap_authorization(supplied, source_bundle)
    status = v226_bootstrap_handoff_status(source, home)
    if status.get("state") != "post_audit_authorization_available":
        raise EngineeringError(
            "Engineering host bootstrap authorization is unavailable pending root post-audit evidence."
        )
    host_normalized = status.get("bootstrap_authorization")
    if host_normalized != supplied_normalized:
        raise EngineeringError("Engineering host bootstrap authorization is mismatched.")
    return host_normalized


def _load_install_receipt(path: Path, key: bytes) -> dict | None:
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering install receipt is invalid.") from error
    legacy_required = {
        "schema",
        "status",
        "skill_version",
        "source_git_commit",
        "source_digest",
        "graphify_commit",
        "installed_at",
        "codex_parity_hash",
        "claude_parity_hash",
        "signature",
    }
    authorization_required = {
        "schema",
        "token_id",
        "token_digest",
        "artifact_digest",
        "acceptance_id",
        "source_bundle",
    }
    authorization = receipt.get("release_authorization") if isinstance(receipt, dict) else None
    bootstrap_authorization = (
        receipt.get("bootstrap_authorization") if isinstance(receipt, dict) else None
    )
    v2_required = legacy_required | {"release_authorization"}
    v3_required = legacy_required | {"bootstrap_authorization"}
    v4_required = legacy_required | {"bootstrap_authorization"}
    current_required = legacy_required | {"source_git_tree"}
    valid_legacy = (
        isinstance(receipt, dict)
        and set(receipt) == legacy_required
        and receipt.get("schema") == "engineering.install.v1"
    )
    valid_v2 = (
        isinstance(receipt, dict)
        and set(receipt) == v2_required
        and receipt.get("schema") == "engineering.install.v2"
        and isinstance(authorization, dict)
        and set(authorization) == authorization_required
        and authorization.get("schema") == "engineering.install-release-authorization.v1"
        and isinstance(authorization.get("source_bundle"), dict)
        and set(authorization["source_bundle"])
        == {"source_git_commit", "source_digest", "skill_version"}
        and authorization["source_bundle"].get("source_git_commit")
        == receipt.get("source_git_commit")
        and authorization["source_bundle"].get("source_digest")
        == receipt.get("source_digest")
        and authorization["source_bundle"].get("skill_version")
        == receipt.get("skill_version")
        and isinstance(authorization.get("token_id"), str)
        and re.fullmatch(r"release-token-[0-9a-f]{32}", authorization["token_id"])
        and all(
            re.fullmatch(r"sha256:[0-9a-f]{64}", str(authorization.get(name, "")))
            for name in ("token_digest", "artifact_digest")
        )
        and isinstance(authorization.get("acceptance_id"), str)
        and re.fullmatch(r"acceptance-[A-Za-z0-9][A-Za-z0-9._-]*", authorization["acceptance_id"])
    )
    source_bundle = {
        "source_git_commit": receipt.get("source_git_commit"),
        "source_digest": receipt.get("source_digest"),
        "skill_version": receipt.get("skill_version"),
    }
    try:
        valid_v3 = (
            isinstance(receipt, dict)
            and set(receipt) == v3_required
            and receipt.get("schema") == "engineering.install.v3"
            and _legacy_v226_bootstrap_authorization(bootstrap_authorization, source_bundle)
            == bootstrap_authorization
        )
    except EngineeringError:
        valid_v3 = False
    try:
        valid_v4 = (
            isinstance(receipt, dict)
            and set(receipt) == v4_required
            and receipt.get("schema") == "engineering.install.v4"
            and _v226_bootstrap_authorization(bootstrap_authorization, source_bundle)
            == bootstrap_authorization
        )
    except EngineeringError:
        valid_v4 = False
    source_bundle_v5 = {
        "source_git_commit": receipt.get("source_git_commit"),
        "source_git_tree": receipt.get("source_git_tree"),
        "source_digest": receipt.get("source_digest"),
        "skill_version": receipt.get("skill_version"),
    }
    receipt_keys = set(receipt) if isinstance(receipt, dict) else set()
    authorization_kind = None
    if receipt_keys == current_required:
        authorization_kind = "none"
    elif receipt_keys == current_required | {"release_authorization"}:
        authorization_kind = "release"
    elif receipt_keys == current_required | {"bootstrap_authorization"}:
        authorization_kind = "bootstrap"
    valid_v5_release = False
    if authorization_kind == "release" and isinstance(authorization, dict):
        valid_v5_release = (
            set(authorization) == authorization_required
            and authorization.get("schema")
            == "engineering.install-release-authorization.v1"
            and authorization.get("source_bundle") == source_bundle_v5
            and isinstance(authorization.get("token_id"), str)
            and re.fullmatch(r"release-token-[0-9a-f]{32}", authorization["token_id"])
            and all(
                re.fullmatch(r"sha256:[0-9a-f]{64}", str(authorization.get(name, "")))
                for name in ("token_digest", "artifact_digest")
            )
            and isinstance(authorization.get("acceptance_id"), str)
            and re.fullmatch(
                r"acceptance-[A-Za-z0-9][A-Za-z0-9._-]*",
                authorization["acceptance_id"],
            )
        )
    try:
        valid_v5_bootstrap = (
            authorization_kind == "bootstrap"
            and _v226_bootstrap_authorization(
                bootstrap_authorization, source_bundle_v5
            )
            == bootstrap_authorization
        )
    except EngineeringError:
        valid_v5_bootstrap = False
    version = receipt.get("skill_version") if isinstance(receipt, dict) else None
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", str(version))
    version_tuple = tuple(int(part) for part in match.groups()) if match else ()
    valid_v5 = (
        isinstance(receipt, dict)
        and receipt.get("schema") == "engineering.install.v5"
        and re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("source_git_tree", "")))
        and (
            valid_v5_release
            or valid_v5_bootstrap
            or (authorization_kind == "none" and version_tuple < (2, 2, 6))
        )
    )
    if (
        not (valid_legacy or valid_v2 or valid_v3 or valid_v4 or valid_v5)
        or receipt.get("status") not in {"installed", "rolled_back"}
        or not re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("source_git_commit", "")))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(receipt.get("source_digest", "")))
        or receipt.get("graphify_commit") != GRAPHIFY_COMMIT
        or receipt.get("codex_parity_hash") != receipt.get("claude_parity_hash")
        or not hmac.compare_digest(
            str(receipt.get("signature", "")),
            _sign_install_receipt(receipt, key)["signature"],
        )
    ):
        raise EngineeringError("Engineering install receipt is invalid.")
    return receipt


def _validated_installed_bundle(path: Path, receipt: dict | None = None) -> str:
    if not path.is_dir() or _is_reparse_point(path):
        raise EngineeringError("Engineering installed bundle is invalid.")
    for required in (
        "SKILL.md",
        "manifest.json",
        "scripts/engineering.py",
        "references/controller-contract.md",
    ):
        if not (path / required).is_file() or _is_reparse_point(path / required):
            raise EngineeringError("Engineering installed bundle is invalid.")
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering installed bundle manifest is invalid.") from error
    parity = "sha256:" + hashlib.sha256((path / "SKILL.md").read_bytes()).hexdigest()
    if not (
        manifest.get("name") == "engineering"
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(manifest.get("version", "")))
        and isinstance(manifest.get("graphify"), dict)
        and manifest["graphify"].get("commit") == GRAPHIFY_COMMIT
    ):
        raise EngineeringError("Engineering installed bundle manifest is invalid.")
    if receipt is not None and not (
        receipt["skill_version"] == manifest["version"]
        and receipt["source_digest"] == _tree_digest(path)
        and receipt["graphify_commit"] == manifest["graphify"]["commit"]
        and receipt["codex_parity_hash"] == parity
        and receipt["claude_parity_hash"] == parity
    ):
        raise EngineeringError("Engineering installed bundle does not match its receipt.")
    return parity


def _valid_forwarder(path: Path, name: str) -> bool:
    candidate = path / "SKILL.md"
    return (
        path.is_dir()
        and not _is_reparse_point(path)
        and candidate.is_file()
        and not _is_reparse_point(candidate)
        and candidate.read_text(encoding="utf-8") == _forwarder(name)
    )


def _validate_install_paths(home: Path, paths: dict[str, Path]) -> None:
    _reject_reparse_ancestors(home)
    for path in paths.values():
        _reject_reparse_ancestors(path, home)


def _install_path_state(path: Path) -> dict:
    if not os.path.lexists(path):
        return {
            "exists": False,
            "kind": "absent",
            "bytes_hex": None,
            "sha256": None,
            "mode": None,
        }
    if path.is_symlink() or _is_reparse_point(path):
        raise EngineeringError(f"Engineering target changed before publication: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if path.is_file():
        content = path.read_bytes()
        return {
            "exists": True,
            "kind": "file",
            "bytes_hex": content.hex(),
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "mode": mode,
        }
    if not path.is_dir():
        raise EngineeringError(f"Engineering target changed before publication: {path}")
    digest = hashlib.sha256(b"engineering.install-path.directory.v1\0")
    for candidate in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if candidate.is_symlink() or _is_reparse_point(candidate):
            raise EngineeringError(
                f"Engineering target changed before publication: {path}"
            )
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        candidate_mode = stat.S_IMODE(candidate.stat().st_mode)
        if candidate.is_dir():
            digest.update(b"directory\0" + relative + b"\0")
            digest.update(str(candidate_mode).encode("ascii") + b"\0")
        elif candidate.is_file():
            digest.update(b"file\0" + relative + b"\0")
            digest.update(str(candidate_mode).encode("ascii") + b"\0")
            digest.update(candidate.read_bytes() + b"\0")
        else:
            raise EngineeringError(
                f"Engineering target changed before publication: {path}"
            )
    return {
        "exists": True,
        "kind": "directory",
        "bytes_hex": None,
        "sha256": "sha256:" + digest.hexdigest(),
        "mode": mode,
    }


def _verify_install_path_state(path: Path, expected: dict | None) -> None:
    if expected is None:
        return
    normalized = {
        key: expected.get(key)
        for key in ("exists", "kind", "bytes_hex", "sha256", "mode")
    }
    if _install_path_state(path) != normalized:
        raise EngineeringError(f"Engineering target changed before publication: {path}")


def _install_replace_retry_delays() -> tuple[float, ...]:
    """Return the bounded native retry policy without changing path semantics."""
    return (0.05, 0.1, 0.2, 0.4, 0.8) if os.name == "nt" else ()


def _replace_install_path(
    source: Path,
    target: Path,
    expected_pre_state: dict | None = None,
    *,
    preimage_path: Path | None = None,
    expected_source_state: dict | None = None,
    expected_target_state: dict | None = None,
) -> None:
    def verify_pre_state() -> None:
        inspected = preimage_path if preimage_path is not None else target
        _verify_install_path_state(inspected, expected_pre_state)
        _verify_install_path_state(source, expected_source_state)
        _verify_install_path_state(target, expected_target_state)

    # Antivirus and indexers can briefly retain Windows directory handles. Keep
    # retries bounded and compare-and-swap safe rather than weakening atomicity.
    retry_delays = _install_replace_retry_delays()
    for delay in (*retry_delays, None):
        verify_pre_state()
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            if delay is None or getattr(error, "winerror", None) not in {5, 32, 33}:
                raise
            time.sleep(delay)


def _transactional_replace(
    replacements: list[tuple[Path, Path]],
    token: str,
    expected_pre_states: dict[Path, dict] | None = None,
    *,
    after_publication=None,
) -> None:
    expected_pre_states = expected_pre_states or {}
    absent = {
        "exists": False,
        "kind": "absent",
        "bytes_hex": None,
        "sha256": None,
        "mode": None,
    }
    backups = {
        target: target.with_name(f".{target.name}.backup-{token}")
        for _, target in replacements
    }
    backed_up: list[Path] = []
    published: list[Path] = []
    target_states = {
        target: expected_pre_states.get(target, _install_path_state(target))
        for _, target in replacements
    }
    stage_states = {stage: _install_path_state(stage) for stage, _ in replacements}
    published_stages: set[Path] = set()
    completed = False
    try:
        for stage, target in replacements:
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = backups[target]
            _remove_install_path(backup, absent)
            expected = target_states[target]
            if os.path.lexists(target):
                if _is_reparse_point(target):
                    raise EngineeringError("Engineering install target is a link/reparse point.")
                _replace_install_path(
                    target,
                    backup,
                    expected_source_state=expected,
                    expected_target_state=absent,
                )
                backed_up.append(target)
                _replace_install_path(
                    stage,
                    target,
                    expected_source_state=stage_states[stage],
                    expected_target_state=absent,
                )
                published_stages.add(stage)
            else:
                _replace_install_path(
                    stage,
                    target,
                    expected_source_state=stage_states[stage],
                    expected_target_state=expected,
                )
                published_stages.add(stage)
            published.append(target)
        if after_publication is not None:
            after_publication()
        completed = True
    except Exception:
        for target in reversed(published):
            stage = next(item for item, destination in replacements if destination == target)
            _remove_install_path(target, stage_states[stage])
        for target in reversed(backed_up):
            backup = backups[target]
            if backup.exists() and not os.path.lexists(target):
                _replace_install_path(
                    backup,
                    target,
                    expected_source_state=target_states[target],
                    expected_target_state=absent,
                )
            elif backup.exists():
                raise EngineeringError(
                    f"Engineering target changed before publication: {target}"
                )
        raise
    finally:
        for stage, _ in replacements:
            _remove_install_path(
                stage,
                absent if stage in published_stages else stage_states[stage],
            )
        if completed:
            for target, backup in backups.items():
                _remove_install_path(backup, target_states[target])


def _expand_install_path(value: Path | str) -> Path:
    """Expand user paths without re-factorying a Path under a mocked os.name."""
    if isinstance(value, Path):
        return value.expanduser()
    expanded = os.path.expanduser(os.fspath(value))
    if os.name == "nt" and sys.platform != "win32" and expanded.startswith("/"):
        return PosixPath(expanded)
    return Path(expanded)


def _release_token_required_for_install(manifest: object) -> bool:
    """Require a v2.2.6+ token while preserving the v2.2.5 rollback path."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get("version"), str):
        raise EngineeringError("Engineering bundle manifest is invalid.")
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", manifest["version"])
    if match is None:
        raise EngineeringError("Engineering bundle manifest is invalid.")
    return tuple(int(part) for part in match.groups()) >= (2, 2, 6)


def install_bundle(
    source: Path,
    home: Path,
    *,
    release_token: object | None = None,
    release_artifact_digest: str | None = None,
    bootstrap_authorization: object | None = None,
) -> dict:
    """Install a bundle only after the required exact-artifact gate preflight.

    The caller retains responsibility for a separate native install approval.
    A v2.2.6+ bundle requires the token/root/artifact trio, except for its
    one-time host-provided bootstrap authorization. The historical v2.2.5 path
    remains readable and rollback-safe but cannot gain a v2.2.6 token
    retrospectively.
    """
    source = _expand_install_path(source)
    home = _expand_install_path(home)
    if not home.is_absolute() and not os.path.isabs(os.path.expanduser(os.fspath(home))):
        raise EngineeringError("Engineering install home must be absolute.")
    if str(home).startswith("\\\\"):
        raise EngineeringError("Engineering installation on UNC paths is unsupported.")
    bundle_snapshot = _bundle_files(source)
    files, manifest, commit, source_digest = bundle_snapshot
    source_git_tree = (
        bundle_snapshot.source_git_tree
        if isinstance(bundle_snapshot, BundleSnapshot)
        else _bundle_git_tree(source, commit)
    )
    expected_source_bundle = {
        "source_git_commit": commit,
        "source_git_tree": source_git_tree,
        "source_digest": source_digest,
        "skill_version": manifest["version"],
    }
    if (release_token is None) != (release_artifact_digest is None):
        raise EngineeringError(
            "Engineering install release gate requires both token and exact artifact digest."
        )
    if bootstrap_authorization is not None and release_token is not None:
        raise EngineeringError(
            "Engineering install accepts either a release token or bootstrap authorization, never both."
        )
    if _release_token_required_for_install(manifest) and (
        release_token is None and bootstrap_authorization is None
    ):
        raise EngineeringError(
            "Engineering v2.2.6+ installation requires an exact release token preflight or bootstrap authorization."
        )
    validated_bootstrap = (
        _host_v226_bootstrap_authorization(
            source, home, bootstrap_authorization, expected_source_bundle
        )
        if bootstrap_authorization is not None
        else None
    )
    release_gate = None
    if release_token is not None:
        if not isinstance(release_token, dict) or set(release_token) != {
            "root",
            "token_id",
        }:
            raise EngineeringError("Engineering install release gate reference is invalid.")
        gate_root = _expand_install_path(release_token["root"])
        if not gate_root.is_absolute() or not isinstance(release_token["token_id"], str):
            raise EngineeringError("Engineering install release gate reference is invalid.")
        release_gate = verify_release_token(
            gate_root,
            release_token["token_id"],
            release_artifact_digest,
            "install",
        )
        source_bundle = release_gate.get("source_bundle") if isinstance(release_gate, dict) else None
        if source_bundle != expected_source_bundle:
            raise EngineeringError(
                "Engineering release token does not authorize this exact source bundle."
            )
        release_authorization = {
            "schema": "engineering.install-release-authorization.v1",
            "token_id": release_gate.get("token_id"),
            "token_digest": release_gate.get("token_digest"),
            "artifact_digest": release_gate.get("artifact_digest"),
            "acceptance_id": release_gate.get("acceptance_id"),
            "source_bundle": expected_source_bundle,
        }
        if (
            not isinstance(release_authorization["token_id"], str)
            or not re.fullmatch(r"release-token-[0-9a-f]{32}", release_authorization["token_id"])
            or any(
                not re.fullmatch(r"sha256:[0-9a-f]{64}", str(release_authorization[name]))
                for name in ("token_digest", "artifact_digest")
            )
            or not isinstance(release_authorization["acceptance_id"], str)
            or not re.fullmatch(
                r"acceptance-[A-Za-z0-9][A-Za-z0-9._-]*",
                release_authorization["acceptance_id"],
            )
        ):
            raise EngineeringError("Engineering release token authorization facts are invalid.")
    else:
        release_authorization = None
    paths = _install_paths(home)
    _validate_install_paths(home, paths)
    home = home.resolve()
    paths = _install_paths(home)
    lock_owner = _acquire_directory_lock(paths["lock"], "Engineering install is already in progress.")
    token = uuid.uuid4().hex
    stages: dict[str, Path] = {
        key: path.with_name(f".{path.name}.backup-{token}")
        for key, path in paths.items()
        if key in {"canonical", "previous", "claude", "shim", "command", "receipt", "previous_receipt"}
    }
    stages = {key: path.with_name(path.name.replace(".backup-", ".stage-")) for key, path in stages.items()}
    absent_install_state = {
        "exists": False,
        "kind": "absent",
        "bytes_hex": None,
        "sha256": None,
        "mode": None,
    }
    staged_cleanup_states: dict[Path, dict] = {}
    transaction_started = False
    try:
        install_key = _install_key(home)
        current = _load_install_receipt(paths["receipt"], install_key)
        if current is not None:
            if not paths["canonical"].is_dir():
                raise EngineeringError("Engineering installed bundle does not match its receipt.")
            _validated_installed_bundle(paths["canonical"], current)
            if (
                current["source_git_commit"] == commit
                and current["source_digest"] == source_digest
                and _valid_forwarder(paths["claude"], "engineering")
                and _valid_forwarder(paths["shim"], "engineering-traceability")
                and _valid_command_launchers(paths["command"])
            ):
                if release_authorization is not None and (
                    current.get("release_authorization") != release_authorization
                ):
                    raise EngineeringError(
                        "Engineering installed bundle release authorization is mismatched."
                    )
                if validated_bootstrap is not None and (
                    current.get("bootstrap_authorization") != validated_bootstrap
                ):
                    raise EngineeringError(
                        "Engineering installed bundle bootstrap authorization is mismatched."
                    )
                return {
                    **current,
                    **({"release_gate": release_gate} if release_gate is not None else {}),
                }
        elif any(paths[key].exists() for key in ("canonical", "previous", "previous_receipt")):
            raise EngineeringError("Engineering install state is incomplete.")
        for path in stages.values():
            _remove_install_path(path, absent_install_state)
        _copy_bundle(
            source,
            stages["canonical"],
            files,
            commit,
            bundle_snapshot.blobs
            if isinstance(bundle_snapshot, BundleSnapshot)
            else None,
        )
        staged_cleanup_states[stages["canonical"]] = _install_path_state(stages["canonical"])
        stages["claude"].mkdir(parents=True)
        (stages["claude"] / "SKILL.md").write_text(
            _forwarder("engineering"), encoding="utf-8", newline="\n"
        )
        staged_cleanup_states[stages["claude"]] = _install_path_state(stages["claude"])
        stages["shim"].mkdir(parents=True)
        (stages["shim"] / "SKILL.md").write_text(
            _forwarder("engineering-traceability"), encoding="utf-8", newline="\n"
        )
        staged_cleanup_states[stages["shim"]] = _install_path_state(stages["shim"])
        _write_command_launchers(stages["command"])
        staged_cleanup_states[stages["command"]] = _install_path_state(stages["command"])
        parity = _validated_installed_bundle(stages["canonical"])
        if _tree_digest(stages["canonical"]) != source_digest:
            raise EngineeringError(
                "Engineering staged bundle does not match the authorized source bundle."
            )
        receipt_payload = {
            "schema": "engineering.install.v5",
            "status": "installed",
            "skill_version": manifest["version"],
            "source_git_commit": commit,
            "source_git_tree": source_git_tree,
            "source_digest": source_digest,
            "graphify_commit": manifest["graphify"]["commit"],
            "installed_at": _utc_now(),
            "codex_parity_hash": parity,
            "claude_parity_hash": parity,
        }
        if release_authorization is not None:
            receipt_payload["release_authorization"] = release_authorization
        if validated_bootstrap is not None:
            receipt_payload["bootstrap_authorization"] = validated_bootstrap
        receipt = _sign_install_receipt(receipt_payload, install_key)
        stages["receipt"].parent.mkdir(parents=True, exist_ok=True)
        stages["receipt"].write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        staged_cleanup_states[stages["receipt"]] = _install_path_state(stages["receipt"])
        replacements = [
            (stages[key], paths[key]) for key in ("canonical", "claude", "shim", "command", "receipt")
        ]
        if current is not None:
            shutil.copytree(paths["canonical"], stages["previous"])
            staged_cleanup_states[stages["previous"]] = _install_path_state(stages["previous"])
            stages["previous_receipt"].write_bytes(paths["receipt"].read_bytes())
            staged_cleanup_states[stages["previous_receipt"]] = _install_path_state(
                stages["previous_receipt"]
            )
            replacements.extend(
                (stages[key], paths[key]) for key in ("previous", "previous_receipt")
            )
        transaction_started = True
        _transactional_replace(
            replacements,
            token,
            after_publication=(
                lambda: _register_windows_command_directory(home, paths["command"])
                if current is None and os.name == "nt"
                else None
            ),
        )
        return {
            **receipt,
            **({"release_gate": release_gate} if release_gate is not None else {}),
        }
    finally:
        if not transaction_started:
            for path, expected_state in staged_cleanup_states.items():
                _remove_install_path(path, expected_state)
        _release_directory_lock(paths["lock"], lock_owner)


def rollback_install(home: Path) -> dict:
    home = _expand_install_path(home)
    if not home.is_absolute() and not os.path.isabs(os.path.expanduser(os.fspath(home))):
        raise EngineeringError("Engineering install home must be absolute.")
    if str(home).startswith("\\\\"):
        raise EngineeringError("Engineering installation on UNC paths is unsupported.")
    paths = _install_paths(home)
    _validate_install_paths(home, paths)
    home = home.resolve()
    paths = _install_paths(home)
    lock_owner = _acquire_directory_lock(paths["lock"], "Engineering install is already in progress.")
    token = uuid.uuid4().hex
    stages = {
        key: path.with_name(f".{path.name}.stage-{token}")
        for key, path in paths.items()
        if key in {"canonical", "previous", "claude", "shim", "command", "receipt", "previous_receipt"}
    }
    staged_cleanup_states: dict[Path, dict] = {}
    transaction_started = False
    try:
        install_key = _install_key(home)
        current = _load_install_receipt(paths["receipt"], install_key)
        previous = _load_install_receipt(paths["previous_receipt"], install_key)
        if current is None or previous is None:
            raise EngineeringError("Engineering has no known-good rollback installation.")
        _validated_installed_bundle(paths["canonical"], current)
        try:
            parity = _validated_installed_bundle(paths["previous"], previous)
        except EngineeringError as error:
            raise EngineeringError("Engineering known-good rollback bundle is invalid.") from error
        shutil.copytree(paths["previous"], stages["canonical"])
        staged_cleanup_states[stages["canonical"]] = _install_path_state(stages["canonical"])
        shutil.copytree(paths["canonical"], stages["previous"])
        staged_cleanup_states[stages["previous"]] = _install_path_state(stages["previous"])
        for key, name in (("claude", "engineering"), ("shim", "engineering-traceability")):
            stages[key].mkdir(parents=True)
            (stages[key] / "SKILL.md").write_text(
                _forwarder(name), encoding="utf-8", newline="\n"
            )
            staged_cleanup_states[stages[key]] = _install_path_state(stages[key])
        _write_command_launchers(stages["command"])
        staged_cleanup_states[stages["command"]] = _install_path_state(stages["command"])
        restored = _sign_install_receipt({
            **previous,
            "status": "rolled_back",
            "installed_at": _utc_now(),
            "codex_parity_hash": parity,
            "claude_parity_hash": parity,
        }, install_key)
        stages["receipt"].write_text(json.dumps(restored, indent=2) + "\n", encoding="utf-8")
        staged_cleanup_states[stages["receipt"]] = _install_path_state(stages["receipt"])
        stages["previous_receipt"].write_text(
            json.dumps(current, indent=2) + "\n", encoding="utf-8"
        )
        staged_cleanup_states[stages["previous_receipt"]] = _install_path_state(
            stages["previous_receipt"]
        )
        transaction_started = True
        _transactional_replace(
            [(stages[key], paths[key]) for key in (
                "canonical", "previous", "claude", "shim", "command", "receipt", "previous_receipt"
            )],
            token,
        )
        return restored
    finally:
        if not transaction_started:
            for path, expected_state in staged_cleanup_states.items():
                _remove_install_path(path, expected_state)
        _release_directory_lock(paths["lock"], lock_owner)


def _legacy_tree_recognized(path: Path) -> bool:
    if (
        path.is_symlink()
        or _is_reparse_point(path)
        or not (path / "graph.json").is_file()
    ):
        return False
    try:
        descendants = list(path.rglob("*"))
    except OSError:
        return False
    for item in descendants:
        if item.is_symlink() or _is_reparse_point(item) or not item.is_file():
            return False
        relative = item.relative_to(path).as_posix()
        if relative not in LEGACY_GRAPHIFY_FILES:
            return False
    return True


def inventory_legacy_outputs(root: Path) -> list[dict]:
    project_root = resolve_project_root(str(root))
    candidates = []
    for worktree in _worktree_roots(project_root):
        path = worktree / "graphify-out"
        if not path.exists() and not path.is_symlink():
            continue
        try:
            inside = (
                path.name == "graphify-out"
                and path.resolve().parent == worktree.resolve()
                and not path.is_symlink()
                and not _is_reparse_point(path)
            )
        except OSError:
            inside = False
        ignored = (
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "check-ignore",
                    "--quiet",
                    "--",
                    "graphify-out",
            ],
            capture_output=True,
            text=True,
            env=_controller_git_environment(),
        ).returncode
            == 0
        )
        replacement = check_merge_readiness(worktree) if inside else {"ready": False}
        candidates.append(
            {
                "path": str(path),
                "worktree": str(worktree),
                "safe_generated": bool(
                    inside
                    and ignored
                    and replacement["ready"]
                    and _legacy_tree_recognized(path)
                ),
                "replacement_succeeded": bool(replacement["ready"]),
                "inventory_version": 1,
            }
        )
    return candidates


def clean_legacy_output(root: Path, candidate_path: Path) -> bool:
    project_root = resolve_project_root(str(root))
    path = Path(candidate_path)
    worktree = next(
        (
            candidate
            for candidate in _worktree_roots(project_root)
            if path == candidate / "graphify-out"
        ),
        None,
    )
    if worktree is None:
        return False
    try:
        if (
            path.name != "graphify-out"
            or path.resolve().parent != worktree.resolve()
            or path.is_symlink()
            or _is_reparse_point(path)
            or not _legacy_tree_recognized(path)
            or subprocess.run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "check-ignore",
                    "--quiet",
                    "--",
                    "graphify-out",
                ],
                capture_output=True,
                text=True,
                env=_controller_git_environment(),
            ).returncode
            != 0
            or not check_merge_readiness(worktree)["ready"]
        ):
            return False
    except OSError:
        return False
    shutil.rmtree(path)
    return not path.exists()


def reconcile_legacy_outputs(root: Path) -> dict:
    project_root = resolve_project_root(str(root))
    operation = _begin_completion(project_root, "legacy-output-reconciliation")
    try:
        observations = []
        for candidate in inventory_legacy_outputs(project_root):
            local = Path(candidate["worktree"]).resolve() == project_root.resolve()
            observations.append(
                {
                    "area": "legacy-output",
                    "artifact": "graphify-out" if local else "legacy-graph-output",
                    "kind": (
                        "legacy_graph_generated"
                        if candidate["safe_generated"] and local
                        else "legacy_graph_ambiguous"
                    ),
                    "impact": (
                        "routine"
                        if candidate["safe_generated"] and local
                        else "ambiguous"
                    ),
                }
            )
        queued = _queue_maintenance_locked(project_root, observations, operation)
        return {
            "maintenance": [
                {"id": item["id"], "kind": item["kind"]} for item in queued
            ]
        }
    finally:
        _end_completion(project_root, operation)


def _hooks_dir(root: Path) -> Path:
    common_raw = _identity_git(root, "rev-parse", "--git-common-dir")
    common = Path(common_raw)
    if not common.is_absolute():
        common = root / common
    _reject_reparse_ancestors(common.absolute())
    common = common.resolve()
    canonical = common / "hooks"
    _reject_reparse_ancestors(canonical.absolute())
    try:
        configured = _identity_git(
            root, "config", "--local", "--get", "core.hooksPath"
        ).strip()
    except EngineeringError:
        configured = ""
    resolved_raw = _identity_git(
        root, "rev-parse", "--path-format=absolute", "--git-path", "hooks"
    )
    resolved = Path(resolved_raw).absolute()
    _reject_reparse_ancestors(resolved)
    resolved = resolved.resolve()
    if resolved != canonical or (configured and resolved != canonical):
        raise EngineeringError(
            "unsupported core.hooksPath: Engineering requires <git-common-dir>/hooks"
        )
    return canonical


def _hook_artifact_paths(root: Path) -> list[Path]:
    hooks = _hooks_dir(root)
    return [
        hooks / "engineering-traceability-dispatcher",
        hooks / PRESERVED_HOOK_MANIFEST,
        *(hooks / event for event in HOOK_EVENTS),
    ]


def _preserved_hook_state(root: Path, directory_name: str) -> list[dict]:
    if directory_name not in {PRESERVED_HOOK_DIRECTORY, "engineering-preserved"}:
        raise EngineeringError("Engineering preserved-hook boundary is unsupported.")
    hooks = _hooks_dir(root)
    preserved = hooks / directory_name
    if preserved.is_symlink() or (
        preserved.exists() and _is_reparse_point(preserved)
    ):
        target = os.readlink(preserved) if preserved.is_symlink() else None
        raise EngineeringError(
            "Engineering preserved-hook directory is a link/reparse point"
            + (f" targeting {target!r}." if target is not None else ".")
        )
    if not preserved.exists():
        return []
    if not preserved.is_dir():
        raise EngineeringError("Engineering preserved-hook boundary is not a directory.")
    records: list[dict] = []
    total_bytes = 0
    for path in sorted(
        preserved.rglob("*"), key=lambda item: item.relative_to(preserved).as_posix()
    ):
        if len(records) >= MAX_PRESERVED_HOOK_ARTIFACTS:
            raise EngineeringError("Engineering preserved-hook inventory is too large.")
        relative = path.relative_to(hooks).as_posix()
        if path.is_symlink() or _is_reparse_point(path):
            target = os.readlink(path) if path.is_symlink() else None
            raise EngineeringError(
                f"Engineering preserved-hook artifact is a link/reparse point: {relative}"
                + (f" -> {target!r}" if target is not None else "")
            )
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir():
            records.append(
                {
                    "path": relative,
                    "exists": True,
                    "kind": "directory",
                    "bytes_hex": None,
                    "sha256": None,
                    "mode": mode,
                    "target": None,
                }
            )
            continue
        if not path.is_file():
            raise EngineeringError(
                f"Engineering preserved-hook artifact type is unsupported: {relative}"
            )
        content = path.read_bytes()
        total_bytes += len(content)
        if total_bytes > MAX_PRESERVED_HOOK_BYTES:
            raise EngineeringError("Engineering preserved-hook inventory is too large.")
        records.append(
            {
                "path": relative,
                "exists": True,
                "kind": "file",
                "bytes_hex": content.hex(),
                "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
                "mode": mode,
                "target": None,
            }
        )
    return records


def _preserved_hook_manifest_bytes(records: list[dict]) -> bytes:
    return (
        json.dumps(
            {
                "schema": "engineering.preserved-hooks.v1",
                "artifacts": records,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _hook_plan_state(root: Path) -> list[dict]:
    hooks = _hooks_dir(root)
    records = []
    for path in _hook_artifact_paths(root):
        if path.exists() and (path.is_symlink() or _is_reparse_point(path)):
            raise EngineeringError("Engineering hook artifact is a link/reparse point.")
        exists = path.exists()
        if exists and not path.is_file():
            raise EngineeringError("Engineering hook artifact type is unsupported.")
        content = path.read_bytes() if exists else b""
        records.append(
            {
                "path": path.relative_to(hooks).as_posix(),
                "exists": exists,
                "bytes_hex": content.hex() if exists else None,
                "sha256": (
                    "sha256:" + hashlib.sha256(content).hexdigest()
                    if exists
                    else None
                ),
                "mode": stat.S_IMODE(path.stat().st_mode) if exists else None,
            }
        )
    records.extend(_preserved_hook_state(root, "engineering-preserved"))
    records.extend(_preserved_hook_state(root, PRESERVED_HOOK_DIRECTORY))
    return records


def _dispatcher_text(
    root: Path, graphify_python: str, script_path: Path
) -> str:
    return (
        "#!/bin/sh\n"
        "# engineering-traceability-dispatcher\n"
        'event="$1"\n'
        "shift\n"
        'hook_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'preserved="$hook_dir/engineering-traceability-preserved/$event"\n'
        'if [ -f "$preserved" ]; then\n'
        '    "$preserved" "$@" || exit $?\n'
        "fi\n"
        'local_env=$(git rev-parse --local-env-vars) || exit $?\n'
        'unset $local_env\n'
        'project_root=$(git -C "$PWD" rev-parse --show-toplevel) || exit $?\n'
        "exec "
        + _shell_quote(str(Path(sys.executable).resolve()))
        + " "
        + _shell_quote(str(script_path.resolve()))
        + ' hook "$event" "$project_root"'
        + " --graphify-python "
        + _shell_quote(str(Path(graphify_python).expanduser().resolve()))
        + "\n"
    )


def _hook_wrapper(event: str) -> str:
    return (
        "#!/bin/sh\n"
        "# engineering-traceability-hook\n"
        'exec "$(dirname -- "$0")/engineering-traceability-dispatcher" '
        f'{event} "$@"\n'
    )


def _round_one_hook_wrapper(event: str) -> bytes:
    return (
        "#!/bin/sh\n"
        "# engineering-hook\n"
        'exec "$(dirname -- "$0")/engineering-dispatcher" '
        f'{event} "$@"\n'
    ).encode("utf-8")


def _approved_hook_records(records: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for record in records:
        path = record.get("path")
        if not isinstance(path, str) or path in indexed:
            raise EngineeringError("Engineering approved hook snapshot is invalid.")
        indexed[path] = record
    return indexed


def _approved_file_bytes(record: dict | None, path: str) -> bytes | None:
    if record is None or not record.get("exists"):
        return None
    if record.get("kind", "file") != "file" or not isinstance(
        record.get("bytes_hex"), str
    ):
        raise EngineeringError(f"Engineering approved hook artifact is invalid: {path}")
    try:
        content = bytes.fromhex(record["bytes_hex"])
    except ValueError as error:
        raise EngineeringError(
            f"Engineering approved hook artifact is invalid: {path}"
        ) from error
    if record.get("sha256") != "sha256:" + hashlib.sha256(content).hexdigest():
        raise EngineeringError(f"Engineering approved hook artifact is invalid: {path}")
    return content


def _preimage_state(record: dict | None) -> dict:
    if record is None:
        return {
            "exists": False,
            "kind": "absent",
            "bytes_hex": None,
            "sha256": None,
            "mode": None,
        }
    exists = bool(record.get("exists"))
    return {
        "exists": exists,
        "kind": record.get("kind", "file" if exists else "absent"),
        "bytes_hex": record.get("bytes_hex"),
        "sha256": record.get("sha256"),
        "mode": record.get("mode"),
    }


def _managed_hook_mode() -> int:
    return 0o666 if os.name == "nt" else 0o755


def _managed_hook_documents(
    root: Path, graphify_python: str, script_path: Path
) -> dict[Path, bytes]:
    hooks = _hooks_dir(root)
    return {
        hooks / "engineering-traceability-dispatcher": _dispatcher_text(
            root, graphify_python, script_path
        ).encode("utf-8"),
        **{
            hooks / event: _hook_wrapper(event).encode("utf-8")
            for event in HOOK_EVENTS
        },
    }


def _strip_native_graphify(content: str) -> str:
    for start, end in (
        ("# graphify-hook-start", "# graphify-hook-end"),
        ("# graphify-checkout-hook-start", "# graphify-checkout-hook-end"),
    ):
        content = re.sub(
            rf"{re.escape(start)}.*?{re.escape(end)}\s*",
            "",
            content,
            flags=re.DOTALL,
        )
    return content.rstrip() + "\n"


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _atomic_bytes(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def install_hooks(
    root: Path, graphify_python: str, script_path: Path
) -> dict:
    del root, graphify_python, script_path
    raise EngineeringError(
        "Direct hook mutation is disabled; use governed setup preview and approve-setup."
    )


def _install_hooks_authorized(
    root: Path,
    graphify_python: str,
    script_path: Path,
    approved_hook_state: list[dict],
) -> dict:
    verify_graphify(graphify_python)
    if _hook_plan_state(root) != approved_hook_state:
        raise EngineeringError("Engineering hook state changed before mutation.")
    hooks = _hooks_dir(root)
    preserved_dir = hooks / PRESERVED_HOOK_DIRECTORY
    round_one_preserved_dir = hooks / "engineering-preserved"
    preserved_manifest = hooks / PRESERVED_HOOK_MANIFEST
    dispatcher = hooks / "engineering-traceability-dispatcher"
    marker = b"# engineering-traceability-hook"
    managed_markers = (marker, b"# engineering-hook")
    expected_documents = _managed_hook_documents(root, graphify_python, script_path)
    approved = _approved_hook_records(approved_hook_state)

    def record(path: Path) -> dict | None:
        return approved.get(path.relative_to(hooks).as_posix())

    dispatcher_bytes = _approved_file_bytes(
        record(dispatcher), dispatcher.relative_to(hooks).as_posix()
    )
    legacy_script = (
        Path.home()
        / ".codex"
        / "skills"
        / "engineering-traceability"
        / "scripts"
        / "engineering_traceability.py"
    )
    known_dispatchers = {
        expected_documents[dispatcher],
        _dispatcher_text(root, graphify_python, legacy_script).encode("utf-8"),
    }
    if dispatcher_bytes is not None and dispatcher_bytes not in known_dispatchers:
            raise TraceabilityError(
                "Existing Engineering dispatcher does not match the exact managed content."
            )
    existing: dict[str, bytes | None] = {}
    for event in HOOK_EVENTS:
        path = hooks / event
        path_record = record(path)
        content = _approved_file_bytes(
            path_record, path.relative_to(hooks).as_posix()
        )
        if content is None:
            existing[event] = None
            continue
        if marker in content:
            if content != expected_documents[path]:
                raise TraceabilityError(
                    f"Existing managed hook does not match exact content: {event}"
                )
            existing[event] = None
        elif b"# engineering-hook" in content:
            if content != _round_one_hook_wrapper(event):
                raise TraceabilityError(
                    f"Existing legacy managed hook does not match exact content: {event}"
                )
            candidate = round_one_preserved_dir / event
            preserved = _approved_file_bytes(
                record(candidate), candidate.relative_to(hooks).as_posix()
            )
            if preserved is not None:
                existing[event] = (
                    None
                    if any(
                        managed_marker in preserved
                        for managed_marker in managed_markers
                    )
                    else _strip_native_graphify(
                        preserved.decode("utf-8")
                    ).encode("utf-8")
                )
            else:
                existing[event] = None
        else:
            try:
                existing[event] = _strip_native_graphify(
                    content.decode("utf-8")
                ).encode("utf-8")
            except UnicodeDecodeError as error:
                raise TraceabilityError(
                    f"Cannot safely preserve existing hook: {path}"
                ) from error
        if (
            existing[event]
            and record(preserved_dir / event) is not None
        ):
            raise TraceabilityError(
                f"Preserved hook already exists and would be overwritten: {event}"
            )
    desired_preserved = [
        dict(item)
        for item in approved_hook_state
        if item["path"].startswith(PRESERVED_HOOK_DIRECTORY + "/")
    ]
    outputs: dict[Path, tuple[bytes, int]] = {}
    for event, content in existing.items():
        if content and content.strip() not in {b"#!/bin/sh", b"#!/bin/bash"}:
            path = preserved_dir / event
            outputs[path] = (content, _managed_hook_mode())
            desired_preserved.append(
                {
                    "path": path.relative_to(hooks).as_posix(),
                    "exists": True,
                    "kind": "file",
                    "bytes_hex": content.hex(),
                    "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
                    "mode": _managed_hook_mode(),
                    "target": None,
                }
            )
    desired_preserved.sort(key=lambda item: item["path"])
    preserved_manifest_content = _preserved_hook_manifest_bytes(desired_preserved)
    outputs[preserved_manifest] = (preserved_manifest_content, _managed_hook_mode())
    for path, content in expected_documents.items():
        outputs[path] = (content, _managed_hook_mode())

    token = uuid.uuid4().hex
    stage_root = Path(tempfile.mkdtemp(prefix="engineering-hook-stage-"))
    replacements: list[tuple[Path, Path]] = []
    try:
        for index, (path, (content, mode)) in enumerate(outputs.items()):
            stage = stage_root / str(index)
            stage.write_bytes(content)
            stage.chmod(mode)
            replacements.append((stage, path))
        def verify_publication() -> None:
            for path, expected in expected_documents.items():
                if (
                    path.read_bytes() != expected
                    or stat.S_IMODE(path.stat().st_mode) != _managed_hook_mode()
                ):
                    raise TraceabilityError(
                        "Engineering hook publication verification failed: "
                        f"{path.name}"
                    )
            if (
                preserved_manifest.read_bytes() != preserved_manifest_content
                or stat.S_IMODE(preserved_manifest.stat().st_mode)
                != _managed_hook_mode()
                or _preserved_hook_state(root, PRESERVED_HOOK_DIRECTORY)
                != desired_preserved
            ):
                raise TraceabilityError(
                    "Engineering preserved-hook inventory publication verification "
                    "failed."
                )

        _transactional_replace(
            replacements,
            token,
            {path: _preimage_state(record(path)) for _, path in replacements},
            after_publication=verify_publication,
        )
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    return {
        "dispatcher": str(dispatcher),
        "events": list(HOOK_EVENTS),
        "preserved": sorted(
            event for event in HOOK_EVENTS if (preserved_dir / event).exists()
        ),
    }


def _expected_cli_blocker(error: EngineeringError) -> dict | None:
    text = str(error)
    if text.startswith(("Expected one commit-bound checkpoint", "Invalid checkpoint", "Checkpoint is not bound")):
        return {
            "schema": "engineering.error.v1",
            "status": "unavailable",
            "reason": "canonical_checkpoint_unavailable",
            "remediation": "recover_or_rebuild_the_exact_canonical_checkpoint_under_setup_authority",
        }
    routes = {
        "manifest_not_tracked": "authorize_engineering_setup",
        "Default branch identity is ambiguous.": "resolve_default_branch",
        "Graphify is missing from the selected Python interpreter.": "authorize_supported_graphify_setup",
        "graphify_adapter_incompatible": "select_supported_graphify",
    }
    remediation = routes.get(text)
    if remediation is None:
        return None
    return {
        "schema": "engineering.error.v1",
        "status": "blocked",
        "reason": text if text == "manifest_not_tracked" else re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_"),
        "remediation": remediation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="engineering")
    commands = parser.add_subparsers(dest="command", required=True)
    worker_parser = commands.add_parser("_graph-worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("root")
    worker_parser.add_argument("operation_id")
    setup_parser = commands.add_parser("setup")
    setup_parser.add_argument("root")
    setup_parser.add_argument("--graphify-python", default=sys.executable)
    approve_setup_parser = commands.add_parser("approve-setup")
    approve_setup_parser.add_argument("root")
    approve_setup_parser.add_argument("--graphify-python", default=sys.executable)
    approve_setup_parser.add_argument("--project-plan-digest", required=True)
    approve_setup_parser.add_argument("--graphify-plan-digest")
    approve_setup_parser.add_argument(
        "--scope",
        action="append",
        required=True,
        choices=("project_controls", "graphify_install"),
    )
    for name in ("bootstrap", "reconstruct"):
        command = commands.add_parser(name)
        command.add_argument("root")
        command.add_argument("--graphify-python", default=sys.executable)
    checkpoint_parser = commands.add_parser("checkpoint")
    checkpoint_parser.add_argument("root")
    checkpoint_parser.add_argument("--commit", required=True)
    checkpoint_parser.add_argument("--previous")
    for name in ("recover-checkpoint", "checkpoint-recover"):
        recovery_parser = commands.add_parser(name)
        recovery_parser.add_argument("root")
        recovery_parser.add_argument("--commit", required=True)
        recovery_parser.add_argument("--graphify-python", default=sys.executable)
    rebuild_parser = commands.add_parser("rebuild")
    rebuild_parser.add_argument("root")
    rebuild_parser.add_argument("--commit", required=True)
    rebuild_parser.add_argument("--graphify-python", default=sys.executable)
    map_parser = commands.add_parser("map")
    map_parser.add_argument("root", nargs="?", default=".")
    map_parser.add_argument("--no-open", action="store_true")
    map_parser.add_argument("--focus")
    for name in ("traceability", "traceability-view"):
        traceability_view_parser = commands.add_parser(name)
        traceability_view_parser.add_argument("root", nargs="?", default=".")
        traceability_view_parser.add_argument("--focus")
        traceability_view_parser.add_argument("--commit")
        traceability_view_parser.add_argument("--as-of")
        traceability_view_parser.add_argument("--html", action="store_true")
    retrospective_parser = commands.add_parser("retrospect")
    retrospective_parser.add_argument("root", nargs="?", default=".")
    retrospective_parser.add_argument("--scope", action="append")
    retrospective_parser.add_argument("--llm-reconcile", action="store_true")
    retrospective_parser.add_argument("--preview-digest")
    ci_parser = commands.add_parser("ci-gate")
    ci_parser.add_argument("root")
    hook_parser = commands.add_parser("hook")
    hook_parser.add_argument("event", choices=HOOK_EVENTS)
    hook_parser.add_argument("root")
    hook_parser.add_argument("--graphify-python", default=sys.executable)
    install_parser = commands.add_parser("install-hooks")
    install_parser.add_argument("root")
    install_parser.add_argument("--graphify-python", default=sys.executable)
    for name in ("status", "coverage"):
        command = commands.add_parser(name)
        command.add_argument("root")
        command.add_argument("--commit")
    for name in ("trace", "impact", "why-code", "why-test"):
        command = commands.add_parser(name)
        command.add_argument("root")
        command.add_argument("identifier")
        command.add_argument("--commit")
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("root")
    compare_parser.add_argument("commit_a")
    compare_parser.add_argument("commit_b")
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("root")
    prepare_parser.add_argument("intent")
    prepare_scope = prepare_parser.add_mutually_exclusive_group(required=True)
    prepare_scope.add_argument("--scope-json")
    prepare_scope.add_argument("--scope-file")
    prepare_parser.add_argument("--override", choices=sorted(AUTONOMY_LEVELS))
    complete_parser = commands.add_parser("complete")
    complete_parser.add_argument("root")
    complete_parser.add_argument("run_id")
    complete_parser.add_argument("--result-scope", action="append")
    approve_checks_parser = commands.add_parser("approve-checks")
    approve_checks_parser.add_argument("root")
    approve_checks_parser.add_argument("--allow-inline-code", action="store_true")
    approve_scope_parser = commands.add_parser("approve-scope")
    approve_scope_parser.add_argument("root")
    approve_scope_parser.add_argument("--decision-id", required=True)
    approve_scope_parser.add_argument("--handoff-file", required=True)
    approve_scope_parser.add_argument("--owner-intent-id")
    intent_bind_parser = commands.add_parser("intent-bind")
    intent_bind_parser.add_argument("root")
    intent_bind_parser.add_argument("--binding-file", required=True)
    intent_bind_parser.add_argument("--approval-file", required=True)
    intent_status_parser = commands.add_parser("intent-status")
    intent_status_parser.add_argument("root")
    intent_status_parser.add_argument("--authority-id")
    intent_import_parser = commands.add_parser("intent-import")
    intent_import_parser.add_argument("root")
    intent_import_parser.add_argument("--import-file", required=True)
    intent_import_parser.add_argument("--approval-file", required=True)
    dependent_dispatch_parser = commands.add_parser("dependent-dispatch-status")
    dependent_dispatch_parser.add_argument("root")
    dependent_dispatch_parser.add_argument(
        "--scope", choices=sorted(POST_ACTIVATION_IMPORT_SCOPES), required=True
    )
    bootstrap_handoff_parser = commands.add_parser("bootstrap-handoff-status")
    bootstrap_handoff_parser.add_argument("source")
    bootstrap_handoff_parser.add_argument("--home", required=True)
    outcome_accept_parser = commands.add_parser("outcome-accept")
    outcome_accept_parser.add_argument("root")
    outcome_accept_parser.add_argument("completion_id")
    outcome_accept_parser.add_argument("--input-file", required=True)
    release_gate_parser = commands.add_parser("release-gate")
    release_gate_parser.add_argument("root")
    release_gate_parser.add_argument("completion_id")
    release_gate_parser.add_argument("--acceptance-id", required=True)
    release_gate_parser.add_argument("--install-source")
    verify_release_token_parser = commands.add_parser("verify-release-token")
    verify_release_token_parser.add_argument("root")
    verify_release_token_parser.add_argument("token_id")
    verify_release_token_parser.add_argument("artifact_digest")
    verify_release_token_parser.add_argument(
        "--action", choices=sorted(RELEASE_TOKEN_ACTIONS), required=True
    )
    assurance_parser = commands.add_parser("assurance-status")
    assurance_parser.add_argument("root")
    assurance_parser.add_argument("capability_id")
    assurance_parser.add_argument("cell_id")
    assurance_parser.add_argument("--as-of")
    autonomy_parser = commands.add_parser("autonomy")
    autonomy_parser.add_argument("level", choices=sorted(AUTONOMY_LEVELS))
    autonomy_parser.add_argument("root", nargs="?", default=".")
    maintain_parser = commands.add_parser("maintain")
    maintain_parser.add_argument("target")
    maintain_parser.add_argument("root", nargs="?")
    maintain_parser.add_argument("--area")
    orphan_status_parser = commands.add_parser("orphan-status")
    orphan_status_parser.add_argument("root")
    orphan_reap_parser = commands.add_parser("orphan-reap")
    orphan_reap_parser.add_argument("root")
    orphan_reap_parser.add_argument("operation_id")
    orphan_reap_parser.add_argument("--timeout-seconds", type=float, default=5.0)
    learning_propose = commands.add_parser("learning-propose")
    learning_propose.add_argument("root")
    learning_propose.add_argument("completion_id")
    learning_propose.add_argument("kind", choices=sorted(CONTRIBUTION_KINDS))
    learning_propose.add_argument("--practice-json", required=True)
    learning_evaluate = commands.add_parser("learning-evaluate")
    learning_evaluate.add_argument("candidate_id")
    learning_evaluate.add_argument("root")
    learning_evaluate.add_argument("completion_id")
    learning_keep = commands.add_parser("learning-keep")
    learning_keep.add_argument("candidate_id")
    commands.add_parser("learning-status")
    learning_inspect = commands.add_parser("learning-inspect")
    learning_inspect.add_argument("candidate_id")
    learning_dismiss = commands.add_parser("learning-dismiss")
    learning_dismiss.add_argument("candidate_id")
    learning_dismiss.add_argument("--confirm", required=True)
    learning_apply = commands.add_parser("learning-promote-apply")
    learning_apply.add_argument("candidate_id")
    learning_apply.add_argument("--evaluation-id", action="append", required=True)
    learning_apply.add_argument("--confirm", required=True)
    learning_disable = commands.add_parser("learning-disable")
    learning_disable.add_argument("candidate_id")
    learning_disable.add_argument("--confirm", required=True)
    learning_source = commands.add_parser("learning-source-proposal")
    learning_source.add_argument("candidate_id")
    delivery_eval = commands.add_parser("delivery-eval")
    delivery_eval.add_argument("root")
    delivery_eval.add_argument("completion_id")
    delivery_eval.add_argument("--input-file", required=True)
    delivery_trends_parser = commands.add_parser("delivery-trends")
    delivery_trends_parser.add_argument("--window", type=int, default=30)
    arguments = parser.parse_args()
    try:
        if arguments.command == "_graph-worker":
            return _graph_worker_entry(
                Path(arguments.root), arguments.operation_id
            )
        if arguments.command == "learning-status":
            result = learning_status()
        elif arguments.command in {"learning-keep", "learning-inspect"}:
            result = inspect_learning(arguments.candidate_id)
        elif arguments.command == "learning-dismiss":
            result = dismiss_learning(
                arguments.candidate_id,
                arguments.confirm == f"dismiss {arguments.candidate_id}",
            )
        elif arguments.command == "learning-promote-apply":
            result = promote_and_apply(
                arguments.candidate_id,
                arguments.evaluation_id,
                arguments.confirm == f"Promote and apply {arguments.candidate_id}",
            )
        elif arguments.command == "learning-disable":
            result = disable_applied_practice(
                arguments.candidate_id,
                arguments.confirm == f"disable {arguments.candidate_id}",
            )
        elif arguments.command == "learning-source-proposal":
            result = source_improvement_proposal(arguments.candidate_id)
        elif arguments.command == "learning-propose":
            try:
                practice = json.loads(arguments.practice_json)
            except json.JSONDecodeError as error:
                raise EngineeringError("Engineering learning practice JSON is invalid.") from error
            result = propose_learning(
                Path(arguments.root), arguments.completion_id, arguments.kind, practice
            )
        elif arguments.command == "learning-evaluate":
            result = evaluate_learning(
                arguments.candidate_id, Path(arguments.root), arguments.completion_id
            )
        elif arguments.command == "maintain":
            if arguments.target == "status":
                if arguments.area is not None:
                    raise EngineeringError("Maintenance status does not accept --area.")
                root = resolve_project_root(arguments.root or ".")
                result = maintenance_status(root)
            else:
                if arguments.root is not None:
                    raise EngineeringError("Maintenance accepts exactly one project root.")
                root = resolve_project_root(arguments.target)
                result = run_maintenance(root, arguments.area)
        elif arguments.command == "orphan-status":
            root = resolve_project_root(arguments.root)
            result = orphan_operation_status(root)
        elif arguments.command == "orphan-reap":
            root = resolve_project_root(arguments.root)
            result = reap_orphan_operation(
                root,
                arguments.operation_id,
                timeout_seconds=arguments.timeout_seconds,
            )
        elif arguments.command in {"map", "traceability", "traceability-view", "prepare", "setup", "retrospect"}:
            advisory = pre_repository_advisory(arguments.root)
            if advisory is not None:
                if arguments.command == "map":
                    result = {
                        "schema": "engineering.map.v1",
                        "status": "unavailable",
                        "reason": "canonical_map_unavailable_until_local_version_control_exists",
                        "advisory": advisory,
                    }
                elif arguments.command in {"traceability", "traceability-view"}:
                    result = {
                        "schema": TRACEABILITY_VIEW_SCHEMA,
                        "status": "unavailable",
                        "reason": "canonical_checkpoint_unavailable_until_local_version_control_exists",
                        "advisory": advisory,
                    }
                elif arguments.command == "prepare":
                    result = {
                        "schema": "engineering.prepare.v1",
                        "readiness": "advisory",
                        "project": advisory,
                        "context": [],
                        "blockers": [],
                    }
                elif arguments.command == "retrospect":
                    result = {
                        "schema": "engineering.retrospective.v1",
                        "state": "advisory",
                        "read_only": True,
                        "finite_universe": [],
                        "findings": [{"classification": "unknown", "reason": "not_version_controlled"}],
                        "remediation": [{"action": "initialize_local_git_and_adopt_engineering", "requires_authority": True}],
                        "llm_reconciliation": {"status": "not_available_in_controller"},
                    }
                else:
                    result = pre_repository_setup_preview(advisory)
                print(json.dumps(result))
                return 1 if arguments.command == "setup" else 0
            root = resolve_project_root(arguments.root)
        elif arguments.command not in {
            "delivery-trends",
            "bootstrap-handoff-status",
        } and not arguments.command.startswith("learning-"):
            root = resolve_project_root(arguments.root)
        if arguments.command.startswith("learning-"):
            print(json.dumps(result))
            return 0
        if arguments.command == "bootstrap-handoff-status":
            result = v226_bootstrap_handoff_status(
                Path(arguments.source), Path(arguments.home)
            )
        elif arguments.command == "delivery-trends":
            result = delivery_trends(arguments.window)
        elif arguments.command == "delivery-eval":
            try:
                source = sys.stdin.read() if arguments.input_file == "-" else Path(arguments.input_file).read_text(encoding="utf-8")
                if len(source.encode("utf-8")) > 64 * 1024:
                    raise ValueError
                value = json.loads(source)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                raise EngineeringError("Engineering delivery evaluation input is invalid.") from error
            result = record_delivery_evaluation(root, arguments.completion_id, value)
        elif arguments.command == "autonomy":
            result = set_autonomy(root, arguments.level)
        elif arguments.command == "setup":
            result = setup(root, arguments.graphify_python)
            if result["readiness"] == "proposal":
                print(json.dumps(result))
                return 1
        elif arguments.command == "approve-setup":
            result = approve_setup(
                root,
                arguments.graphify_python,
                arguments.project_plan_digest,
                scopes=arguments.scope,
                graphify_plan_digest=arguments.graphify_plan_digest,
            )
        elif arguments.command == "approve-checks":
            result = approve_checks(root, allow_inline_code=arguments.allow_inline_code)
        elif arguments.command == "approve-scope":
            try:
                source = (
                    sys.stdin.read()
                    if arguments.handoff_file == "-"
                    else Path(arguments.handoff_file).read_text(encoding="utf-8")
                )
                if len(source.encode("utf-8")) > 64 * 1024:
                    raise ValueError
                handoff = json.loads(source)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                raise EngineeringError("Engineering scope handoff JSON is invalid.") from error
            result = approve_scope_handoff(
                root,
                arguments.decision_id,
                handoff,
                owner_intent_id=arguments.owner_intent_id,
            )
        elif arguments.command == "intent-bind":
            try:
                binding_source = (
                    sys.stdin.read()
                    if arguments.binding_file == "-"
                    else Path(arguments.binding_file).read_text(encoding="utf-8")
                )
                approval_source = (
                    sys.stdin.read()
                    if arguments.approval_file == "-"
                    else Path(arguments.approval_file).read_text(encoding="utf-8")
                )
                if (
                    len(binding_source.encode("utf-8")) > 64 * 1024
                    or len(approval_source.encode("utf-8")) > 64 * 1024
                ):
                    raise ValueError
                binding = json.loads(binding_source)
                approval = json.loads(approval_source)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                raise EngineeringError("Engineering owner intent input is invalid.") from error
            result = bind_owner_intent(root, binding, approval)
        elif arguments.command == "intent-status":
            result = owner_intent_status(root, arguments.authority_id)
        elif arguments.command == "intent-import":
            try:
                if arguments.import_file == "-" and arguments.approval_file == "-":
                    raise ValueError
                imported_source = (
                    sys.stdin.read()
                    if arguments.import_file == "-"
                    else Path(arguments.import_file).read_text(encoding="utf-8")
                )
                approval_source = (
                    sys.stdin.read()
                    if arguments.approval_file == "-"
                    else Path(arguments.approval_file).read_text(encoding="utf-8")
                )
                if (
                    len(imported_source.encode("utf-8")) > 64 * 1024
                    or len(approval_source.encode("utf-8")) > 64 * 1024
                ):
                    raise ValueError
                imported = json.loads(imported_source)
                approval = json.loads(approval_source)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                raise EngineeringError(
                    "Engineering owner intent import input is invalid."
                ) from error
            result = import_owner_intent(root, imported, approval)
        elif arguments.command == "dependent-dispatch-status":
            result = dependent_dispatch_status(root, arguments.scope)
        elif arguments.command == "outcome-accept":
            try:
                source = (
                    sys.stdin.read()
                    if arguments.input_file == "-"
                    else Path(arguments.input_file).read_text(encoding="utf-8")
                )
                if len(source.encode("utf-8")) > 64 * 1024:
                    raise ValueError
                acceptance = json.loads(source)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                raise EngineeringError("Engineering outcome acceptance input is invalid.") from error
            result = record_outcome_acceptance(root, arguments.completion_id, acceptance)
        elif arguments.command == "release-gate":
            release_kwargs = (
                {"install_source": Path(arguments.install_source)}
                if arguments.install_source is not None
                else {}
            )
            result = release_gate(
                root,
                arguments.completion_id,
                arguments.acceptance_id,
                **release_kwargs,
            )
        elif arguments.command == "verify-release-token":
            result = verify_release_token(
                root,
                arguments.token_id,
                arguments.artifact_digest,
                arguments.action,
            )
        elif arguments.command == "assurance-status":
            result = assurance_status(root, arguments.capability_id, arguments.cell_id, arguments.as_of)
        elif arguments.command == "complete":
            result = complete(
                root,
                arguments.run_id,
                [],
                result_scope=arguments.result_scope,
            )
        elif arguments.command == "prepare":
            try:
                if arguments.scope_file is not None:
                    source = sys.stdin.read() if arguments.scope_file == "-" else Path(arguments.scope_file).read_text(encoding="utf-8")
                else:
                    source = arguments.scope_json
                if not isinstance(source, str) or len(source.encode("utf-8")) > 64 * 1024:
                    raise ValueError
                scope = json.loads(source)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise EngineeringError("Preparation scope JSON is invalid.") from error
            result = prepare(root, arguments.intent, scope, arguments.override)
            if result["readiness"] == "blocked":
                print(json.dumps(result))
                return 1
        elif arguments.command in {"bootstrap", "reconstruct"}:
            result = legacy_setup_forwarder(
                root, arguments.graphify_python, arguments.command
            )
            if result["readiness"] == "proposal":
                print(json.dumps(result))
                return 1
        elif arguments.command == "checkpoint":
            path = construct_checkpoint(root, arguments.commit, arguments.previous)
            result = {"checkpoint": str(path)}
        elif arguments.command in {"recover-checkpoint", "checkpoint-recover"}:
            result = recover_checkpoint(root, arguments.commit, arguments.graphify_python)
        elif arguments.command == "rebuild":
            path = rebuild(root, arguments.commit, arguments.graphify_python)
            result = {"checkpoint": str(path)}
        elif arguments.command == "map":
            result = render_map(
                root, open_output=not arguments.no_open, focus=arguments.focus
            )
        elif arguments.command in {"traceability", "traceability-view"}:
            result = traceability_view(
                root,
                as_of=arguments.as_of,
                focus=arguments.focus,
                commit=arguments.commit,
            )
            if arguments.html:
                result = {"view": result, "html": write_traceability_view_html(root, result)}
        elif arguments.command == "retrospect":
            if arguments.preview_digest is None:
                result = retrospective_preview(
                    root, scope=arguments.scope, llm_reconcile=arguments.llm_reconcile
                )
            else:
                result = retrospective(
                    root,
                    scope=arguments.scope,
                    llm_reconcile=arguments.llm_reconcile,
                    preview_digest=arguments.preview_digest,
                )
        elif arguments.command == "hook":
            result = handle_hook(
                arguments.event, root, arguments.graphify_python
            )
            if result.get("freshness") == "stale":
                print(
                    "Engineering: checkpoint pending "
                    f"({result.get('reason', 'unknown')}); run a foreground rebuild when ready.",
                    file=sys.stderr,
                )
            return 0
        elif arguments.command == "install-hooks":
            result = legacy_setup_forwarder(
                root, arguments.graphify_python, arguments.command
            )
            if result["readiness"] == "proposal":
                print(json.dumps(result))
                return 1
        elif arguments.command == "ci-gate":
            result = check_merge_readiness(root)
            if not result["ready"]:
                print(json.dumps(result))
                return 1
        elif arguments.command == "compare":
            result = compare_checkpoints(
                _load_checkpoint(root, git(root, "rev-parse", arguments.commit_a)),
                _load_checkpoint(root, git(root, "rev-parse", arguments.commit_b)),
            )
        elif arguments.command not in {"maintain", "orphan-status", "orphan-reap"}:
            commit = git(root, "rev-parse", arguments.commit or "HEAD")
            checkpoint = _load_checkpoint(root, commit)
            if arguments.command == "status":
                config_path, links_path, _, _ = _project_paths(root)
                manifest = _json_at(root, commit, config_path)
                links = _json_at(root, commit, links_path)
                _, _, integrity = _validate_overlay(root, commit, manifest, links)
                result = {
                    "project": checkpoint["metadata"]["project"],
                    "branch": checkpoint["metadata"]["branch"],
                    "commit": commit,
                    "checkpoint_kind": checkpoint["metadata"]["kind"],
                    "fresh": integrity["input_digest"] == checkpoint["metadata"]["input_digest"],
                    "integrity": checkpoint["integrity"],
                }
            else:
                result = query_result(
                    arguments.command, checkpoint, getattr(arguments, "identifier", None)
                )
    except (OSError, subprocess.SubprocessError, TraceabilityError, ValueError) as error:
        if isinstance(error, EngineeringError):
            payload = _expected_cli_blocker(error)
            if payload is not None:
                print(json.dumps(payload))
                return 2
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
