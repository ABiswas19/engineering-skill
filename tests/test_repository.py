from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
import importlib.util
import json
import os
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
    def test_release_manifest_is_v2_2_4_with_pinned_graphify(self) -> None:
        manifest = json.loads((SKILL_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("2.2.4", manifest["version"])
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
            "python -m unittest discover -s .agents/skills/engineering/tests",
            workflow,
        )
        self.assertIn("if: runner.os == 'Windows'", workflow)
        self.assertIn(
            "Task7ContractTests."
            "test_temporary_home_install_replay_and_rollback_do_not_mutate_windows_path",
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

            result = module.export_tree(ROOT, destination)

            self.assertTrue(marker.is_file())
            receipt = json.loads(
                (destination / ".git" / "engineering-public-export.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("engineering.public-export-receipt.v3", receipt["schema"])
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
            actual_shared = actual - ({"SECURITY.md"} if has_audience_policy else set())
            self.assertEqual(expected, actual_shared)
            for relative in expected:
                self.assertEqual(
                    (ROOT / relative).read_bytes(),
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
            with self.assertRaisesRegex(module.ExportError, "audience-specific security"):
                module.export_tree(ROOT, destination)

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
