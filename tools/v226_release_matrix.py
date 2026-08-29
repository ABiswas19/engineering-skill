from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath

_SHARED_SCRIPTS = str(
    Path(__file__).resolve().parents[1] / ".agents" / "skills" / "engineering" / "scripts"
)
sys.path.insert(0, _SHARED_SCRIPTS)
try:
    from engineering_host_boundary import (
        HostBoundaryError,
        canonical_host_home as _shared_canonical_host_home,
        reject_reparse_ancestors as _shared_reject_reparse_ancestors,
        verify_owner_private as _shared_verify_owner_private,
    )
finally:
    sys.path.remove(_SHARED_SCRIPTS)


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
    "adjacent_tool_comparison_gate",
    "authenticated_execution_envelopes",
    "deterministic_release_matrix",
    "external_consumer_authority",
    "exact_release_install_binding",
    "external_owner_authority",
    "external_owner_source_projection",
    "git_object_byte_identity",
    "graph_execution_semantics",
    "graph_one_writer_enforcement",
    "host_private_postactivation_trust",
    "hostile_git_environment",
    "independent_equivalence",
    "independent_exact_artifact_acceptance",
    "intent_digest_continuity",
    "model_routing_disclosure",
    "named_consumer_contract_correction",
    "native_harness_real_outcome_gate",
    "noncircular_bootstrap",
    "outcome_survival_baseline",
    "postactivation_all_outcomes_binding",
    "per_outcome_dispatch_mapping",
    "predecessor_disposition",
    "public_sanitized_parity",
    "readme_native_observability_truth",
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
    "graph_false_edge_rejection",
    "graph_amdahl_parallelism_semantics",
    "graph_fresh_verifier_enforcement",
    "graph_critical_path_enforcement",
    "graph_full_one_writer_enforcement",
    "readme_contract_truth",
    "langfuse_deferred",
    "v226_activation_boundary",
    "postactivation_completeness_import",
    "all_owner_outcome_release_enforcement",
    "native_codex_claude_harness_proof",
    "adjacent_orchestrator_comparison",
    "successor_runtime_delivery",
    "capability_observability_api",
    "named_consumer_contract_correction",
    "primary_consumer_integration",
    "external_consumer_owner_receipt",
    "external_consumer_integration",
    "unified_product",
    "remaining_plugin_independent_frontend",
    "full_consumer_release_gate",
)
OWNER_LEDGER_FIELDS = {
    "schema",
    "source_requirements",
    "pending_requirements",
    "pending_obligations",
    "requirements",
    "obligations",
}
OWNER_SOURCE_SUPPORT = {
    "OWNER-V226-AUTHENTICATED-RUN-RECEIPTS": {
        "excerpt": "authenticated run receipts",
        "requirements": {"authenticated_execution_envelopes"},
        "obligations": {"first_pass_incident_preservation"},
    },
    "OWNER-V226-EXACT-SOURCE-INSTALL": {
        "excerpt": "exact source/install",
        "requirements": {"exact_release_install_binding"},
        "obligations": set(),
    },
    "OWNER-V226-GIT-OBJECT-BINDING": {
        "excerpt": "Git-object binding",
        "requirements": {"git_object_byte_identity"},
        "obligations": set(),
    },
    "OWNER-V226-INDEPENDENT-EQUIVALENCE": {
        "excerpt": "independent equivalence review",
        "requirements": {"independent_equivalence"},
        "obligations": set(),
    },
    "OWNER-V226-MODEL-ROUTING-DISCLOSURE": {
        "excerpt": "full model-routing disclosure",
        "requirements": {"model_routing_disclosure"},
        "obligations": set(),
    },
    "OWNER-V226-TRANSACTIONAL-PREIMAGES": {
        "excerpt": "transactional preimage checks",
        "requirements": {"transactional_install_preimages"},
        "obligations": set(),
    },
    "OWNER-V226-PREVIEW-FIRST-SETUP": {
        "excerpt": "preview-first setup",
        "requirements": set(),
        "obligations": {"project_setup_preview_authority"},
    },
    "OWNER-V226-BOUNDED-VERIFIED-MAINTENANCE": {
        "excerpt": "bounded verified maintenance",
        "requirements": set(),
        "obligations": {"bounded_maintenance"},
    },
    "OWNER-V226-EXTERNAL-CONSUMER": {
        "excerpt": None,
        "requirements": {"external_consumer_authority"},
        "obligations": {
            "external_consumer_owner_receipt",
            "external_consumer_integration",
        },
    },
}


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


def _normalize_registry(
    value: object, owner_ledger: object | None = None
) -> tuple[list[dict], list[dict]]:
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
    if (
        not isinstance(owner_ledger, dict)
        or set(owner_ledger) != OWNER_LEDGER_FIELDS
        or owner_ledger.get("schema")
        != "engineering.v2.2.6-owner-approved-ledger.v2"
        or not isinstance(owner_ledger.get("source_requirements"), list)
        or not isinstance(owner_ledger.get("pending_requirements"), list)
        or not isinstance(owner_ledger.get("pending_obligations"), list)
        or not isinstance(owner_ledger.get("requirements"), list)
        or not isinstance(owner_ledger.get("obligations"), list)
    ):
        raise MatrixError("external owner ledger is required and invalid")
    owner_ids = [
        row.get("id")
        for row in owner_ledger["requirements"]
        if isinstance(row, dict)
    ]
    if (
        ids != owner_ids
        or len(ids) != len(set(ids))
        or any(not isinstance(item, str) or not item for item in ids)
    ):
        raise MatrixError("candidate registry mismatches external owner ledger")
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
            or set(evidence) != {"gate", "minimum_class", "interface", "environment"}
            or evidence.get("gate") not in GATES
            or evidence.get("minimum_class") not in EVIDENCE_CLASSES
            or not isinstance(evidence.get("interface"), str)
            or not evidence["interface"]
            or not isinstance(evidence.get("environment"), str)
            or not evidence["environment"]
            or not isinstance(row.get("runtime_behavior"), str)
            or not row["runtime_behavior"]
        ):
            raise MatrixError("authoritative requirement evidence contract is invalid")
        normalized.append(dict(row))
    obligation_rows = value["obligations"]
    obligation_ids = [row.get("id") for row in obligation_rows if isinstance(row, dict)]
    if (
        len(obligation_ids) != len(set(obligation_ids))
        or any(not isinstance(item, str) or not item for item in obligation_ids)
    ):
        raise MatrixError("authoritative obligation coverage is invalid")
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
    owner_requirements = normalized
    if (
        owner_ledger["requirements"] != owner_requirements
        or owner_ledger["obligations"] != normalized_obligations
    ):
        raise MatrixError("candidate registry mismatches external owner ledger")
    _validate_owner_source_projection(owner_ledger)
    return normalized, normalized_obligations


