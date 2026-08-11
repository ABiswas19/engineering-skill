from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path


POLICY_SCHEMA = "engineering.audience-isolation-policy.v1"
SNAPSHOT_SCHEMA = "engineering.audience-metadata-snapshot.v1"
AUDIENCES = {"source", "distribution"}
HISTORY_LIMIT = 256 * 1024 * 1024
PERSONAL_PATH = re.compile(
    r"(?i)(?:[a-z]:[\\/]users[\\/][^\\/\s]+|/(?:users|home)/[^/\s]+)"
)
_HISTORY_CACHE: dict[tuple[str, str, str, str], tuple[str, ...]] = {}


class AudienceError(RuntimeError):
    pass


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    return []


def _validated_policy(value: object) -> dict:
    required = {
        "schema",
        "audiences",
        "surfaces",
        "export",
        "literal_exceptions",
        "history_exceptions",
    }
    if not isinstance(value, dict) or set(value) != required or value.get("schema") != POLICY_SCHEMA:
        raise AudienceError("audience policy is invalid")
    audiences = value.get("audiences")
    if not isinstance(audiences, dict) or set(audiences) != AUDIENCES:
        raise AudienceError("audience policy is invalid")
    for audience in AUDIENCES:
        item = audiences[audience]
        if not isinstance(item, dict) or set(item) != {"forbidden_markers", "security_route"}:
            raise AudienceError("audience policy is invalid")
        markers = item["forbidden_markers"]
        route = item["security_route"]
        if (
            not isinstance(markers, list)
            or not markers
            or markers != sorted(set(markers), key=str.casefold)
            or any(not isinstance(marker, str) or not marker.strip() for marker in markers)
            or not isinstance(route, dict)
        ):
            raise AudienceError("audience policy is invalid")
        state = route.get("state")
        if state == "verified":
            valid_route = (
                set(route) == {"state", "mechanism"}
                and isinstance(route.get("mechanism"), str)
                and bool(route["mechanism"].strip())
            )
        elif state == "unknown":
            valid_route = (
                set(route) == {"state", "mechanism"}
                and route.get("mechanism") is None
            )
        elif state == "not_required":
            valid_route = (
                set(route)
                == {"state", "mechanism", "authority_reference", "residual_risk"}
                and route.get("mechanism") is None
                and re.fullmatch(
                    r"owner-approved:[a-z0-9._-]{1,120}",
                    str(route.get("authority_reference", "")),
                )
                is not None
                and isinstance(route.get("residual_risk"), str)
                and 1 <= len(route["residual_risk"].strip()) <= 240
            )
        else:
            valid_route = False
        if not valid_route:
            raise AudienceError("audience policy is invalid")
    surfaces = value.get("surfaces")
    if (
        not isinstance(surfaces, dict)
        or set(surfaces) != {"tree", "history", "metadata"}
        or surfaces.get("tree") != ["manifests", "tree", "workflows"]
        or surfaces.get("history") != ["reachable_history"]
        or surfaces.get("metadata")
        != ["comments", "issues", "pull_requests", "releases", "reviews"]
    ):
        raise AudienceError("audience policy is invalid")
    export = value.get("export")
    if (
        not isinstance(export, dict)
        or set(export) != {"mode", "same_snapshot_required", "transformations"}
        or export.get("mode") not in {"byte_identical", "declared_transformations"}
        or export.get("same_snapshot_required") is not True
        or not isinstance(export.get("transformations"), list)
    ):
        raise AudienceError("audience policy is invalid")
    for transformation in export["transformations"]:
        if (
            not isinstance(transformation, dict)
            or set(transformation) != {"path", "method", "equivalence"}
            or any(not isinstance(transformation[key], str) or not transformation[key].strip() for key in transformation)
        ):
            raise AudienceError("audience transformation is invalid")
    if export["mode"] == "byte_identical" and export["transformations"]:
        raise AudienceError("byte-identical export cannot declare transformations")
    exceptions = value.get("literal_exceptions")
    if not isinstance(exceptions, list):
        raise AudienceError("audience policy is invalid")
    for item in exceptions:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "reason"}
            or item.get("reason") not in {"negative_test", "policy_manifest"}
            or not isinstance(item.get("path"), str)
            or not item["path"]
            or Path(item["path"]).is_absolute()
            or ".." in Path(item["path"]).parts
        ):
            raise AudienceError("audience literal exception is invalid")
    history_exceptions = value.get("history_exceptions")
    if not isinstance(history_exceptions, list):
        raise AudienceError("audience history exceptions are invalid")
    expected_order: list[tuple[str, str, str, str]] = []
    for item in history_exceptions:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "audience",
                "introduced_commit",
                "removed_commit",
                "marker",
                "reason",
                "authority_reference",
            }
            or item.get("audience") not in AUDIENCES
            or not re.fullmatch(r"[0-9a-f]{40}", str(item.get("introduced_commit", "")))
            or not re.fullmatch(r"[0-9a-f]{40}", str(item.get("removed_commit", "")))
            or not isinstance(item.get("marker"), str)
            or item["marker"].casefold()
            not in {
                marker.casefold()
                for marker in audiences[item["audience"]]["forbidden_markers"]
            }
            or not isinstance(item.get("reason"), str)
            or not 1 <= len(item["reason"].strip()) <= 240
            or not re.fullmatch(
                r"owner-approved:[a-z0-9._-]{1,120}",
                str(item.get("authority_reference", "")),
            )
        ):
            raise AudienceError("audience history exception is invalid")
        expected_order.append(
            (
                item["audience"],
                item["introduced_commit"],
                item["removed_commit"],
                item["marker"].casefold(),
            )
        )
    if expected_order != sorted(set(expected_order)):
        raise AudienceError("audience history exceptions are invalid")
    return value


