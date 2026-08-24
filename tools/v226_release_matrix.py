from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath


class MatrixError(RuntimeError):
    pass


REQUIREMENTS_SCHEMA = "engineering.v2.2.6-owner-requirements.v2"
MATRIX_SCHEMA = "engineering.v2.2.6-release-matrix.v1"
HOST_EXECUTION_ENVELOPE_SCHEMA = "engineering.host-execution-envelope.v1"
NATIVE_EXECUTION_META_SCHEMA = "engineering.native-execution-meta.v1"
NATIVE_INCIDENT_META_SCHEMA = "engineering.native-incident-meta.v1"
INDEPENDENT_AUDIT_META_SCHEMA = "engineering.independent-audit-meta.v1"
EVIDENCE_CLASSES = ("proxy", "design", "unit", "integration", "end_to_end", "real_outcome")
GATES = ("artifact_acceptance", "post_activation")
V226_REQUIRED_REQUIREMENTS = (
    "complete_owner_obligation_ledger",
    "authenticated_execution_envelopes",
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
V226_REQUIRED_OBLIGATIONS = (
    "graphify_base_checkpoint",
    "deterministic_engineering_overlay",
    "trace_coverage_impact_why_views",
    "project_setup_preview_authority",
    "checkpoint_integrity",
    "completion_outcome_survival",
    "authority_persistence",
    "bounded_maintenance",
    "semantic_traceability_matrices",
    "capability_assurance",
    "project_local_learning",
    "project_identity_binding",
    "measurement_truth",
    "first_pass_incident_preservation",
    "false_acceptance_prevention",
    "graph_engineering_contract",
    "readme_contract_truth",
    "langfuse_deferred",
    "v226_activation_boundary",
    "postactivation_completeness_import",
    "all_owner_outcome_release_enforcement",
    "native_codex_claude_harness_proof",
    "v061_runtime_delivery",
    "ctao_observability_api",
    "kaka_consumer_integration",
    "decision_studio_consumer_integration",
    "headless_unified_product",
    "remaining_plugin_independent_frontend",
    "full_consumer_release_gate",
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


def _normalize_registry(value: object) -> tuple[list[dict], list[dict]]:
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
        or set(value) != {"schema", "requirements", "obligations"}
        or value.get("schema") != REQUIREMENTS_SCHEMA
        or not isinstance(value.get("requirements"), list)
        or not isinstance(value.get("obligations"), list)
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
    obligation_rows = value["obligations"]
    obligation_ids = [row.get("id") for row in obligation_rows if isinstance(row, dict)]
    if tuple(obligation_ids) != V226_REQUIRED_OBLIGATIONS:
        raise MatrixError("authoritative obligation coverage is incomplete")
    obligation_expected = {
        "id", "category", "phase", "dependencies", "disposition",
        "acceptance_criteria", "dispatch_gate",
    }
    seen_obligations: set[str] = set()
    normalized_obligations = []
    for row in obligation_rows:
        disposition = row.get("disposition") if isinstance(row, dict) else None
        criteria = row.get("acceptance_criteria") if isinstance(row, dict) else None
        dependencies = row.get("dependencies") if isinstance(row, dict) else None
        if (
            not isinstance(row, dict)
            or set(row) != obligation_expected
            or not isinstance(row.get("id"), str)
            or not isinstance(row.get("category"), str)
            or not row["category"]
            or row.get("phase") not in {"inherited", "activation", "post_activation"}
            or not isinstance(dependencies, list)
            or dependencies != list(dict.fromkeys(dependencies))
            or any(not isinstance(item, str) or item not in seen_obligations for item in dependencies)
            or not isinstance(disposition, dict)
            or set(disposition) != {"state", "reason"}
            or disposition.get("state") not in {"included", "deferred"}
            or not isinstance(disposition.get("reason"), str)
            or not disposition["reason"]
            or not isinstance(criteria, dict)
            or set(criteria) != {"evidence_class", "interface", "environment", "fail_closed"}
            or criteria.get("evidence_class") not in EVIDENCE_CLASSES
            or not isinstance(criteria.get("interface"), str)
            or not criteria["interface"]
            or not isinstance(criteria.get("environment"), str)
            or not criteria["environment"]
            or criteria.get("fail_closed") is not True
            or not isinstance(row.get("dispatch_gate"), str)
            or not row["dispatch_gate"]
        ):
            raise MatrixError("authoritative obligation mapping is invalid")
        seen_obligations.add(row["id"])
        normalized_obligations.append(dict(row))
    return normalized, normalized_obligations


def _normalize_requirements(value: object) -> list[dict]:
    """Compatibility helper retained for callers that only consume matrix rows."""
    return _normalize_registry(value)[0]


def _external_path(repository: Path, value: object, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise MatrixError(f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise MatrixError(f"{label} path is invalid")
    current = path
    while True:
        if current.exists() and current.is_symlink():
            raise MatrixError(f"{label} path is invalid")
        if current.parent == current:
            break
        current = current.parent
    resolved = path.resolve()
    try:
        resolved.relative_to(repository.resolve())
    except ValueError:
        return resolved
    raise MatrixError(f"{label} path must be outside candidate Git")


def _external_bytes(repository: Path, value: object, label: str) -> bytes:
    path = _external_path(repository, value, label)
    if not path.is_file():
        raise MatrixError(f"{label} is unavailable")
    return path.read_bytes()


def _reference_bytes(repository: Path, evidence_root: Path, value: object, label: str) -> bytes:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "digest"}
        or not isinstance(value.get("path"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("digest", "")))
    ):
        raise MatrixError(f"{label} reference is invalid")
    relative = PurePosixPath(value["path"])
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise MatrixError(f"{label} reference is invalid")
    path = (evidence_root / Path(*relative.parts)).resolve()
    try:
        path.relative_to(evidence_root)
    except ValueError as error:
        raise MatrixError(f"{label} reference is invalid") from error
    content = _external_bytes(repository, path, label)
    if _digest(content) != value["digest"]:
        raise MatrixError(f"{label} digest is mismatched")
    return content


def _utc(value: object) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^\s]+(?:Z|[+-]\d{2}:\d{2})", value)
    )