def _validate_owner_source_projection(
    owner_ledger: object, source_bytes: bytes | None = None
) -> list[dict]:
    """Validate the independently authored mapping from owner source to registry."""
    if (
        not isinstance(owner_ledger, dict)
        or owner_ledger.get("schema")
        != "engineering.v2.2.6-owner-approved-ledger.v2"
        or not isinstance(owner_ledger.get("requirements"), list)
        or not isinstance(owner_ledger.get("obligations"), list)
        or not isinstance(owner_ledger.get("source_requirements"), list)
        or not owner_ledger["source_requirements"]
        or not isinstance(owner_ledger.get("pending_requirements"), list)
        or not isinstance(owner_ledger.get("pending_obligations"), list)
    ):
        raise MatrixError("external owner source projection is invalid")
    requirement_ids = [
        row.get("id") for row in owner_ledger["requirements"] if isinstance(row, dict)
    ]
    obligation_ids = [
        row.get("id") for row in owner_ledger["obligations"] if isinstance(row, dict)
    ]
    if (
        len(requirement_ids) != len(owner_ledger["requirements"])
        or len(obligation_ids) != len(owner_ledger["obligations"])
        or any(not isinstance(item, str) or not item for item in requirement_ids + obligation_ids)
    ):
        raise MatrixError("external owner source projection is invalid")
    normalized = []
    mapped_requirements: list[str] = []
    mapped_obligations: list[str] = []
    source_ids: set[str] = set()
    expected = {
        "source_requirement_id",
        "lifecycle_state",
        "source_excerpt",
        "statement_digest",
        "requirement_ids",
        "obligation_ids",
    }
    for row in owner_ledger["source_requirements"]:
        if (
            not isinstance(row, dict)
            or set(row) != expected
            or not isinstance(row.get("source_requirement_id"), str)
            or not row["source_requirement_id"]
            or row["source_requirement_id"] in source_ids
            or row.get("lifecycle_state") != "OWNER_APPROVED"
            or not isinstance(row.get("source_excerpt"), str)
            or not row["source_excerpt"].strip()
            or not isinstance(row.get("requirement_ids"), list)
            or not isinstance(row.get("obligation_ids"), list)
            or len(row["requirement_ids"]) != len(set(row["requirement_ids"]))
            or len(row["obligation_ids"]) != len(set(row["obligation_ids"]))
            or any(not isinstance(item, str) or not item for item in row["requirement_ids"])
            or any(not isinstance(item, str) or not item for item in row["obligation_ids"])
        ):
            raise MatrixError("external owner source projection is invalid")
        excerpt_bytes = row["source_excerpt"].encode("utf-8")
        support = OWNER_SOURCE_SUPPORT.get(row["source_requirement_id"])
        if row.get("statement_digest") != _digest(excerpt_bytes):
            raise MatrixError("external owner source projection is invalid")
        if support is None:
            if row["requirement_ids"] or row["obligation_ids"]:
                raise MatrixError("external owner source projection is semantically invalid")
        elif (
            (support["excerpt"] is not None and row["source_excerpt"] != support["excerpt"])
            or not set(row["requirement_ids"]).issubset(support["requirements"])
            or not set(row["obligation_ids"]).issubset(support["obligations"])
        ):
            raise MatrixError("external owner source projection is semantically invalid")
        if source_bytes is not None and source_bytes.count(excerpt_bytes) != 1:
            raise MatrixError("external owner source projection is mismatched")
        source_ids.add(row["source_requirement_id"])
        mapped_requirements.extend(row["requirement_ids"])
        mapped_obligations.extend(row["obligation_ids"])
        normalized.append(dict(row))
    def pending_ids(rows: object) -> list[str]:
        if not isinstance(rows, list):
            raise MatrixError("external owner source projection pending state is invalid")
        values = []
        for item in rows:
            if (
                not isinstance(item, dict)
                or set(item) != {"id", "state", "reason"}
                or not isinstance(item.get("id"), str)
                or item.get("state") != "pending"
                or not isinstance(item.get("reason"), str)
                or not item["reason"].strip()
            ):
                raise MatrixError("external owner source projection pending state is invalid")
            values.append(item["id"])
        return values

    pending_requirements = pending_ids(owner_ledger["pending_requirements"])
    pending_obligations = pending_ids(owner_ledger["pending_obligations"])
    if (
        len(mapped_requirements) != len(set(mapped_requirements))
        or len(mapped_obligations) != len(set(mapped_obligations))
        or len(pending_requirements) != len(set(pending_requirements))
        or len(pending_obligations) != len(set(pending_obligations))
        or set(mapped_requirements) & set(pending_requirements)
        or set(mapped_obligations) & set(pending_obligations)
        or sorted(mapped_requirements + pending_requirements) != sorted(requirement_ids)
        or sorted(mapped_obligations + pending_obligations) != sorted(obligation_ids)
    ):
        raise MatrixError("external owner source projection is incomplete or conflicting")
    return normalized


def _native_message_text(value: object, expected_role: str) -> tuple[dict, str]:
    if not isinstance(value, dict) or value.get("type") != "response_item":
        raise MatrixError("native decision source is invalid")
    payload = value.get("payload")
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "message"
        or payload.get("role") != expected_role
        or not isinstance(payload.get("id"), str)
        or not payload["id"]
        or not isinstance(payload.get("content"), list)
        or len(payload["content"]) != 1
    ):
        raise MatrixError("native decision source is invalid")
    content = payload["content"][0]
    expected_content = "output_text" if expected_role == "assistant" else "input_text"
    metadata = payload.get("internal_chat_message_metadata_passthrough")
    if (
        not isinstance(content, dict)
        or content.get("type") != expected_content
        or not isinstance(content.get("text"), str)
        or not isinstance(metadata, dict)
        or not isinstance(metadata.get("turn_id"), str)
        or not metadata["turn_id"]
    ):
        raise MatrixError("native decision source is invalid")
    return payload, content["text"]


