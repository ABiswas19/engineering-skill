from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath


class MatrixError(RuntimeError):
    pass


REQUIREMENTS_SCHEMA = "engineering.v2.2.6-owner-requirements.v1"
MATRIX_SCHEMA = "engineering.v2.2.6-release-matrix.v1"
EXECUTION_RECEIPT_SCHEMA = "engineering.exact-artifact-execution-receipt.v1"
EVIDENCE_CLASSES = ("proxy", "design", "unit", "integration", "end_to_end", "real_outcome")
GATES = ("artifact_acceptance", "post_activation")
V226_REQUIRED_REQUIREMENTS = (
    "deterministic_release_matrix",
    "exact_release_install_binding",
    "external_owner_authority",
    "git_object_byte_identity",
    "host_private_postactivation_trust",
    "hostile_git_environment",
    "independent_equivalence",
    "independent_exact_artifact_acceptance",
    "intent_digest_continuity",
    "model_routing_disclosure",
    "native_harness_real_outcome_gate",
    "noncircular_bootstrap",
    "outcome_survival_baseline",
    "postactivation_all_outcomes_binding",
    "predecessor_disposition",
    "public_sanitized_parity",
    "refreshed_intent_impact",
    "transactional_install_preimages",
    "typed_evidence_hierarchy",
    "v060_incident_regression",
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _git(root: Path, *arguments: str, binary: bool = False):
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        env=_git_environment(),
    )
    if result.returncode:
        raise MatrixError("exact Git artifact is unavailable")
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def _artifact(root: Path, role: str) -> dict:
    if role not in {"internal", "public"}:
        raise MatrixError("artifact role is invalid")
    commit = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise MatrixError("exact Git artifact identity is invalid")
    return {"role": role, "commit": commit, "tree": tree}


def _blob(root: Path, commit: str, relative: str) -> bytes:
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise MatrixError("requirement mapping path is invalid")
    return _git(root, "cat-file", "blob", f"{commit}:{relative}", binary=True)


def _normalize_requirements(value: object) -> list[dict]:
    expected_row = {
        "id",
        "lifecycle_state",
        "design",
        "contract",
        "runtime_behavior",
        "negative_test",
        "native_evidence",
    }
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "requirements"}
        or value.get("schema") != REQUIREMENTS_SCHEMA
        or not isinstance(value.get("requirements"), list)
    ):
        raise MatrixError("authoritative requirement registry is invalid")
    rows = value["requirements"]
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if tuple(ids) != V226_REQUIRED_REQUIREMENTS:
        raise MatrixError("authoritative requirement coverage is incomplete")
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_row:
            raise MatrixError("authoritative requirement mapping is invalid")
        if row.get("lifecycle_state") not in {"implemented", "post_activation_required"}:
            raise MatrixError("authoritative requirement lifecycle is invalid")
        for key in ("design", "contract", "negative_test"):
            item = row.get(key)
            names = {
                "design": {"path", "section"},
                "contract": {"path", "symbol"},
                "negative_test": {"path", "selector"},
            }[key]
            if (
                not isinstance(item, dict)
                or set(item) != names
                or any(not isinstance(item[name], str) or not item[name] for name in names)
            ):
                raise MatrixError("authoritative requirement mapping is invalid")
        evidence = row.get("native_evidence")
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"gate", "minimum_class"}
            or evidence.get("gate") not in GATES
            or evidence.get("minimum_class") not in EVIDENCE_CLASSES
            or not isinstance(row.get("runtime_behavior"), str)
            or not row["runtime_behavior"]
        ):
            raise MatrixError("authoritative requirement evidence contract is invalid")
        normalized.append(dict(row))
    return normalized