def _unittest_counts(log: bytes) -> dict:
    try:
        text = log.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MatrixError("native execution log is not UTF-8") from error
    ran = re.search(r"(?m)^Ran (\d+) tests? in ", text)
    if ran is None:
        raise MatrixError("native execution log has no unittest terminal count")
    failures = re.search(r"failures=(\d+)", text)
    errors = re.search(r"errors=(\d+)", text)
    skipped = re.search(r"skipped=(\d+)", text)
    ok = any(line == "OK" or line.startswith("OK (") for line in text.splitlines())
    if not ok and "FAILED (" not in text:
        raise MatrixError("native execution log has no unittest terminal result")
    return {
        "run": int(ran.group(1)),
        "failures": int(failures.group(1)) if failures else 0,
        "errors": int(errors.group(1)) if errors else 0,
        "skipped": int(skipped.group(1)) if skipped else 0,
    }


def _native_command(
    repository: Path,
    artifact: dict,
    role: str,
    evidence_root: Path,
    reference: object,
    requirement_ids: set[str],
) -> dict:
    if not isinstance(reference, dict) or set(reference) != {"command_id", "meta", "log"}:
        raise MatrixError("native execution reference is invalid")
    meta_bytes = _reference_bytes(repository, evidence_root, reference["meta"], "native meta")
    log_bytes = _reference_bytes(repository, evidence_root, reference["log"], "native log")
    try:
        meta = json.loads(meta_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("native execution meta is not exact UTF-8 JSON") from error
    expected = {
        "schema", "command_id", "executor", "artifact_before", "artifact_after",
        "role", "argv", "cwd", "started_at", "finished_at", "exit_code", "parser",
        "counts", "evidence_class", "requirement_ids",
    }
    counts = meta.get("counts") if isinstance(meta, dict) else None
    ids = meta.get("requirement_ids") if isinstance(meta, dict) else None
    executor = meta.get("executor") if isinstance(meta, dict) else None
    if (
        not isinstance(meta, dict)
        or set(meta) != expected
        or meta.get("schema") != NATIVE_EXECUTION_META_SCHEMA
        or meta.get("command_id") != reference.get("command_id")
        or not isinstance(meta.get("command_id"), str)
        or not meta["command_id"]
        or meta.get("artifact_before") != artifact
        or meta.get("artifact_after") != artifact
        or meta.get("role") != role
        or not isinstance(meta.get("argv"), list)
        or not meta["argv"]
        or any(not isinstance(item, str) or not item for item in meta["argv"])
        or os.path.normcase(os.path.realpath(str(meta.get("cwd", ""))))
        != os.path.normcase(os.path.realpath(str(repository)))
        or not _utc(meta.get("started_at"))
        or not _utc(meta.get("finished_at"))
        or not isinstance(meta.get("exit_code"), int)
        or meta.get("parser") != "python-unittest-v1"
        or not isinstance(counts, dict)
        or set(counts) != {"run", "failures", "errors", "skipped"}
        or any(not isinstance(counts[name], int) or counts[name] < 0 for name in counts)
        or meta.get("evidence_class") not in EVIDENCE_CLASSES
        or not isinstance(ids, list)
        or ids != sorted(set(ids))
        or not set(ids) <= requirement_ids
        or "independent_exact_artifact_acceptance" in ids
        or not isinstance(executor, dict)
        or set(executor) != {"role", "identity"}
        or executor.get("role") not in {"implementer", "native_test_runner"}
        or executor.get("identity") != {"state": "unknown"}
        or _unittest_counts(log_bytes) != counts
        or (meta["exit_code"] == 0) != (counts["failures"] + counts["errors"] == 0)
    ):
        raise MatrixError("authenticated native execution evidence is invalid")
    return {
        **meta,
        "meta_digest": _digest(meta_bytes),
        "log_digest": _digest(log_bytes),
    }


def _independent_audit(
    repository: Path,
    artifact: dict,
    evidence_root: Path,
    reference: object,
) -> dict:
    if not isinstance(reference, dict) or set(reference) != {"audit_id", "meta", "report"}:
        raise MatrixError("independent audit reference is invalid")
    meta_bytes = _reference_bytes(repository, evidence_root, reference["meta"], "audit meta")
    report_bytes = _reference_bytes(repository, evidence_root, reference["report"], "audit report")
    try:
        meta = json.loads(meta_bytes.decode("utf-8"))
        report_bytes.decode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("independent audit evidence is not exact UTF-8") from error
    expected = {"schema", "audit_id", "category", "auditor", "artifact", "decision", "issued_at", "report_digest"}
    auditor = meta.get("auditor") if isinstance(meta, dict) else None
    if (
        not isinstance(meta, dict)
        or set(meta) != expected
        or meta.get("schema") != INDEPENDENT_AUDIT_META_SCHEMA
        or meta.get("audit_id") != reference.get("audit_id")
        or meta.get("category") not in {"semantic", "technical_security"}
        or not isinstance(auditor, dict)
        or set(auditor) != {"role", "principal_id", "identity"}
        or auditor.get("role") != "independent_auditor"
        or not isinstance(auditor.get("principal_id"), str)
        or not auditor["principal_id"]
        or auditor.get("identity") != {"state": "unknown"}
        or meta.get("artifact") != artifact
        or meta.get("decision") != "accepted"
        or not _utc(meta.get("issued_at"))
        or meta.get("report_digest") != _digest(report_bytes)
    ):
        raise MatrixError("independent exact-artifact audit evidence is invalid")
    return {**meta, "meta_digest": _digest(meta_bytes)}


def _native_incident(
    repository: Path,
    artifact: dict,
    role: str,
    evidence_root: Path,
    reference: object,
) -> dict:
    if not isinstance(reference, dict) or set(reference) != {"incident_id", "meta", "log"}:
        raise MatrixError("native incident reference is invalid")
    meta_bytes = _reference_bytes(repository, evidence_root, reference["meta"], "incident meta")
    log_bytes = _reference_bytes(repository, evidence_root, reference["log"], "incident log")
    try:
        meta = json.loads(meta_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("native incident meta is not exact UTF-8 JSON") from error
    expected = {
        "schema", "incident_id", "observed_at", "artifact", "role", "executor",
        "argv", "cwd", "result", "exit_code", "parser", "counts", "evidence_state",
        "reconciliation",
    }
    executor = meta.get("executor") if isinstance(meta, dict) else None
    observed = meta.get("artifact") if isinstance(meta, dict) else None
    counts = meta.get("counts") if isinstance(meta, dict) else None
    reconciliation = meta.get("reconciliation") if isinstance(meta, dict) else None
    if (
        not isinstance(meta, dict)
        or set(meta) != expected
        or meta.get("schema") != NATIVE_INCIDENT_META_SCHEMA
        or meta.get("incident_id") != reference.get("incident_id")
        or not _utc(meta.get("observed_at"))
        or not isinstance(observed, dict)
        or set(observed) != {"role", "commit", "tree"}
        or observed.get("role") != role
        or meta.get("role") != role
        or any(not re.fullmatch(r"[0-9a-f]{40}", str(observed.get(name, ""))) for name in ("commit", "tree"))
        or not isinstance(executor, dict)
        or set(executor) != {"role", "identity"}
        or executor.get("role") not in {"implementer", "native_test_runner"}
        or executor.get("identity") != {"state": "unknown"}
        or not isinstance(meta.get("argv"), list)
        or not meta["argv"]
        or any(not isinstance(item, str) or not item for item in meta["argv"])
        or os.path.normcase(os.path.realpath(str(meta.get("cwd", ""))))
        != os.path.normcase(os.path.realpath(str(repository)))
        or meta.get("result") != "failed"
        or not isinstance(meta.get("exit_code"), int)
        or meta["exit_code"] == 0
        or meta.get("parser") != "python-unittest-v1"
        or not isinstance(counts, dict)
        or set(counts) != {"run", "failures", "errors", "skipped"}
        or _unittest_counts(log_bytes) != counts
        or counts["failures"] + counts["errors"] == 0
        or meta.get("evidence_state") != "canonical_log"
        or not isinstance(reconciliation, dict)
        or set(reconciliation) != {"state", "exact_artifact"}
        or reconciliation.get("state") != "superseded_by_exact_artifact"
        or reconciliation.get("exact_artifact") != artifact
    ):
        raise MatrixError("native incident evidence is not exact and role-bound")
    return {**meta, "meta_digest": _digest(meta_bytes), "log_digest": _digest(log_bytes)}


def _host_execution_envelope(
    repository: Path,
    artifact: dict,
    role: str,
    envelope_path: object,
    requirement_ids: set[str],
) -> dict | None:
    if envelope_path is None:
        return None
    envelope_file = _external_path(repository, envelope_path, "host envelope")
    host = _canonical_host_home()
    if not host.is_absolute() or ".." in host.parts:
        raise MatrixError("host envelope authentication is unavailable")
    key_path = host / ".agents" / "engineering" / "controller" / "controller.key"
    key_bytes = _external_bytes(repository, key_path, "host controller key")
    try:
        key = bytes.fromhex(key_bytes.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError) as error:
        raise MatrixError("host envelope authentication is unavailable") from error
    if len(key) != 32:
        raise MatrixError("host envelope authentication is unavailable")
    envelope_bytes = _external_bytes(repository, envelope_file, "host envelope")
    try:
        envelope = json.loads(envelope_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("host envelope is not exact UTF-8 JSON") from error
    expected = {"schema", "issuer", "artifact", "evidence_root", "commands", "incidents", "audits", "signature"}
    if not isinstance(envelope, dict) or set(envelope) != expected:
        raise MatrixError("host envelope is invalid")
    payload = {name: value for name, value in envelope.items() if name != "signature"}
    expected_signature = "hmac-sha256:" + hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()
    issuer = envelope.get("issuer")
    if (
        envelope.get("schema") != HOST_EXECUTION_ENVELOPE_SCHEMA
        or not hmac.compare_digest(str(envelope.get("signature", "")), expected_signature)
        or not isinstance(issuer, dict)
        or set(issuer) != {"boundary_id", "key_id", "identity"}
        or issuer.get("boundary_id") != "native-host-controller"
        or issuer.get("key_id") != _digest(key)
        or issuer.get("identity") != {"state": "unknown"}
        or envelope.get("artifact") != artifact
        or not isinstance(envelope.get("commands"), list)
        or not isinstance(envelope.get("incidents"), list)
        or not isinstance(envelope.get("audits"), list)
    ):
        raise MatrixError("host envelope is not authenticated")
    evidence_root = _external_path(repository, envelope["evidence_root"], "host evidence root")
    if not evidence_root.is_dir():
        raise MatrixError("host evidence root is unavailable")
    commands = [
        _native_command(repository, artifact, role, evidence_root, item, requirement_ids)
        for item in envelope["commands"]
    ]
    command_ids = [item["command_id"] for item in commands]
    if len(command_ids) != len(set(command_ids)):
        raise MatrixError("native execution command IDs are duplicated")
    incidents = [
        _native_incident(repository, artifact, role, evidence_root, item)
        for item in envelope["incidents"]
    ]
    incident_ids = [item["incident_id"] for item in incidents]
    if len(incident_ids) != len(set(incident_ids)):
        raise MatrixError("native incident IDs are duplicated")
    audits = [
        _independent_audit(repository, artifact, evidence_root, item)
        for item in envelope["audits"]
    ]
    audit_ids = [item["audit_id"] for item in audits]
    if len(audit_ids) != len(set(audit_ids)):
        raise MatrixError("independent audit IDs are duplicated")
    return {
        "envelope_digest": _digest(envelope_bytes),
        "issuer": issuer,
        "commands": commands,
        "incidents": incidents,
        "audits": audits,
    }


def _canonical_host_home() -> Path:
    """Return the native host boundary; callers cannot substitute another key root."""
    return Path.home().resolve()


def matrix_digest(report: dict) -> str:
    return _digest(_canonical({key: value for key, value in report.items() if key != "matrix_digest"}))


def generate_matrix(
    root: Path,
    role: str,
    execution_envelope: object | None,
) -> dict:
    root = Path(root).resolve()
    artifact = _artifact(root, role)
    registry_bytes = _blob(root, artifact["commit"], "release/v2.2.6-requirements.json")
    try:
        requirements, obligations = _normalize_registry(
            json.loads(registry_bytes.decode("utf-8"))
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("authoritative requirement registry is invalid") from error
    receipt = _host_execution_envelope(
        root,
        artifact,
        role,
        execution_envelope,
        set(V226_REQUIRED_REQUIREMENTS),
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
        if requirement["id"] == "independent_exact_artifact_acceptance":
            audits = [] if receipt is None else receipt["audits"]
            categories = {item["category"] for item in audits}
            principals = {item["auditor"]["principal_id"] for item in audits}
            satisfying = (
                audits
                if categories == {"semantic", "technical_security"}
                and len(principals) == 2
                else []
            )
        else:
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
                "evidence_command_ids": [
                    item.get("command_id", item.get("audit_id")) for item in satisfying
                ],
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
        "execution_receipt_digest": receipt["envelope_digest"] if receipt else None,
        "rows": rows,
        "obligations": obligations,
        "unknowns": sorted(unknowns),
        "proxy_rejections": sorted(proxy_rejections),
        "gates": gates,
        "incidents": [] if receipt is None else receipt["incidents"],
        "independent_audits": [] if receipt is None else receipt["audits"],
    }
    report["matrix_digest"] = matrix_digest(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(prog="v226-release-matrix")
    parser.add_argument("root")
    parser.add_argument("--role", choices=("internal", "public"), required=True)
    parser.add_argument("--execution-envelope")
    arguments = parser.parse_args()
    try:
        print(
            json.dumps(
                generate_matrix(
                    Path(arguments.root),
                    arguments.role,
                    arguments.execution_envelope,
                )
            )
        )
    except (OSError, MatrixError) as error:
        print(f"ERROR: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