def _native_source_line(source_path: Path, line_number: int) -> bytes:
    if not isinstance(line_number, int) or isinstance(line_number, bool) or line_number < 1:
        raise MatrixError("native decision source is invalid")
    with source_path.open("rb") as source:
        for current, line in enumerate(source, 1):
            if current == line_number:
                if line.endswith(b"\n"):
                    line = line[:-1]
                if line.endswith(b"\r"):
                    line = line[:-1]
                return line
    raise MatrixError("native decision source is invalid")


def _validate_native_record(
    record: object, source_path: Path, expected_role: str
) -> tuple[dict, str]:
    expected = {
        "line_number",
        "message_id",
        "turn_id",
        "timestamp",
        "role",
        "excerpt",
        "excerpt_digest",
        "excerpt_utf8_span",
        "raw_line_digest",
    }
    if (
        not isinstance(record, dict)
        or set(record) != expected
        or record.get("role") != expected_role
        or not isinstance(record.get("message_id"), str)
        or not record["message_id"]
        or not isinstance(record.get("turn_id"), str)
        or not record["turn_id"]
        or not isinstance(record.get("timestamp"), str)
        or not _utc(record["timestamp"])
        or not isinstance(record.get("excerpt"), str)
        or not record["excerpt"].strip()
    ):
        raise MatrixError("native decision source is invalid")
    raw = _native_source_line(source_path, record["line_number"])
    if record.get("raw_line_digest") != _digest(raw):
        raise MatrixError("native decision source is mismatched")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("native decision source is invalid") from error
    payload, text = _native_message_text(value, expected_role)
    metadata = payload["internal_chat_message_metadata_passthrough"]
    if (
        value.get("timestamp") != record["timestamp"]
        or payload["id"] != record["message_id"]
        or metadata["turn_id"] != record["turn_id"]
    ):
        raise MatrixError("native decision source is mismatched")
    excerpt_bytes = record["excerpt"].encode("utf-8")
    span = record.get("excerpt_utf8_span")
    text_bytes = text.encode("utf-8")
    if (
        record.get("excerpt_digest") != _digest(excerpt_bytes)
        or not isinstance(span, dict)
        or set(span) != {"start", "end"}
        or not isinstance(span.get("start"), int)
        or isinstance(span.get("start"), bool)
        or not isinstance(span.get("end"), int)
        or isinstance(span.get("end"), bool)
        or span["start"] < 0
        or span["end"] <= span["start"]
        or span["end"] > len(text_bytes)
        or text_bytes[span["start"] : span["end"]] != excerpt_bytes
    ):
        raise MatrixError("native decision source is mismatched")
    return value, text


def _native_owner_request(text: str) -> str:
    """Remove only Codex's typed ambient-context wrapper from a user request."""
    request = text.strip()
    if request.startswith('<in-app-browser-context source="ambient-ui-state">'):
        ambient = re.match(
            r'\A<in-app-browser-context source="ambient-ui-state">\s*.*?\s*'
            r"</in-app-browser-context>\s*",
            request,
            flags=re.DOTALL,
        )
        if ambient is None:
            raise MatrixError("native decision source is not affirmatively linked")
        request = request[ambient.end() :].strip()
    heading = "## My request:"
    if request.startswith(heading):
        request = request[len(heading) :].strip()
    return request


def _proposal_affirmatively_links_decision(text: str, decision_id: str) -> bool:
    """Accept one exact-ID request or the one bounded nine-safeguard request."""
    commands = list(
        re.finditer(
            r"(?i)\brecommendation\s*:\s*(?:explicitly\s+)?approve\b",
            text,
        )
    )
    if len(commands) != 1:
        return False
    if re.search(
        r"(?i)\b(?:change|changed|switch|replace)(?:\s+to)?\s+"
        r"(?:the\s+)?decision\b|\bdecision\s+(?:to|is now)\b",
        text,
    ):
        return False
    remainder = text[commands[0].end() :]
    boundary = r"(?=$|[\s;:,.!?—–])"
    exact = re.match(r"\s+" + re.escape(decision_id) + boundary, remainder)
    if exact and not re.match(
        r"(?i)\s*(?:/|\bor\b|\band\b)\s*[A-Za-z0-9][A-Za-z0-9._-]{2,127}",
        remainder[exact.end() :],
    ):
        return True
    return bool(
        re.match(
            r"(?i)\s+the\s+nine\s+missing\s+Engineering\s+release\s+"
            r"safeguards" + boundary,
            remainder,
        )
    )