def _execution_receipt(value: object, artifact: dict, requirement_ids: set[str]) -> dict | None:
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "artifact", "commands", "incidents"}
        or value.get("schema") != EXECUTION_RECEIPT_SCHEMA
        or value.get("artifact") != artifact
        or not isinstance(value.get("commands"), list)
        or not isinstance(value.get("incidents"), list)
    ):
        raise MatrixError("exact-artifact execution receipt is invalid")
    command_keys = {
        "command_id",
        "command",
        "started_at",
        "finished_at",
        "exit_code",
        "counts",
        "evidence_class",
        "requirement_ids",
        "stdout_digest",
        "stderr_digest",
    }
    commands = []
    seen: set[str] = set()
    for command in value["commands"]:
        counts = command.get("counts") if isinstance(command, dict) else None
        ids = command.get("requirement_ids") if isinstance(command, dict) else None
        if (
            not isinstance(command, dict)
            or set(command) != command_keys
            or not isinstance(command.get("command_id"), str)
            or not command["command_id"]
            or command["command_id"] in seen
            or not isinstance(command.get("command"), str)
            or not command["command"]
            or not all(
                isinstance(command.get(name), str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^\s]+(?:Z|[+-]\d{2}:\d{2})", command[name])
                for name in ("started_at", "finished_at")
            )
            or not isinstance(command.get("exit_code"), int)
            or not isinstance(counts, dict)
            or set(counts) != {"run", "failures", "errors", "skipped"}
            or any(not isinstance(counts[name], int) or counts[name] < 0 for name in counts)
            or command.get("evidence_class") not in EVIDENCE_CLASSES
            or not isinstance(ids, list)
            or ids != sorted(set(ids))
            or not set(ids) <= requirement_ids
            or any(
                not re.fullmatch(r"sha256:[0-9a-f]{64}", str(command.get(name, "")))
                for name in ("stdout_digest", "stderr_digest")
            )
        ):
            raise MatrixError("exact-artifact execution receipt is invalid")
        seen.add(command["command_id"])
        commands.append(dict(command))
    incident_keys = {
        "incident_id",
        "observed_at",
        "artifact",
        "environment",
        "command",
        "result",
        "counts",
        "evidence_state",
        "source_reference",
        "reconciliation",
    }
    incidents = []
    incident_ids: set[str] = set()
    for incident in value["incidents"]:
        observed = incident.get("artifact") if isinstance(incident, dict) else None
        counts = incident.get("counts") if isinstance(incident, dict) else None
        reconciliation = (
            incident.get("reconciliation") if isinstance(incident, dict) else None
        )
        if (
            not isinstance(incident, dict)
            or set(incident) != incident_keys
            or not isinstance(incident.get("incident_id"), str)
            or not incident["incident_id"]
            or incident["incident_id"] in incident_ids
            or not isinstance(incident.get("observed_at"), str)
            or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T[^\s]+(?:Z|[+-]\d{2}:\d{2})",
                incident["observed_at"],
            )
            or not isinstance(observed, dict)
            or set(observed) != {"role", "commit", "tree"}
            or observed.get("role") not in {"internal", "public"}
            or any(
                not re.fullmatch(r"[0-9a-f]{40}", str(observed.get(name, "")))
                for name in ("commit", "tree")
            )
            or not isinstance(incident.get("environment"), str)
            or not incident["environment"]
            or not isinstance(incident.get("command"), str)
            or not incident["command"]
            or incident.get("result") != "failed"
            or not isinstance(counts, dict)
            or set(counts) != {"run", "failures", "errors", "skipped"}
            or any(not isinstance(counts[name], int) or counts[name] < 0 for name in counts)
            or counts["failures"] + counts["errors"] == 0
            or incident.get("evidence_state")
            not in {"canonical_log", "operator_observed_raw_log_unavailable"}
            or not isinstance(incident.get("source_reference"), str)
            or not incident["source_reference"]
            or not isinstance(reconciliation, dict)
            or set(reconciliation) != {"state", "exact_artifact"}
            or reconciliation.get("state") != "superseded_by_exact_artifact"
            or reconciliation.get("exact_artifact") != artifact
        ):
            raise MatrixError("exact-artifact incident receipt is invalid")
        incident_ids.add(incident["incident_id"])
        incidents.append(dict(incident))
    return {**value, "commands": commands, "incidents": incidents}


