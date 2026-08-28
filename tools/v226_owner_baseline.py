"""Render and verify v2.2.6 owner-baseline artifacts without writing authority."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile


TOOL = Path(__file__).resolve().with_name("v226_release_matrix.py")
SPEC = importlib.util.spec_from_file_location("engineering_v226_matrix_support", TOOL)
MATRIX = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MATRIX)


def _registry(root: Path, role: str) -> tuple[dict, dict]:
    artifact = MATRIX._artifact(root, role)
    raw = MATRIX._blob(root, artifact["commit"], "release/v2.2.6-requirements.json")
    value = json.loads(raw.decode("utf-8"))
    return artifact, value


def _authority_material() -> tuple[Path, dict, bytes, bytes]:
    home = MATRIX._canonical_host_home()
    directory = home / ".agents" / "engineering" / "bootstrap-authority"
    anchor_path = directory / "bootstrap-trust-anchor.json"
    allowed_path = directory / "allowed-signers"
    ledger_path = directory / "v2.2.6-owner-approved-ledger.json"
    for path in (directory, anchor_path, allowed_path, ledger_path):
        MATRIX._reject_host_reparse_ancestors(path, directory)
    MATRIX._verify_owner_private_path(directory, directory=True)
    for path in (anchor_path, allowed_path, ledger_path):
        MATRIX._verify_owner_private_path(path, directory=False)
    anchor_bytes = anchor_path.read_bytes()
    allowed = allowed_path.read_bytes()
    ledger_bytes = ledger_path.read_bytes()
    anchor = json.loads(anchor_bytes.decode("utf-8"))
    if (
        anchor.get("schema") != "engineering.v2.2.6-bootstrap-trust-anchor.v1"
        or anchor.get("signers_digest") != MATRIX._digest(allowed)
    ):
        raise MATRIX.MatrixError("owner baseline trust anchor is invalid")
    return directory, anchor, allowed, ledger_bytes


def render_ledger(
    internal_root: Path, public_root: Path, owner_ledger: Path, source: Path
) -> dict:
    _, internal = _registry(internal_root, "internal")
    _, public = _registry(public_root, "public")
    ledger_path = MATRIX._external_path(internal_root, owner_ledger, "owner ledger")
    if ledger_path.resolve().is_relative_to(public_root.resolve()):
        raise MATRIX.MatrixError("owner ledger path must be outside candidate Git")
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MATRIX.MatrixError("external owner ledger is unavailable or invalid") from error
    MATRIX._normalize_registry(internal, ledger)
    MATRIX._normalize_registry(public, ledger)
    source_path = MATRIX._external_path(internal_root, source, "owner source")
    if source_path.resolve().is_relative_to(public_root.resolve()):
        raise MATRIX.MatrixError("owner source path must be outside candidate Git")
    source_bytes = source_path.read_bytes()
    try:
        source_value = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        source_value = None
    if (
        isinstance(source_value, dict)
        and source_value.get("schema")
        == "engineering.owner-approved-native-decision-source.v1"
    ):
        MATRIX._validate_native_decision_source_receipt(
            source_path, ledger, internal_root
        )
    else:
        MATRIX._validate_owner_source_projection(ledger, source_bytes)
    return ledger


def render_decision_source(
    manifest_path: Path, session_path: Path, ledger_path: Path, repository: Path
) -> dict:
    """Validate and canonicalize a root-authored native decision receipt."""
    manifest_path = MATRIX._external_path(repository, manifest_path, "decision manifest")
    ledger_path = MATRIX._external_path(repository, ledger_path, "owner ledger")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MATRIX.MatrixError("native decision source or owner ledger is invalid") from error
    if MATRIX._canonical(manifest) != manifest_bytes:
        raise MATRIX.MatrixError("native decision source is not canonical UTF-8")
    source = manifest.get("native_source") if isinstance(manifest, dict) else None
    resolved_session = Path(session_path).resolve(strict=True)
    if not isinstance(source, dict) or source.get("path") != str(resolved_session):
        raise MATRIX.MatrixError("native decision source session is mismatched")
    MATRIX._validate_native_decision_source_receipt(manifest_path, ledger, repository)
    return manifest


def render_material(arguments: argparse.Namespace) -> dict:
    internal_artifact, internal_registry = _registry(arguments.internal_root, "internal")
    public_artifact, public_registry = _registry(arguments.public_root, "public")
    _, anchor, allowed, ledger_bytes = _authority_material()
    retained_ledger = json.loads(ledger_bytes.decode("utf-8"))
    source_path = Path(arguments.source)
    MATRIX._reject_host_reparse_ancestors(source_path)
    source_path = source_path.resolve(strict=True)
    for root in (arguments.internal_root.resolve(), arguments.public_root.resolve()):
        if source_path.is_relative_to(root):
            raise MATRIX.MatrixError("owner bootstrap source is candidate-controlled")
    source_bytes = source_path.read_bytes()
    MATRIX._normalize_registry(internal_registry, retained_ledger)
    MATRIX._normalize_registry(public_registry, retained_ledger)
    try:
        source_value = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        source_value = None
    requested_kind = arguments.source_kind
    is_native = (
        isinstance(source_value, dict)
        and source_value.get("schema")
        == "engineering.owner-approved-native-decision-source.v1"
    )
    if requested_kind == "codex_native_decision_receipt" and not is_native:
        raise MATRIX.MatrixError("native decision source is invalid")
    if requested_kind == "codex_automation_prompt" and is_native:
        raise MATRIX.MatrixError("owner source kind is mismatched")
    if is_native:
        MATRIX._validate_native_decision_source_receipt(
            source_path, retained_ledger, arguments.internal_root
        )
        source_id = arguments.source_id or source_value["decision_id"]
        if source_id != source_value["decision_id"]:
            raise MATRIX.MatrixError("native decision source is mismatched")
        source_evidence = {
            "schema": "engineering.owner-approved-bootstrap-source.v2",
            "kind": "codex_native_decision_receipt",
            "source_id": source_id,
            "path": str(source_path),
            "digest": MATRIX._digest(source_bytes),
            "length": len(source_bytes),
            "version": arguments.source_version,
        }
    else:
        if not arguments.automation_id:
            raise MATRIX.MatrixError("owner automation source identity is unavailable")
        MATRIX._validate_owner_source_projection(retained_ledger, source_bytes)
        source_evidence = {
            "schema": "engineering.owner-approved-bootstrap-source.v1",
            "kind": "codex_automation_prompt",
            "automation_id": arguments.automation_id,
            "path": str(source_path),
            "digest": MATRIX._digest(source_bytes),
            "length": len(source_bytes),
            "version": arguments.source_version,
        }
    role_separation = {
        "owner_principal": arguments.owner_principal,
        "architect_principal": arguments.architect_principal,
        "implementer_principal": arguments.implementer_principal,
        "writer_principal": arguments.writer_principal,
        "auditors": [
            {
                "category": category,
                "principal_id": principal,
                "signer_fingerprint": MATRIX._allowed_signer_fingerprint(
                    allowed, principal
                ),
            }
            for category, principal in (
                ("semantic", arguments.semantic_principal),
                ("technical_security", arguments.technical_principal),
            )
        ],
    }
    claims = {
        "baseline_id": arguments.baseline_id,
        "authority_epoch": arguments.authority_epoch,
        "repository_ids": {
            "internal": MATRIX._repository_identity(arguments.internal_root),
            "public": MATRIX._repository_identity(arguments.public_root),
        },
        "source_evidence": source_evidence,
        "ledger_digest": MATRIX._digest(ledger_bytes),
        "role_separation": role_separation,
        "issued_at": arguments.issued_at,
        "expires_at": arguments.expires_at,
        "status": "active",
        "replay_policy": "idempotent_same_digest_only",
        "replay_nonce": arguments.replay_nonce,
    }
    receipt = {
        "schema": "engineering.v2.2.6-owner-baseline-host-receipt.v1",
        "receipt_id": arguments.receipt_id,
        "authority_epoch": arguments.authority_epoch,
        "contract": "engineering.v2.2.6-owner-approved-ledger.v2",
        "identity": {"state": "unknown"},
        "trust_anchor": anchor,
    }
    material = {
        "schema": "engineering.v2.2.6-owner-baseline-claims.v1",
        "claims": claims,
        "host_receipt": receipt,
    }
    # Validate all time/scope shapes by assembling a temporary signed-shaped
    # approval only after the native signer has produced a real signature.
    del internal_artifact, public_artifact
    return material


def render_approval(material_path: Path, signature_path: Path) -> dict:
    _, _, allowed, _ = _authority_material()
    material_bytes = material_path.read_bytes()
    material = json.loads(material_bytes.decode("utf-8"))
    if MATRIX._canonical(material) != material_bytes:
        raise MATRIX.MatrixError("owner baseline material is not canonical UTF-8")
    claims = material.get("claims") if isinstance(material, dict) else None
    separation = claims.get("role_separation") if isinstance(claims, dict) else None
    approver = separation.get("owner_principal") if isinstance(separation, dict) else None
    MATRIX._allowed_signer_fingerprint(allowed, approver)
    signature = signature_path.read_text(encoding="ascii")
    with tempfile.TemporaryDirectory(prefix="engineering-owner-baseline-verify-") as temporary:
        signers = Path(temporary) / "allowed-signers"
        signers.write_bytes(allowed)
        verified = subprocess.run(
            [
                "ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", approver,
                "-n", "engineering-v226-owner-baseline", "-s", str(signature_path),
            ],
            input=material_bytes,
            capture_output=True,
            timeout=10,
            check=False,
        )
    if verified.returncode != 0:
        raise MATRIX.MatrixError("owner baseline signature is invalid")
    return {
        "schema": "engineering.v2.2.6-owner-baseline-approval.v1",
        "approver": approver,
        "claims": claims,
        "host_receipt": material["host_receipt"],
        "signature": signature,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="v226-owner-baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    ledger = commands.add_parser("ledger")
    ledger.add_argument("--internal-root", type=Path, required=True)
    ledger.add_argument("--public-root", type=Path, required=True)
    ledger.add_argument("--owner-ledger", type=Path, required=True)
    ledger.add_argument("--source", type=Path, required=True)
    decision_source = commands.add_parser("decision-source")
    decision_source.add_argument("--manifest", type=Path, required=True)
    decision_source.add_argument("--session", type=Path, required=True)
    decision_source.add_argument("--owner-ledger", type=Path, required=True)
    decision_source.add_argument("--repository", type=Path, required=True)
    material = commands.add_parser("material")
    material.add_argument("--internal-root", type=Path, required=True)
    material.add_argument("--public-root", type=Path, required=True)
    material.add_argument("--source", type=Path, required=True)
    material.add_argument(
        "--source-kind",
        choices=("auto", "codex_automation_prompt", "codex_native_decision_receipt"),
        default="auto",
    )
    material.add_argument("--source-id")
    material.add_argument("--automation-id")
    for name in (
        "source-version", "authority-epoch", "baseline-id",
        "receipt-id", "owner-principal", "architect-principal",
        "implementer-principal", "writer-principal", "semantic-principal",
        "technical-principal", "issued-at", "expires-at", "replay-nonce",
    ):
        material.add_argument("--" + name, required=True)
    approval = commands.add_parser("approval")
    approval.add_argument("--material", type=Path, required=True)
    approval.add_argument("--signature", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command == "ledger":
            value = render_ledger(
                arguments.internal_root,
                arguments.public_root,
                arguments.owner_ledger,
                arguments.source,
            )
        elif arguments.command == "decision-source":
            value = render_decision_source(
                arguments.manifest,
                arguments.session,
                arguments.owner_ledger,
                arguments.repository,
            )
        elif arguments.command == "material":
            value = render_material(arguments)
        else:
            value = render_approval(arguments.material, arguments.signature)
        print(MATRIX._canonical(value).decode("utf-8"), end="")
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, MATRIX.MatrixError) as error:
        print(f"ERROR: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