def load_policy(path: Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AudienceError("audience policy is unavailable") from error
    return _validated_policy(value)


def _content_blockers(texts: list[str], policy: dict, audience: str, prefix: str) -> list[str]:
    if audience not in AUDIENCES:
        raise AudienceError("audience is invalid")
    markers = policy["audiences"][audience]["forbidden_markers"]
    folded = [text.casefold() for text in texts]
    blockers: list[str] = []
    if any(marker.casefold() in text for marker in markers for text in folded):
        blockers.append(f"{prefix}_marker_crossflow")
    if any(PERSONAL_PATH.search(text) for text in texts):
        blockers.append(f"{prefix}_personal_path")
    return blockers


def audit_metadata(
    policy_value: object,
    snapshot: object,
    expected_audience: str | None = None,
    expected_source_commit: str | None = None,
) -> list[str]:
    policy = _validated_policy(policy_value)
    if not isinstance(snapshot, dict):
        return ["metadata_surface_unknown"]
    required = {"schema", "audience", "source_commit", "surfaces"}
    audience = snapshot.get("audience")
    surfaces = snapshot.get("surfaces")
    expected = policy["surfaces"]["metadata"]
    if (
        set(snapshot) != required
        or snapshot.get("schema") != SNAPSHOT_SCHEMA
        or audience not in AUDIENCES
        or not re.fullmatch(r"[0-9a-f]{40}", str(snapshot.get("source_commit", "")))
        or not isinstance(surfaces, dict)
        or sorted(surfaces) != expected
        or any(not isinstance(surfaces[name], list) for name in expected)
    ):
        return ["metadata_surface_unknown"]
    if expected_audience is not None and audience != expected_audience:
        return ["metadata_audience_mismatch"]
    if expected_source_commit is not None and snapshot["source_commit"] != expected_source_commit:
        return ["metadata_snapshot_mismatch"]
    return sorted(set(_content_blockers(_strings(surfaces), policy, audience, "metadata")))


def audit_reachable_history(root: Path, policy_value: object, audience: str) -> list[str]:
    policy = _validated_policy(policy_value)
    root = Path(root)
    try:
        commits = subprocess.run(
            ["git", "-C", str(root), "rev-list", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except subprocess.SubprocessError:
        return ["history_surface_unknown"]
    head = commits[0] if commits else ""
    policy_digest = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cache_key = (str(root.resolve()), head, audience, policy_digest)
    cached = _HISTORY_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)
    allowed: dict[str, set[str]] = {}
    for item in policy["history_exceptions"]:
        if item["audience"] != audience:
            continue
        try:
            ancestry = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "rev-list",
                    "--ancestry-path",
                    f'{item["introduced_commit"]}..{item["removed_commit"]}^',
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            introduced = subprocess.run(
                ["git", "-C", str(root), "rev-parse", item["introduced_commit"]],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(root), "merge-base", "--is-ancestor", introduced, item["removed_commit"]],
                check=True,
                capture_output=True,
            )
        except subprocess.SubprocessError:
            return ["history_surface_unknown"]
        allowed.setdefault(item["marker"].casefold(), set()).update(ancestry + [introduced])
    exceptions = {
        item["path"].replace("\\", "/") for item in policy["literal_exceptions"]
    }
    markers = policy["audiences"][audience]["forbidden_markers"]
    total = 0
    blockers: set[str] = set()
    for commit in commits:
        try:
            message = subprocess.run(
                ["git", "-C", str(root), "show", "-s", "--format=%B", commit],
                check=True,
                capture_output=True,
            ).stdout
            archive = subprocess.run(
                ["git", "-C", str(root), "archive", "--format=tar", commit],
                check=True,
                capture_output=True,
            ).stdout
        except subprocess.SubprocessError:
            return ["history_surface_unknown"]
        chunks = [message]
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tree:
                for member in tree.getmembers():
                    normalized = member.name.replace("\\", "/")
                    if not member.isfile() or normalized in exceptions:
                        continue
                    handle = tree.extractfile(member)
                    if handle is not None:
                        chunks.append(handle.read())
        except (tarfile.TarError, OSError):
            return ["history_surface_unknown"]
        total += sum(len(chunk) for chunk in chunks)
        if total > HISTORY_LIMIT:
            return ["history_surface_unknown"]
        texts = [chunk.decode("utf-8", errors="ignore") for chunk in chunks]
        folded = "\n".join(texts).casefold()
        for marker in markers:
            key = marker.casefold()
            if key in folded and commit not in allowed.get(key, set()):
                blockers.add("history_marker_crossflow")
        if any(PERSONAL_PATH.search(text) for text in texts):
            blockers.add("history_personal_path")
    result = tuple(sorted(blockers))
    _HISTORY_CACHE[cache_key] = result
    return list(result)


def audit_tree(root: Path, paths: list[str], policy_value: object, audience: str) -> list[str]:
    policy = _validated_policy(policy_value)
    exceptions = {
        item["path"].replace("\\", "/") for item in policy["literal_exceptions"]
    }
    texts: list[str] = []
    for relative in paths:
        normalized = relative.replace("\\", "/")
        if normalized in exceptions:
            continue
        path = Path(root).joinpath(*normalized.split("/"))
        if not path.is_file() or path.is_symlink():
            return ["tree_surface_unknown"]
        try:
            texts.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
    return sorted(set(_content_blockers(texts, policy, audience, "tree")))


def audit_security_overlay(root: Path, policy_value: object, audience: str) -> list[str]:
    policy = _validated_policy(policy_value)
    if audience not in AUDIENCES:
        raise AudienceError("audience is invalid")
    path = Path(root) / "SECURITY.md"
    if not path.is_file() or path.is_symlink():
        return ["security_policy_unknown"]
    try:
        security = " ".join(path.read_text(encoding="utf-8").casefold().split())
    except (OSError, UnicodeDecodeError):
        return ["security_policy_unknown"]
    route = policy["audiences"][audience]["security_route"]
    if route["state"] == "unknown":
        return ["security_route_unknown"]
    if route["state"] == "not_required":
        required = (
            "does not provide a repository-supported vulnerability-reporting channel",
            "must not be submitted through ordinary issues",
            "do not open an ordinary issue for a suspected vulnerability",
            "residual risk",
            route["residual_risk"].casefold(),
        )
        blockers: list[str] = []
        if any(marker not in security for marker in required):
            blockers.append("security_policy_unknown")
        if (
            "github private vulnerability reporting" in security
            or "security/advisories/new" in security
            or re.search(r"https?://|[a-z0-9._%+-]+@[a-z0-9.-]+", security)
        ):
            blockers.append("security_route_invented")
        if any(
            marker in security
            for marker in (
                "report it in an ordinary issue",
                "submit it through an ordinary issue",
                "disclose it in an ordinary issue",
            )
        ):
            blockers.append("ordinary_issue_vulnerability_intake")
        return sorted(set(blockers))
    if (
        route["mechanism"] != "github_private_vulnerability_reporting"
        or "github private vulnerability reporting" not in security
        or "security/advisories/new" not in security
    ):
        return ["security_route_unknown"]
    return []


def policy_blockers(
    policy_value: object,
    audience: str,
    metadata: object | None,
    expected_source_commit: str | None = None,
) -> list[str]:
    policy = _validated_policy(policy_value)
    if audience not in AUDIENCES:
        raise AudienceError("audience is invalid")
    blockers: list[str] = []
    if policy["audiences"][audience]["security_route"]["state"] == "unknown":
        blockers.append("security_route_unknown")
    if metadata is None:
        blockers.append("metadata_audit_unknown")
    else:
        blockers.extend(
            audit_metadata(policy, metadata, audience, expected_source_commit)
        )
        if expected_source_commit is None:
            blockers.append("metadata_snapshot_unknown")
    return sorted(set(blockers))


def main() -> int:
    parser = argparse.ArgumentParser(prog="check-audience")
    parser.add_argument("root")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--audience", required=True, choices=sorted(AUDIENCES))
    parser.add_argument("--metadata")
    arguments = parser.parse_args()
    try:
        root = Path(arguments.root).resolve()
        policy = load_policy(Path(arguments.policy))
        metadata = (
            json.loads(Path(arguments.metadata).read_text(encoding="utf-8"))
            if arguments.metadata
            else None
        )
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8").split("\0")
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        blockers = policy_blockers(policy, arguments.audience, metadata, head)
        blockers.extend(audit_tree(root, [item for item in tracked if item], policy, arguments.audience))
        blockers.extend(audit_security_overlay(root, policy, arguments.audience))
        blockers.extend(audit_reachable_history(root, policy, arguments.audience))
        blockers = sorted(set(blockers))
    except (AudienceError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(json.dumps({"schema": "engineering.audience-audit.v1", "status": "blocked", "blockers": ["audit_unknown"], "detail": str(error)}))
        return 2
    print(json.dumps({"schema": "engineering.audience-audit.v1", "status": "ready" if not blockers else "blocked", "blockers": blockers}))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
