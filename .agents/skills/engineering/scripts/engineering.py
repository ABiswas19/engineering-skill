#!/usr/bin/env python3
"""Run project-scoped Engineering controls."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import quote


GRAPHIFY_REPOSITORY = "https://github.com/safishamsi/graphify"
GRAPHIFY_TAG = "v0.9.5"
GRAPHIFY_VERSION = "0.9.5"
GRAPHIFY_COMMIT = "d89ec68af95e0cad801b56d88df383991e659823"
REQUIRED_GRAPHIFY_COMMANDS = ("update", "query", "path", "explain")
CLEANUP_TERMINATION_GRACE_SECONDS = 0.25
ORPHAN_MINIMUM_AGE_SECONDS = 30.0
DEFAULT_CONTEXT_TOKEN_BUDGET = 1000
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
    "plan_task",
    "contract",
    "code_symbol",
    "test",
    "evaluation",
    "verification_receipt",
    "commit",
    "pull_request",
    "project",
    "checkpoint",
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
}
PREPARATION_ADVISORIES = {
    "remote_freshness_unknown": "canonical remote freshness is unknown",
    "historical_gap_before_baseline_acceptance": (
        "historical gaps remain before baseline acceptance"
    ),
    "unrelated_maintenance": "unrelated maintenance is queued",
}


class EngineeringError(Exception):
    pass


TraceabilityError = EngineeringError


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


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 15,
) -> str:
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout, env=env
    )
    if result.returncode:
        raise TraceabilityError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def git(root: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return run(["git", "-C", str(root), *arguments], env=environment)


def _identity_git(root: Path, *arguments: str) -> str:
    """Run Git for trust decisions without caller-controlled Git state."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
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
    _reject_reparse_ancestors(supplied)
    interpreter = supplied.resolve()
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
    except TraceabilityError as error:
        raise TraceabilityError("Default branch identity is ambiguous.") from error
    return branch.removeprefix("origin/")


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
        existing = [path for path in scaffold_payload if path.exists()]
        if existing:
            raise EngineeringError(
                "Refusing partial Engineering setup: "
                + ", ".join(str(path.relative_to(root)) for path in existing)
            )
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
        "project_plan": project_plan,
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


def setup(root: Path, graphify_python: str) -> dict:
    project_root = resolve_project_root(str(root))
    result, claims = _setup_preview(project_root, graphify_python)
    if not result["approvals_required"]:
        return result
    if _matching_setup_attestation(project_root, claims) is None:
        return result

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
        **result,
        "readiness": "applied",
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
    preview, _ = _setup_preview(resolve_project_root(str(root)), graphify_python)
    return {
        **preview,
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
        path, line = _source(node, identifier)
        input_paths.add(path)
        sources.append((identifier, path, line))
        identifiers.add(identifier)
        node_ids.add(identifier)

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
    if final_dir.exists():
        if (
            not destination.is_file()
            or not validate_checkpoint(root, destination, commit)["valid"]
        ):
            raise TraceabilityError(
                f"Immutable checkpoint directory is incomplete: {final_dir}"
            )
        return destination

    final_dir.parent.mkdir(parents=True, exist_ok=True)
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
        environment = os.environ.copy()
        environment["GRAPHIFY_OUT"] = str(stage)
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
    return [
        path
        for path in changed
        if path in controls
        or path.startswith(control_prefix)
        or Path(path).suffix.lower() not in set(code_extensions)
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


def _terminate_process_tree(
    process: subprocess.Popen, pgid: int | None = None
) -> bool:
    if os.name == "nt":
        if process.poll() is not None:
            return False
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
        return process.poll() is not None
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
    if "worker_pid" not in record or record.get("worker_process_tree_dead") is True:
        return record
    worker_pid = record.get("worker_pid")
    pgid = record.get("worker_pgid")
    killpg = getattr(os, "killpg", None)
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
        if _process_alive(cleanup_pid):
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
        and _process_alive(record.get("owner_pid"))
        and not record.get("worker_process_tree_dead")
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
    if owner is not None and (
        owner.get("operation_id") != operation_id
        or owner.get("lock_token") != record.get("lock_token")
        or (
            _process_alive(owner.get("owner_pid"))
            and not record.get("worker_process_tree_dead")
        )
    ):
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
            return _orphan_cleanup_result(
                project_root,
                operation_id,
                record,
                "repository_lock_owner_mismatch",
                started,
            )
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
        if lock.exists():
            owner_path = lock / "owner.json"
            if owner_path.exists():
                paths = trusted_paths()
                if paths is None:
                    return invalid_boundary()
                (paths["repository_lock_path"] / "owner.json").unlink()
            paths = trusted_paths()
            if paths is None:
                return invalid_boundary()
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
            _process_alive(
                owner.get("owner_pid") if owner is not None else record.get("owner_pid")
            )
            and not record.get("worker_process_tree_dead")
        ):
            live.append(child.name)
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
    try:
        environment_before = os.environ.get("GRAPHIFY_OUT")
        os.environ["GRAPHIFY_OUT"] = str(stage)
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
        cwd_before = Path.cwd()
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
                run(list(command), env=os.environ.copy(), timeout=600)
        finally:
            os.chdir(cwd_before)
            if environment_before is None:
                os.environ.pop("GRAPHIFY_OUT", None)
            else:
                os.environ["GRAPHIFY_OUT"] = environment_before
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
                },
                indent=2,
            )
            + "\n",
        )
        return 0
    except Exception as error:
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
                }
            )
            + "\n",
        )
        return 1