def _validate_native_decision_source_receipt(
    receipt_path: Path, owner_ledger: object, repository: Path
) -> dict:
    """Resolve one host-owned native proposal/approval receipt exactly."""
    receipt_path = Path(receipt_path)
    repository = repository.resolve(strict=True)
    try:
        if not receipt_path.is_absolute() or ".." in receipt_path.parts:
            raise MatrixError("native decision source path is invalid")
        _reject_host_reparse_ancestors(receipt_path)
        receipt_path = receipt_path.resolve(strict=True)
        if receipt_path.is_relative_to(repository):
            raise MatrixError("native decision source is candidate-controlled")
        _verify_owner_private_path(receipt_path, directory=False)
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("native decision source is unavailable") from error
    if _canonical(receipt) != receipt_bytes:
        raise MatrixError("native decision source is not canonical UTF-8")
    expected = {
        "schema",
        "decision_id",
        "lifecycle_state",
        "native_source",
        "proposal",
        "approval",
        "proposal_binding",
        "safeguards",
    }
    source = receipt.get("native_source") if isinstance(receipt, dict) else None
    if (
        not isinstance(receipt, dict)
        or set(receipt) != expected
        or receipt.get("schema")
        != "engineering.owner-approved-native-decision-source.v2"
        or not isinstance(receipt.get("decision_id"), str)
        or not receipt["decision_id"]
        or receipt.get("lifecycle_state") != "OWNER_APPROVED"
        or not isinstance(source, dict)
        or set(source) != {"schema", "kind", "path", "digest", "length"}
        or source.get("schema") != "engineering.native-codex-session-jsonl.v1"
        or source.get("kind") != "codex_session_jsonl"
        or not isinstance(source.get("path"), str)
        or not isinstance(source.get("length"), int)
        or source["length"] < 1
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(source.get("digest", "")))
        or not isinstance(receipt.get("safeguards"), list)
        or len(receipt["safeguards"]) != 9
    ):
        raise MatrixError("native decision source is invalid")
    source_path = Path(source["path"])
    try:
        if not source_path.is_absolute() or ".." in source_path.parts:
            raise MatrixError("native decision source is invalid")
        _reject_host_reparse_ancestors(source_path)
        source_path = source_path.resolve(strict=True)
        if source_path.is_relative_to(repository):
            raise MatrixError("native decision source is candidate-controlled")
        _verify_owner_private_path(source_path, directory=False)
        source_bytes = source_path.read_bytes()
    except OSError as error:
        raise MatrixError("native decision source is unavailable") from error
    if (
        str(source_path) != source["path"]
        or len(source_bytes) != source["length"]
        or _digest(source_bytes) != source["digest"]
    ):
        raise MatrixError("native decision source is mismatched")
    _, proposal_text = _validate_native_record(
        receipt["proposal"], source_path, "assistant"
    )
    _, approval_text = _validate_native_record(
        receipt["approval"], source_path, "user"
    )
    if (
        receipt["proposal"]["line_number"] >= receipt["approval"]["line_number"]
        or _utc_instant(receipt["proposal"]["timestamp"])
        >= _utc_instant(receipt["approval"]["timestamp"])
    ):
        raise MatrixError("native decision source is ill-ordered")
    decision_id = receipt["decision_id"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}", decision_id):
        raise MatrixError("native decision source is not affirmatively linked")
    binding = receipt.get("proposal_binding")
    ledger_rows = _validate_owner_source_projection(owner_ledger)
    binding_expected = {
        "decision_id",
        "proposal_line_number",
        "proposal_message_id",
        "proposal_turn_id",
        "safeguard_projection_digest",
    }
    if (
        not isinstance(binding, dict)
        or set(binding) != binding_expected
        or binding.get("decision_id") != decision_id
        or binding.get("proposal_line_number")
        != receipt["proposal"]["line_number"]
        or binding.get("proposal_message_id")
        != receipt["proposal"]["message_id"]
        or binding.get("proposal_turn_id") != receipt["proposal"]["turn_id"]
        or binding.get("safeguard_projection_digest")
        != _digest(_canonical(ledger_rows))
    ):
        raise MatrixError("native decision source is not affirmatively linked")
    if not _proposal_affirmatively_links_decision(proposal_text, decision_id):
        raise MatrixError("native decision source is not affirmatively linked")
    approval = _native_owner_request(approval_text)
    if (
        receipt["approval"]["excerpt"] != approval
        or approval.casefold()
        not in {
            f"{decision_id} approved".casefold(),
            f"approve {decision_id}".casefold(),
            f"approved {decision_id}".casefold(),
            f"yes, approve {decision_id}".casefold(),
            f"yes: approve {decision_id}".casefold(),
        }
    ):
        raise MatrixError("native decision source is not affirmatively linked")
    normalized_safeguards = []
    for safeguard in receipt["safeguards"]:
        if not isinstance(safeguard, dict):
            raise MatrixError("native decision source is invalid")
        span = safeguard.get("proposal_excerpt_utf8_span")
        row = {name: value for name, value in safeguard.items() if name != "proposal_excerpt_utf8_span"}
        excerpt = row.get("source_excerpt")
        excerpt_bytes = excerpt.encode("utf-8") if isinstance(excerpt, str) else b""
        proposal_bytes = proposal_text.encode("utf-8")
        if (
            set(safeguard) != {
                "source_requirement_id", "lifecycle_state", "source_excerpt",
                "statement_digest", "requirement_ids", "obligation_ids",
                "proposal_excerpt_utf8_span",
            }
            or not isinstance(span, dict)
            or set(span) != {"start", "end"}
            or not isinstance(span.get("start"), int)
            or isinstance(span.get("start"), bool)
            or not isinstance(span.get("end"), int)
            or isinstance(span.get("end"), bool)
            or span["start"] < 0
            or span["end"] <= span["start"]
            or span["end"] > len(proposal_bytes)
            or proposal_bytes[span["start"] : span["end"]] != excerpt_bytes
        ):
            raise MatrixError("native decision source safeguard is mismatched")
        normalized_safeguards.append(row)
    if normalized_safeguards != ledger_rows:
        raise MatrixError("native decision source safeguard mapping is mismatched")
    return receipt


