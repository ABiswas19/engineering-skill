from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import importlib.util
import hashlib
import hmac
import json
import os
import sys
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
    "scripts/engineering_host_boundary.py",
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
    def write_public_only_overlay(self, destination: Path) -> None:
        path = destination / "docs" / "public-contributing.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Public contribution route\n", encoding="utf-8")

    def candidate_owner_ledger(self, source_excerpt: str = "owner approved package") -> dict:
        """Explicit test-only external projection; production never derives this."""
        registry = json.loads(
            (ROOT / "release" / "v2.2.6-requirements.json").read_text(
                encoding="utf-8"
            )
        )
        return {
            "schema": "engineering.v2.2.6-owner-approved-ledger.v2",
            "source_requirements": [
                {
                    "source_requirement_id": "OWNER-V226-UNCLASSIFIED",
                    "lifecycle_state": "OWNER_APPROVED",
                    "source_excerpt": source_excerpt,
                    "statement_digest": "sha256:"
                    + hashlib.sha256(source_excerpt.encode("utf-8")).hexdigest(),
                    "requirement_ids": [],
                    "obligation_ids": [],
                }
            ],
            "pending_requirements": [
                {"id": row["id"], "state": "pending", "reason": "owner source does not semantically entail this generic contract"}
                for row in registry["requirements"]
            ],
            "pending_obligations": [
                {"id": row["id"], "state": "pending", "reason": "owner source does not semantically entail this generic obligation"}
                for row in registry["obligations"]
            ],
            "requirements": [
                json.loads(json.dumps(row))
                for row in registry["requirements"]
            ],
            "obligations": registry["obligations"],
        }

    def candidate_native_owner_ledger(self) -> dict:
        ledger = self.candidate_owner_ledger()
        support = (
            ("OWNER-V226-AUTHENTICATED-RUN-RECEIPTS", "authenticated run receipts", ["authenticated_execution_envelopes"], ["first_pass_incident_preservation"]),
            ("OWNER-V226-EXACT-SOURCE-INSTALL", "exact source/install", ["exact_release_install_binding"], []),
            ("OWNER-V226-GIT-OBJECT-BINDING", "Git-object binding", ["git_object_byte_identity"], []),
            ("OWNER-V226-INDEPENDENT-EQUIVALENCE", "independent equivalence review", ["independent_equivalence"], []),
            ("OWNER-V226-MODEL-ROUTING-DISCLOSURE", "full model-routing disclosure", ["model_routing_disclosure"], []),
            ("OWNER-V226-TRANSACTIONAL-PREIMAGES", "transactional preimage checks", ["transactional_install_preimages"], []),
            ("OWNER-V226-PREVIEW-FIRST-SETUP", "preview-first setup", [], ["project_setup_preview_authority"]),
            ("OWNER-V226-BOUNDED-VERIFIED-MAINTENANCE", "bounded verified maintenance", [], ["bounded_maintenance"]),
            ("OWNER-V226-EXTERNAL-CONSUMER", "external consumer-contract plus owner review", ["external_consumer_authority"], ["external_consumer_owner_receipt", "external_consumer_integration"]),
        )
        rows = []
        mapped_requirements = set()
        mapped_obligations = set()
        for source_id, excerpt, requirements, obligations in support:
            mapped_requirements.update(requirements)
            mapped_obligations.update(obligations)
            rows.append({
                "source_requirement_id": source_id,
                "lifecycle_state": "OWNER_APPROVED",
                "source_excerpt": excerpt,
                "statement_digest": "sha256:" + hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                "requirement_ids": requirements,
                "obligation_ids": obligations,
            })
        ledger["source_requirements"] = rows
        ledger["pending_requirements"] = [
            {"id": row["id"], "state": "pending", "reason": "not semantically entailed by the exact owner safeguard excerpts"}
            for row in ledger["requirements"] if row["id"] not in mapped_requirements
        ]
        ledger["pending_obligations"] = [
            {"id": row["id"], "state": "pending", "reason": "not semantically entailed by the exact owner safeguard excerpts"}
            for row in ledger["obligations"] if row["id"] not in mapped_obligations
        ]
        return ledger

    def write_native_decision_source(
        self, directory: Path, ledger: dict
    ) -> tuple[Path, dict]:
        decision_id = "native-decision-fixture"
        proposal_text = f"Recommendation: approve {decision_id}; " + "; ".join(
            row["source_excerpt"] for row in ledger["source_requirements"]
        )
        approval_text = f"{decision_id} approved"
        proposal = {
            "timestamp": "2026-08-28T01:09:08.125Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "proposal-message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": proposal_text}],
                "internal_chat_message_metadata_passthrough": {
                    "turn_id": "proposal-turn"
                },
            },
        }
        approval = {
            "timestamp": "2026-08-28T08:13:20.109Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "approval-message",
                "role": "user",
                "content": [{"type": "input_text", "text": approval_text}],
                "internal_chat_message_metadata_passthrough": {
                    "turn_id": "approval-turn"
                },
            },
        }
        raw_lines = [
            json.dumps(proposal, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            json.dumps(approval, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        ]
        session = directory / "native-session.jsonl"
        session.write_bytes(b"\n".join(raw_lines) + b"\n")

        def record(line_number: int, value: dict, text: str, excerpt: str) -> dict:
            encoded = text.encode("utf-8")
            excerpt_bytes = excerpt.encode("utf-8")
            start = encoded.index(excerpt_bytes)
            return {
                "line_number": line_number,
                "message_id": value["payload"]["id"],
                "turn_id": value["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"],
                "timestamp": value["timestamp"],
                "role": value["payload"]["role"],
                "excerpt": excerpt,
                "excerpt_digest": "sha256:" + hashlib.sha256(excerpt_bytes).hexdigest(),
                "excerpt_utf8_span": {"start": start, "end": start + len(excerpt_bytes)},
                "raw_line_digest": "sha256:" + hashlib.sha256(raw_lines[line_number - 1]).hexdigest(),
            }

        safeguards = []
        for row in ledger["source_requirements"]:
            excerpt = row["source_excerpt"]
            excerpt_bytes = excerpt.encode("utf-8")
            proposal_bytes = proposal_text.encode("utf-8")
            start = proposal_bytes.index(excerpt_bytes)
            safeguards.append(
                {
                    **json.loads(json.dumps(row)),
                    "proposal_excerpt_utf8_span": {
                        "start": start,
                        "end": start + len(excerpt_bytes),
                    },
                }
            )
        receipt = {
            "schema": "engineering.owner-approved-native-decision-source.v2",
            "decision_id": decision_id,
            "lifecycle_state": "OWNER_APPROVED",
            "native_source": {
                "schema": "engineering.native-codex-session-jsonl.v1",
                "kind": "codex_session_jsonl",
                "path": str(session.resolve()),
                "digest": "sha256:" + hashlib.sha256(session.read_bytes()).hexdigest(),
                "length": session.stat().st_size,
            },
            "proposal": record(1, proposal, proposal_text, proposal_text),
            "approval": record(2, approval, approval_text, approval_text),
            "proposal_binding": {
                "decision_id": decision_id,
                "proposal_line_number": 1,
                "proposal_message_id": "proposal-message",
                "proposal_turn_id": "proposal-turn",
                "safeguard_projection_digest": "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        ledger["source_requirements"],
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest(),
            },
            "safeguards": safeguards,
        }
        return session, receipt

    def rewrite_native_proposal(
        self, module, session: Path, receipt: dict, proposal_text: str
    ) -> dict:
        """Test-only exact native-source rewrite with independently rebuilt spans."""
        updated = json.loads(json.dumps(receipt))
        lines = session.read_bytes().splitlines()
        proposal = json.loads(lines[0].decode("utf-8"))
        proposal["payload"]["content"][0]["text"] = proposal_text
        lines[0] = json.dumps(
            proposal, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        session.write_bytes(b"\n".join(lines) + b"\n")
        source_bytes = session.read_bytes()
        updated["native_source"].update(
            digest=module._digest(source_bytes), length=len(source_bytes)
        )
        proposal_bytes = proposal_text.encode("utf-8")
        updated["proposal"].update(
            excerpt=proposal_text,
            excerpt_digest=module._digest(proposal_bytes),
            excerpt_utf8_span={"start": 0, "end": len(proposal_bytes)},
            raw_line_digest=module._digest(lines[0]),
        )
        for row in updated["safeguards"]:
            excerpt_bytes = row["source_excerpt"].encode("utf-8")
            start = proposal_bytes.index(excerpt_bytes)
            row["proposal_excerpt_utf8_span"] = {
                "start": start,
                "end": start + len(excerpt_bytes),
            }
        return updated

    def candidate_owner_baseline(self) -> dict:
        """Explicit test-only projection; production resolves a signed host ledger."""
        return {
            "ledger": self.candidate_owner_ledger(),
            "authority_epoch": "test-only-owner-baseline-epoch",
            "role_separation": {
                "owner_principal": "owner-test",
                "architect_principal": "architect-test",
                "implementer_principal": "implementer-test",
                "writer_principal": "implementer-test",
                "auditors": [],
            },
            "source_evidence": {
                "schema": "engineering.owner-approved-bootstrap-source.v1",
                "kind": "test_fixture",
            },
            "approval_digest": "sha256:" + "1" * 64,
            "trust_anchor_digest": "sha256:" + "2" * 64,
            "allowed_signers": b"",
        }

    def test_v226_release_matrix_is_exact_complete_and_fail_closed(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        registry = ROOT / "release" / "v2.2.6-requirements.json"
        self.assertTrue(tool.is_file())
        self.assertTrue(registry.is_file())
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_release_matrix", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        role = (
            "internal"
            if (ROOT / "release" / "audience-classification.json").is_file()
            else "public"
        )
        with patch.object(
            module, "_owner_approved_ledger", return_value=self.candidate_owner_baseline()
        ):
            unknown = module.generate_matrix(ROOT, role, None)
        self.assertEqual(
            set(module.V226_REQUIRED_REQUIREMENTS),
            {row["requirement_id"] for row in unknown["rows"]},
        )
        self.assertFalse(unknown["gates"]["artifact_acceptance_ready"])
        self.assertFalse(unknown["gates"]["post_activation_ready"])
        self.assertTrue(unknown["unknowns"])
        with self.assertRaisesRegex(module.MatrixError, "external owner ledger"):
            module._normalize_registry(
                {
                    "schema": module.REQUIREMENTS_SCHEMA,
                    "requirements": [],
                    "obligations": json.loads(registry.read_text(encoding="utf-8"))[
                        "obligations"
                    ],
                },
                self.candidate_owner_baseline()["ledger"],
            )

        artifact_rows = [
            row
            for row in unknown["rows"]
            if row["gate"] == "artifact_acceptance"
        ]
        with tempfile.TemporaryDirectory() as temporary:
            host_home = Path(temporary) / "host-home"
            evidence_root = Path(temporary) / "native-evidence"
            key_path = host_home / ".agents" / "engineering" / "controller" / "attestation.key"
            key_path.parent.mkdir(parents=True)
            key = bytes.fromhex("42" * 32)
            key_path.write_text(key.hex() + "\n", encoding="ascii")
            evidence_root.mkdir()
            def reference(path: Path) -> dict:
                return {
                    "path": path.relative_to(evidence_root).as_posix(),
                    "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            commands = []
            for row in artifact_rows:
                if row["requirement_id"] == "independent_exact_artifact_acceptance":
                    continue
                selector = row["negative_test"]["selector"]
                command_id = "requirement-" + row["requirement_id"]
                log = evidence_root / f"{command_id}.log"
                meta = evidence_root / f"{command_id}.meta.json"
                log.write_text("Ran 1 test in 0.001s\n\nOK\n", encoding="utf-8")
                argv = (
                    [
                        "python", "-m", "unittest",
                        f"tests.test_repository.RepositoryContractTests.{selector}",
                    ]
                    if row["negative_test"]["path"] == "tests/test_repository.py"
                    else [
                        "python",
                        str((ROOT / row["negative_test"]["path"]).resolve()),
                        selector,
                    ]
                )
                meta.write_text(
                    json.dumps(
                        {
                            "schema": module.NATIVE_EXECUTION_META_SCHEMA,
                            "command_id": command_id,
                            "executor": {
                                "role": "native_test_runner",
                                "identity": {"state": "unknown"},
                            },
                            "artifact_before": unknown["artifact"],
                            "artifact_after": unknown["artifact"],
                            "role": role,
                            "argv": argv,
                            "cwd": str(ROOT.resolve()),
                            "started_at": "2026-08-25T08:00:00+00:00",
                            "finished_at": "2026-08-25T08:01:00+00:00",
                            "exit_code": 0,
                            "parser": "python-unittest-v1",
                            "counts": {
                                "run": 1, "failures": 0, "errors": 0, "skipped": 0
                            },
                            "selector": selector,
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                commands.append(
                    {"command_id": command_id, "meta": reference(meta), "log": reference(log)}
                )

            auditor_keys = {}
            allowed_lines = []
            for category in ("semantic", "technical_security"):
                principal = f"auditor-{category}"
                signer = Path(temporary) / principal
                subprocess.run(
                    ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(signer)],
                    check=True,
                    capture_output=True,
                )
                public = signer.with_suffix(".pub").read_text(encoding="ascii").strip()
                allowed_lines.append(f"{principal} {public}\n")
                auditor_keys[category] = signer
            allowed_signers = "".join(allowed_lines).encode("ascii")
            baseline = self.candidate_owner_baseline()
            baseline["allowed_signers"] = allowed_signers
            baseline["role_separation"]["auditors"] = [
                {
                    "category": category,
                    "principal_id": f"auditor-{category}",
                    "signer_fingerprint": module._allowed_signer_fingerprint(
                        allowed_signers, f"auditor-{category}"
                    ),
                }
                for category in ("semantic", "technical_security")
            ]
            for command in commands:
                try:
                    module._native_command(
                        ROOT,
                        unknown["artifact"],
                        role,
                        evidence_root,
                        command,
                        {row["requirement_id"] for row in artifact_rows},
                    )
                except module.MatrixError as error:
                    self.fail(f"{command['command_id']}: {error}")

            envelope_payload = {
                "schema": module.HOST_EXECUTION_ENVELOPE_SCHEMA,
                "issuer": {
                    "boundary_id": "native-host-controller",
                    "key_id": "sha256:" + hashlib.sha256(key).hexdigest(),
                    "identity": {"state": "unknown"},
                },
                "artifact": unknown["artifact"],
                "evidence_root": str(evidence_root.resolve()),
                "commands": commands,
                "incidents": [],
                "audits": [],
            }

            def write_envelope(payload: dict) -> Path:
                signed = dict(payload)
                signed["signature"] = "hmac-sha256:" + hmac.new(
                    key, module._canonical(payload), hashlib.sha256
                ).hexdigest()
                path = Path(temporary) / "host-execution-envelope.json"
                path.write_text(json.dumps(signed, sort_keys=True), encoding="utf-8")
                return path

            envelope = write_envelope(envelope_payload)
            with (
                patch.object(module, "_canonical_host_home", return_value=host_home),
                patch.object(module, "_verify_owner_private_path", return_value=None),
                patch.object(
                    module,
                    "_owner_approved_ledger",
                    return_value=baseline,
                ),
            ):
                exact_without_audits = module.generate_matrix(ROOT, role, envelope)
            independent = next(
                row
                for row in exact_without_audits["rows"]
                if row["requirement_id"] == "independent_exact_artifact_acceptance"
            )
            self.assertEqual("unknown", independent["evidence_state"])
            self.assertFalse(
                exact_without_audits["gates"]["artifact_acceptance_ready"]
            )

            audit_references = []
            for category in ("semantic", "technical_security"):
                report = evidence_root / f"{category}.report.txt"
                report.write_text("ACCEPT exact artifact\n", encoding="utf-8")
                audit_meta = evidence_root / f"{category}.meta.json"
                audit_meta.write_text(
                    json.dumps(
                        {
                            "schema": module.INDEPENDENT_AUDIT_META_SCHEMA,
                            "audit_id": f"audit-{category}",
                            "category": category,
                            "auditor": {
                                "role": "independent_auditor",
                                "principal_id": f"auditor-{category}",
                                "signer_fingerprint": module._allowed_signer_fingerprint(
                                    allowed_signers, f"auditor-{category}"
                                ),
                                "identity": {"state": "unknown"},
                            },
                            "artifact": unknown["artifact"],
                            "decision": "accepted",
                            "issued_at": "2026-08-25T08:02:00+00:00",
                            "report_digest": reference(report)["digest"],
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                claims_path = evidence_root / f"{category}.claims.json"
                claims_path.write_bytes(
                    module._canonical(
                        {
                            "schema": "engineering.independent-audit-claims.v1",
                            "meta": json.loads(audit_meta.read_text(encoding="utf-8")),
                        }
                    )
                )
                subprocess.run(
                    [
                        "ssh-keygen", "-Y", "sign", "-f", str(auditor_keys[category]),
                        "-n", f"engineering-v226-{category}-audit", str(claims_path),
                    ],
                    check=True,
                    capture_output=True,
                )
                signature = claims_path.with_suffix(".json.sig")
                audit_references.append(
                    {
                        "audit_id": f"audit-{category}",
                        "meta": reference(audit_meta),
                        "report": reference(report),
                        "signature": reference(signature),
                    }
                )
            accepted_payload = dict(envelope_payload)
            accepted_payload["audits"] = audit_references
            with (
                patch.object(module, "_canonical_host_home", return_value=host_home),
                patch.object(module, "_verify_owner_private_path", return_value=None),
                patch.object(
                    module,
                    "_owner_approved_ledger",
                    return_value=baseline,
                ),
            ):
                accepted = module.generate_matrix(
                    ROOT, role, write_envelope(accepted_payload)
                )
            self.assertTrue(
                accepted["gates"]["artifact_acceptance_ready"], accepted["unknowns"]
            )
            self.assertFalse(accepted["gates"]["post_activation_ready"])

            unsigned = json.loads(envelope.read_text(encoding="utf-8"))
            unsigned["signature"] = "hmac-sha256:" + "0" * 64
            envelope.write_text(json.dumps(unsigned), encoding="utf-8")
            with self.assertRaisesRegex(module.MatrixError, "authenticated"):
                with (
                    patch.object(module, "_canonical_host_home", return_value=host_home),
                    patch.object(module, "_verify_owner_private_path", return_value=None),
                    patch.object(
                        module,
                        "_owner_approved_ledger",
                        return_value=baseline,
                    ),
                ):
                    module.generate_matrix(ROOT, role, envelope)

            for row in accepted["rows"]:
                self.assertEqual(accepted["artifact"], row["exact_artifact_identity"])
                self.assertRegex(row["design_blob"], r"^sha256:[0-9a-f]{64}$")
                self.assertRegex(row["contract_blob"], r"^sha256:[0-9a-f]{64}$")
                self.assertRegex(row["negative_test_blob"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(accepted["matrix_digest"], module.matrix_digest(accepted))

    def test_v226_registry_completeness_comes_from_external_owner_ledger(self) -> None:
        """Candidate constants cannot omit the same owner outcome as candidate JSON."""
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_external_owner_ledger", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        registry = json.loads(
            (ROOT / "release" / "v2.2.6-requirements.json").read_text(
                encoding="utf-8"
            )
        )
        owner_ledger = self.candidate_owner_ledger()
        module._normalize_registry(registry, owner_ledger)
        omitted = json.loads(json.dumps(registry))
        omitted["requirements"] = omitted["requirements"][:-1]
        with self.assertRaisesRegex(module.MatrixError, "external owner ledger"):
            module._normalize_registry(omitted, owner_ledger)
        remapped = json.loads(json.dumps(registry))
        remapped["requirements"][0]["design"]["section"] = "Candidate-controlled remap"
        with self.assertRaisesRegex(module.MatrixError, "external owner ledger"):
            module._normalize_registry(remapped, owner_ledger)

    def test_v226_owner_baseline_is_fixed_host_private_and_fail_closed(self) -> None:
        """The candidate cannot supply a path when the native owner ledger is absent."""
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_owner_baseline_missing", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        role = (
            "internal"
            if (ROOT / "release" / "audience-classification.json").is_file()
            else "public"
        )
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            module, "_canonical_host_home", return_value=Path(temporary)
        ):
            with self.assertRaisesRegex(
                module.MatrixError, "owner-approved baseline is unavailable"
            ):
                module._owner_approved_ledger(ROOT, role)

    def test_v226_governing_host_root_is_shared_and_owner_private(self) -> None:
        """Release and runtime gates share one native root and reject weak ACLs."""
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_shared_host_boundary", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            "engineering_host_boundary", module._shared_canonical_host_home.__module__
        )
        with tempfile.TemporaryDirectory() as temporary:
            weak = Path(temporary) / "attestation.key"
            weak.write_text("00" * 32 + "\n", encoding="ascii")
            if os.name != "nt":
                os.chmod(weak, 0o644)
            with self.assertRaisesRegex(module.MatrixError, "owner-private"):
                module._verify_owner_private_path(weak, directory=False)

    def test_v226_host_boundary_loads_native_acl_module_without_profile_state(self) -> None:
        script = ROOT / ".agents" / "skills" / "engineering" / "scripts" / "engineering_host_boundary.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_host_boundary_acl", script
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn("[System.IO.DirectoryInfo]", module._WINDOWS_ACL_QUERY)
        self.assertIn("[System.IO.FileInfo]", module._WINDOWS_ACL_QUERY)
        self.assertNotIn("Get-Acl", module._WINDOWS_ACL_QUERY)
        executable = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
        environment = module._native_powershell_environment(executable)
        self.assertEqual(
            str(executable.parent / "Modules"), environment["PSModulePath"]
        )
        self.assertNotIn("codex-runtimes", environment["PSModulePath"].casefold())
        controller = ROOT / ".agents" / "skills" / "engineering" / "scripts" / "engineering.py"
        controller_spec = importlib.util.spec_from_file_location(
            "engineering_v226_controller_acl", controller
        )
        controller_module = importlib.util.module_from_spec(controller_spec)
        sys.modules[controller_spec.name] = controller_module
        controller_spec.loader.exec_module(controller_module)
        self.assertIn("[System.IO.DirectoryInfo]", controller_module._WINDOWS_PRIVATE_ACL)
        self.assertIn("[System.IO.FileInfo]", controller_module._WINDOWS_PRIVATE_ACL)
        self.assertNotIn("Get-Acl", controller_module._WINDOWS_PRIVATE_ACL)

    def test_v226_owner_baseline_cli_only_validates_external_owner_projection(self) -> None:
        tool = ROOT / "tools" / "v226_owner_baseline.py"
        missing = subprocess.run(
            [
                "python", str(tool), "ledger",
                "--internal-root", str(ROOT),
                "--public-root", str(ROOT),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertNotEqual(0, missing.returncode, missing.stdout + missing.stderr)
        with tempfile.TemporaryDirectory() as temporary:
            external = Path(temporary) / "owner-ledger.json"
            source_path = Path(temporary) / "owner-source.toml"
            source_path.write_text(
                "prompt = 'owner approved package'\n", encoding="utf-8"
            )
            external.write_text(
                json.dumps(self.candidate_owner_ledger(), sort_keys=True),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python", str(tool), "ledger",
                    "--internal-root", str(ROOT),
                    "--public-root", str(ROOT),
                    "--owner-ledger", str(external),
                    "--source", str(source_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        ledger = json.loads(result.stdout)
        self.assertEqual("engineering.v2.2.6-owner-approved-ledger.v2", ledger["schema"])
        source = tool.read_text(encoding="utf-8")
        self.assertNotIn("v2.2.6-owner-approved-ledger.json\").write", source)

    def test_v226_owner_source_projection_is_exact_external_and_complete(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_owner_source_projection", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_owner_ledger("owner approved package")
        module._validate_owner_source_projection(
            ledger, b"prompt = 'owner approved package'\n"
        )
        missing = json.loads(json.dumps(ledger))
        missing["pending_requirements"].pop()
        with self.assertRaisesRegex(module.MatrixError, "source projection"):
            module._validate_owner_source_projection(
                missing, b"prompt = 'owner approved package'\n"
            )
        conflict = json.loads(json.dumps(ledger))
        conflict["source_requirements"].append(
            json.loads(json.dumps(conflict["source_requirements"][0]))
        )
        with self.assertRaisesRegex(module.MatrixError, "source projection"):
            module._validate_owner_source_projection(
                conflict, b"prompt = 'owner approved package'\n"
            )
        changed = b"prompt = 'candidate changed package'\n"
        with self.assertRaisesRegex(module.MatrixError, "source projection"):
            module._validate_owner_source_projection(ledger, changed)

    def test_v226_native_decision_source_binds_exact_approval_pair_and_nine_safeguards(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_decision_source", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _, receipt = self.write_native_decision_source(directory, ledger)
            receipt_path = directory / "decision-source.json"
            receipt_path.write_bytes(module._canonical(receipt))
            with patch.object(module, "_verify_owner_private_path", return_value=None):
                resolved = module._validate_native_decision_source_receipt(
                    receipt_path, ledger, ROOT
                )
        self.assertEqual("native-decision-fixture", resolved["decision_id"])
        self.assertEqual(
            [row["source_requirement_id"] for row in ledger["source_requirements"]],
            [row["source_requirement_id"] for row in resolved["safeguards"]],
        )

    def test_v226_owner_projection_rejects_semantically_overbroad_complete_mapping(self) -> None:
        """Cardinality cannot promote one narrow safeguard into all owner outcomes."""
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_owner_projection_semantic", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_owner_ledger("transactional preimage checks")
        ledger["source_requirements"][0]["source_requirement_id"] = (
            "OWNER-V226-TRANSACTIONAL-PREIMAGES"
        )
        ledger["source_requirements"][0]["requirement_ids"] = [
            row["id"] for row in ledger["requirements"]
        ]
        ledger["source_requirements"][0]["obligation_ids"] = [
            row["id"] for row in ledger["obligations"]
        ]
        ledger["pending_requirements"] = []
        ledger["pending_obligations"] = []
        with self.assertRaisesRegex(module.MatrixError, "semantic|pending|projection"):
            module._validate_owner_source_projection(ledger)

    def test_public_manifest_contains_only_project_neutral_outcome_categories(self) -> None:
        """Populated local product identities stay in host-private owner evidence."""
        manifest = json.loads(
            (ROOT / "release" / "public-export.json").read_text(encoding="utf-8")
        )
        populated = (
            "decision" + "_studio",
            "decision " + "studio",
            "manage_" + "".join(chr(value) for value in (107, 97, 107, 97)),
            "".join(chr(value) for value in (107, 97, 107, 97)) + "_consumer",
            "".join(chr(value) for value in (99, 116, 97, 111)) + "_",
            "v" + "061",
            "v0" + ".6.1",
            "headless_" + "unified_product",
        )
        leaked = []
        for relative in manifest["files"]:
            path = ROOT / relative
            try:
                text = path.read_text(encoding="utf-8").casefold()
            except UnicodeDecodeError:
                continue
            if any(term in text for term in populated):
                leaked.append(relative)
        self.assertEqual([], leaked)

    def test_v226_native_decision_source_rejects_changed_native_evidence(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_decision_negative", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        mutations = {
            "wrong proposal line": lambda value: value["proposal"].update(line_number=2),
            "wrong approval message": lambda value: value["approval"].update(message_id="forged"),
            "wrong approval turn": lambda value: value["approval"].update(turn_id="forged"),
            "wrong approval timestamp": lambda value: value["approval"].update(timestamp="2026-08-28T00:00:00Z"),
            "wrong approval digest": lambda value: value["approval"].update(raw_line_digest="sha256:" + "0" * 64),
            "wrong approval excerpt": lambda value: value["approval"].update(excerpt="approved"),
            "wrong approval span": lambda value: value["approval"].update(excerpt_utf8_span={"start": 1, "end": 5}),
            "wrong safeguard mapping": lambda value: value["safeguards"][0]["requirement_ids"].append("fabricated"),
            "missing safeguard": lambda value: value["safeguards"].pop(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _, original = self.write_native_decision_source(directory, ledger)
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    receipt = json.loads(json.dumps(original))
                    mutate(receipt)
                    receipt_path = directory / f"{label.replace(' ', '-')}.json"
                    receipt_path.write_bytes(module._canonical(receipt))
                    with (
                        patch.object(module, "_verify_owner_private_path", return_value=None),
                        self.assertRaisesRegex(module.MatrixError, "native decision source"),
                    ):
                        module._validate_native_decision_source_receipt(
                            receipt_path, ledger, ROOT
                        )

    def test_v226_native_decision_source_requires_exact_affirmative_linkage(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_decision_semantics", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        decisions = (
            "No, do not approve native-decision-fixture.",
            "Maybe native-decision-fixture approved?",
            "Thanks for the update about native-decision-fixture.",
            "different-decision approved",
            "native-decision-fixture approved, but use a changed scope",
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            session, original = self.write_native_decision_source(directory, ledger)
            for index, decision in enumerate(decisions):
                with self.subTest(decision=decision):
                    receipt = json.loads(json.dumps(original))
                    lines = session.read_bytes().splitlines()
                    approval = json.loads(lines[1].decode("utf-8"))
                    approval["payload"]["content"][0]["text"] = decision
                    lines[1] = json.dumps(
                        approval, separators=(",", ":"), ensure_ascii=False
                    ).encode("utf-8")
                    session.write_bytes(b"\n".join(lines) + b"\n")
                    source_bytes = session.read_bytes()
                    receipt["native_source"]["digest"] = module._digest(source_bytes)
                    receipt["native_source"]["length"] = len(source_bytes)
                    excerpt = decision.encode("utf-8")
                    receipt["approval"].update(
                        excerpt=decision,
                        excerpt_digest=module._digest(excerpt),
                        excerpt_utf8_span={"start": 0, "end": len(excerpt)},
                        raw_line_digest=module._digest(lines[1]),
                    )
                    receipt_path = directory / f"semantic-{index}.json"
                    receipt_path.write_bytes(module._canonical(receipt))
                    with (
                        patch.object(module, "_verify_owner_private_path", return_value=None),
                        self.assertRaisesRegex(module.MatrixError, "affirmative|linked"),
                    ):
                        module._validate_native_decision_source_receipt(
                            receipt_path, ledger, ROOT
                        )

    def test_native_decision_receipt_rejects_cross_decision_generic_proposal(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_cross_decision", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            session, original = self.write_native_decision_source(directory, ledger)
            proposal_text = "Recommendation: explicitly approve different-decision; " + "; ".join(
                row["source_excerpt"] for row in ledger["source_requirements"]
            )
            receipt = self.rewrite_native_proposal(
                module, session, original, proposal_text
            )
            receipt_path = directory / "cross-decision.json"
            receipt_path.write_bytes(module._canonical(receipt))
            with (
                patch.object(module, "_verify_owner_private_path", return_value=None),
                self.assertRaisesRegex(module.MatrixError, "affirmative|linked|decision"),
            ):
                module._validate_native_decision_source_receipt(
                    receipt_path, ledger, ROOT
                )

    def test_native_decision_receipt_rejects_missing_proposal_identity(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_missing_identity", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            session, original = self.write_native_decision_source(directory, ledger)
            proposal_text = "Recommendation: explicitly approve; " + "; ".join(
                row["source_excerpt"] for row in ledger["source_requirements"]
            )
            receipt = self.rewrite_native_proposal(
                module, session, original, proposal_text
            )
            del receipt["proposal_binding"]
            receipt_path = directory / "missing-identity.json"
            receipt_path.write_bytes(module._canonical(receipt))
            with (
                patch.object(module, "_verify_owner_private_path", return_value=None),
                self.assertRaisesRegex(module.MatrixError, "affirmative|linked|decision"),
            ):
                module._validate_native_decision_source_receipt(
                    receipt_path, ledger, ROOT
                )

    def test_native_decision_receipt_rejects_multiple_proposal_candidates(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_multiple_proposals", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            session, original = self.write_native_decision_source(directory, ledger)
            proposal_text = (
                "Recommendation: approve different-decision; "
                "Recommendation: approve native-decision-fixture; "
                + "; ".join(
                    row["source_excerpt"] for row in ledger["source_requirements"]
                )
            )
            receipt = self.rewrite_native_proposal(
                module, session, original, proposal_text
            )
            receipt_path = directory / "multiple-proposals.json"
            receipt_path.write_bytes(module._canonical(receipt))
            with (
                patch.object(module, "_verify_owner_private_path", return_value=None),
                self.assertRaisesRegex(module.MatrixError, "affirmative|linked|decision"),
            ):
                module._validate_native_decision_source_receipt(
                    receipt_path, ledger, ROOT
                )

    def test_v226_native_decision_source_accepts_host_ambient_context_outside_request(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_decision_ambient", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            session, receipt = self.write_native_decision_source(directory, ledger)
            lines = session.read_bytes().splitlines()
            proposal = json.loads(lines[0].decode("utf-8"))
            proposal_text = (
                "Recommendation: explicitly approve native-decision-fixture; "
                "the nine missing Engineering release safeguards—"
                + "; ".join(
                    row["source_excerpt"] for row in ledger["source_requirements"]
                )
            )
            proposal["payload"]["content"][0]["text"] = proposal_text
            lines[0] = json.dumps(
                proposal, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            approval = json.loads(lines[1].decode("utf-8"))
            decision = receipt["approval"]["excerpt"]
            approval_text = (
                '<in-app-browser-context source="ambient-ui-state">\n'
                "Ambient product state; not part of the user request.\n"
                "</in-app-browser-context>\n\n"
                "## My request:\n"
                f"{decision}\n"
            )
            approval["payload"]["content"][0]["text"] = approval_text
            lines[1] = json.dumps(
                approval, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            session.write_bytes(b"\n".join(lines) + b"\n")
            source_bytes = session.read_bytes()
            receipt["native_source"].update(
                digest=module._digest(source_bytes), length=len(source_bytes)
            )
            proposal_bytes = proposal_text.encode("utf-8")
            receipt["proposal"].update(
                excerpt=proposal_text,
                excerpt_digest=module._digest(proposal_bytes),
                excerpt_utf8_span={"start": 0, "end": len(proposal_bytes)},
                raw_line_digest=module._digest(lines[0]),
            )
            for row in receipt["safeguards"]:
                excerpt_bytes = row["source_excerpt"].encode("utf-8")
                start = proposal_bytes.index(excerpt_bytes)
                row["proposal_excerpt_utf8_span"] = {
                    "start": start,
                    "end": start + len(excerpt_bytes),
                }
            excerpt = decision.encode("utf-8")
            start = approval_text.encode("utf-8").index(excerpt)
            receipt["approval"].update(
                excerpt_digest=module._digest(excerpt),
                excerpt_utf8_span={"start": start, "end": start + len(excerpt)},
                raw_line_digest=module._digest(lines[1]),
            )
            receipt_path = directory / "ambient-decision.json"
            receipt_path.write_bytes(module._canonical(receipt))
            with patch.object(module, "_verify_owner_private_path", return_value=None):
                resolved = module._validate_native_decision_source_receipt(
                    receipt_path, ledger, ROOT
                )
        self.assertEqual("native-decision-fixture", resolved["decision_id"])

    def test_v226_external_evidence_paths_use_shared_reparse_boundary(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_external_reparse", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            evidence_root = Path(temporary).resolve() / "junction-evidence-root"
            evidence_root.mkdir()
            child = evidence_root / "meta.json"
            child.write_bytes(b"{}")

            def reject_root(path: Path, boundary: Path | None = None) -> None:
                if Path(path) == evidence_root:
                    raise module.HostBoundaryError("junction/reparse boundary")

            with (
                patch.object(
                    module, "_shared_reject_reparse_ancestors", side_effect=reject_root
                ),
                self.assertRaisesRegex(module.MatrixError, "junction/reparse"),
            ):
                module._reference_bytes(
                    ROOT,
                    evidence_root,
                    {"path": "meta.json", "digest": module._digest(b"{}")},
                    "native meta",
                )

    def test_v226_native_decision_source_rejects_session_or_candidate_control(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_decision_boundary", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            session, receipt = self.write_native_decision_source(directory, ledger)
            receipt_path = directory / "decision-source.json"
            receipt_path.write_bytes(module._canonical(receipt))
            session.write_bytes(session.read_bytes() + b"{}\n")
            with (
                patch.object(module, "_verify_owner_private_path", return_value=None),
                self.assertRaisesRegex(module.MatrixError, "native decision source"),
            ):
                module._validate_native_decision_source_receipt(receipt_path, ledger, ROOT)
            with self.assertRaisesRegex(module.MatrixError, "candidate-controlled"):
                module._validate_native_decision_source_receipt(
                    ROOT / "release" / "v2.2.6-requirements.json", ledger, ROOT
                )

    def test_v226_owner_baseline_cli_renders_generic_native_decision_receipt(self) -> None:
        tool = ROOT / "tools" / "v226_owner_baseline.py"
        tool_spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_decision_cli", tool
        )
        tool_module = importlib.util.module_from_spec(tool_spec)
        tool_spec.loader.exec_module(tool_module)
        matrix_spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_decision_cli_matrix",
            ROOT / "tools" / "v226_release_matrix.py",
        )
        matrix = importlib.util.module_from_spec(matrix_spec)
        matrix_spec.loader.exec_module(matrix)
        ledger = self.candidate_native_owner_ledger()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            session, receipt = self.write_native_decision_source(directory, ledger)
            manifest = directory / "decision-manifest.json"
            manifest.write_bytes(matrix._canonical(receipt))
            ledger_path = directory / "owner-ledger.json"
            ledger_path.write_bytes(matrix._canonical(ledger))
            with patch.object(
                tool_module.MATRIX, "_verify_owner_private_path", return_value=None
            ):
                rendered = tool_module.render_decision_source(
                    manifest, session, ledger_path, ROOT
                )
        self.assertEqual(receipt, rendered)
        help_result = subprocess.run(
            ["python", str(tool), "decision-source", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, help_result.returncode, help_result.stdout + help_result.stderr)
        self.assertIn("--manifest", help_result.stdout)

    def test_v226_owner_ledger_resolves_native_decision_receipt_not_automation_prose(self) -> None:
        tool = ROOT / "tools" / "v226_owner_baseline.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_ledger", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _, receipt = self.write_native_decision_source(directory, ledger)
            receipt_path = directory / "decision-source.json"
            receipt_path.write_bytes(module.MATRIX._canonical(receipt))
            ledger_path = directory / "owner-ledger.json"
            ledger_path.write_bytes(module.MATRIX._canonical(ledger))
            with patch.object(
                module.MATRIX, "_verify_owner_private_path", return_value=None
            ):
                resolved = module.render_ledger(
                    ROOT, ROOT, ledger_path, receipt_path
                )
            self.assertEqual(ledger, resolved)
            automation = directory / "automation.toml"
            automation.write_text(
                "prompt = '" + ledger["source_requirements"][0]["source_excerpt"] + "'\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                module.MATRIX.MatrixError, "source projection"
            ):
                module.render_ledger(ROOT, ROOT, ledger_path, automation)

    def test_v226_native_source_evidence_kind_is_exact_and_fail_closed(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_source_evidence", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _, receipt = self.write_native_decision_source(directory, ledger)
            receipt_path = directory / "decision-source.json"
            receipt_path.write_bytes(module._canonical(receipt))
            source = {
                "schema": "engineering.owner-approved-bootstrap-source.v2",
                "kind": "codex_native_decision_receipt",
                "source_id": receipt["decision_id"],
                "path": str(receipt_path.resolve()),
                "digest": "sha256:" + hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "length": receipt_path.stat().st_size,
                "version": "1",
            }
            with patch.object(module, "_verify_owner_private_path", return_value=None):
                resolved = module._resolve_owner_source_evidence(source, ledger, ROOT)
                self.assertEqual(receipt["decision_id"], resolved["decision_id"])
                for field, changed in (
                    ("kind", "codex_automation_prompt"),
                    ("source_id", "forged-decision"),
                    ("digest", "sha256:" + "0" * 64),
                ):
                    invalid = json.loads(json.dumps(source))
                    invalid[field] = changed
                    with self.subTest(field=field), self.assertRaisesRegex(
                        module.MatrixError, "source evidence"
                    ):
                        module._resolve_owner_source_evidence(invalid, ledger, ROOT)

    def test_v226_owner_material_binds_native_decision_receipt_kind(self) -> None:
        tool = ROOT / "tools" / "v226_owner_baseline.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_native_material", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ledger = self.candidate_native_owner_ledger()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _, receipt = self.write_native_decision_source(directory, ledger)
            receipt_path = directory / "decision-source.json"
            receipt_path.write_bytes(module.MATRIX._canonical(receipt))
            expected_source = {
                "schema": "engineering.owner-approved-bootstrap-source.v2",
                "kind": "codex_native_decision_receipt",
                "source_id": "native-decision-fixture",
                "path": str(receipt_path.resolve()),
                "digest": "sha256:" + hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "length": receipt_path.stat().st_size,
                "version": "1",
            }
            arguments = type(
                "Arguments",
                (),
                {
                    "internal_root": ROOT,
                    "public_root": ROOT,
                    "source": receipt_path,
                    "source_kind": "codex_native_decision_receipt",
                    "source_id": receipt["decision_id"],
                    "source_version": "1",
                    "automation_id": None,
                    "authority_epoch": "native-decision-epoch",
                    "baseline_id": "native-decision-baseline",
                    "receipt_id": "native-decision-host-receipt",
                    "owner_principal": "owner",
                    "architect_principal": "architect",
                    "implementer_principal": "writer",
                    "writer_principal": "writer",
                    "semantic_principal": "semantic",
                    "technical_principal": "technical",
                    "issued_at": "2026-08-28T08:20:00Z",
                    "expires_at": "2026-09-27T08:20:00Z",
                    "replay_nonce": "native-decision-replay",
                },
            )()
            allowed = (
                b"semantic ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfdNG34nGjtyEKfE2G6nuJhd3X1rcMiKotL82Wjvyl3\n"
                b"technical ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEAtAh1BVCQLTLNfAVPXryxzSjKHtlA+m8FLkSWBnx5j\n"
            )
            anchor = {
                "schema": "engineering.v2.2.6-bootstrap-trust-anchor.v1",
                "anchor_id": "fixture",
                "format_version": 1,
                "signers_digest": "sha256:" + hashlib.sha256(allowed).hexdigest(),
                "identity": {"state": "unknown"},
            }
            with (
                patch.object(module.MATRIX, "_verify_owner_private_path", return_value=None),
                patch.object(
                    module,
                    "_authority_material",
                    return_value=(directory, anchor, allowed, module.MATRIX._canonical(ledger)),
                ),
            ):
                material = module.render_material(arguments)
        self.assertEqual(expected_source, material["claims"]["source_evidence"])

    def test_readme_native_observability_is_truthful_and_precedes_comparisons(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        section = "## Native observability and limits"
        self.assertIn(section, readme)
        comparison_positions = [
            readme.index(name) for name in ("LangGraph", "Langfuse") if name in readme
        ]
        self.assertTrue(comparison_positions)
        self.assertLess(readme.index(section), min(comparison_positions))
        self.assertIn(
            "| Capability | Owning module | Evidence source | Storage/projection | Interface | Privacy boundary | Support state | Known limitation |",
            readme,
        )
        normalized = " ".join(readme.lower().split())
        for boundary in (
            "not a runtime telemetry backend",
            "no persistent dashboard",
            "no token or cost collection",
            "static html is a projection, not the canonical store",
            "does not grant owner, merge, install, deployment, or product authority",
        ):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, normalized)

    def test_v226_owner_baseline_binds_source_repo_epoch_and_role_separation(self) -> None:
        """Signed external ledger is exact; changed durable authority fails closed."""
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_owner_baseline_exact", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        role = (
            "internal"
            if (ROOT / "release" / "audience-classification.json").is_file()
            else "public"
        )
        registry = json.loads(
            (ROOT / "release" / "v2.2.6-requirements.json").read_text(
                encoding="utf-8"
            )
        )
        ledger = self.candidate_owner_ledger("owner approved package")
        root_commit = subprocess.run(
            ["git", "-C", str(ROOT), "rev-list", "--max-parents=0", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        repository_id = "sha256:" + hashlib.sha256(
            f"git-root\0{root_commit}".encode("ascii")
        ).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            host_home = Path(temporary) / "host-home"
            authority = host_home / ".agents" / "engineering" / "bootstrap-authority"
            trust = authority
            trust.mkdir(parents=True)
            owner_key = Path(temporary) / "owner-key"
            semantic_key = Path(temporary) / "semantic-key"
            technical_key = Path(temporary) / "technical-key"
            for key in (owner_key, semantic_key, technical_key):
                subprocess.run(
                    ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                    check=True,
                    capture_output=True,
                )

            def public(key: Path) -> str:
                return key.with_suffix(".pub").read_text(encoding="ascii").strip()

            allowed = (
                f"owner-baseline-owner {public(owner_key)}\n"
                f"semantic-auditor {public(semantic_key)}\n"
                f"technical-auditor {public(technical_key)}\n"
            ).encode("ascii")
            (trust / "allowed-signers").write_bytes(allowed)
            anchor = {
                "schema": "engineering.v2.2.6-bootstrap-trust-anchor.v1",
                "anchor_id": "owner-baseline-anchor-fixture",
                "format_version": 1,
                "signers_digest": "sha256:" + hashlib.sha256(allowed).hexdigest(),
                "identity": {"state": "unknown"},
            }
            (trust / "bootstrap-trust-anchor.json").write_text(
                json.dumps(anchor), encoding="utf-8"
            )
            ledger_path = authority / "v2.2.6-owner-approved-ledger.json"
            ledger_path.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
            source = Path(temporary) / "owner-automation.toml"
            source.write_text("prompt = 'owner approved package'\n", encoding="utf-8")

            def signer_fingerprint(key: Path) -> str:
                parts = public(key).split()
                return "sha256:" + hashlib.sha256(
                    (parts[0] + " " + parts[1]).encode("ascii")
                ).hexdigest()

            claims = {
                "baseline_id": "owner-approved-v226-bootstrap-fixture",
                "authority_epoch": "owner-approved-v226-epoch-fixture",
                "repository_ids": {
                    role: repository_id,
                    "public" if role == "internal" else "internal": "sha256:" + "f" * 64,
                },
                "source_evidence": {
                    "schema": "engineering.owner-approved-bootstrap-source.v1",
                    "kind": "codex_automation_prompt",
                    "automation_id": "office-automations-residual-closure",
                    "path": str(source.resolve()),
                    "digest": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
                    "length": source.stat().st_size,
                    "version": "2026-08-13T22:40:50.9723607Z",
                },
                "ledger_digest": "sha256:"
                + hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
                "role_separation": {
                    "owner_principal": "owner-baseline-owner",
                    "architect_principal": "architect-principal",
                    "implementer_principal": "implementer-principal",
                    "writer_principal": "implementer-principal",
                    "auditors": [
                        {
                            "category": "semantic",
                            "principal_id": "semantic-auditor",
                            "signer_fingerprint": signer_fingerprint(semantic_key),
                        },
                        {
                            "category": "technical_security",
                            "principal_id": "technical-auditor",
                            "signer_fingerprint": signer_fingerprint(technical_key),
                        },
                    ],
                },
                "issued_at": "2026-08-25T09:00:00+00:00",
                "expires_at": "2026-09-24T09:00:00+00:00",
                "status": "active",
                "replay_policy": "idempotent_same_digest_only",
                "replay_nonce": "owner-baseline-fixture-nonce",
            }
            host_receipt = {
                "schema": "engineering.v2.2.6-owner-baseline-host-receipt.v1",
                "receipt_id": "owner-baseline-host-receipt-fixture",
                "authority_epoch": claims["authority_epoch"],
                "contract": "engineering.v2.2.6-owner-approved-ledger.v2",
                "identity": {"state": "unknown"},
                "trust_anchor": anchor,
            }
            material = module._canonical(
                {
                    "schema": "engineering.v2.2.6-owner-baseline-claims.v1",
                    "claims": claims,
                    "host_receipt": host_receipt,
                }
            )
            material_path = Path(temporary) / "owner-baseline-claims.json"
            material_path.write_bytes(material)
            subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "sign",
                    "-f",
                    str(owner_key),
                    "-n",
                    "engineering-v226-owner-baseline",
                    str(material_path),
                ],
                check=True,
                capture_output=True,
            )
            approval = {
                "schema": "engineering.v2.2.6-owner-baseline-approval.v1",
                "approver": "owner-baseline-owner",
                "claims": claims,
                "host_receipt": host_receipt,
                "signature": material_path.with_suffix(".json.sig").read_text(
                    encoding="ascii"
                ),
            }
            (authority / "v2.2.6-owner-approved-ledger-approval.json").write_text(
                json.dumps(approval), encoding="utf-8"
            )
            with (
                patch.object(module, "_canonical_host_home", return_value=host_home),
                patch.object(module, "_verify_owner_private_path", return_value=None),
            ):
                resolved = module._owner_approved_ledger(ROOT, role)
            self.assertEqual(ledger, resolved["ledger"])
            self.assertEqual(claims["authority_epoch"], resolved["authority_epoch"])
            self.assertEqual(claims["role_separation"], resolved["role_separation"])

            source.write_text("prompt = 'changed authority'\n", encoding="utf-8")
            with (
                patch.object(module, "_canonical_host_home", return_value=host_home),
                patch.object(module, "_verify_owner_private_path", return_value=None),
            ):
                with self.assertRaisesRegex(
                    module.MatrixError, "owner-approved source evidence is mismatched"
                ):
                    module._owner_approved_ledger(ROOT, role)

    def test_v226_release_matrix_rejects_fabricated_native_evidence(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location("engineering_v226_matrix_negative", tool)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        role = "internal" if (ROOT / "release" / "audience-classification.json").is_file() else "public"
        artifact = module._artifact(ROOT, role)
        with (
            patch.object(
                module,
                "_owner_approved_ledger",
                return_value=self.candidate_owner_baseline(),
            ),
            self.assertRaisesRegex(module.MatrixError, "host envelope path"),
        ):
            module.generate_matrix(
                ROOT,
                role,
                {
                    "schema": module.HOST_EXECUTION_ENVELOPE_SCHEMA,
                    "artifact": artifact,
                    "evidence_class": "real_outcome",
                    "requirement_ids": list(module.V226_REQUIRED_REQUIREMENTS),
                },
            )

    def test_v226_native_command_cannot_self_promote_or_claim_requirements(self) -> None:
        """A generic unit-suite receipt cannot label itself E2E for arbitrary rows."""
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_no_self_promotion", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        role = (
            "internal"
            if (ROOT / "release" / "audience-classification.json").is_file()
            else "public"
        )
        artifact = module._artifact(ROOT, role)
        with tempfile.TemporaryDirectory() as temporary:
            evidence_root = Path(temporary).resolve()
            log = evidence_root / "generic.log"
            log.write_text("Ran 491 tests in 1.000s\n\nOK\n", encoding="utf-8")
            meta = evidence_root / "generic.meta.json"
            meta.write_text(
                json.dumps(
                    {
                        "schema": module.NATIVE_EXECUTION_META_SCHEMA,
                        "command_id": "caller-promoted-suite",
                        "executor": {
                            "role": "implementer",
                            "identity": {"state": "unknown"},
                        },
                        "artifact_before": artifact,
                        "artifact_after": artifact,
                        "role": role,
                        "argv": ["python", ".agents/skills/engineering/tests/test_engineering.py"],
                        "cwd": str(ROOT.resolve()),
                        "started_at": "2026-08-25T10:00:00+00:00",
                        "finished_at": "2026-08-25T10:01:00+00:00",
                        "exit_code": 0,
                        "parser": "python-unittest-v1",
                        "counts": {
                            "run": 491,
                            "failures": 0,
                            "errors": 0,
                            "skipped": 0,
                        },
                        "evidence_class": "end_to_end",
                        "requirement_ids": sorted(
                            item
                            for item in module.V226_REQUIRED_REQUIREMENTS
                            if item != "independent_exact_artifact_acceptance"
                        ),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            reference = lambda path: {
                "path": path.relative_to(evidence_root).as_posix(),
                "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            with self.assertRaisesRegex(
                module.MatrixError, "selector-specific|self-declared"
            ):
                module._native_command(
                    ROOT,
                    artifact,
                    role,
                    evidence_root,
                    {
                        "command_id": "caller-promoted-suite",
                        "meta": reference(meta),
                        "log": reference(log),
                    },
                    set(module.V226_REQUIRED_REQUIREMENTS),
                )

    def test_v226_independent_audit_requires_external_role_signature(self) -> None:
        """A host-envelope principal label is not an independent audit signature."""
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_signed_auditor", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        role = "internal" if (ROOT / "release" / "audience-classification.json").is_file() else "public"
        artifact = module._artifact(ROOT, role)
        with tempfile.TemporaryDirectory() as temporary:
            evidence_root = Path(temporary).resolve()
            allowed = b"semantic-auditor ssh-ed25519 " + b"A" * 68 + b"\n"
            fingerprint = module._allowed_signer_fingerprint(
                allowed, "semantic-auditor"
            )
            report = evidence_root / "semantic.report.txt"
            report.write_text("ACCEPT exact artifact\n", encoding="utf-8")
            meta = evidence_root / "semantic.meta.json"
            signature = evidence_root / "semantic.sig"
            signature.write_text("not signed\n", encoding="ascii")
            meta.write_text(
                json.dumps(
                    {
                        "schema": module.INDEPENDENT_AUDIT_META_SCHEMA,
                        "audit_id": "unsigned-semantic",
                        "category": "semantic",
                        "auditor": {
                            "role": "independent_auditor",
                            "principal_id": "semantic-auditor",
                            "signer_fingerprint": fingerprint,
                            "identity": {"state": "unknown"},
                        },
                        "artifact": artifact,
                        "decision": "accepted",
                        "issued_at": "2026-08-25T09:00:00+00:00",
                        "report_digest": "sha256:"
                        + hashlib.sha256(report.read_bytes()).hexdigest(),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            def reference(path: Path) -> dict:
                return {
                    "path": path.relative_to(evidence_root).as_posix(),
                    "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            with self.assertRaisesRegex(module.MatrixError, "signature"):
                module._independent_audit(
                    ROOT,
                    artifact,
                    evidence_root,
                    {
                        "audit_id": "unsigned-semantic",
                        "meta": reference(meta),
                        "report": reference(report),
                        "signature": reference(signature),
                    },
                    {
                        "category": "semantic",
                        "principal_id": "semantic-auditor",
                        "signer_fingerprint": fingerprint,
                    },
                    allowed,
                )

    def test_v226_same_artifact_requirement_pass_cannot_mask_failure(self) -> None:
        """A duplicate or conflicting selector history is never evidence satisfaction."""
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location(
            "engineering_v226_command_conflict", tool
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        passed = {
            "command_id": "pass",
            "selector": "test_exact_requirement",
            "exit_code": 0,
            "counts": {"run": 1, "failures": 0, "errors": 0, "skipped": 0},
        }
        failed = {
            "command_id": "fail",
            "selector": "test_exact_requirement",
            "exit_code": 1,
            "counts": {"run": 1, "failures": 1, "errors": 0, "skipped": 0},
        }
        with self.assertRaisesRegex(module.MatrixError, "conflict|ambiguous"):
            module._validate_command_set([failed, passed])
        with self.assertRaisesRegex(module.MatrixError, "ambiguous"):
            module._validate_command_set([passed, {**passed, "command_id": "pass-2"}])

    def test_v226_incident_evidence_is_exact_and_role_bound(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location("engineering_v226_incident", tool)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        role = "internal" if (ROOT / "release" / "audience-classification.json").is_file() else "public"
        artifact = module._artifact(ROOT, role)
        with tempfile.TemporaryDirectory() as temporary:
            evidence_root = Path(temporary).resolve()
            log = evidence_root / "incident.log"
            log.write_text(
                "Ran 1 test in 0.001s\n\nFAILED (failures=1)\n",
                encoding="utf-8",
            )
            meta = evidence_root / "incident.meta.json"
            wrong_role = "public" if role == "internal" else "internal"
            meta.write_text(
                json.dumps(
                    {
                        "schema": module.NATIVE_INCIDENT_META_SCHEMA,
                        "incident_id": "incident-wrong-role",
                        "observed_at": "2026-08-24T10:00:00+00:00",
                        "artifact": {**artifact, "role": wrong_role},
                        "role": wrong_role,
                        "executor": {"role": "implementer", "identity": {"state": "unknown"}},
                        "argv": ["python", "-m", "unittest"],
                        "cwd": str(ROOT.resolve()),
                        "result": "failed",
                        "exit_code": 1,
                        "parser": "python-unittest-v1",
                        "counts": {"run": 1, "failures": 1, "errors": 0, "skipped": 0},
                        "evidence_state": "canonical_log",
                        "reconciliation": {
                            "state": "superseded_by_exact_artifact",
                            "exact_artifact": artifact,
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            reference = lambda path: {
                "path": path.relative_to(evidence_root).as_posix(),
                "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            with self.assertRaisesRegex(module.MatrixError, "role-bound"):
                module._native_incident(
                    ROOT,
                    artifact,
                    role,
                    evidence_root,
                    {
                        "incident_id": "incident-wrong-role",
                        "meta": reference(meta),
                        "log": reference(log),
                    },
                )

    def test_v226_requirement_registry_has_complete_generic_obligation_dag(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location("engineering_v226_obligations", tool)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        registry = json.loads(
            (ROOT / "release" / "v2.2.6-requirements.json").read_text(encoding="utf-8")
        )
        requirements, obligations = module._normalize_registry(
            registry, self.candidate_owner_baseline()["ledger"]
        )
        self.assertEqual(
            set(module.V226_REQUIRED_REQUIREMENTS),
            {row["id"] for row in requirements},
        )
        self.assertEqual(
            tuple(module.V226_REQUIRED_OBLIGATIONS),
            tuple(row["id"] for row in obligations),
        )
        required_categories = {
            "graphify_overlay", "trace_coverage_impact_why", "setup_checkpoint_completion",
            "authority_persistence", "maintenance", "semantic_matrices",
            "capability_assurance", "learning", "successor_runtime", "capability_api",
            "unified_product", "consumer_integration", "external_consumer",
            "native_harness", "project_identity", "measurement", "first_pass",
            "false_acceptance", "graph_engineering", "readme", "langfuse_deferment",
            "postactivation_completeness",
        }
        self.assertTrue(required_categories <= {row["category"] for row in obligations})
        for row in obligations:
            self.assertIn(row["disposition"]["state"], {"included", "deferred"})
            self.assertTrue(row["acceptance_criteria"]["fail_closed"])
        missing = json.loads(json.dumps(registry))
        missing["obligations"].pop()
        with self.assertRaisesRegex(module.MatrixError, "external owner ledger"):
            module._normalize_registry(
                missing, self.candidate_owner_baseline()["ledger"]
            )

    def test_v226_graph_semantic_owner_obligations_are_explicit_and_unbound(self) -> None:
        registry = json.loads(
            (ROOT / "release" / "v2.2.6-requirements.json").read_text(encoding="utf-8")
        )
        obligations = {row["id"]: row for row in registry["obligations"]}
        required = {
            "graph_false_edge_rejection",
            "graph_amdahl_parallelism_semantics",
            "graph_fresh_verifier_enforcement",
            "graph_critical_path_enforcement",
        }
        self.assertTrue(required <= obligations.keys())
        for identifier in required:
            self.assertEqual("post_activation", obligations[identifier]["phase"])
            self.assertEqual(
                "real_outcome",
                obligations[identifier]["acceptance_criteria"]["evidence_class"],
            )
            self.assertTrue(obligations[identifier]["acceptance_criteria"]["fail_closed"])

    def test_v226_graph_one_writer_is_full_graph_and_postactivation(self) -> None:
        registry = json.loads(
            (ROOT / "release" / "v2.2.6-requirements.json").read_text(encoding="utf-8")
        )
        row = next(
            item for item in registry["obligations"]
            if item["id"] == "graph_full_one_writer_enforcement"
        )
        self.assertEqual("post_activation", row["phase"])
        self.assertIn("all active graph lanes", row["acceptance_criteria"]["environment"])
        self.assertEqual("real_outcome", row["acceptance_criteria"]["evidence_class"])

    def test_v226_external_consumer_authority_remains_external_and_unbound(self) -> None:
        registry = json.loads(
            (ROOT / "release" / "v2.2.6-requirements.json").read_text(encoding="utf-8")
        )
        obligations = {row["id"]: row for row in registry["obligations"]}
        receipt = obligations["external_consumer_owner_receipt"]
        consumer = obligations["external_consumer_integration"]
        self.assertIn("external", receipt["acceptance_criteria"]["interface"].lower())
        self.assertIn("external_consumer_owner_receipt", consumer["dependencies"])
        self.assertEqual("post_activation", receipt["phase"])

    def test_v226_named_consumer_correction_is_a_separate_downstream_gate(self) -> None:
        registry = json.loads(
            (ROOT / "release" / "v2.2.6-requirements.json").read_text(encoding="utf-8")
        )
        obligations = {row["id"]: row for row in registry["obligations"]}
        correction = obligations["named_consumer_contract_correction"]
        integration = obligations["primary_consumer_integration"]
        self.assertIn("capability_observability_api", correction["dependencies"])
        self.assertIn("named_consumer_contract_correction", integration["dependencies"])
        self.assertNotEqual(correction["dispatch_gate"], integration["dispatch_gate"])

    def test_v226_adjacent_tool_comparison_is_factual_and_dependency_scanned(self) -> None:
        registry = json.loads(
            (ROOT / "release" / "v2.2.6-requirements.json").read_text(encoding="utf-8")
        )
        obligations = {row["id"]: row for row in registry["obligations"]}
        comparison = obligations["adjacent_orchestrator_comparison"]
        self.assertIn("dependency-scan", comparison["acceptance_criteria"]["interface"])
        self.assertIn("langfuse_deferred", comparison["dependencies"])
        self.assertEqual("post_activation", comparison["phase"])

    def test_v226_native_command_meta_and_log_tampering_fail_closed(self) -> None:
        tool = ROOT / "tools" / "v226_release_matrix.py"
        spec = importlib.util.spec_from_file_location("engineering_v226_native_tamper", tool)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        role = "internal" if (ROOT / "release" / "audience-classification.json").is_file() else "public"
        artifact = module._artifact(ROOT, role)
        with tempfile.TemporaryDirectory() as temporary:
            evidence_root = Path(temporary).resolve()
            log = evidence_root / "command.log"
            meta = evidence_root / "command.meta.json"
            log.write_text("Ran 1 test in 0.001s\n\nOK\n", encoding="utf-8")
            selector = "test_v226_release_matrix_is_exact_complete_and_fail_closed"
            base = {
                "schema": module.NATIVE_EXECUTION_META_SCHEMA,
                "command_id": "exact-command",
                "executor": {"role": "implementer", "identity": {"state": "unknown"}},
                "artifact_before": artifact,
                "artifact_after": artifact,
                "role": role,
                "argv": [
                    "python",
                    "-m",
                    "unittest",
                    f"tests.test_repository.RepositoryContractTests.{selector}",
                ],
                "cwd": str(ROOT.resolve()),
                "started_at": "2026-08-24T10:00:00+00:00",
                "finished_at": "2026-08-24T10:01:00+00:00",
                "exit_code": 0,
                "parser": "python-unittest-v1",
                "counts": {"run": 1, "failures": 0, "errors": 0, "skipped": 0},
                "selector": selector,
            }
            def reference(path: Path) -> dict:
                return {
                    "path": path.relative_to(evidence_root).as_posix(),
                    "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            def command_reference() -> dict:
                return {
                    "command_id": "exact-command",
                    "meta": reference(meta),
                    "log": reference(log),
                }
            meta.write_text(json.dumps(base, sort_keys=True), encoding="utf-8")
            original_meta_reference = reference(meta)
            module._native_command(
                ROOT,
                artifact,
                role,
                evidence_root,
                command_reference(),
                set(module.V226_REQUIRED_REQUIREMENTS),
            )
            original_log_reference = reference(log)
            log.write_text("substituted\n", encoding="utf-8")
            with self.assertRaisesRegex(module.MatrixError, "digest"):
                module._native_command(
                    ROOT,
                    artifact,
                    role,
                    evidence_root,
                    {
                        "command_id": "exact-command",
                        "meta": reference(meta),
                        "log": original_log_reference,
                    },
                    set(module.V226_REQUIRED_REQUIREMENTS),
                )
            log.write_text("Ran 1 test in 0.001s\n\nOK\n", encoding="utf-8")
            mutations = [
                {"cwd": str(evidence_root)},
                {"role": "public" if role == "internal" else "internal"},
                {"argv": ["python", "different.py"]},
                {"artifact_before": {**artifact, "commit": "0" * 40}},
                {"artifact_after": {**artifact, "tree": "0" * 40}},
            ]
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    changed = {**base, **mutation}
                    meta.write_text(json.dumps(changed, sort_keys=True), encoding="utf-8")
                    with self.assertRaisesRegex(module.MatrixError, "digest"):
                        module._native_command(
                            ROOT,
                            artifact,
                            role,
                            evidence_root,
                            {
                                "command_id": "exact-command",
                                "meta": original_meta_reference,
                                "log": reference(log),
                            },
                            set(module.V226_REQUIRED_REQUIREMENTS),
                        )
            fabricated = {**base, "requirement_ids": ["fabricated_requirement"]}
            meta.write_text(json.dumps(fabricated, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(module.MatrixError, "self-declared native evidence"):
                module._native_command(
                    ROOT,
                    artifact,
                    role,
                    evidence_root,
                    command_reference(),
                    set(module.V226_REQUIRED_REQUIREMENTS),
                )

    def test_v226_internal_plans_receipt_docs_and_utf8_are_truthful(self) -> None:
        audience_path = ROOT / "release" / "audience-classification.json"
        if audience_path.is_file():
            audience = json.loads(audience_path.read_text(encoding="utf-8"))
            shared = set(
                json.loads(
                    (ROOT / "release" / "public-export.json").read_text(encoding="utf-8")
                )["files"]
            )
            classified = (
                shared
                | set(audience["internal_only"])
                | set(audience["public_only"])
                | set(audience["audience_specific"])
            )
            tracked = subprocess.check_output(
                ["git", "-C", str(ROOT), "ls-files", "docs/plans", "docs/superpowers/plans"],
                text=True,
                encoding="utf-8",
            ).splitlines()
            self.assertEqual([], sorted(set(tracked) - classified))
        receipt_doc = (
            ROOT / "docs" / "specs" / "engineering-v2.2.6-owner-intent-audit-repair.md"
        ).read_text(encoding="utf-8")
        self.assertIn("engineering.install.v5", receipt_doc)
        self.assertIn("after the one-time bootstrap", receipt_doc)
        self.assertNotIn("retained as `engineering.install.v4`", receipt_doc)
        for relative in sorted(subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files"], text=True, encoding="utf-8"
        ).splitlines()):
            path = ROOT / relative
            try:
                content = path.read_bytes()
                text = content.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            self.assertFalse(content.startswith(b"\xef\xbb\xbf"), relative)
            self.assertTrue(normalized.endswith("\n"), relative)
            self.assertFalse(normalized.endswith("\n\n"), relative)
            self.assertFalse(
                any(line.endswith((" ", "\t")) for line in text.splitlines()), relative
            )

    def test_release_manifest_is_v2_2_6_with_owner_intent_gate(self) -> None:
        manifest = json.loads((SKILL_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("2.2.6", manifest["version"])
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

    def test_shared_controller_contract_documents_owner_intent_release_gate(self) -> None:
        contract = (SKILL_ROOT / "references" / "controller-contract.md").read_text(
            encoding="utf-8"
        )
        for command in (
            "intent-bind",
            "intent-status",
            "outcome-accept",
            "release-gate",
            "verify-release-token",
        ):
            with self.subTest(command=command):
                self.assertIn(command, contract)
        self.assertIn("engineering.owner-intent.v1", contract)
        self.assertIn("engineering.release-token.v2", contract)

    def test_ci_installs_the_pinned_graphify_dependency(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "python -m pip install \"git+https://github.com/safishamsi/graphify.git"
            "@d89ec68af95e0cad801b56d88df383991e659823\"",
            workflow,
        )

    def test_ci_fetches_reachable_history_for_audience_audit(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            workflow,
            r"(?m)^      - uses: actions/checkout@v4\n        with:\n"
            r"          fetch-depth: 0$",
        )

    def test_ci_runs_windows_controller_and_installer_isolation_regression(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("matrix:\n        os: [ubuntu-latest, windows-latest]", workflow)
        self.assertIn(
            "python -B -m unittest discover -s tests",
            workflow,
        )
        self.assertIn(
            "python -B -m unittest discover -s .agents/skills/engineering/tests",
            workflow,
        )
        self.assertIn("if: runner.os == 'Windows'", workflow)
        self.assertIn(
            "Task7ContractTests."
            "test_temporary_home_install_replay_and_rollback_do_not_mutate_windows_path",
            workflow,
        )
        self.assertIn(
            "python -B .agents/skills/engineering/tests/test_engineering.py",
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

    def test_handoff_and_reapproval_semantics_survive_without_narrowing(self) -> None:
        """Rollover may compress prose but cannot narrow authority or terminal states."""
        skill = " ".join(
            (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8").split()
        )
        for required in (
            "Reject narrow handoffs and proxy-only results.",
            "bounded repair epochs",
            "project, target, action, scope, safeguards, or epoch changes",
            "they do not re-ask or retire automatically",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill)

    def test_readme_states_the_operating_and_evidence_boundaries(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for required in (
            "## Why, what, how",
            "## Deterministic core, optional reasoning",
            "## Dependencies and prerequisites",
            "## Quick start",
            "## Scale and limits",
            "Unknown",
            "semantic_matrices",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)

    def test_readme_leads_with_traceability_and_demotes_workflow_integration(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## .+$", readme, flags=re.MULTILINE)
        self.assertGreaterEqual(len(headings), 4)
        self.assertEqual("## Why, what, how", headings[0])
        self.assertEqual("## Capabilities at a glance", headings[1])
        self.assertEqual("## Traceability flow", headings[2])
        self.assertIn("## Workflow integrations", headings)
        self.assertGreater(
            headings.index("## Workflow integrations"),
            headings.index("## Deterministic core, optional reasoning"),
        )
        opening = readme[: readme.index("## Traceability flow")].lower()
        for required in (
            "requirements",
            "decisions",
            "code",
            "tests",
            "exact commit",
            "unknown",
            "fail closed",
        ):
            with self.subTest(required=required):
                self.assertIn(required, opening)
        self.assertNotIn("native task dag", opening)

    def test_readme_inventory_covers_the_shipped_capability_families(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        inventory = " ".join(
            readme[
                readme.index("## Capabilities at a glance") :
                readme.index("## Traceability flow")
            ].lower().split()
        )
        for required in (
            "repository assessment",
            "governed setup",
            "exact-commit checkpoints",
            "status, coverage, trace, impact, why-code, why-test, and compare",
            "prepare and complete",
            "approval persistence",
            "guided",
            "collaborative (default)",
            "steward",
            "foreground maintenance",
            "semantic matrices",
            "read-only retrospect",
            "delivery evaluation and trends",
            "applied learning",
        ):
            with self.subTest(required=required):
                self.assertIn(required, inventory)

    def test_internal_overlay_gives_exact_commit_install_without_shared_leakage(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        shared_install = " ".join(
            readme[
                readme.index("## Install for a project") :
                readme.index("## Quick start")
            ].lower().split()
        )
        for required in (
            "skill-installer",
            "--repo <owner>/<repository>",
            ".agents/skills/engineering",
            "--ref <exact-40-character-merged-release-commit>",
            "engineering setup",
            "engineering approve-setup",
            "codex-only",
            "claude",
            "unsupported",
        ):
            with self.subTest(shared_required=required):
                self.assertIn(required, shared_install)
        classification_path = ROOT / "release" / "audience-classification.json"
        if not classification_path.is_file():
            self.assertFalse((ROOT / "docs" / "internal-installation.md").exists())
            return
        overlay = " ".join(
            (ROOT / "docs" / "internal-installation.md")
            .read_text(encoding="utf-8")
            .lower()
            .split()
        )
        for required in (
            "phi" + "lips-internal/engineering-skill",
            "exact 40-character merged release commit",
            "read-only",
            "does not grant write access",
            "no tags or releases",
        ):
            with self.subTest(overlay_required=required):
                self.assertIn(required, overlay)

    def test_readme_documents_the_real_traceability_flow_and_queries(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        flow = readme[
            readme.index("## Traceability flow") :
            readme.index("## Deterministic core, optional reasoning")
        ].lower()
        ordered_markers = (
            "assess the repository",
            "preview and approve project controls",
            "first eligible commit",
            "pinned graphify code graph",
            "deterministic overlay",
            "query locally",
            "prepare and complete",
            "retained receipts",
        )
        offsets = [flow.index(marker) for marker in ordered_markers]
        self.assertEqual(sorted(offsets), offsets)
        for command in (
            "engineering map",
            "engineering status",
            "engineering coverage",
            "engineering trace",
            "engineering impact",
            "engineering why-code",
            "engineering why-test",
            "engineering compare",
        ):
            with self.subTest(command=command):
                self.assertIn(f"`{command}", flow)

    def test_readme_separates_local_determinism_from_optional_reasoning(self) -> None:
        readme = " ".join(
            (ROOT / "README.md").read_text(encoding="utf-8").lower().split()
        )
        for required in (
            "no background llm",
            "no daemon",
            "no hidden provider calls",
            "no enterprise graph upload",
            "codex or claude is optional",
            "greenfield",
            "mid-flight",
            "linked worktrees",
            "independent clones",
            "local/private evidence",
            "stale, missing, or conflicting evidence",
            "native destructive and connector approvals",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)

    def test_readme_has_a_concrete_trace_example_and_resolving_local_links(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        example = readme[
            readme.index("### Trace one requirement") :
            readme.index("## Workflow integrations")
        ]
        self.assertIn("engineering trace <root> REQ-", example)
        self.assertIn("engineering why-code <root>", example)
        self.assertIn("engineering why-test <root>", example)
        relative_links = re.findall(r"\[[^]]+\]\((?!https?://|#)([^)]+)\)", readme)
        self.assertGreaterEqual(len(relative_links), 2)
        for relative in relative_links:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file(), relative)

    def test_readme_explains_the_local_map_surface_without_hosted_ui_claims(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        section = " ".join(
            readme[
                readme.index("## Where to see the graph") :
                readme.index("## Workflow integrations")
            ].lower().split()
        )
        for required in (
            "engineering map <root>",
            "--focus <identifier>",
            "--no-open",
            "engineering.map.v1",
            "engineering-graphs/maps/<cache>/index.html",
            "default browser",
            "more than 5000 nodes",
            "node and type",
            "deterministic link count",
            "relationship paths",
            "local/private",
            "not uploaded",
            "current checkpoint",
        ):
            with self.subTest(required=required):
                self.assertIn(required, section)
        self.assertIn("no hosted ui", section)

    def test_readme_documents_autonomy_without_expanding_authority(self) -> None:
        readme = " ".join(
            (ROOT / "README.md").read_text(encoding="utf-8").lower().split()
        )
        for required in (
            "guided",
            "collaborative (default)",
            "steward",
            "engineering status <root>",
            "engineering autonomy <level> [root]",
            "none schedules or backgrounds work",
            "does not expand native permissions",
            "does not override exact authority",
            "safe queued maintenance during a foreground engineering run",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)

    def test_readme_documents_the_existing_applied_learning_trust_lifecycle(self) -> None:
        readme = " ".join(
            (ROOT / "README.md").read_text(encoding="utf-8").lower().split()
        )
        for required in (
            "sanitized project-local improvement candidate",
            "distinct second project",
            "keeps, inspects, dismisses, or promotes and applies",
            "promotion-attested applied practice",
            "proposal-only upstream source-improvement proposal",
            "raw project bodies",
            "paths, secrets, commands, diffs, commits, publication, release, and install actions",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)

    def test_readme_windows_quick_start_matches_launcher_fallback(self) -> None:
        readme = " ".join(
            (ROOT / "README.md").read_text(encoding="utf-8").lower().split()
        )
        self.assertIn("prefers the python launcher (`py -3`)", readme)
        self.assertIn("falls back to `python` when `py` is unavailable", readme)

    def test_readme_routes_feedback_without_crossing_private_data_boundaries(self) -> None:
        readme = " ".join(
            (ROOT / "README.md").read_text(encoding="utf-8").lower().split()
        )
        self.assertIn("open an issue in the repository from which you installed the skill", readme)
        self.assertIn("follow that repository's security policy", readme)
        self.assertIn("nothing is uploaded automatically", readme)
        self.assertIn("sanitized or synthetic examples only", readme)
        self.assertIn("never report a suspected vulnerability in an issue", readme)
        self.assertNotRegex(readme, r"\b(?:fork|pull request|pr)\b")

    def test_shared_export_surfaces_are_audience_neutral_in_both_directions(self) -> None:
        manifest = json.loads(
            (ROOT / "release" / "public-export.json").read_text(encoding="utf-8")
        )
        prohibited = re.compile(
            r"(?i)(?:phi" + "lips|phi" + "lips-internal|abis" + "was19|"
            r"github\.com/(?:phi" + "lips-internal|abis" + "was19)/|"
            + "public " + "mirror|internal repository " + "installation)"
        )
        for relative in manifest["files"]:
            path = ROOT / relative
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            with self.subTest(relative=relative):
                self.assertIsNone(prohibited.search(text))

    def test_audience_classification_keeps_internal_and_public_overlays_asymmetric(self) -> None:
        classification_path = ROOT / "release" / "audience-classification.json"
        if not classification_path.is_file():
            self.assertFalse((ROOT / "docs" / "internal-installation.md").exists())
            public_overlay = ROOT / "docs" / "public-contributing.md"
            if public_overlay.is_file():
                text = public_overlay.read_text(encoding="utf-8").lower()
                self.assertNotIn("phi" + "lips", text)
                self.assertNotIn("internal-only", text)
            return
        classification = json.loads(classification_path.read_text(encoding="utf-8"))
        manifest = json.loads(
            (ROOT / "release" / "public-export.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {
                "schema",
                "shared_manifest",
                "internal_only",
                "public_only",
                "audience_specific",
            },
            set(classification),
        )
        self.assertEqual("engineering.audience-classification.v1", classification["schema"])
        self.assertEqual("release/public-export.json", classification["shared_manifest"])
        shared = set(manifest["files"])
        internal_only = set(classification["internal_only"])
        public_only = set(classification["public_only"])
        audience_specific = set(classification["audience_specific"])
        self.assertFalse(shared & internal_only)
        self.assertFalse(shared & public_only)
        self.assertFalse(shared & audience_specific)
        self.assertFalse(internal_only & public_only)
        self.assertFalse(internal_only & audience_specific)
        self.assertFalse(public_only & audience_specific)
        self.assertTrue(internal_only)
        self.assertTrue(public_only)
        for relative in internal_only:
            self.assertTrue((ROOT / relative).is_file(), relative)
        for relative in audience_specific:
            self.assertTrue((ROOT / relative).is_file(), relative)
        for relative in public_only:
            self.assertFalse((ROOT / relative).exists(), relative)

        policy = json.loads(
            (ROOT / "release" / "audience-isolation-policy.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(["manifests", "tree", "workflows"], policy["surfaces"]["tree"])
        self.assertEqual(["reachable_history"], policy["surfaces"]["history"])
        self.assertEqual(
            ["comments", "issues", "pull_requests", "releases", "reviews"],
            policy["surfaces"]["metadata"],
        )
        self.assertEqual("byte_identical", policy["export"]["mode"])
        self.assertTrue(policy["export"]["same_snapshot_required"])
        self.assertEqual([], policy["export"]["transformations"])
        source_route = policy["audiences"]["source"]["security_route"]
        self.assertEqual("not_required", source_route["state"])
        self.assertIsNone(source_route["mechanism"])
        self.assertRegex(
            source_route["authority_reference"],
            r"^owner-approved:[a-z0-9._-]+$",
        )
        self.assertIn(
            "no repository-supported vulnerability intake",
            source_route["residual_risk"].lower(),
        )
        distribution_route = policy["audiences"]["distribution"]["security_route"]
        self.assertEqual(
            {
                "state": "verified",
                "mechanism": "github_private_vulnerability_reporting",
            },
            distribution_route,
        )

        governance = " ".join(
            (ROOT / "docs" / "plans" / "engineering-v2.2.4-security-governance.md")
            .read_text(encoding="utf-8")
            .lower()
            .split()
        )
        for marker in (
            "requirement matrix",
            "design matrix",
            "trace matrix",
            "release matrix",
            "owner-approved:engineering-v2.2.4-internal-security-intake-not-required",
            "residual risk",
        ):
            self.assertIn(marker, governance)
        self.assertNotIn(
            "docs/plans/engineering-v2.2.4-security-governance.md",
            json.loads(
                (ROOT / "release" / "public-export.json").read_text(
                    encoding="utf-8"
                )
            )["files"],
        )

        internal = " ".join(
            (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").lower().split()
        )
        self.assertIn("issues only", internal)
        self.assertIn("evaluates accepted suggestions", internal)
        self.assertIn("governed paired-release workflow", internal)
        self.assertIn("source repository and issue reference", internal)
        self.assertIn("sanitize and minimize", internal)
        self.assertIn("deduplicate", internal)
        self.assertIn("evaluate and propose", internal)
        self.assertIn("owner decision", internal)
        self.assertIn("implement once", internal)
        self.assertIn("verify the paired export", internal)
        self.assertIn("do not copy private issue bodies", internal)
        self.assertIn("allow_forking=false", internal)
        self.assertIn("zero existing forks", internal)
        self.assertNotIn("fork this", internal)
        self.assertNotRegex(internal, r"\b(?:pull request|pr)\b")

    def test_feedback_surfaces_separate_sanitized_issues_from_private_security(self) -> None:
        required = (
            "credentials",
            "business data",
            "tenant identifiers",
            "generated graphs",
            "checkpoints",
            "personal paths",
            "production evidence",
            "sanitized",
            "synthetic",
        )
        readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").lower().split())
        for marker in required:
            self.assertIn(marker, readme)
        classification_path = ROOT / "release" / "audience-classification.json"
        security = " ".join((ROOT / "SECURITY.md").read_text(encoding="utf-8").lower().split())
        self.assertNotIn("discussion", security)
        if not classification_path.is_file():
            self.assertIn("github private vulnerability reporting", security)
            self.assertIn("security/advisories/new", security)
            return

        self.assertIn("do not open an ordinary issue", security)
        self.assertIn("does not provide a repository-supported vulnerability-reporting channel", security)
        self.assertIn("must not be submitted through ordinary issues", security)
        self.assertIn("residual risk", security)
        self.assertNotIn("github private vulnerability reporting", security)
        self.assertNotIn("security/advisories/new", security)
        self.assertNotRegex(security, r"https?://|[a-z0-9._%+-]+@[a-z0-9.-]+")
        forms = {
            "bug": ROOT / ".github" / "ISSUE_TEMPLATE" / "bug-idea.yml",
            "code": ROOT / ".github" / "ISSUE_TEMPLATE" / "code-proposal.yml",
        }
        for kind, path in forms.items():
            text = " ".join(path.read_text(encoding="utf-8").lower().split())
            with self.subTest(kind=kind):
                for marker in required:
                    self.assertIn(marker, text)
                self.assertIn("never include vulnerability", text)
                self.assertIn("private logs", text)
        bug = forms["bug"].read_text(encoding="utf-8").lower()
        for marker in (
            "outcome",
            "expected behavior",
            "actual behavior",
            "exact skill version or commit",
            "minimal sanitized reproduction",
            "affected capability",
            "safe logs or screenshots",
            "impact",
            "suggested acceptance checks",
        ):
            self.assertIn(marker, bug)
        code = forms["code"].read_text(encoding="utf-8").lower()
        for marker in (
            "problem and outcome",
            "affected paths or components",
            "proposed algorithm or design",
            "sanitized diff, snippet, or pseudocode",
            "tests and evidence",
            "compatibility and security impact",
            "no upstream write",
        ):
            self.assertIn(marker, code)

    def test_sensitive_path_guard_covers_windows_and_posix_separator_forms(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_sensitive", ROOT / "tools" / "check_sensitive.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        pattern = module.PATTERNS["personal path"]
        samples = (
            "C:" + "\\" + "Users\\sample\\artifact.txt",
            "C:" + "/" + "Users/sample/artifact.txt",
            "/" + "Users/sample/artifact.txt",
            "/" + "home/sample/artifact.txt",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertIsNotNone(pattern.search(sample))

    def test_shared_tree_passes_sensitive_scanner(self) -> None:
        result = subprocess.run(
            ["python", "-B", "tools/check_sensitive.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_audience_guard_rejects_crossflow_metadata_history_and_unknowns(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_audience", ROOT / "tools" / "check_audience.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        policy = {
            "schema": "engineering.audience-isolation-policy.v1",
            "audiences": {
                "source": {
                    "forbidden_markers": ["DISTRIBUTION-ONLY"],
                    "security_route": {
                        "state": "not_required",
                        "mechanism": None,
                        "authority_reference": "owner-approved:synthetic-release-scope",
                        "residual_risk": "No repository-supported vulnerability intake is available.",
                    },
                },
                "distribution": {
                    "forbidden_markers": ["CANONICAL-ONLY"],
                    "security_route": {"state": "verified", "mechanism": "private"},
                },
            },
            "surfaces": {
                "tree": ["manifests", "tree", "workflows"],
                "history": ["reachable_history"],
                "metadata": ["comments", "issues", "pull_requests", "releases", "reviews"],
            },
            "export": {
                "mode": "byte_identical",
                "same_snapshot_required": True,
                "transformations": [],
            },
            "literal_exceptions": [
                {
                    "path": "release/audience-isolation-policy.json",
                    "reason": "policy_manifest",
                }
            ],
            "history_exceptions": [],
        }
        valid = {
            "schema": "engineering.audience-metadata-snapshot.v1",
            "audience": "distribution",
            "source_commit": "a" * 40,
            "surfaces": {name: [] for name in policy["surfaces"]["metadata"]},
        }
        self.assertEqual([], module.audit_metadata(policy, valid))
        wrong_audience = json.loads(json.dumps(valid))
        wrong_audience["audience"] = "source"
        self.assertIn(
            "metadata_audience_mismatch",
            module.policy_blockers(policy, "distribution", wrong_audience),
        )
        wrong_snapshot = json.loads(json.dumps(valid))
        wrong_snapshot["source_commit"] = "b" * 40
        self.assertIn(
            "metadata_snapshot_mismatch",
            module.policy_blockers(
                policy,
                "distribution",
                wrong_snapshot,
                expected_source_commit="a" * 40,
            ),
        )
        contaminated = json.loads(json.dumps(valid))
        contaminated["surfaces"]["pull_requests"] = [
            {"id": "4", "text": "references CANONICAL-ONLY repository"}
        ]
        self.assertIn("metadata_marker_crossflow", module.audit_metadata(policy, contaminated))
        incomplete = json.loads(json.dumps(valid))
        del incomplete["surfaces"]["comments"]
        self.assertIn("metadata_surface_unknown", module.audit_metadata(policy, incomplete))
        self.assertNotIn("security_route_unknown", module.policy_blockers(policy, "source", None))
        self.assertIn("metadata_audit_unknown", module.policy_blockers(policy, "source", None))

        source_security = """# Security

This release does not provide a repository-supported vulnerability-reporting channel.
Vulnerability and security-sensitive or private-production details must not be submitted
through ordinary Issues. Do not open an ordinary Issue for a suspected vulnerability.
Residual risk: No repository-supported vulnerability intake is available.
"""
        with tempfile.TemporaryDirectory() as temporary:
            security_root = Path(temporary)
            (security_root / "SECURITY.md").write_text(source_security, encoding="utf-8")
            self.assertEqual(
                [], module.audit_security_overlay(security_root, policy, "source")
            )
            (security_root / "SECURITY.md").write_text(
                source_security + "\nReport it in an ordinary Issue.\n", encoding="utf-8"
            )
            self.assertIn(
                "ordinary_issue_vulnerability_intake",
                module.audit_security_overlay(security_root, policy, "source"),
            )

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest = base / "release" / "audience-isolation-policy.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("CANONICAL-ONLY negative marker\n", encoding="utf-8")
            self.assertEqual(
                [],
                module.audit_tree(
                    base,
                    ["release/audience-isolation-policy.json"],
                    policy,
                    "distribution",
                ),
            )
            self.assertEqual(
                [],
                module.audit_tree(
                    base,
                    ["release\\audience-isolation-policy.json"],
                    policy,
                    "distribution",
                ),
            )
            (base / "README.md").write_text("CANONICAL-ONLY live marker\n", encoding="utf-8")
            self.assertIn(
                "tree_marker_crossflow",
                module.audit_tree(base, ["README.md"], policy, "distribution"),
            )

            root = base / "history"
            subprocess.run(["git", "init", "--initial-branch=main", str(root)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Synthetic"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "synthetic" + "@" + "example.invalid"],
                check=True,
            )
            (root / "README.md").write_text("safe\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-m", "mentions CANONICAL-ONLY source"],
                check=True,
                capture_output=True,
            )
            self.assertIn(
                "history_marker_crossflow",
                module.audit_reachable_history(root, policy, "distribution"),
            )
            historical_commit = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            (root / "README.md").write_text("safe again\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-m", "remove legacy term"],
                check=True,
                capture_output=True,
            )
            removed_commit = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            policy["history_exceptions"] = [
                {
                    "audience": "distribution",
                    "introduced_commit": historical_commit,
                    "removed_commit": removed_commit,
                    "marker": "CANONICAL-ONLY",
                    "reason": "Pre-isolation synthetic terminology retained without rewriting history.",
                    "authority_reference": "owner-approved:synthetic-history-exception",
                }
            ]
            self.assertEqual(
                [], module.audit_reachable_history(root, policy, "distribution")
            )

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

    def test_public_export_accepts_an_independent_linked_worktree_destination(self) -> None:
        """An isolated public worktree retains its own Git common directory."""
        if not (ROOT / "tools" / "export_public.py").is_file():
            self.skipTest("canonical-only exporter is intentionally absent")
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            primary = base / "public-primary"
            destination = base / "public-linked"
            subprocess.run(
                ["git", "init", "--initial-branch=main", str(primary)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(primary), "config", "user.name", "Synthetic"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(primary),
                    "config",
                    "user.email",
                    "synthetic" + "@" + "example.invalid",
                ],
                check=True,
            )
            (primary / "SECURITY.md").write_text(
                "# Security\n\nUse GitHub private vulnerability reporting at "
                "https://example.invalid/security/advisories/new.\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "-C", str(primary), "add", "SECURITY.md"], check=True
            )
            subprocess.run(
                ["git", "-C", str(primary), "commit", "-m", "security overlay"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(primary),
                    "worktree",
                    "add",
                    "-b",
                    "candidate",
                    str(destination),
                    "HEAD",
                ],
                check=True,
                capture_output=True,
            )
            self.assertTrue((destination / ".git").is_file())
            self.write_public_only_overlay(destination)

            result = module.export_tree(ROOT, destination)

            self.assertEqual(module._source_commit(ROOT), result["source_commit"])
            self.assertTrue(
                (primary / ".git" / "engineering-public-export.json").is_file()
            )

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
            has_audience_policy = (
                ROOT / "release" / "audience-isolation-policy.json"
            ).is_file()
            if has_audience_policy:
                (destination / "SECURITY.md").write_text(
                    "# Security\n\nUse GitHub private\nvulnerability reporting at "
                    "https://example.invalid/security/advisories/new.\n",
                    encoding="utf-8",
                )
            self.write_public_only_overlay(destination)

            result = module.export_tree(ROOT, destination)

            self.assertTrue(marker.is_file())
            receipt = json.loads(
                (destination / ".git" / "engineering-public-export.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("engineering.public-export-receipt.v4", receipt["schema"])
            source_commit = subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(source_commit, receipt["source_commit"])
            self.assertEqual(result["tree_digest"], receipt["tree_digest"])
            self.assertEqual(source_commit, result["source_commit"])
            if has_audience_policy:
                self.assertEqual(
                    module._file_digest(destination / "SECURITY.md"),
                    receipt["audience_specific_files"]["SECURITY.md"],
                )
            self.assertFalse(result["publication_ready"])
            expected_blockers = (
                ["metadata_audit_unknown"]
                if (ROOT / "release" / "audience-isolation-policy.json").is_file()
                else ["audience_policy_unknown"]
            )
            self.assertEqual(expected_blockers, result["blockers"])
            self.assertFalse((destination / "release" / "migration-receipt.json").exists())
            self.assertFalse((destination / "release" / "audience-classification.json").exists())
            self.assertFalse((destination / "CONTRIBUTING.md").exists())
            self.assertFalse((destination / "docs" / "internal-installation.md").exists())
            self.assertTrue((destination / "docs" / "public-contributing.md").is_file())
            self.assertEqual(has_audience_policy, (destination / "SECURITY.md").exists())
            self.assertFalse((destination / ".github" / "ISSUE_TEMPLATE" / "bug-idea.yml").exists())
            self.assertFalse((destination / ".github" / "ISSUE_TEMPLATE" / "code-proposal.yml").exists())
            expected = set(
                json.loads((ROOT / "release" / "public-export.json").read_text(encoding="utf-8"))["files"]
            )
            actual = {
                path.relative_to(destination).as_posix()
                for path in destination.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }
            overlays = {"docs/public-contributing.md"}
            if has_audience_policy:
                overlays.add("SECURITY.md")
            actual_shared = actual - overlays
            self.assertEqual(expected, actual_shared)
            for relative in expected:
                self.assertEqual(
                    module._git_blob_bytes(ROOT, source_commit, relative),
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

            verified_metadata = {
                "source": {
                    "schema": "engineering.audience-metadata-snapshot.v1",
                    "audience": "source",
                    "source_commit": source_commit,
                    "surfaces": {
                        name: []
                        for name in [
                            "comments",
                            "issues",
                            "pull_requests",
                            "releases",
                            "reviews",
                        ]
                    },
                },
                "distribution": {
                    "schema": "engineering.audience-metadata-snapshot.v1",
                    "audience": "distribution",
                    "source_commit": "b" * 40,
                    "surfaces": {
                        name: []
                        for name in [
                            "comments",
                            "issues",
                            "pull_requests",
                            "releases",
                            "reviews",
                        ]
                    },
                },
            }
            if has_audience_policy:
                subprocess.run(
                    ["git", "-C", str(destination), "config", "user.name", "Synthetic"],
                    check=True,
                )
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(destination),
                        "config",
                        "user.email",
                        "synthetic" + "@" + "example.invalid",
                    ],
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", str(destination), "add", "SECURITY.md"],
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", str(destination), "commit", "-m", "security overlay"],
                    check=True,
                    capture_output=True,
                )
                verified_metadata["distribution"]["source_commit"] = subprocess.run(
                    ["git", "-C", str(destination), "rev-parse", "HEAD"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            verified = module.export_tree(
                ROOT,
                destination,
                metadata=verified_metadata,
            )
            if has_audience_policy:
                self.assertEqual([], verified["blockers"])
            else:
                self.assertEqual(["audience_policy_unknown"], verified["blockers"])
            if has_audience_policy:
                forged = json.loads(json.dumps(verified_metadata))
                forged["source"]["source_commit"] = "c" * 40
                rejected = module.export_tree(ROOT, destination, metadata=forged)
                self.assertIn("metadata_snapshot_mismatch", rejected["blockers"])

    def test_public_export_fails_closed_without_a_verified_security_overlay(self) -> None:
        if not (ROOT / "release" / "audience-isolation-policy.json").is_file():
            self.skipTest("audience-specific policy is canonical-only")
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
            self.write_public_only_overlay(destination)
            with self.assertRaisesRegex(module.ExportError, "audience-specific security"):
                module.export_tree(ROOT, destination)

    def test_public_export_requires_every_declared_public_only_destination_file(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            destination = Path(temporary) / "public"
            (source / "release").mkdir(parents=True)
            destination.mkdir()
            (source / "release" / "audience-classification.json").write_text(
                json.dumps(
                    {
                        "schema": "engineering.audience-classification.v1",
                        "shared_manifest": "release/public-export.json",
                        "internal_only": ["release/audience-classification.json"],
                        "public_only": ["docs/public-contributing.md"],
                        "audience_specific": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(module.ExportError, "public-only destination"):
                module._validate_audience_classification(
                    source, [], destination=destination
                )

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
            if (ROOT / "release" / "audience-isolation-policy.json").is_file():
                (destination / "SECURITY.md").write_text(
                    "Use GitHub private vulnerability reporting at "
                    "https://example.invalid/security/advisories/new.\n",
                    encoding="utf-8",
                )
            self.write_public_only_overlay(destination)
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
            if (ROOT / "release" / "audience-isolation-policy.json").is_file():
                (destination / "SECURITY.md").write_text(
                    "Use GitHub private vulnerability reporting at "
                    "https://example.invalid/security/advisories/new.\n",
                    encoding="utf-8",
                )
            self.write_public_only_overlay(destination)
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

    def test_public_export_rejects_a_hard_linked_source(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            external = base / "outside.txt"
            external.write_text("private\n", encoding="utf-8")
            os.link(external, source / "README.md")
            with self.assertRaises(module.ExportError):
                module._safe_file(source, "README.md")

    def test_public_export_binds_clean_source_bytes_to_head(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            subprocess.run(
                ["git", "init", "--initial-branch=main", str(source)],
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Synthetic"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "config",
                    "user.email",
                    "synthetic" + "@" + "example.invalid",
                ],
                check=True,
            )
            (source / "README.md").write_text("committed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(source), "commit", "-m", "baseline"],
                check=True,
                capture_output=True,
            )
            module._assert_clean_head_snapshot(source, ["README.md"])
            (source / "README.md").write_text("modified\n", encoding="utf-8")
            with self.assertRaises(module.ExportError):
                module._assert_clean_head_snapshot(source, ["README.md"])

    def test_public_export_identity_and_bytes_are_stable_across_checkout_eol(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "engineering_public_export", ROOT / "tools" / "export_public.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            origin = base / "origin"
            subprocess.run(
                ["git", "init", "--initial-branch=main", str(origin)],
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "-C", str(origin), "config", "user.name", "Synthetic"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(origin),
                    "config",
                    "user.email",
                    "synthetic" + "@" + "example.invalid",
                ],
                check=True,
            )
            (origin / "release").mkdir()
            (origin / "README.md").write_bytes(b"one\ntwo\n")
            (origin / "release" / "public-export.json").write_text(
                json.dumps(
                    {
                        "schema": "engineering.public-export.v1",
                        "files": ["README.md"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(origin), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(origin), "commit", "-m", "exact source"],
                check=True,
                capture_output=True,
            )
            results = []
            isolated_git_config = base / "empty.gitconfig"
            isolated_git_config.write_text("", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "GIT_CONFIG_GLOBAL": str(isolated_git_config),
                    "GIT_CONFIG_NOSYSTEM": "1",
                },
            ):
                for name, autocrlf in (("lf", "false"), ("crlf", "true")):
                    source = base / f"source-{name}"
                    destination = base / f"public-{name}"
                    subprocess.run(
                        [
                            "git",
                            "clone",
                            "--config",
                            f"core.autocrlf={autocrlf}",
                            str(origin),
                            str(source),
                        ],
                        check=True,
                        capture_output=True,
                    )
                    subprocess.run(
                        ["git", "init", "--initial-branch=main", str(destination)],
                        check=True,
                        capture_output=True,
                    )
                    results.append((module.export_tree(source, destination), destination))
            self.assertNotEqual(
                (base / "source-lf" / "README.md").read_bytes(),
                (base / "source-crlf" / "README.md").read_bytes(),
            )
            self.assertEqual(results[0][0]["tree_digest"], results[1][0]["tree_digest"])
            expected_tree = subprocess.run(
                ["git", "-C", str(origin), "rev-parse", "HEAD^{tree}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(expected_tree, results[0][0]["source_git_tree"])
            expected_readme = subprocess.run(
                ["git", "-C", str(origin), "show", "HEAD:README.md"],
                check=True,
                capture_output=True,
            ).stdout
            for _, destination in results:
                self.assertEqual(expected_readme, (destination / "README.md").read_bytes())
            receipts = [
                json.loads(
                    (destination / ".git" / "engineering-public-export.json").read_text(
                        encoding="utf-8"
                    )
                )
                for _, destination in results
            ]
            self.assertEqual(receipts[0], receipts[1])

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