def _start_worker(command: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=(os.name != "nt"),
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
                or owner.get("lock_token")
                != unresolved_record.get("lock_token")
                or (
                    _process_alive(owner.get("owner_pid"))
                    and not unresolved_record.get("worker_process_tree_dead")
                )
            ):
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
        )
        _write_operation(record)
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
        }
    )
    if worker_pgid is not None:
        record["worker_pgid"] = worker_pgid
    else:
        record.pop("worker_pgid", None)
    _write_operation(record)
    _atomic_text(
        Path(record["repository_lock_path"]) / "owner.json",
        json.dumps(
            {
                "operation_id": record["operation_id"],
                "lock_token": record["lock_token"],
                "owner_pid": process.pid,
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
    root: Path, *, refresh_remote: bool
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
    graphify_python: str = sys.executable,
    hook_budget_seconds: float | None = None,
) -> dict:
    project_root = resolve_project_root(str(root))
    authority = _canonical_authority_details(
        project_root, refresh_remote=refresh_remote
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
            in {"current", "not_configured"},
            "authority_revalidated_before_publication": (
                result.get("freshness") in {"current", "not_configured"}
            ),
        }
    )
    return result


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
    environment = os.environ.copy()
    output = _common_graph_dir(project_root) / "maintenance"
    environment["GRAPHIFY_OUT"] = str(output)
    run(
        [
            str(Path(graphify_python).expanduser().resolve()),
            "-m",
            "graphify",
            "update",
            str(project_root),
        ],
        env=environment,
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


def coverage(checkpoint: dict) -> list[dict]:
    nodes = {node["id"]: node for node in checkpoint["nodes"]}
    design_types = {"decision", "specification", "plan_task", "contract"}
    verification_types = {"test", "evaluation", "verification_receipt"}
    result = []
    for requirement in sorted(
        (node for node in checkpoint["nodes"] if node["type"] == "requirement"),
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


def _contains_credential(value: str) -> bool:
    return _redact_credentials(value) != value


def _scope_envelope(scope: dict) -> dict[str, object]:
    if not isinstance(scope, dict):
        raise EngineeringError("Preparation scope must be an object.")
    result: dict[str, list[str]] = {}
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
    result["deterministic_only_approved"] = deterministic_only
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
        if nodes[identifier].get("type") in {"requirement", "decision"}
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
    try:
        verify_graphify(sys.executable)
    except EngineeringError:
        return {"status": "unavailable", "context": [], "reason": "graphify_unavailable"}
    environment = os.environ.copy()
    environment["GRAPHIFY_OUT"] = str(checkpoint_path.parent)
    environment["GRAPHIFY_QUERY_LOG_DISABLE"] = "1"
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "graphify",
                "query",
                intent,
                "--budget",
                str(token_budget),
                "--graph",
                str(graph_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "context": [], "reason": "query_timeout"}
    except (OSError, subprocess.SubprocessError):
        return {"status": "unavailable", "context": [], "reason": "query_unavailable"}
    if result.returncode:
        return {"status": "unavailable", "context": [], "reason": "query_failed"}
    output = result.stdout.strip()
    if output == "No matching nodes found.":
        return {"status": "empty", "context": []}
    lines = output.splitlines()
    header = re.fullmatch(
        r"Traversal: (?:BFS|DFS) depth=\d+ \| Start: .* \| (\d+) nodes found",
        lines[0] if lines else "",
    )
    if not header:
        return {"status": "invalid", "context": [], "reason": "invalid_query_output"}
    labels: dict[str, list[str]] = {}
    for node in graph["nodes"]:
        identifier = node["id"]
        labels.setdefault(str(node.get("label", identifier)), []).append(identifier)
    selected, used, seen = [], 0, set()
    for line in lines[1:]:
        if not line:
            continue
        node_match = re.fullmatch(r"NODE (.+) \[src=.* loc=.* community=.*\]", line)
        if node_match:
            matches = sorted(labels.get(node_match.group(1), []))
            if not matches:
                return {"status": "invalid", "context": [], "reason": "unknown_query_id"}
            for identifier in matches:
                if _contains_credential(identifier):
                    return {
                        "status": "invalid",
                        "context": [],
                        "reason": "credential_query_id",
                    }
                cost = max(1, (len(identifier) + 3) // 4)
                if identifier not in seen and used + cost <= token_budget:
                    selected.append(
                        {
                            "id": identifier,
                            "provenance": "inferred" if len(matches) == 1 else "ambiguous",
                        }
                    )
                    seen.add(identifier)
                    used += cost
            continue
        if line.startswith("EDGE ") and "-->" in line:
            continue
        if line.startswith("... (truncated"):
            continue
        return {"status": "invalid", "context": [], "reason": "invalid_query_output"}
    if int(header.group(1)) and not selected:
        return {"status": "invalid", "context": [], "reason": "invalid_query_output"}
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


def _dirty_paths(root: Path) -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "-z", "--untracked-files=all"],
        capture_output=True,
        check=True,
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


def _contract_change_approved(scope: dict) -> bool:
    return scope.get("contract_change_approved") is True


def prepare(
    root: Path, intent: str, scope: dict, override: str | None = None
) -> dict:
    project = resolve_project(Path(root))
    bounded_intent = _bounded_intent(intent)
    authorization = _scope_envelope(scope)
    config = load_project_config(project.root)
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
        blocker_codes.append("missing_current_checkpoint")

    nodes = {node["id"]: node for node in checkpoint["nodes"]}
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
    deterministic_only = authorization["deterministic_only_approved"]
    if query_outcome["status"] in {"unavailable", "invalid"} and not deterministic_only:
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
    if contract_impact and not _contract_change_approved(scope):
        blocker_codes.append("unapproved_contract_change")
    if any(
        re.search(rf"\b{re.escape(action)}\b", bounded_intent, re.IGNORECASE)
        for action in authorization["forbidden"]
    ):
        blocker_codes.append("conflicting_authority")
    if required_checks:
        try:
            _require_attestation(
                _project_controller_dir(project.root),
                "check_capability",
                _check_capability_claims(project.root, required_checks),
            )
        except EngineeringError:
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
            not item["safe"] and item["artifact"] in authorization["scope"]
            for item in maintenance["items"]
        ):
            blocker_codes.append("conflicting_authority")

    blocker_codes = list(dict.fromkeys(blocker_codes))
    advisory_codes = list(dict.fromkeys(advisory_codes))
    applied_practices, practice_status = _practice_projection("preparation")
    completion_practices, completion_practice_status = _practice_projection("completion")
    result = {
        "schema": "engineering.prepare.v1",
        "run_id": "",
        "project": {
            "root_digest": f"sha256:{checkpoint_identity(project.root, project.commit)}",
            "branch": project.branch,
            "commit": project.commit,
        },
        "intent": bounded_intent,
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
    }
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
    return {
        "repository_id": _project_contribution_digest(root),
        "commands_digest": _json_digest(identities),
        "inline_code": inline_code,
        "allow_inline_code": inline_code,
    }


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
    current.update(phase="orphaned", worker_process_tree_dead=True)
    _write_operation(current)
    result = cleanup_hook_operation(root, current["operation_id"], timeout_seconds=10)
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


def _completion_payload(
    preparation: dict,
    changed: list[str],
    result_identity: dict,
    checkpoint_status: dict,
    dirty: bool,
    checks: list[dict],
    maintenance_ids: list[str],
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
    return payload


def complete(root: Path, run_id: str, receipts: list[dict]) -> dict:
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
        checkpoint_status = check_merge_readiness(project.root)
        if not dirty and not checkpoint_status["ready"]:
            raise EngineeringError("Engineering feature checkpoint refresh failed.")
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
            expected = _completion_payload(
                preparation,
                changed,
                result_identity,
                checkpoint_status,
                dirty,
                retained["checks"],
                maintenance_ids,
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

        required = preparation["required_checks"]
        if discover_checks(project.root) != required:
            raise EngineeringError("Engineering project check capability changed after preparation.")
        if required:
            _require_attestation(
                _project_controller_dir(project.root),
                "check_capability",
                _check_capability_claims(project.root, required),
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
    home = Path(configured).expanduser() if configured else Path.home()
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
    [bool]$enforce,
    [bool]$directory
)
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
if ($enforce) {
    $acl = Get-Acl -LiteralPath $path
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
    $acl.SetOwner($sid)
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $path -AclObject $acl
}
$verified = Get-Acl -LiteralPath $path
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
@{
    protected = $verified.AreAccessRulesProtected
    owner_sid = $ownerSid
    current_sid = $sid.Value
    access = $entries
} | ConvertTo-Json -Compress -Depth 4
}
""".strip()


def _windows_owner_private(path: Path, *, enforce: bool) -> None:
    directory = path.is_dir()
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _WINDOWS_PRIVATE_ACL,
            str(path),
            "$true" if enforce else "$false",
            "$true" if directory else "$false",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise EngineeringError("Engineering controller owner-private ACL verification failed.") from error
    current_sid = payload.get("current_sid")
    access = payload.get("access")
    if (
        result.returncode != 0
        or payload.get("protected") is not True
        or payload.get("owner_sid") != payload.get("current_sid")
        or not isinstance(access, list)
        or not access
        or any(
            not isinstance(item, dict)
            or item.get("sid") != current_sid
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


def _private_atomic_bytes(path: Path, content: bytes) -> None:
    _reject_reparse_ancestors(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _enforce_owner_private(path.parent)
    _reject_reparse_ancestors(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        _enforce_owner_private(temporary)
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
            not in {"check_capability", "completion", "promotion", "setup"}
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
    source = Path(source).expanduser()
    _reject_reparse_ancestors(source)
    source = source.resolve()
    if not source.is_dir() or _is_reparse_point(source):
        raise EngineeringError("Engineering bundle source is missing or is a link/reparse point.")
    for path in source.rglob("*"):
        if _is_reparse_point(path):
            raise EngineeringError("Engineering bundle contains a link/reparse point.")
    required = {
        Path("SKILL.md"),
        Path("manifest.json"),
        Path("scripts/engineering.py"),
        Path("references/controller-contract.md"),
    }
    try:
        repository = Path(git(source, "rev-parse", "--show-toplevel")).resolve()
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
        relative = Path(tracked_path.removeprefix(prefix))
        candidate = source / relative
        if not candidate.is_file() or _is_reparse_point(candidate):
            raise EngineeringError("Engineering bundle source closure is invalid.")
        files.append(relative)
    if not required <= set(files) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise EngineeringError("Engineering bundle source closure is invalid.")
    try:
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
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
    skill = (source / "SKILL.md").read_text(encoding="utf-8")
    if "name: engineering" not in skill:
        raise EngineeringError("Engineering canonical skill metadata is invalid.")
    digest = hashlib.sha256()
    for relative in sorted(files, key=lambda value: value.as_posix()):
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        digest.update((source / relative).read_bytes() + b"\0")
    return files, manifest, commit, "sha256:" + digest.hexdigest()


def _copy_bundle(source: Path, target: Path, files: list[Path]) -> None:
    target.mkdir(parents=True)
    for relative in files:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)


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
        if candidate.is_file():
            relative = candidate.relative_to(path).as_posix()
            digest.update(relative.encode("utf-8") + b"\0")
            digest.update(candidate.read_bytes() + b"\0")
    return "sha256:" + digest.hexdigest()


def _remove_install_path(path: Path) -> None:
    if not path.exists():
        return
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
        "receipt": home / ".agents" / "engineering" / "install-receipt.json",
        "previous_receipt": home / ".agents" / "engineering" / "previous-install-receipt.json",
        "lock": home / ".agents" / "engineering" / "install.lock",
    }


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


def _load_install_receipt(path: Path, key: bytes) -> dict | None:
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineeringError("Engineering install receipt is invalid.") from error
    required = {
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
    if (
        not isinstance(receipt, dict)
        or set(receipt) != required
        or receipt.get("schema") != "engineering.install.v1"
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


def _replace_install_path(
    source: Path,
    target: Path,
    expected_pre_state: dict | None = None,
    *,
    preimage_path: Path | None = None,
) -> None:
    if expected_pre_state is not None:
        inspected = preimage_path if preimage_path is not None else target
        exists = os.path.lexists(inspected)
        if exists:
            if inspected.is_symlink() or _is_reparse_point(inspected):
                raise EngineeringError(
                    f"Engineering target changed before publication: {inspected}"
                )
            if not inspected.is_file():
                raise EngineeringError(
                    f"Engineering target changed before publication: {inspected}"
                )
            content = inspected.read_bytes()
            actual = {
                "exists": True,
                "kind": "file",
                "bytes_hex": content.hex(),
                "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
                "mode": stat.S_IMODE(inspected.stat().st_mode),
            }
        else:
            actual = {
                "exists": False,
                "kind": "absent",
                "bytes_hex": None,
                "sha256": None,
                "mode": None,
            }
        expected = {
            key: expected_pre_state.get(key)
            for key in ("exists", "kind", "bytes_hex", "sha256", "mode")
        }
        if actual != expected:
            raise EngineeringError(
                f"Engineering target changed before publication: {inspected}"
            )
    os.replace(source, target)


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
    completed = False
    try:
        for stage, target in replacements:
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = backups[target]
            _remove_install_path(backup)
            expected = expected_pre_states.get(target)
            if os.path.lexists(target):
                if _is_reparse_point(target):
                    raise EngineeringError("Engineering install target is a link/reparse point.")
                _replace_install_path(
                    target,
                    backup,
                    expected,
                    preimage_path=target,
                )
                backed_up.append(target)
                _replace_install_path(stage, target, absent)
            else:
                _replace_install_path(stage, target, expected)
            published.append(target)
        if after_publication is not None:
            after_publication()
        completed = True
    except Exception:
        for target in reversed(published):
            _remove_install_path(target)
        for target in reversed(backed_up):
            backup = backups[target]
            if backup.exists() and not os.path.lexists(target):
                _replace_install_path(backup, target)
            elif backup.exists():
                _remove_install_path(backup)
        raise
    finally:
        for stage, _ in replacements:
            _remove_install_path(stage)
        if completed:
            for backup in backups.values():
                _remove_install_path(backup)


def install_bundle(source: Path, home: Path) -> dict:
    source = Path(source).expanduser()
    home = Path(home).expanduser()
    if not home.is_absolute():
        raise EngineeringError("Engineering install home must be absolute.")
    if str(home).startswith("\\\\"):
        raise EngineeringError("Engineering installation on UNC paths is unsupported.")
    files, manifest, commit, source_digest = _bundle_files(source)
    paths = _install_paths(home)
    _validate_install_paths(home, paths)
    home = home.resolve()
    paths = _install_paths(home)
    lock_owner = _acquire_directory_lock(paths["lock"], "Engineering install is already in progress.")
    token = uuid.uuid4().hex
    stages: dict[str, Path] = {
        key: path.with_name(f".{path.name}.backup-{token}")
        for key, path in paths.items()
        if key in {"canonical", "previous", "claude", "shim", "receipt", "previous_receipt"}
    }
    stages = {key: path.with_name(path.name.replace(".backup-", ".stage-")) for key, path in stages.items()}
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
            ):
                return current
        elif any(paths[key].exists() for key in ("canonical", "previous", "previous_receipt")):
            raise EngineeringError("Engineering install state is incomplete.")
        for path in stages.values():
            _remove_install_path(path)
        _copy_bundle(source, stages["canonical"], files)
        stages["claude"].mkdir(parents=True)
        (stages["claude"] / "SKILL.md").write_text(
            _forwarder("engineering"), encoding="utf-8", newline="\n"
        )
        stages["shim"].mkdir(parents=True)
        (stages["shim"] / "SKILL.md").write_text(
            _forwarder("engineering-traceability"), encoding="utf-8", newline="\n"
        )
        parity = _validated_installed_bundle(stages["canonical"])
        receipt = _sign_install_receipt({
            "schema": "engineering.install.v1",
            "status": "installed",
            "skill_version": manifest["version"],
            "source_git_commit": commit,
            "source_digest": source_digest,
            "graphify_commit": manifest["graphify"]["commit"],
            "installed_at": _utc_now(),
            "codex_parity_hash": parity,
            "claude_parity_hash": parity,
        }, install_key)
        stages["receipt"].parent.mkdir(parents=True, exist_ok=True)
        stages["receipt"].write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        replacements = [
            (stages[key], paths[key]) for key in ("canonical", "claude", "shim", "receipt")
        ]
        if current is not None:
            shutil.copytree(paths["canonical"], stages["previous"])
            stages["previous_receipt"].write_bytes(paths["receipt"].read_bytes())
            replacements.extend(
                (stages[key], paths[key]) for key in ("previous", "previous_receipt")
            )
        _transactional_replace(replacements, token)
        return receipt
    finally:
        for path in stages.values():
            _remove_install_path(path)
        _release_directory_lock(paths["lock"], lock_owner)


def rollback_install(home: Path) -> dict:
    home = Path(home).expanduser()
    if not home.is_absolute():
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
        if key in {"canonical", "previous", "claude", "shim", "receipt", "previous_receipt"}
    }
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
        shutil.copytree(paths["canonical"], stages["previous"])
        for key, name in (("claude", "engineering"), ("shim", "engineering-traceability")):
            stages[key].mkdir(parents=True)
            (stages[key] / "SKILL.md").write_text(
                _forwarder(name), encoding="utf-8", newline="\n"
            )
        restored = _sign_install_receipt({
            **previous,
            "status": "rolled_back",
            "installed_at": _utc_now(),
            "codex_parity_hash": parity,
            "claude_parity_hash": parity,
        }, install_key)
        stages["receipt"].write_text(json.dumps(restored, indent=2) + "\n", encoding="utf-8")
        stages["previous_receipt"].write_text(
            json.dumps(current, indent=2) + "\n", encoding="utf-8"
        )
        _transactional_replace(
            [(stages[key], paths[key]) for key in (
                "canonical", "previous", "claude", "shim", "receipt", "previous_receipt"
            )],
            token,
        )
        return restored
    finally:
        for path in stages.values():
            _remove_install_path(path)
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
    rebuild_parser = commands.add_parser("rebuild")
    rebuild_parser.add_argument("root")
    rebuild_parser.add_argument("--commit", required=True)
    rebuild_parser.add_argument("--graphify-python", default=sys.executable)
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
    prepare_parser.add_argument("--scope-json", required=True)
    prepare_parser.add_argument("--override", choices=sorted(AUTONOMY_LEVELS))
    complete_parser = commands.add_parser("complete")
    complete_parser.add_argument("root")
    complete_parser.add_argument("run_id")
    approve_checks_parser = commands.add_parser("approve-checks")
    approve_checks_parser.add_argument("root")
    approve_checks_parser.add_argument("--allow-inline-code", action="store_true")
    autonomy_parser = commands.add_parser("autonomy")
    autonomy_parser.add_argument("level", choices=sorted(AUTONOMY_LEVELS))
    autonomy_parser.add_argument("root", nargs="?", default=".")
    maintain_parser = commands.add_parser("maintain")
    maintain_parser.add_argument("target")
    maintain_parser.add_argument("root", nargs="?")
    maintain_parser.add_argument("--area")
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
        elif not arguments.command.startswith("learning-"):
            root = resolve_project_root(arguments.root)
        if arguments.command.startswith("learning-"):
            print(json.dumps(result))
            return 0
        if arguments.command == "autonomy":
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
        elif arguments.command == "complete":
            result = complete(root, arguments.run_id, [])
        elif arguments.command == "prepare":
            try:
                scope = json.loads(arguments.scope_json)
            except json.JSONDecodeError as error:
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
        elif arguments.command == "rebuild":
            path = rebuild(root, arguments.commit, arguments.graphify_python)
            result = {"checkpoint": str(path)}
        elif arguments.command == "hook":
            result = handle_hook(
                arguments.event, root, arguments.graphify_python
            )
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
        elif arguments.command != "maintain":
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
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