def _resolve_owner_source_evidence(
    source: object, owner_ledger: object, repository: Path
) -> dict:
    """Resolve the signed source kind without accepting caller path substitution."""
    if not isinstance(source, dict):
        raise MatrixError("owner-approved source evidence is invalid")
    common = {"schema", "kind", "path", "digest", "length", "version"}
    if source.get("schema") == "engineering.owner-approved-bootstrap-source.v1":
        expected = common | {"automation_id"}
        if (
            set(source) != expected
            or source.get("kind") != "codex_automation_prompt"
            or not isinstance(source.get("automation_id"), str)
            or not source["automation_id"]
        ):
            raise MatrixError("owner-approved source evidence is invalid")
        native = False
    elif source.get("schema") == "engineering.owner-approved-bootstrap-source.v2":
        expected = common | {"source_id"}
        if (
            set(source) != expected
            or source.get("kind") != "codex_native_decision_receipt"
            or not isinstance(source.get("source_id"), str)
            or not source["source_id"]
        ):
            raise MatrixError("owner-approved source evidence is invalid")
        native = True
    else:
        raise MatrixError("owner-approved source evidence is invalid")
    if (
        not isinstance(source.get("path"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(source.get("digest", "")))
        or not isinstance(source.get("length"), int)
        or isinstance(source.get("length"), bool)
        or source["length"] < 1
        or not isinstance(source.get("version"), str)
        or not source["version"]
    ):
        raise MatrixError("owner-approved source evidence is invalid")
    repository = repository.resolve(strict=True)
    source_path = Path(source["path"])
    try:
        if not source_path.is_absolute() or ".." in source_path.parts:
            raise MatrixError("owner-approved source evidence is invalid")
        _reject_host_reparse_ancestors(source_path)
        source_path = source_path.resolve(strict=True)
        if source_path.is_relative_to(repository):
            raise MatrixError("owner-approved source evidence is candidate-controlled")
        _verify_owner_private_path(source_path, directory=False)
        source_bytes = source_path.read_bytes()
    except OSError as error:
        raise MatrixError("owner-approved source evidence is unavailable") from error
    if (
        str(source_path) != source["path"]
        or len(source_bytes) != source["length"]
        or _digest(source_bytes) != source["digest"]
    ):
        raise MatrixError("owner-approved source evidence is mismatched")
    if native:
        receipt = _validate_native_decision_source_receipt(
            source_path, owner_ledger, repository
        )
        if receipt["decision_id"] != source["source_id"]:
            raise MatrixError("owner-approved source evidence is mismatched")
        return receipt
    _validate_owner_source_projection(owner_ledger, source_bytes)
    return {
        "schema": source["schema"],
        "kind": source["kind"],
        "automation_id": source["automation_id"],
    }


def _normalize_requirements(value: object) -> list[dict]:
    """Compatibility helper retained for callers that only consume matrix rows."""
    return _normalize_registry(value)[0]


def _external_path(repository: Path, value: object, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise MatrixError(f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise MatrixError(f"{label} path is invalid")
    _reject_host_reparse_ancestors(path)
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
    evidence_root = _external_path(repository, evidence_root, "host evidence root")
    relative = PurePosixPath(value["path"])
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise MatrixError(f"{label} reference is invalid")
    path = _external_path(
        repository, evidence_root / Path(*relative.parts), label
    )
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


def _native_execution_profile(argv: object, selector: object) -> dict:
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item for item in argv)
        or not isinstance(selector, str)
        or not re.fullmatch(r"test_[A-Za-z0-9_]+", selector)
    ):
        raise MatrixError("native execution is not selector-specific")
    normalized = [item.replace("\\", "/") for item in argv]
    targeted_engineering = (
        len(normalized) == 3
        and normalized[1].endswith(
            ".agents/skills/engineering/tests/test_engineering.py"
        )
        and normalized[2].split(".")[-1] == selector
    )
    targeted_repository = (
        len(normalized) == 4
        and normalized[1:3] == ["-m", "unittest"]
        and normalized[3].startswith("tests.test_repository.")
        and normalized[3].split(".")[-1] == selector
    )
    if not targeted_engineering and not targeted_repository:
        raise MatrixError("native execution is not selector-specific")
    return {
        "profile": "python-unittest-exact-selector-v1",
        "evidence_class": "integration",
        "interface": f"python-unittest-selector:{selector}",
        "environment": "isolated_exact_git_contract_fixture",
    }


def _utc_instant(value: object) -> datetime:
    if not _utc(value):
        raise MatrixError("native evidence timestamp is invalid")
    try:
        instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise MatrixError("native evidence timestamp is invalid") from error
    if instant.tzinfo is None:
        raise MatrixError("native evidence timestamp is invalid")
    return instant.astimezone(timezone.utc)


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
    if isinstance(meta, dict) and (
        "evidence_class" in meta or "requirement_ids" in meta
    ):
        raise MatrixError(
            "self-declared native evidence is prohibited; selector-specific receipt required"
        )
    expected = {
        "schema", "command_id", "executor", "artifact_before", "artifact_after",
        "role", "argv", "cwd", "started_at", "finished_at", "exit_code", "parser",
        "counts", "selector",
    }
    counts = meta.get("counts") if isinstance(meta, dict) else None
    executor = meta.get("executor") if isinstance(meta, dict) else None
    try:
        profile = _native_execution_profile(
            meta.get("argv") if isinstance(meta, dict) else None,
            meta.get("selector") if isinstance(meta, dict) else None,
        )
    except MatrixError:
        profile = None
    try:
        started = _utc_instant(meta.get("started_at") if isinstance(meta, dict) else None)
        finished = _utc_instant(meta.get("finished_at") if isinstance(meta, dict) else None)
        fresh = (
            started <= finished
            and finished <= datetime.now(timezone.utc) + timedelta(minutes=5)
            and datetime.now(timezone.utc) - finished <= timedelta(days=30)
        )
    except MatrixError:
        fresh = False
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
        or not fresh
        or not isinstance(meta.get("exit_code"), int)
        or meta.get("parser") != "python-unittest-v1"
        or not isinstance(counts, dict)
        or set(counts) != {"run", "failures", "errors", "skipped"}
        or any(not isinstance(counts[name], int) or counts[name] < 0 for name in counts)
        or profile is None
        or counts.get("run") != 1
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
        "actual_evidence_class": profile["evidence_class"],
        "actual_interface": profile["interface"],
        "actual_environment": profile["environment"],
        "execution_profile": profile["profile"],
        "meta_digest": _digest(meta_bytes),
        "log_digest": _digest(log_bytes),
    }


def _validate_command_set(commands: list[dict]) -> None:
    by_selector: dict[str, list[dict]] = {}
    for command in commands:
        by_selector.setdefault(command["selector"], []).append(command)
    for items in by_selector.values():
        if len(items) == 1:
            continue
        outcomes = {
            (
                item["exit_code"] == 0
                and item["counts"]["failures"] == 0
                and item["counts"]["errors"] == 0
            )
            for item in items
        }
        if len(outcomes) > 1:
            raise MatrixError(
                "native execution pass/fail conflict is unreconciled for a requirement"
            )
        raise MatrixError("native execution evidence is ambiguous for a requirement")


