from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path


class ExportError(RuntimeError):
    pass


def _audience_module():
    try:
        return importlib.import_module("check_audience")
    except ModuleNotFoundError:
        return importlib.import_module("tools.check_audience")


def _git_common(root: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    path = Path(result.stdout.strip())
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _safe_file(root: Path, relative: str) -> Path:
    path = root / relative
    if (
        not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or not path.is_file()
        or path.is_symlink()
        or path.lstat().st_nlink != 1
        or bool(
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    ):
        raise ExportError(f"unsafe or missing export file: {relative}")
    return path


def _safe_destination(root: Path, relative: str) -> Path:
    candidate = root / relative
    current = root
    for part in Path(relative).parts[:-1]:
        current /= part
        if not current.exists():
            break
        if current.is_symlink() or bool(
            getattr(current.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ExportError(f"unsafe export destination: {relative}")
    if os.path.lexists(candidate) and (
        not candidate.is_file()
        or candidate.is_symlink()
        or candidate.lstat().st_nlink != 1
        or bool(
            getattr(candidate.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    ):
        raise ExportError(f"unsafe export destination: {relative}")
    return candidate


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _source_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ExportError("source commit is invalid")
    return commit


def _assert_clean_head_snapshot(root: Path, files: list[str]) -> None:
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        check=True,
        capture_output=True,
    ).stdout
    if status:
        raise ExportError("export source worktree is not clean")
    for relative in files:
        _safe_file(root, relative)
        try:
            committed = subprocess.run(
                ["git", "-C", str(root), "rev-parse", f"HEAD:{relative}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            observed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "hash-object",
                    f"--path={relative}",
                    relative,
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except subprocess.SubprocessError as error:
            raise ExportError("export source is not bound to HEAD") from error
        if observed != committed:
            raise ExportError("export source bytes do not match HEAD")


def _snapshot_digest(commit: str, tree_digest: str) -> str:
    return "sha256:" + hashlib.sha256(
        (commit + "\0" + tree_digest).encode("ascii")
    ).hexdigest()


def _tree_digest(root: Path, files: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update((root / relative).read_bytes() + b"\0")
    return "sha256:" + digest.hexdigest()


def _validate_audience_classification(source: Path, shared_files: list[str]) -> set[str]:
    path = source / "release" / "audience-classification.json"
    if not path.exists():
        return set()
    if not path.is_file() or path.is_symlink():
        raise ExportError("audience classification is unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or set(value) != {
            "schema",
            "shared_manifest",
            "internal_only",
            "public_only",
            "audience_specific",
        }
        or value.get("schema") != "engineering.audience-classification.v1"
        or value.get("shared_manifest") != "release/public-export.json"
    ):
        raise ExportError("audience classification is invalid")
    classes: dict[str, list[str]] = {}
    for name in ("internal_only", "public_only", "audience_specific"):
        items = value.get(name)
        if (
            not isinstance(items, list)
            or items != sorted(set(items))
            or any(
                not isinstance(item, str)
                or not item
                or Path(item).is_absolute()
                or ".." in Path(item).parts
                for item in items
            )
        ):
            raise ExportError("audience classification is invalid")
        classes[name] = items
    shared = set(shared_files)
    internal = set(classes["internal_only"])
    public = set(classes["public_only"])
    audience_specific = set(classes["audience_specific"])
    if (
        shared & internal
        or shared & public
        or shared & audience_specific
        or internal & public
        or internal & audience_specific
        or public & audience_specific
    ):
        raise ExportError("audience classifications overlap")
    if "release/audience-classification.json" not in internal:
        raise ExportError("audience classification must classify itself")
    for relative in internal | audience_specific:
        _safe_file(source, relative)
    for relative in public:
        if os.path.lexists(source / relative):
            raise ExportError("public-only file is present in the canonical source")
    return audience_specific


def _audience_policy(
    source: Path,
    destination: Path,
    shared_files: list[str],
    metadata: dict[str, object] | None = None,
) -> tuple[dict | None, list[str]]:
    path = source / "release" / "audience-isolation-policy.json"
    if not path.is_file():
        return None, ["audience_policy_unknown"]
    module = _audience_module()
    policy = module.load_policy(path)
    snapshots = metadata if isinstance(metadata, dict) else {}
    commits = {"source": _source_commit(source)}
    if metadata is not None:
        commits["distribution"] = _source_commit(destination)
    blockers = module.policy_blockers(
        policy, "source", snapshots.get("source"), commits.get("source")
    )
    blockers.extend(
        module.policy_blockers(
            policy,
            "distribution",
            snapshots.get("distribution"),
            commits.get("distribution"),
        )
    )
    blockers.extend(module.audit_reachable_history(source, policy, "source"))
    blockers.extend(module.audit_security_overlay(source, policy, "source"))
    blockers.extend(module.audit_tree(source, shared_files, policy, "distribution"))
    if policy["export"]["mode"] != "byte_identical" or policy["export"]["transformations"]:
        blockers.append("transformation_equivalence_unimplemented")
    return policy, sorted(set(blockers))


def _audience_specific_receipt(
    destination: Path,
    audience_specific: set[str],
    policy: dict | None,
) -> dict[str, str]:
    if policy is None:
        return {}
    if "SECURITY.md" not in audience_specific:
        raise ExportError("audience-specific security policy is unclassified")
    paths: dict[str, Path] = {}
    for relative in sorted(audience_specific):
        try:
            paths[relative] = _safe_file(destination, relative)
        except ExportError as error:
            raise ExportError("audience-specific security overlay is unavailable") from error
    module = _audience_module()
    if module.audit_tree(destination, sorted(paths), policy, "distribution"):
        raise ExportError("audience-specific security overlay is contaminated")
    if module.audit_security_overlay(destination, policy, "distribution"):
        raise ExportError("audience-specific security route is unverified")
    return {relative: _file_digest(path) for relative, path in sorted(paths.items())}


def _atomic_private_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def export_tree(
    source: Path,
    destination: Path,
    metadata: dict[str, object] | None = None,
) -> dict:
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    destination_git = destination / ".git"
    if (
        not (source / ".git").exists()
        or not destination_git.is_dir()
        or destination_git.is_symlink()
        or bool(
            getattr(destination_git.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    ):
        raise ExportError("source and destination must be independent Git repositories")
    if _git_common(source) == _git_common(destination):
        raise ExportError("public export must use independent Git history")
    manifest_path = source / "release" / "public-export.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        set(manifest) != {"schema", "files"}
        or manifest.get("schema") != "engineering.public-export.v1"
        or not isinstance(manifest.get("files"), list)
        or manifest["files"] != sorted(set(manifest["files"]))
    ):
        raise ExportError("public export manifest is invalid")
    files = manifest["files"]
    _assert_clean_head_snapshot(source, files)
    source_commit = _source_commit(source)
    audience_specific = _validate_audience_classification(source, files)
    policy, policy_blockers = _audience_policy(
        source, destination, files, metadata
    )
    audience_specific_files = _audience_specific_receipt(
        destination, audience_specific, policy
    )
    sources = {relative: _safe_file(source, relative) for relative in files}
    source_tree_digest = _tree_digest(source, files)
    source_snapshot_digest = _snapshot_digest(source_commit, source_tree_digest)
    receipt_path = _safe_destination(destination_git, "engineering-public-export.json")
    previous = {}
    if receipt_path.is_file():
        retained = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            isinstance(retained, dict)
            and retained.get("schema")
            in {
                "engineering.public-export-receipt.v2",
                "engineering.public-export-receipt.v3",
            }
            and isinstance(retained.get("files"), dict)
        ):
            previous = retained["files"]
    for relative, expected_digest in previous.items():
        if (
            relative not in files
            and relative not in audience_specific
            and isinstance(relative, str)
            and relative
            and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts
            and isinstance(expected_digest, str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest)
        ):
            target = _safe_destination(destination, relative)
            if target.is_file() and _file_digest(target) == expected_digest:
                target.unlink()
    for relative, source_path in sources.items():
        target = _safe_destination(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = _safe_destination(destination, relative)
        shutil.copy2(source_path, target)
    destination_tree_digest = _tree_digest(destination, files)
    if destination_tree_digest != source_tree_digest:
        raise ExportError("same-snapshot byte parity failed")
    receipt = {
        "schema": "engineering.public-export-receipt.v3",
        "files": {relative: _file_digest(destination / relative) for relative in files},
        "source_commit": source_commit,
        "tree_digest": destination_tree_digest,
        "source_snapshot_digest": source_snapshot_digest,
        "manifest_digest": _file_digest(manifest_path),
        "audience_specific_files": audience_specific_files,
        "metadata_snapshot_digests": {
            audience: "sha256:"
            + hashlib.sha256(
                json.dumps(
                    snapshot, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            for audience, snapshot in sorted((metadata or {}).items())
        },
    }
    _atomic_private_text(receipt_path, json.dumps(receipt, indent=2) + "\n")
    blockers = list(policy_blockers)
    if not (destination / "LICENSE").is_file():
        blockers.append("license_missing")
    blockers = sorted(set(blockers))
    return {
        "schema": "engineering.public-export-result.v1",
        "tree_digest": destination_tree_digest,
        "source_commit": source_commit,
        "source_snapshot_digest": source_snapshot_digest,
        "file_count": len(files),
        "publication_ready": not blockers,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="export-public")
    parser.add_argument("source")
    parser.add_argument("destination")
    arguments = parser.parse_args()
    try:
        result = export_tree(Path(arguments.source), Path(arguments.destination))
    except (OSError, ValueError, subprocess.SubprocessError, ExportError) as error:
        print(f"ERROR: {error}")
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