def matrix_digest(report: dict) -> str:
    return _digest(_canonical({key: value for key, value in report.items() if key != "matrix_digest"}))


def generate_matrix(root: Path, role: str, execution_receipt: object | None) -> dict:
    root = Path(root).resolve()
    artifact = _artifact(root, role)
    registry_bytes = _blob(root, artifact["commit"], "release/v2.2.6-requirements.json")
    try:
        requirements = _normalize_requirements(json.loads(registry_bytes.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("authoritative requirement registry is invalid") from error
    receipt = _execution_receipt(
        execution_receipt, artifact, set(V226_REQUIRED_REQUIREMENTS)
    )
    rows = []
    unknowns = []
    proxy_rejections = []
    for requirement in requirements:
        design = requirement["design"]
        contract = requirement["contract"]
        negative = requirement["negative_test"]
        design_blob = _blob(root, artifact["commit"], design["path"])
        contract_blob = _blob(root, artifact["commit"], contract["path"])
        negative_blob = _blob(root, artifact["commit"], negative["path"])
        if (
            design["section"].encode("utf-8") not in design_blob
            or contract["symbol"].encode("utf-8") not in contract_blob
            or negative["selector"].encode("utf-8") not in negative_blob
        ):
            raise MatrixError("authoritative requirement mapping is unresolved")
        minimum = requirement["native_evidence"]["minimum_class"]
        matching = [] if receipt is None else [
            command
            for command in receipt["commands"]
            if requirement["id"] in command["requirement_ids"]
            and command["exit_code"] == 0
            and command["counts"]["failures"] == 0
            and command["counts"]["errors"] == 0
        ]
        satisfying = [
            command
            for command in matching
            if EVIDENCE_CLASSES.index(command["evidence_class"])
            >= EVIDENCE_CLASSES.index(minimum)
        ]
        evidence_state = "satisfied" if satisfying else "unknown"
        if not satisfying:
            unknowns.append(requirement["id"])
            if matching:
                proxy_rejections.append(requirement["id"])
        rows.append(
            {
                "requirement_id": requirement["id"],
                "lifecycle_state": requirement["lifecycle_state"],
                "design": design,
                "design_blob": _digest(design_blob),
                "contract": contract,
                "contract_blob": _digest(contract_blob),
                "runtime_behavior": requirement["runtime_behavior"],
                "negative_test": negative,
                "negative_test_blob": _digest(negative_blob),
                "native_evidence": requirement["native_evidence"],
                "evidence_state": evidence_state,
                "evidence_command_ids": [item["command_id"] for item in satisfying],
                "gate": requirement["native_evidence"]["gate"],
                "exact_artifact_identity": artifact,
            }
        )
    gates = {
        f"{gate}_ready": all(
            row["evidence_state"] == "satisfied" for row in rows if row["gate"] == gate
        )
        for gate in GATES
    }
    report = {
        "schema": MATRIX_SCHEMA,
        "artifact": artifact,
        "requirements_digest": _digest(registry_bytes),
        "execution_receipt_digest": _digest(_canonical(receipt)) if receipt else None,
        "rows": rows,
        "unknowns": sorted(unknowns),
        "proxy_rejections": sorted(proxy_rejections),
        "gates": gates,
        "incidents": [] if receipt is None else receipt["incidents"],
    }
    report["matrix_digest"] = matrix_digest(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(prog="v226-release-matrix")
    parser.add_argument("root")
    parser.add_argument("--role", choices=("internal", "public"), required=True)
    parser.add_argument("--execution-receipt")
    arguments = parser.parse_args()
    try:
        receipt = (
            json.loads(Path(arguments.execution_receipt).read_text(encoding="utf-8"))
            if arguments.execution_receipt
            else None
        )
        print(json.dumps(generate_matrix(Path(arguments.root), arguments.role, receipt)))
    except (OSError, json.JSONDecodeError, MatrixError) as error:
        print(f"ERROR: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