def _independent_audit(
    repository: Path,
    artifact: dict,
    evidence_root: Path,
    reference: object,
    expected_auditor: dict,
    allowed_signers: bytes,
) -> dict:
    if not isinstance(reference, dict) or set(reference) != {
        "audit_id", "meta", "report", "signature"
    }:
        raise MatrixError("independent audit reference is invalid")
    meta_bytes = _reference_bytes(repository, evidence_root, reference["meta"], "audit meta")
    report_bytes = _reference_bytes(repository, evidence_root, reference["report"], "audit report")
    signature_bytes = _reference_bytes(
        repository, evidence_root, reference["signature"], "audit signature"
    )
    try:
        meta = json.loads(meta_bytes.decode("utf-8"))
        report_bytes.decode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("independent audit evidence is not exact UTF-8") from error
    expected = {"schema", "audit_id", "category", "auditor", "artifact", "decision", "issued_at", "report_digest"}
    auditor = meta.get("auditor") if isinstance(meta, dict) else None
    try:
        issued = _utc_instant(meta.get("issued_at") if isinstance(meta, dict) else None)
        fresh = (
            issued <= datetime.now(timezone.utc) + timedelta(minutes=5)
            and datetime.now(timezone.utc) - issued <= timedelta(days=30)
        )
    except MatrixError:
        fresh = False
    if (
        not isinstance(meta, dict)
        or set(meta) != expected
        or meta.get("schema") != INDEPENDENT_AUDIT_META_SCHEMA
        or meta.get("audit_id") != reference.get("audit_id")
        or meta.get("category") != expected_auditor.get("category")
        or not isinstance(auditor, dict)
        or set(auditor) != {"role", "principal_id", "signer_fingerprint", "identity"}
        or auditor.get("role") != "independent_auditor"
        or auditor.get("principal_id") != expected_auditor.get("principal_id")
        or auditor.get("signer_fingerprint")
        != expected_auditor.get("signer_fingerprint")
        or auditor.get("signer_fingerprint")
        != _allowed_signer_fingerprint(allowed_signers, auditor.get("principal_id", ""))
        or auditor.get("identity") != {"state": "unknown"}
        or meta.get("artifact") != artifact
        or meta.get("decision") != "accepted"
        or not fresh
        or meta.get("report_digest") != _digest(report_bytes)
    ):
        raise MatrixError("independent exact-artifact audit evidence is invalid")
    try:
        signature = signature_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise MatrixError("independent audit signature is invalid") from error
    if not signature.startswith("-----BEGIN SSH SIGNATURE-----\n") or len(signature) > 16384:
        raise MatrixError("independent audit signature is invalid")
    with tempfile.TemporaryDirectory(prefix="engineering-independent-audit-") as temporary:
        temporary_path = Path(temporary)
        signers_copy = temporary_path / "allowed-signers"
        signature_copy = temporary_path / "audit.sig"
        signers_copy.write_bytes(allowed_signers)
        signature_copy.write_text(signature, encoding="ascii")
        try:
            verified = subprocess.run(
                [
                    "ssh-keygen", "-Y", "verify", "-f", str(signers_copy),
                    "-I", auditor["principal_id"],
                    "-n", f"engineering-v226-{meta['category']}-audit",
                    "-s", str(signature_copy),
                ],
                input=_canonical(
                    {
                        "schema": "engineering.independent-audit-claims.v1",
                        "meta": meta,
                    }
                ),
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MatrixError("independent audit signature verification is unavailable") from error
    if verified.returncode != 0:
        raise MatrixError("independent audit signature is invalid")
    return {
        **meta,
        "meta_digest": _digest(meta_bytes),
        "signature_digest": _digest(signature_bytes),
    }


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
    owner_baseline: dict,
) -> dict | None:
    if envelope_path is None:
        return None
    envelope_file = _external_path(repository, envelope_path, "host envelope")
    host = _canonical_host_home()
    if not host.is_absolute() or ".." in host.parts:
        raise MatrixError("host envelope authentication is unavailable")
    key_path = host / ".agents" / "engineering" / "controller" / "attestation.key"
    _reject_host_reparse_ancestors(key_path, host)
    _verify_owner_private_path(key_path.parent, directory=True)
    _verify_owner_private_path(key_path, directory=False)
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
    _validate_command_set(commands)
    incidents = [
        _native_incident(repository, artifact, role, evidence_root, item)
        for item in envelope["incidents"]
    ]
    incident_ids = [item["incident_id"] for item in incidents]
    if len(incident_ids) != len(set(incident_ids)):
        raise MatrixError("native incident IDs are duplicated")
    auditor_contracts = {
        item["category"]: item for item in owner_baseline["role_separation"]["auditors"]
    }
    audits = []
    for item in envelope["audits"]:
        category = item.get("category") if isinstance(item, dict) else None
        if category is None and isinstance(item, dict):
            meta_reference = item.get("meta")
            if isinstance(meta_reference, dict):
                try:
                    meta_preview = json.loads(
                        _reference_bytes(
                            repository, evidence_root, meta_reference, "audit meta"
                        ).decode("utf-8")
                    )
                    category = meta_preview.get("category")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    category = None
        expected_auditor = auditor_contracts.get(category)
        if expected_auditor is None:
            raise MatrixError("independent audit role is not externally authorized")
        audits.append(
            _independent_audit(
                repository,
                artifact,
                evidence_root,
                item,
                expected_auditor,
                owner_baseline["allowed_signers"],
            )
        )
    audit_ids = [item["audit_id"] for item in audits]
    if len(audit_ids) != len(set(audit_ids)):
        raise MatrixError("independent audit IDs are duplicated")
    if len({item["category"] for item in audits}) != len(audits):
        raise MatrixError("independent audit categories are duplicated")
    if commands and audits:
        last_command = max(_utc_instant(item["finished_at"]) for item in commands)
        if any(_utc_instant(item["issued_at"]) < last_command for item in audits):
            raise MatrixError("independent audit evidence is ill-ordered")
    return {
        "envelope_digest": _digest(envelope_bytes),
        "issuer": issuer,
        "commands": commands,
        "incidents": incidents,
        "audits": audits,
    }


def _canonical_host_home() -> Path:
    try:
        return _shared_canonical_host_home()
    except HostBoundaryError as error:
        raise MatrixError("canonical host boundary is unavailable") from error


def _reject_host_reparse_ancestors(path: Path, boundary: Path | None = None) -> None:
    try:
        _shared_reject_reparse_ancestors(path, boundary)
    except HostBoundaryError as error:
        raise MatrixError(str(error)) from error


def _verify_owner_private_path(path: Path, *, directory: bool) -> None:
    try:
        _shared_verify_owner_private(path, directory=directory)
    except HostBoundaryError as error:
        raise MatrixError(str(error)) from error


def _owner_approved_ledger(repository: Path, role: str) -> dict:
    """Resolve the one fixed external owner ledger; callers supply no path."""
    if role not in {"internal", "public"}:
        raise MatrixError("owner-approved baseline repository role is invalid")
    home = _canonical_host_home()
    directory = home / ".agents" / "engineering" / "bootstrap-authority"
    ledger_path = directory / "v2.2.6-owner-approved-ledger.json"
    approval_path = directory / "v2.2.6-owner-approved-ledger-approval.json"
    trust = directory
    anchor_path = directory / "bootstrap-trust-anchor.json"
    allowed_path = directory / "allowed-signers"
    for path in (
        directory,
        ledger_path,
        approval_path,
        trust,
        anchor_path,
        allowed_path,
    ):
        _reject_host_reparse_ancestors(path, directory)
    if (
        not ledger_path.is_file()
        or not approval_path.is_file()
        or not trust.is_dir()
        or not anchor_path.is_file()
        or not allowed_path.is_file()
    ):
        raise MatrixError("owner-approved baseline is unavailable")
    for path in {directory, trust}:
        _verify_owner_private_path(path, directory=True)
    for path in (ledger_path, approval_path, anchor_path, allowed_path):
        _verify_owner_private_path(path, directory=False)
    try:
        repository = repository.resolve(strict=True)
        if directory.resolve().is_relative_to(repository):
            raise MatrixError("owner-approved baseline is candidate-controlled")
        ledger_bytes = ledger_path.read_bytes()
        approval_bytes = approval_path.read_bytes()
        anchor_bytes = anchor_path.read_bytes()
        allowed = allowed_path.read_bytes()
        ledger = json.loads(ledger_bytes.decode("utf-8"))
        approval = json.loads(approval_bytes.decode("utf-8"))
        anchor = json.loads(anchor_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("owner-approved baseline is invalid") from error
    if (
        not isinstance(anchor, dict)
        or set(anchor)
        != {"schema", "anchor_id", "format_version", "signers_digest", "identity"}
        or anchor.get("schema")
        != "engineering.v2.2.6-bootstrap-trust-anchor.v1"
        or not isinstance(anchor.get("anchor_id"), str)
        or not anchor["anchor_id"]
        or anchor.get("format_version") != 1
        or anchor.get("signers_digest") != _digest(allowed)
        or anchor.get("identity") != {"state": "unknown"}
        or not allowed
        or len(allowed) > 65536
        or b"\x00" in allowed
    ):
        raise MatrixError("owner-approved baseline trust anchor is invalid")
    if (
        not isinstance(ledger, dict)
        or set(ledger) != OWNER_LEDGER_FIELDS
        or ledger.get("schema") != "engineering.v2.2.6-owner-approved-ledger.v2"
        or not isinstance(ledger.get("source_requirements"), list)
        or not isinstance(ledger.get("pending_requirements"), list)
        or not isinstance(ledger.get("pending_obligations"), list)
        or not isinstance(ledger.get("requirements"), list)
        or not isinstance(ledger.get("obligations"), list)
    ):
        raise MatrixError("owner-approved baseline ledger is invalid")
    expected_approval = {"schema", "approver", "claims", "host_receipt", "signature"}
    claims = approval.get("claims") if isinstance(approval, dict) else None
    receipt = approval.get("host_receipt") if isinstance(approval, dict) else None
    signature = approval.get("signature") if isinstance(approval, dict) else None
    expected_claims = {
        "baseline_id",
        "authority_epoch",
        "repository_ids",
        "source_evidence",
        "ledger_digest",
        "role_separation",
        "issued_at",
        "expires_at",
        "status",
        "replay_policy",
        "replay_nonce",
    }
    if (
        not isinstance(approval, dict)
        or set(approval) != expected_approval
        or approval.get("schema")
        != "engineering.v2.2.6-owner-baseline-approval.v1"
        or not isinstance(claims, dict)
        or set(claims) != expected_claims
        or not isinstance(signature, str)
        or not signature.startswith("-----BEGIN SSH SIGNATURE-----\n")
        or len(signature) > 16384
    ):
        raise MatrixError("owner-approved baseline approval is invalid")
    repository_ids = claims.get("repository_ids")
    source = claims.get("source_evidence")
    separation = claims.get("role_separation")
    auditors = separation.get("auditors") if isinstance(separation, dict) else None
    if (
        not isinstance(claims.get("baseline_id"), str)
        or not claims["baseline_id"]
        or not isinstance(claims.get("authority_epoch"), str)
        or not claims["authority_epoch"]
        or not isinstance(claims.get("replay_nonce"), str)
        or not claims["replay_nonce"]
        or not _utc(claims.get("issued_at"))
        or not _utc(claims.get("expires_at"))
        or claims.get("status") != "active"
        or claims.get("replay_policy") != "idempotent_same_digest_only"
        or not isinstance(repository_ids, dict)
        or set(repository_ids) != {"internal", "public"}
        or any(
            not re.fullmatch(r"sha256:[0-9a-f]{64}", str(repository_ids.get(name, "")))
            for name in ("internal", "public")
        )
        or repository_ids.get(role) != _repository_identity(repository)
        or claims.get("ledger_digest") != _digest(ledger_bytes)
        or not isinstance(source, dict)
        or not isinstance(separation, dict)
        or set(separation)
        != {
            "owner_principal",
            "architect_principal",
            "implementer_principal",
            "writer_principal",
            "auditors",
        }
        or not isinstance(auditors, list)
        or len(auditors) != 2
    ):
        raise MatrixError("owner-approved baseline claims are invalid")
    issued_at = _utc_instant(claims["issued_at"])
    expires_at = _utc_instant(claims["expires_at"])
    now = datetime.now(timezone.utc)
    if (
        issued_at > now + timedelta(minutes=5)
        or expires_at <= now
        or expires_at <= issued_at
        or expires_at - issued_at > timedelta(days=31)
    ):
        raise MatrixError("owner-approved baseline is expired or not current")
    principal_fields = (
        separation["owner_principal"],
        separation["architect_principal"],
        separation["implementer_principal"],
        separation["writer_principal"],
    )
    if (
        any(not isinstance(item, str) or not item for item in principal_fields)
        or separation["owner_principal"] in principal_fields[1:]
        or separation["architect_principal"]
        in {separation["implementer_principal"], separation["writer_principal"]}
    ):
        raise MatrixError("owner-approved baseline role separation is invalid")
    normalized_auditors = []
    for auditor in auditors:
        if (
            not isinstance(auditor, dict)
            or set(auditor) != {"category", "principal_id", "signer_fingerprint"}
            or auditor.get("category") not in {"semantic", "technical_security"}
            or not isinstance(auditor.get("principal_id"), str)
            or not auditor["principal_id"]
            or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(auditor.get("signer_fingerprint", ""))
            )
            or auditor["principal_id"] in set(principal_fields)
        ):
            raise MatrixError("owner-approved baseline role separation is invalid")
        expected_fingerprint = _allowed_signer_fingerprint(allowed, auditor["principal_id"])
        if auditor["signer_fingerprint"] != expected_fingerprint:
            raise MatrixError("owner-approved baseline auditor signer is mismatched")
        normalized_auditors.append(auditor)
    if (
        {item["category"] for item in normalized_auditors}
        != {"semantic", "technical_security"}
        or len({item["principal_id"] for item in normalized_auditors}) != 2
        or len({item["signer_fingerprint"] for item in normalized_auditors}) != 2
    ):
        raise MatrixError("owner-approved baseline role separation is invalid")
    approver = approval.get("approver")
    if approver != separation["owner_principal"]:
        raise MatrixError("owner-approved baseline approver is invalid")
    _allowed_signer_fingerprint(allowed, approver)
    expected_receipt = {
        "schema": "engineering.v2.2.6-owner-baseline-host-receipt.v1",
        "receipt_id": receipt.get("receipt_id") if isinstance(receipt, dict) else None,
        "authority_epoch": claims["authority_epoch"],
        "contract": "engineering.v2.2.6-owner-approved-ledger.v2",
        "identity": {"state": "unknown"},
        "trust_anchor": anchor,
    }
    if (
        not isinstance(receipt, dict)
        or receipt != expected_receipt
        or not isinstance(receipt.get("receipt_id"), str)
        or not receipt["receipt_id"]
    ):
        raise MatrixError("owner-approved baseline host receipt is invalid")
    _resolve_owner_source_evidence(source, ledger, repository)
    material = _canonical(
        {
            "schema": "engineering.v2.2.6-owner-baseline-claims.v1",
            "claims": claims,
            "host_receipt": receipt,
        }
    )
    with tempfile.TemporaryDirectory(prefix="engineering-owner-baseline-") as temporary:
        temporary_path = Path(temporary)
        signers_copy = temporary_path / "allowed-signers"
        signature_copy = temporary_path / "approval.sig"
        signers_copy.write_bytes(allowed)
        signature_copy.write_text(signature, encoding="ascii")
        try:
            verified = subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(signers_copy),
                    "-I",
                    approver,
                    "-n",
                    "engineering-v226-owner-baseline",
                    "-s",
                    str(signature_copy),
                ],
                input=material,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MatrixError("owner-approved baseline verification is unavailable") from error
    if verified.returncode != 0:
        raise MatrixError("owner-approved baseline signature is invalid")
    return {
        "ledger": ledger,
        "authority_epoch": claims["authority_epoch"],
        "role_separation": separation,
        "source_evidence": source,
        "approval_digest": _digest(approval_bytes),
        "trust_anchor_digest": _digest(anchor_bytes),
        "allowed_signers": allowed,
    }


def _repository_identity(repository: Path) -> str:
    roots = _git(repository, "rev-list", "--max-parents=0", "HEAD").splitlines()
    if len(roots) != 1 or not re.fullmatch(r"[0-9a-f]{40}", roots[0]):
        raise MatrixError("owner-approved baseline repository identity is unavailable")
    return _digest(b"git-root\0" + roots[0].encode("ascii"))


def _allowed_signer_fingerprint(allowed: bytes, principal: str) -> str:
    try:
        lines = allowed.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise MatrixError("owner-approved baseline trust anchor is invalid") from error
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
            raise MatrixError("owner-approved baseline trust anchor is invalid")
        matches.append(parts[1] + " " + parts[2])
    if len(matches) != 1:
        raise MatrixError("owner-approved baseline signer is unavailable or ambiguous")
    return _digest(matches[0].encode("ascii"))


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
    baseline = _owner_approved_ledger(root, role)
    try:
        requirements, obligations = _normalize_registry(
            json.loads(registry_bytes.decode("utf-8")), baseline["ledger"]
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MatrixError("authoritative requirement registry is invalid") from error
    receipt = _host_execution_envelope(
        root,
        artifact,
        role,
        execution_envelope,
        {row["id"] for row in requirements},
        baseline,
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
            if command["selector"] == negative["selector"]
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
                if EVIDENCE_CLASSES.index(command["actual_evidence_class"])
                >= EVIDENCE_CLASSES.index(minimum)
                and command["actual_interface"]
                == requirement["native_evidence"]["interface"]
                and command["actual_environment"]
                == requirement["native_evidence"]["environment"]
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
        "owner_baseline": {
            "authority_epoch": baseline["authority_epoch"],
            "source_evidence": baseline["source_evidence"],
            "approval_digest": baseline["approval_digest"],
            "trust_anchor_digest": baseline["trust_anchor_digest"],
        },
        "execution_receipt_digest": receipt["envelope_digest"] if receipt else None,
        "rows": rows,
        "obligations": [
            {
                **obligation,
                "evidence_state": (
                    "source_contract_only"
                    if obligation["phase"] == "inherited"
                    else "unbound_postactivation"
                ),
            }
            for obligation in obligations
        ],
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
