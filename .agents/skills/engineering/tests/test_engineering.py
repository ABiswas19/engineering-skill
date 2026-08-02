import importlib.util
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import runpy
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL = SKILL_DIR / "SKILL.md"
MANIFEST = SKILL_DIR / "manifest.json"
ENGINEERING_SCRIPT = SKILL_DIR / "scripts" / "engineering.py"
V1_SCRIPT = (
    Path.home()
    / ".codex"
    / "skills"
    / "engineering-traceability"
    / "scripts"
    / "engineering_traceability.py"
)


def load_engineering():
    if not ENGINEERING_SCRIPT.is_file():
        return None
    spec = importlib.util.spec_from_file_location("engineering_v2", ENGINEERING_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


engineering = load_engineering()


class CrossPlatformFilesystemTests(unittest.TestCase):
    def test_posix_ignores_windows_reparse_attributes(self):
        class OrdinaryPath:
            def is_symlink(self):
                return False

            def lstat(self):
                return type(
                    "StatResult",
                    (),
                    {"st_file_attributes": getattr(engineering.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)},
                )()

        with patch.object(engineering.os, "name", "posix"):
            self.assertFalse(engineering._is_reparse_point(OrdinaryPath()))

    def test_interpreter_alias_is_validated_after_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            alias = Path(temporary) / "python-alias"
            try:
                os.symlink(sys.executable, alias)
            except OSError:
                self.skipTest("test environment cannot create interpreter aliases")

            identity = engineering._interpreter_identity(Path(temporary).resolve(), alias)

        self.assertEqual(str(Path(sys.executable).resolve()), identity["path"])


class SkillShapeTests(unittest.TestCase):
    def test_skill_is_engineering_and_human_readable(self):
        self.assertTrue(SKILL.exists(), "SKILL.md must exist")
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("name: engineering", text)
        self.assertIn("What Engineering does", text)
        self.assertIn("What always needs approval", text)
        self.assertNotIn("PRIVATE_PROJECT_ALPHA", text)
        self.assertNotIn("ORG_INTERNAL_NAME", text)

    def test_manifest_pins_graphify(self):
        self.assertTrue(MANIFEST.exists(), "manifest.json must exist")
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual("0.9.5", manifest["graphify"]["version"])
        self.assertEqual(
            "d89ec68af95e0cad801b56d88df383991e659823",
            manifest["graphify"]["commit"],
        )

    def test_skill_explains_local_first_operation_and_performance(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())
        for required in (
            "local-first",
            "one developer",
            "Graphify normally provides the base graph",
            "deterministic Engineering overlay",
            "Each developer recreates or reuses their own local checkpoints",
            "Same-machine worktrees share the Git-common checkpoint",
            "separate machines do not",
            "Git and CI coordinate shared drift through the repository",
            "future inactive explicit opt-in",
            "Version 2 makes no enterprise-graph network calls",
            "never switches to enterprise mode automatically",
            "cold start",
            "incremental run",
            "cache hit",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_controller_prohibits_global_graphs_and_live_hook_changes(self):
        contract = " ".join(
            (SKILL_DIR / "references" / "controller-contract.md")
            .read_text(encoding="utf-8")
            .split()
        )
        for required in (
            "Graphify `global`",
            "Graphify `merge-graphs`",
            "canonical umbrella graph",
            "separate explicit authorization",
            "Ordinary task authorization is insufficient",
        ):
            with self.subTest(required=required):
                self.assertIn(required, contract)

    def test_skill_explains_setup_storage_maintenance_and_install_boundaries(self):
        skill = " ".join(SKILL.read_text(encoding="utf-8").split())
        contract = " ".join(
            (SKILL_DIR / "references" / "controller-contract.md")
            .read_text(encoding="utf-8")
            .split()
        )
        for required in (
            "opaque branch lineage",
            "approved deterministic-only",
            "proposes the v2 manifest",
            "after approval",
            "adopts the legacy controls",
            "does not create duplicates",
            "current user's home",
            "Claude loader",
            "HMAC-authenticated local integrity",
            "existing legacy autonomy entries",
            "machine-local durable attestation",
            "exact normalized argv digest",
            "ordinary source edits preserve",
            "does not execute the checks",
            "allow-inline-code",
            "does not expand scope",
            "hostile or shared multi-user storage",
            "UNC storage",
            "not public-key signing or nonrepudiation",
            "ENGINEERING_USER_HOME",
            "<engineering-home>",
            ".agents/skills/engineering/",
            ".claude/skills/engineering/SKILL.md",
            ".agents/engineering/controller/attestations.json",
            "allow_inline_code",
            "not a sandbox",
            "remaining process permissions",
            "credential-reduced environment retains only",
            "external effects still need separate approval",
            "compatibility shim remains until",
        ):
            with self.subTest(required=required):
                self.assertIn(required, skill)
        for required in (
            "tracked inputs",
            "compiled overlay",
            "completion manifests",
            "contribution queue",
            "attestations",
            "install receipt",
            "controller-private",
            "remains visible until inputs change or an explicit rerun or resolution",
        ):
            with self.subTest(required=required):
                self.assertIn(required, contract)


class Task2ContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def init_repo(self, name: str | None = None) -> Path:
        root = Path(self.temporary_directory.name)
        if name is not None:
            root /= name
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(root)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "synthetic"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Synthetic Test"],
            check=True,
        )
        (root / "README.md").write_text("# Synthetic\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-m", "initial"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "update-ref",
                "refs/remotes/origin/main",
                "HEAD",
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            ],
            check=True,
        )
        return root

    def git(self, root: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit_all(self, root: Path, message: str) -> str:
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", message)
        return self.git(root, "rev-parse", "HEAD")

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ENGINEERING_SCRIPT), *map(str, arguments)],
            capture_output=True,
            text=True,
        )

    def write_controls(
        self,
        root: Path,
        *,
        generation: str = "v1",
        provenance: str = "direct",
        complete: bool = True,
    ) -> None:
        (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
        (root / "requirements.md").write_text("# REQ-1\n", encoding="utf-8")
        (root / "design.md").write_text("# DEC-1\n", encoding="utf-8")
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_app.py").write_text(
            "import unittest\n\n"
            "class ValueTests(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        if generation == "v1":
            manifest_name = "engineering-traceability.json"
            trace_name = "engineering-traceability"
            manifest_version = 1
        else:
            manifest_name = "engineering.json"
            trace_name = "engineering"
            manifest_version = 2
        trace_dir = root / "docs" / trace_name
        trace_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "version": manifest_version,
            "mode": "mid-flight",
            "project": {"name": root.name, "default_branch": "main"},
            "graphify": {"version": "0.9.5"},
            "overlay": {"version": 1},
            "inputs": [f"docs/{trace_name}/links.json"],
            "integrity": {"min_retained_ratio": 0.8},
        }
        nodes = [
            {
                "id": "REQ-1",
                "type": "requirement",
                "title": "Keep a stable value",
                "source": {"path": "requirements.md", "line": 1},
            },
            {
                "id": "DEC-1",
                "type": "decision",
                "title": "Use a module constant",
                "source": {"path": "design.md", "line": 1},
            },
            {
                "id": "CODE-1",
                "type": "code_symbol",
                "title": "README",
                "source": {"path": "README.md", "line": 1},
            },
            {
                "id": "TEST-1",
                "type": "test",
                "title": "test_value",
                "source": {"path": "tests/test_app.py", "line": 1},
            },
        ]
        edges = [
            {
                "id": "EDGE-1",
                "from": "REQ-1",
                "to": "DEC-1",
                "type": "decided_by",
                "provenance": provenance,
                "source": {"path": "requirements.md", "line": 1},
            }
        ]
        if complete:
            edges.extend(
                [
                    {
                        "id": "EDGE-2",
                        "from": "DEC-1",
                        "to": "CODE-1",
                        "type": "implements",
                        "provenance": "derived",
                        "source": {"path": "README.md", "line": 1},
                    },
                    {
                        "id": "EDGE-3",
                        "from": "CODE-1",
                        "to": "TEST-1",
                        "type": "verified_by",
                        "provenance": "direct",
                        "source": {"path": "tests/test_app.py", "line": 1},
                    },
                ]
            )
        (root / manifest_name).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        (trace_dir / "links.json").write_text(
            json.dumps({"version": 1, "nodes": nodes, "edges": edges}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        (trace_dir / "decision-ledger.md").write_text(
            "# Engineering Traceability Decision Ledger\n", encoding="utf-8"
        )
        (trace_dir / "README.md").write_text(
            "# Engineering traceability\n", encoding="utf-8"
        )

    def control_paths(self, root: Path, generation: str) -> tuple[Path, Path]:
        if generation == "v1":
            return (
                root / "engineering-traceability.json",
                root / "docs" / "engineering-traceability",
            )
        return root / "engineering.json", root / "docs" / "engineering"

    def write_fake_graphify(self) -> Path:
        root = Path(self.temporary_directory.name) / "fake-graphify"
        package = root / "graphify"
        metadata = root / "graphifyy-0.9.5.dist-info"
        package.mkdir(parents=True, exist_ok=True)
        metadata.mkdir(exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "__main__.py").write_text(
            "import json, os, pathlib, subprocess, sys\n"
            "if '--help' in sys.argv:\n"
            "    print('  update PATH\\n  query TEXT\\n  path A B\\n  explain X')\n"
            "elif len(sys.argv) > 2 and sys.argv[1] == 'update':\n"
            "    if os.environ.get('FAKE_GRAPHIFY_RECORD'):\n"
            "        pathlib.Path(os.environ['FAKE_GRAPHIFY_RECORD']).open('a', encoding='utf-8').write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "    if os.environ.get('FAKE_GRAPHIFY_SLOW'):\n"
            "        __import__('time').sleep(float(os.environ['FAKE_GRAPHIFY_SLOW']))\n"
            "    out = pathlib.Path(os.environ['GRAPHIFY_OUT'])\n"
            "    out.mkdir(parents=True, exist_ok=True)\n"
            "    commit = subprocess.run(['git', '-C', sys.argv[2], 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()\n"
            "    (out / 'graph.json').write_text(json.dumps({'directed': True, 'multigraph': False, 'graph': {}, 'nodes': [], 'links': [], 'built_at_commit': commit}))\n"
            "    if os.environ.get('FAKE_GRAPHIFY_FAIL'):\n"
            "        raise SystemExit(7)\n"
            "else:\n"
            "    raise SystemExit(3)\n",
            encoding="utf-8",
        )
        (package / "detect.py").write_text(
            "CODE_EXTENSIONS = {'.py', '.mjs', '.ps1'}\n",
            encoding="utf-8",
        )
        (package / "watch.py").write_text(
            "import json, os, pathlib, subprocess, sys, time\n"
            "def _rebuild_code(watch_path, *, changed_paths=None, follow_symlinks=False, force=False, no_cluster=False, acquire_lock=True, block_on_lock=False):\n"
            "    if os.environ.get('FAKE_GRAPHIFY_RECORD'):\n"
            "        pathlib.Path(os.environ['FAKE_GRAPHIFY_RECORD']).open('a', encoding='utf-8').write(json.dumps(['private_rebuild_code', str(pathlib.Path.cwd()), *[str(p) for p in (changed_paths or [])]]) + '\\n')\n"
            "    if os.environ.get('FAKE_GRAPHIFY_SLOW'):\n"
            "        if os.environ.get('FAKE_GRAPHIFY_CHILD_PID'):\n"
            "            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            "            pathlib.Path(os.environ['FAKE_GRAPHIFY_CHILD_PID']).write_text(str(child.pid))\n"
            "        time.sleep(float(os.environ['FAKE_GRAPHIFY_SLOW']))\n"
            "    out = pathlib.Path(os.environ['GRAPHIFY_OUT'])\n"
            "    out.mkdir(parents=True, exist_ok=True)\n"
            "    graph_path = out / 'graph.json'\n"
            "    graph = json.loads(graph_path.read_text()) if graph_path.exists() else {'directed': True, 'multigraph': False, 'graph': {}, 'nodes': [], 'links': []}\n"
            "    graph['built_at_commit'] = subprocess.run(['git', '-C', str(watch_path), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()\n"
            "    graph_path.write_text(json.dumps(graph))\n"
            "    return not bool(os.environ.get('FAKE_GRAPHIFY_FAIL'))\n",
            encoding="utf-8",
        )
        (metadata / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: graphifyy\nVersion: 0.9.5\n",
            encoding="utf-8",
        )
        (metadata / "direct_url.json").write_text(
            json.dumps(
                {
                    "url": "https://github.com/safishamsi/graphify.git",
                    "vcs_info": {
                        "vcs": "git",
                        "commit_id": (
                            "d89ec68af95e0cad801b56d88df383991e659823"
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )
        return root

    def test_project_discovery_contract_surface(self):
        module = self.module()
        for name in (
            "resolve_project",
            "load_project_config",
            "discover_checks",
            "verify_graphify",
        ):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(module, name, None)))

    def test_check_capability_approval_is_lineage_and_command_bound(self):
        module = self.module()
        root, commit = self.prepared_repo("check-capability")
        manifest = root / "engineering-traceability.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["checks"] = [[sys.executable, "-m", "unittest", "--help"]]
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        commit = self.commit_all(root, "configure safe check")
        fake = self.write_fake_graphify()
        with patch.dict(os.environ, {"PYTHONPATH": str(fake)}, clear=False):
            module.rebuild(root, commit, sys.executable)

        blocked = module.prepare(root, "change REQ-1", {"scope": ["README.md"]})
        self.assertEqual("blocked", blocked["readiness"])
        self.assertTrue(any("check capability" in item for item in blocked["blockers"]))

        approval = module.approve_checks(root)
        self.assertRegex(approval["approval_id"], r"^attestation-[0-9a-f]{32}$")
        ready = module.prepare(root, "change REQ-1", {"scope": ["README.md"]})
        self.assertNotEqual("blocked", ready["readiness"])

        (root / "README.md").write_text("# ordinary source edit\n", encoding="utf-8")
        still_ready = module.prepare(root, "change REQ-1", {"scope": ["README.md"]})
        self.assertNotEqual("blocked", still_ready["readiness"])

        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["checks"] = [[sys.executable, "-m", "unittest", "discover"]]
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.commit_all(root, "change check capability")
        changed = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md", "engineering-traceability.json"]},
        )
        self.assertEqual("blocked", changed["readiness"])

    def test_inline_interpreter_code_requires_separate_explicit_approval(self):
        module = self.module()
        root, commit = self.prepared_repo("inline-check-capability")
        manifest = root / "engineering-traceability.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["checks"] = [[sys.executable, "-c", "print('unsafe inline')"]]
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        commit = self.commit_all(root, "configure inline check")
        fake = self.write_fake_graphify()
        with patch.dict(os.environ, {"PYTHONPATH": str(fake)}, clear=False):
            module.rebuild(root, commit, sys.executable)

        with self.assertRaisesRegex(module.EngineeringError, "inline"):
            module.approve_checks(root)
        approval = module.approve_checks(root, allow_inline_code=True)
        self.assertTrue(approval["inline_code_approved"])
        claims = module._check_capability_claims(
            root, [[sys.executable, "-c", "print('unsafe inline')"]]
        )
        self.assertTrue(claims["allow_inline_code"])

    def test_inline_interpreter_detection_covers_joined_and_encoded_modes(self):
        module = self.module()
        vectors = (
            ["python", "-cx"],
            ["python", "-cprint(1)"],
            ["node", "-eprocess.exit()"],
            ["node", "--eval=process.exit()"],
            ["node", "-p1+1"],
            ["node", "--print=1+1"],
            ["powershell", "-Command:Write-Host x"],
            ["pwsh", "-EncodedCommand", "AA=="],
            ["pwsh", "-encAA=="],
            ["cmd", "/cwhoami"],
            ["cmd.exe", "/k", "whoami"],
            ["bash", "-cecho x"],
            ["sh", "-c", "echo x"],
            ["py", "-c", "print(1)"],
            ["python3.12", "-c", "print(1)"],
            ["node20", "-e", "process.exit()"],
            ["pwsh7", "-Command", "Write-Host x"],
            ["zsh", "-c", "echo x"],
            ["ruby", "-e", "puts 1"],
            ["perl", "-E", "say 1"],
        )
        for argv in vectors:
            with self.subTest(argv=argv):
                self.assertTrue(module._contains_inline_code(argv))
        for argv in (["python", "-Qunknown"], ["node", "--unknown-mode"], ["pwsh", "-NoExit"]):
            with self.subTest(argv=argv), self.assertRaisesRegex(module.EngineeringError, "mode"):
                module._contains_inline_code(argv)

    def test_known_interpreters_require_a_positive_non_inline_mode(self):
        module = self.module()
        benign = (
            ["py", "-m", "unittest"],
            ["py.exe", "-3.12", "-m", "unittest"],
            ["python3.12", "check.py"],
            ["node20", "check.js"],
            ["pwsh7", "-NoProfile", "-File", "check.ps1"],
            ["zsh", "check.sh"],
            ["ruby3.3", "check.rb"],
            ["perl", "check.pl"],
        )
        for argv in benign:
            with self.subTest(argv=argv):
                self.assertFalse(module._contains_inline_code(argv))
        for argv in (["py", "-3.12"], ["zsh", "-x"], ["ruby", "-w"]):
            with self.subTest(argv=argv), self.assertRaisesRegex(module.EngineeringError, "mode"):
                module._contains_inline_code(argv)

    def test_legacy_check_attestation_is_non_inline_only(self):
        module = self.module()
        root, _ = self.prepared_repo("legacy-check-attestation")
        safe = module._check_capability_claims(
            root, [[sys.executable, "-m", "unittest", "--help"]]
        )
        legacy_safe = dict(safe)
        legacy_safe.pop("allow_inline_code")
        controller = module._project_controller_dir(root)
        registry, _, key = module._append_attestation(
            controller, "check_capability", legacy_safe
        )
        module._transactional_json_documents(
            [(module._attestation_path(controller), registry)],
            [(module._controller_key_path(controller), key)] if key else None,
        )
        self.assertEqual(
            legacy_safe,
            module._require_attestation(controller, "check_capability", safe)["claims"],
        )

        inline = module._check_capability_claims(
            root, [[sys.executable, "-c", "print(1)"]]
        )
        retained_inline = dict(inline)
        retained_inline.pop("allow_inline_code")
        self.assertFalse(
            module._attestation_claims_match(
                "check_capability", retained_inline, inline
            )
        )

    def test_check_execution_uses_credential_reduced_environment(self):
        module = self.module()
        captured = {}

        def run(argv, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout=b"ok", stderr=b"")

        with (
            patch.dict(os.environ, {"SYNTHETIC_SECRET_TOKEN": "do-not-pass"}, clear=False),
            patch.object(module.subprocess, "run", side_effect=run),
        ):
            module._execute_check([sys.executable, "--version"], timeout_seconds=1)

        self.assertNotIn("SYNTHETIC_SECRET_TOKEN", captured["env"])
        self.assertFalse(captured["shell"])

    def test_project_resolution_keeps_exact_git_identity(self):
        module = self.module()
        root = self.init_repo()

        project = module.resolve_project(root)

        self.assertEqual(root.resolve(), project.root)
        self.assertEqual("main", project.branch)
        self.assertEqual("main", project.default_branch)
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            project.commit,
        )

    def test_v1_paths_are_adopted_before_v2_defaults(self):
        module = self.module()
        root = self.init_repo()
        legacy = root / "engineering-traceability.json"
        legacy.write_text('{"version": 1}\n', encoding="utf-8")
        (root / "engineering.json").write_text('{"version": 2}\n', encoding="utf-8")

        config = module.load_project_config(root)

        self.assertEqual(legacy, config["source_path"])

    def test_setup_commands_adopt_complete_controls_without_parallel_files(self):
        for generation in ("v1", "v2"):
            for command in ("bootstrap", "reconstruct"):
                with self.subTest(generation=generation, command=command):
                    root = self.init_repo(f"{generation}-{command}")
                    self.write_controls(root, generation=generation)
                    manifest_path, trace_dir = self.control_paths(root, generation)
                    other_manifest, other_trace_dir = self.control_paths(
                        root, "v2" if generation == "v1" else "v1"
                    )
                    self.commit_all(root, "existing controls")
                    original = manifest_path.read_bytes()

                    result = self.run_cli(
                        command,
                        root,
                        "--graphify-python",
                        sys.executable,
                    )

                    self.assertEqual(1, result.returncode, result.stderr)
                    proposal = json.loads(result.stdout)
                    self.assertEqual("setup", proposal["forwarded_to"])
                    self.assertFalse(proposal["writes_applied"])
                    self.assertEqual(original, manifest_path.read_bytes())
                    self.assertTrue(trace_dir.is_dir())
                    self.assertFalse(other_manifest.exists())
                    self.assertFalse(other_trace_dir.exists())

    def test_setup_commands_fail_closed_for_config_only_controls(self):
        for generation in ("v1", "v2"):
            with self.subTest(generation=generation):
                root = self.init_repo(generation)
                self.write_controls(root, generation=generation)
                _, trace_dir = self.control_paths(root, generation)
                shutil.rmtree(trace_dir)
                self.commit_all(root, "legacy controls")

                result = self.run_cli(
                    "bootstrap",
                    root,
                    "--graphify-python",
                    sys.executable,
                )

                self.assertEqual(2, result.returncode)
                self.assertIn("missing_links", result.stderr)

    def test_setup_commands_fail_closed_for_incomplete_controls(self):
        for generation in ("v1", "v2"):
            with self.subTest(generation=generation):
                root = self.init_repo(generation)
                self.write_controls(root, generation=generation)
                _, trace_dir = self.control_paths(root, generation)
                (trace_dir / "decision-ledger.md").unlink()
                self.commit_all(root, "incomplete controls")

                result = self.run_cli(
                    "reconstruct",
                    root,
                    "--graphify-python",
                    sys.executable,
                )

                self.assertEqual(2, result.returncode)
                self.assertIn("missing_ledger", result.stderr)

    def test_python_project_uses_unittest_discovery(self):
        module = self.module()
        root = self.init_repo()
        (root / "pyproject.toml").write_text("[project]\nname='synthetic'\n")

        self.assertIn(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            module.discover_checks(root),
        )

    def test_node_project_uses_existing_test_command(self):
        module = self.module()
        root = self.init_repo()
        (root / "package-lock.json").write_text("{}\n", encoding="utf-8")

        self.assertIn(["npm", "test", "--", "--run"], module.discover_checks(root))

    def test_explicit_stack_neutral_argv_takes_precedence(self):
        module = self.module()
        root = self.init_repo()
        (root / "package-lock.json").write_text("{}\n", encoding="utf-8")
        (root / "engineering.json").write_text(
            json.dumps({"version": 2, "checks": [["make", "verify"]]}),
            encoding="utf-8",
        )

        self.assertEqual([["make", "verify"]], module.discover_checks(root))

    def test_shell_string_check_is_rejected(self):
        module = self.module()
        root = self.init_repo()
        (root / "engineering.json").write_text(
            json.dumps({"version": 2, "checks": ["make verify"]}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(module.EngineeringError, "argv"):
            module.discover_checks(root)

    def test_managed_instruction_argv_takes_precedence_over_config(self):
        module = self.module()
        root = self.init_repo()
        (root / "engineering.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "checks": [["config-check"]],
                    "managed_instructions": {"checks": [["managed-check"]]},
                }
            ),
            encoding="utf-8",
        )

        self.assertEqual([["managed-check"]], module.discover_checks(root))

    def test_managed_instruction_free_text_is_rejected(self):
        module = self.module()
        root = self.init_repo()
        (root / "engineering.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "checks": [["config-check"]],
                    "managed_instructions": {"checks": "make verify"},
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(module.EngineeringError, "managed.*argv"):
            module.discover_checks(root)

    def test_free_text_instructions_are_never_parsed_as_commands(self):
        module = self.module()
        root = self.init_repo()
        (root / "pyproject.toml").write_text("[project]\nname='synthetic'\n")
        (root / "AGENTS.md").write_text(
            "Run checks with: powershell -Command Remove-Item important.txt\n",
            encoding="utf-8",
        )

        self.assertEqual(
            [[sys.executable, "-m", "unittest", "discover", "-s", "tests"]],
            module.discover_checks(root),
        )

    def test_installed_graphify_matches_exact_reviewed_identity(self):
        module = self.module()

        identity = module.verify_graphify(Path(sys.executable))

        self.assertEqual("0.9.5", identity.version)
        self.assertEqual(
            "d89ec68af95e0cad801b56d88df383991e659823",
            identity.commit,
        )
        self.assertEqual(
            ("update", "query", "path", "explain"),
            identity.required_commands,
        )

    def test_synthetic_repo_has_an_owner_private_controller_directory(self):
        module = self.module()
        root = self.init_repo("private-controller")
        controller = module._project_controller_dir(root)
        controller.mkdir(parents=True)

        module._enforce_owner_private(controller)
        module._verify_owner_private(controller, directory=True)

    def test_graphify_install_argv_is_exact_and_pinned(self):
        module = self.module()

        self.assertEqual(
            [
                "uv",
                "tool",
                "install",
                "git+https://github.com/safishamsi/graphify.git"
                "@d89ec68af95e0cad801b56d88df383991e659823",
            ],
            module.graphify_install_argv("v0.9.5"),
        )

    def test_unpinned_graphify_is_rejected(self):
        module = self.module()

        with self.assertRaisesRegex(module.EngineeringError, "pinned"):
            module.graphify_install_argv("main")

    def test_ambiguous_overlay_provenance_is_rejected(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root, provenance="ambiguous")
        commit = self.commit_all(root, "ambiguous overlay")

        with self.assertRaisesRegex(module.EngineeringError, "Invalid edge schema"):
            module.construct_checkpoint(root, commit, None)

    def test_v1_hook_migration_preserves_original_and_runs_controller_once(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root)
        self.commit_all(root, "legacy controls")
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        hooks.mkdir(parents=True, exist_ok=True)
        original = hooks / "pre-commit"
        original.write_text(
            "#!/bin/sh\nprintf 'original\\n' >> \"$PWD/hook.log\"\n",
            encoding="utf-8",
            newline="\n",
        )
        original.chmod(0o755)
        preserved = hooks / "engineering-preserved"
        preserved.mkdir(parents=True)
        (preserved / "pre-commit").write_bytes(original.read_bytes())
        original.write_bytes(module._round_one_hook_wrapper("pre-commit"))

        module._install_hooks_authorized(
            root,
            sys.executable,
            ENGINEERING_SCRIPT,
            module._hook_plan_state(root),
        )
        result = subprocess.run(
            ["git", "-C", str(root), "hook", "run", "pre-commit"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((root / "hook.log").exists())
        self.assertEqual(
            ["original"],
            (root / "hook.log").read_text(encoding="utf-8").splitlines(),
        )
        self.assertEqual(
            1,
            (result.stdout + result.stderr).count('"event": "pre-commit"'),
            f"stdout={result.stdout!r}; stderr={result.stderr!r}",
        )

    def test_round_one_hook_marker_migrates_only_original_preserved_body(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root)
        self.commit_all(root, "legacy controls")
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        preserved = hooks / "engineering-preserved"
        preserved.mkdir(parents=True)
        (preserved / "pre-commit").write_text(
            "#!/bin/sh\nprintf 'original\\n' >> \"$PWD/hook.log\"\n",
            encoding="utf-8",
            newline="\n",
        )
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\n"
            "# engineering-hook\n"
            'exec "$(dirname -- "$0")/engineering-dispatcher" pre-commit "$@"\n',
            encoding="utf-8",
            newline="\n",
        )

        original_bytes = (preserved / "pre-commit").read_bytes()
        module._install_hooks_authorized(
            root,
            sys.executable,
            ENGINEERING_SCRIPT,
            module._hook_plan_state(root),
        )
        result = subprocess.run(
            ["git", "-C", str(root), "hook", "run", "pre-commit"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((root / "hook.log").exists())
        self.assertEqual(
            ["original"],
            (root / "hook.log").read_text(encoding="utf-8").splitlines(),
        )
        self.assertEqual(
            1, (result.stdout + result.stderr).count('"event": "pre-commit"')
        )
        self.assertEqual(
            original_bytes,
            (
                hooks
                / "engineering-traceability-preserved"
                / "pre-commit"
            ).read_bytes(),
        )

    def test_query_commands_preserve_v1_results(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root)
        commit = self.commit_all(root, "query overlay")
        module.construct_checkpoint(root, commit, None)

        cases = {
            ("status", root): lambda value: self.assertTrue(value["fresh"]),
            ("coverage", root): lambda value: self.assertTrue(
                value["requirements"][0]["covered"]
            ),
            ("trace", root, "REQ-1"): lambda value: self.assertEqual(
                ["REQ-1", "DEC-1", "CODE-1", "TEST-1"], value["path"]
            ),
            ("impact", root, "REQ-1"): lambda value: self.assertEqual(
                ["DEC-1", "CODE-1", "TEST-1"], value["exact"]
            ),
            ("why-code", root, "CODE-1"): lambda value: self.assertEqual(
                ["REQ-1"], value["requirements"]
            ),
            ("why-test", root, "TEST-1"): lambda value: self.assertEqual(
                ["REQ-1"], value["requirements"]
            ),
            ("compare", root, commit, commit): lambda value: self.assertEqual(
                {"added": [], "removed": [], "changed": []}, value["nodes"]
            ),
        }
        for arguments, assertion in cases.items():
            with self.subTest(command=arguments[0]):
                result = self.run_cli(*arguments)
                self.assertEqual(0, result.returncode, result.stderr)
                assertion(json.loads(result.stdout))

    def prepared_repo(
        self,
        name: str,
        *,
        baseline_accepted: bool = True,
        provenance: str = "direct",
        source_body: str | None = None,
    ) -> tuple[Path, str]:
        root = self.init_repo(name)
        self.write_controls(root, provenance=provenance)
        if source_body is not None:
            (root / "requirements.md").write_text(
                "# REQ-1\n" + source_body + "\n", encoding="utf-8"
            )
        manifest = root / "engineering-traceability.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["baseline"] = {"accepted": baseline_accepted}
        payload["context"] = {"token_budget": 128}
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        commit = self.commit_all(root, "preparation fixture")
        fake_graphify = self.write_fake_graphify()
        with patch.dict(os.environ, {"PYTHONPATH": str(fake_graphify)}, clear=False):
            engineering.rebuild(root, commit, sys.executable)
        return root, commit

    def set_base_graph_nodes(self, root: Path, nodes: list[dict]) -> Path:
        module = self.module()
        commit = self.git(root, "rev-parse", "HEAD")
        checkpoint_path = module._checkpoint_path(root, commit)
        graph_path = checkpoint_path.parent / "graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        graph["nodes"] = nodes
        graph["links"] = []
        graph_path.write_text(json.dumps(graph), encoding="utf-8")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["metadata"]["graph_digest"] = hashlib.sha256(
            graph_path.read_bytes()
        ).hexdigest()
        checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
        return checkpoint_path

    def test_prepare_returns_bounded_ready_contract_and_atomic_metadata(self):
        module = self.module()
        root, commit = self.prepared_repo(
            "prepare-ready", source_body="PRIVATE SYNTHETIC BODY"
        )
        module.approve_checks(root)

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md", "tests/test_app.py"], "forbidden": ["publish", "deploy"]},
            None,
        )

        self.assertEqual(
            {
                "schema",
                "run_id",
                "project",
                "intent",
                "authorization",
                "autonomy",
                "readiness",
                "blockers",
                "advisories",
                "context",
                "impact",
                "required_checks",
            },
            set(result),
        )
        self.assertEqual("engineering.prepare.v1", result["schema"])
        self.assertRegex(result["run_id"], r"^run-[0-9a-f]{6}$")
        self.assertEqual(commit, result["project"]["commit"])
        self.assertEqual("main", result["project"]["branch"])
        self.assertRegex(result["project"]["root_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual("ready", result["readiness"])
        self.assertEqual([{"id": "REQ-1", "provenance": "direct"}], result["context"][:1])
        self.assertTrue(any(item["id"] == "README.md" for item in result["impact"]))
        retained = (
            module.common_graph_dir(root)
            / "runs"
            / result["run_id"]
            / "preparation.json"
        )
        self.assertEqual(result, json.loads(retained.read_text(encoding="utf-8")))
        self.assertNotIn("PRIVATE SYNTHETIC BODY", retained.read_text(encoding="utf-8"))
        self.assertFalse(any(path.name.startswith(".preparation.json") for path in retained.parent.iterdir()))

    def test_prepare_deduplicates_graphify_context_and_exact_neighbours(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-context")
        graphify_context = {
            "status": "success",
            "context": [{"id": "REQ-1", "provenance": "inferred"}],
        }

        with patch.object(module, "_graphify_query_context", return_value=graphify_context) as query:
            result = module.prepare(
                root,
                "change REQ-1",
                {"scope": ["README.md"], "forbidden": []},
                None,
            )

        query.assert_called_once()
        self.assertEqual(1, sum(item["id"] == "REQ-1" for item in result["context"]))
        self.assertIn({"id": "DEC-1", "provenance": "direct"}, result["context"])
        self.assertIn({"id": "REQ-1", "provenance": "direct"}, result["context"])

    def test_prepare_reports_baseline_remote_and_unrelated_maintenance_advisories(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-advisory", baseline_accepted=False)
        module.approve_checks(root)
        module.queue_maintenance(
            root,
            {
                "area": "docs",
                "artifact": "docs/guide.md",
                "kind": "stale_artifact",
                "impact": "routine",
            },
        )
        self.git(root, "remote", "add", "upstream", str(root / "missing.git"))

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )

        self.assertEqual("ready_with_advisories", result["readiness"])
        self.assertEqual(
            [
                "canonical remote freshness is unknown",
                "historical gaps remain before baseline acceptance",
                "Engineering maintenance: 1 queued artifact(s). Run `engineering maintain` "
                "once to repair safe items; blocked items still require review. The command "
                "does not change autonomy.",
            ],
            result["advisories"],
        )

    def test_prepare_blocks_missing_exact_context_and_dirty_out_of_scope_work(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-blocked")
        (root / "outside.txt").write_text("existing user work\n", encoding="utf-8")

        result = module.prepare(
            root,
            "change REQ-MISSING",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("required source or exact context is missing", result["blockers"])
        self.assertIn("dirty work exists outside the authorized scope", result["blockers"])

    def test_prepare_blocks_unapproved_contract_impact(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-contract")
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        checkpoint["nodes"].append(
            {
                "id": "CONTRACT-1",
                "type": "contract",
                "title": "Synthetic contract",
                "source": {"path": "design.md", "line": 1},
            }
        )
        checkpoint["edges"].append(
            {
                "id": "EDGE-CONTRACT",
                "from": "REQ-1",
                "to": "CONTRACT-1",
                "type": "specified_in",
                "provenance": "direct",
                "source": {"path": "requirements.md", "line": 1},
            }
        )

        with patch.object(module, "_load_checkpoint", return_value=checkpoint):
            result = module.prepare(
                root,
                "change REQ-1 contract",
                {"scope": ["design.md"], "forbidden": []},
                None,
            )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("public contract change lacks explicit approval", result["blockers"])

    def test_prepare_cli_emits_json_and_uses_blocked_exit_code(self):
        root, _ = self.prepared_repo("prepare-cli")
        self.module().approve_checks(root)

        ready = self.run_cli(
            "prepare",
            root,
            "change REQ-1",
            "--scope-json",
            json.dumps({"scope": ["README.md"], "forbidden": []}),
        )
        blocked = self.run_cli(
            "prepare",
            root,
            "change REQ-MISSING",
            "--scope-json",
            json.dumps({"scope": ["README.md"], "forbidden": []}),
        )

        self.assertEqual(0, ready.returncode, ready.stderr)
        self.assertEqual("engineering.prepare.v1", json.loads(ready.stdout)["schema"])
        self.assertEqual(1, blocked.returncode, blocked.stderr)
        self.assertEqual("blocked", json.loads(blocked.stdout)["readiness"])

    def test_prepare_exact_run_cache_does_not_rewrite_metadata(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-exact-cache")
        arguments = (
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )
        first = module.prepare(*arguments)

        with patch.object(module, "_atomic_text") as atomic_write:
            second = module.prepare(*arguments)

        self.assertEqual(first, second)
        atomic_write.assert_not_called()

    def test_scaffold_and_legacy_prepare_use_the_documented_context_budget(self):
        module = self.module()
        for generation in ("current", "legacy"):
            with self.subTest(generation=generation):
                root = self.init_repo(f"prepare-budget-{generation}")
                if generation == "current":
                    self.write_controls(root, generation="v2")
                else:
                    self.write_controls(root, generation="v1")
                commit = self.commit_all(root, "bounded context budget")
                fake_graphify = self.write_fake_graphify()
                with patch.dict(os.environ, {"PYTHONPATH": str(fake_graphify)}, clear=False):
                    module.rebuild(root, commit, sys.executable)
                empty = {"status": "empty", "context": []}
                with patch.object(
                    module, "_graphify_query_context", return_value=empty
                ) as query:
                    result = module.prepare(
                        root,
                        "change REQ-1",
                        {"scope": ["README.md"], "forbidden": []},
                        None,
                    )

                self.assertEqual("engineering.prepare.v1", result["schema"])
                self.assertEqual(1000, query.call_args.args[2])

    def test_graphify_query_uses_only_validated_bounded_node_text(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "query-contract"
        checkpoint = root / "checkpoint.json"
        root.mkdir()
        (root / "graph.json").write_text(
            json.dumps(
                {
                    "nodes": [
                        {"id": "base:req", "label": "Synthetic requirement"},
                        {"id": "base:code", "label": "Synthetic code"},
                    ],
                    "links": [],
                }
            ),
            encoding="utf-8",
        )
        output = (
            "Traversal: BFS depth=2 | Start: ['Synthetic requirement'] | 2 nodes found\n\n"
            "NODE Synthetic requirement [src=requirements.md loc=L1 community=]\n"
            "NODE Synthetic code [src=src/app.py loc=L1 community=]\n"
            "EDGE Synthetic requirement --implements [high]--> Synthetic code\n"
        )

        with patch.object(module, "verify_graphify"), patch.object(
            module.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, output, ""),
        ) as runner:
            result = module._graphify_query_context("change auth", checkpoint, 16)

        self.assertEqual("success", result["status"])
        self.assertEqual(
            [
                {"id": "base:req", "provenance": "inferred"},
                {"id": "base:code", "provenance": "inferred"},
            ],
            result["context"],
        )
        self.assertNotIn(output, json.dumps(result))
        self.assertEqual("1", runner.call_args.kwargs["env"]["GRAPHIFY_QUERY_LOG_DISABLE"])

    def test_graphify_query_distinguishes_empty_unavailable_and_invalid(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "query-outcomes"
        checkpoint = root / "checkpoint.json"
        root.mkdir()
        (root / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "base:req", "label": "Requirement"}], "links": []}),
            encoding="utf-8",
        )
        cases = (
            (subprocess.CompletedProcess([], 0, "No matching nodes found.\n", ""), "empty"),
            (subprocess.CompletedProcess([], 7, "", "PRIVATE STDERR"), "unavailable"),
            (subprocess.CompletedProcess([], 0, '{"nodes": []}\n', ""), "invalid"),
            (
                subprocess.CompletedProcess(
                    [],
                    0,
                    "Traversal: BFS depth=2 | Start: ['Unknown'] | 1 nodes found\n\n"
                    "NODE Unknown [src=x loc=L1 community=]\n",
                    "",
                ),
                "invalid",
            ),
        )
        for completed, expected in cases:
            with self.subTest(expected=expected), patch.object(
                module, "verify_graphify"
            ), patch.object(module.subprocess, "run", return_value=completed):
                result = module._graphify_query_context("change auth", checkpoint, 16)
                self.assertEqual(expected, result["status"])
                self.assertNotIn("PRIVATE STDERR", json.dumps(result))

    def test_empty_graph_does_not_hide_missing_graphify(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "empty-query"
        checkpoint = root / "checkpoint.json"
        root.mkdir()
        (root / "graph.json").write_text(
            json.dumps({"nodes": [], "links": []}), encoding="utf-8"
        )

        with patch.object(
            module,
            "verify_graphify",
            side_effect=module.EngineeringError("missing"),
        ) as verify, patch.object(module.subprocess, "run") as runner:
            result = module._graphify_query_context("change auth", checkpoint, 16)

        self.assertEqual("unavailable", result["status"])
        verify.assert_called_once_with(sys.executable)
        runner.assert_not_called()

    def test_query_never_returns_credential_shaped_graph_ids(self):
        module = self.module()
        root = Path(self.temporary_directory.name) / "credential-query-id"
        checkpoint = root / "checkpoint.json"
        root.mkdir()
        credential_id = "sk-synthetic123456789"
        (root / "graph.json").write_text(
            json.dumps(
                {"nodes": [{"id": credential_id, "label": "Credential node"}], "links": []}
            ),
            encoding="utf-8",
        )
        output = (
            "Traversal: BFS depth=2 | Start: ['Credential node'] | 1 nodes found\n\n"
            "NODE Credential node [src=x loc=L1 community=]\n"
        )

        with patch.object(module, "verify_graphify"), patch.object(
            module.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, output, ""),
        ):
            result = module._graphify_query_context("change auth", checkpoint, 16)

        self.assertEqual("invalid", result["status"])
        self.assertNotIn(credential_id, json.dumps(result))

    def test_context_merge_keeps_strongest_provenance_and_first_id_order(self):
        module = self.module()

        result = module._merge_context(
            [
                {"id": "REQ-1", "provenance": "inferred"},
                {"id": "DEC-1", "provenance": "ambiguous"},
                {"id": "REQ-1", "provenance": "direct"},
                {"id": "DEC-1", "provenance": "derived"},
            ]
        )

        self.assertEqual(
            [
                {"id": "REQ-1", "provenance": "direct"},
                {"id": "DEC-1", "provenance": "derived"},
            ],
            result,
        )

    def test_prepare_blocks_contract_intent_without_exact_context_or_impact(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-contract-no-id")

        result = module.prepare(
            root,
            "change the synthetic authentication contract",
            {"scope": ["design.md"], "forbidden": []},
            None,
        )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("required source or exact context is missing", result["blockers"])
        self.assertEqual([], result["impact"])

    def test_successful_empty_query_still_blocks_empty_exact_evidence(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-empty-evidence")

        with patch.object(
            module,
            "_graphify_query_context",
            return_value={"status": "empty", "context": []},
        ):
            result = module.prepare(
                root,
                "change authentication behavior",
                {"scope": ["README.md"], "forbidden": []},
                None,
            )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("required source or exact context is missing", result["blockers"])

    def test_exact_context_carries_derived_provenance_across_the_full_path(self):
        module = self.module()
        checkpoint = {
            "edges": [
                {
                    "id": "EDGE-1",
                    "from": "ORIGIN",
                    "to": "A",
                    "provenance": "derived",
                },
                {
                    "id": "EDGE-2",
                    "from": "A",
                    "to": "X",
                    "provenance": "direct",
                },
            ]
        }

        self.assertEqual(
            [
                {"id": "A", "provenance": "derived"},
                {"id": "X", "provenance": "derived"},
            ],
            module._exact_context_neighbours(checkpoint, ["ORIGIN"]),
        )

    def test_exact_context_upgrades_a_later_all_direct_path_without_duplicates(self):
        module = self.module()
        checkpoint = {
            "edges": [
                {
                    "id": "EDGE-1",
                    "from": "ORIGIN",
                    "to": "X",
                    "provenance": "derived",
                },
                {
                    "id": "EDGE-2",
                    "from": "ORIGIN",
                    "to": "A",
                    "provenance": "direct",
                },
                {
                    "id": "EDGE-3",
                    "from": "A",
                    "to": "X",
                    "provenance": "direct",
                },
            ]
        }

        result = module._exact_context_neighbours(checkpoint, ["ORIGIN"])

        self.assertEqual(
            [
                {"id": "X", "provenance": "direct"},
                {"id": "A", "provenance": "direct"},
            ],
            result,
        )
        self.assertEqual(1, sum(item["id"] == "X" for item in result))
        self.assertEqual(
            result,
            module._exact_context_neighbours(checkpoint, ["ORIGIN"]),
        )

    def test_query_selected_id_drives_exact_contract_impact_and_approval_gate(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-query-contract")
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        checkpoint["nodes"].append(
            {
                "id": "CONTRACT-1",
                "type": "contract",
                "title": "Synthetic contract",
                "source": {"path": "design.md", "line": 1},
            }
        )
        checkpoint["edges"].append(
            {
                "id": "EDGE-CONTRACT",
                "from": "REQ-1",
                "to": "CONTRACT-1",
                "type": "specified_in",
                "provenance": "direct",
                "source": {"path": "requirements.md", "line": 1},
            }
        )
        query = {"status": "success", "context": [{"id": "REQ-1", "provenance": "inferred"}]}

        with patch.object(module, "_load_checkpoint", return_value=checkpoint), patch.object(
            module, "_graphify_query_context", return_value=query
        ):
            result = module.prepare(
                root,
                "change the authentication contract",
                {"scope": ["design.md"], "forbidden": []},
                None,
            )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("public contract change lacks explicit approval", result["blockers"])
        self.assertTrue(any(item["id"] == "design.md" for item in result["impact"]))

    def test_query_unavailable_requires_exact_deterministic_only_approval(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-deterministic-only")
        module.approve_checks(root)
        unavailable = {"status": "unavailable", "context": [], "reason": "query_timeout"}

        with patch.object(module, "_graphify_query_context", return_value=unavailable):
            blocked = module.prepare(
                root,
                "change REQ-1",
                {"scope": ["README.md"], "forbidden": []},
                None,
            )
            approved = module.prepare(
                root,
                "change REQ-1",
                {
                    "scope": ["README.md"],
                    "forbidden": [],
                    "deterministic_only_approved": True,
                },
                None,
            )
            empty_approved = module.prepare(
                root,
                "change authentication behavior",
                {
                    "scope": ["README.md"],
                    "forbidden": [],
                    "deterministic_only_approved": True,
                },
                None,
            )

        self.assertEqual("blocked", blocked["readiness"])
        self.assertEqual("ready", approved["readiness"])
        self.assertFalse(blocked["authorization"]["deterministic_only_approved"])
        self.assertTrue(approved["authorization"]["deterministic_only_approved"])
        self.assertEqual("blocked", empty_approved["readiness"])

    def test_direct_contract_origin_requires_only_documented_approval_key(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-direct-contract")
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        checkpoint["nodes"].append(
            {
                "id": "CONTRACT-1",
                "type": "contract",
                "title": "Synthetic contract",
                "source": {"path": "design.md", "line": 1},
            }
        )
        checkpoint["edges"].append(
            {
                "id": "EDGE-CONTRACT",
                "from": "REQ-1",
                "to": "CONTRACT-1",
                "type": "specified_in",
                "provenance": "direct",
                "source": {"path": "requirements.md", "line": 1},
            }
        )
        empty = {"status": "empty", "context": []}
        base_scope = {
            "scope": ["design.md"],
            "forbidden": [],
            "context_ids": ["CONTRACT-1"],
        }
        aliases = (
            {"approve_contract_change": True},
            {"contract_change": "approved"},
            {"approvals": ["contract_change"]},
        )
        with patch.object(module, "_load_checkpoint", return_value=checkpoint), patch.object(
            module, "_graphify_query_context", return_value=empty
        ):
            blocked = [
                module.prepare(root, "change contract", {**base_scope, **alias}, None)
                for alias in aliases
            ]
            approved = module.prepare(
                root,
                "change contract",
                {**base_scope, "contract_change_approved": True},
                None,
            )

        for result in blocked:
            self.assertIn("public contract change lacks explicit approval", result["blockers"])
        self.assertNotIn("public contract change lacks explicit approval", approved["blockers"])
        self.assertTrue(any(item["id"] == "design.md" for item in approved["impact"]))

    def test_upstream_contract_in_exact_context_requires_approval(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-upstream-contract")
        checkpoint = module._load_checkpoint(root, module.git(root, "rev-parse", "HEAD"))
        decision = next(node for node in checkpoint["nodes"] if node["id"] == "DEC-1")
        decision.update({"id": "CONTRACT-1", "type": "contract"})
        for edge in checkpoint["edges"]:
            if edge["to"] == "DEC-1":
                edge["to"] = "CONTRACT-1"
            if edge["from"] == "DEC-1":
                edge["from"] = "CONTRACT-1"
        empty = {"status": "empty", "context": []}
        base_scope = {
            "scope": ["README.md"],
            "forbidden": [],
            "context_ids": ["CODE-1"],
        }

        with patch.object(module, "_load_checkpoint", return_value=checkpoint), patch.object(
            module, "_graphify_query_context", return_value=empty
        ):
            blocked = module.prepare(root, "change CODE-1", base_scope, None)
            approved = module.prepare(
                root,
                "change CODE-1",
                {**base_scope, "contract_change_approved": True},
                None,
            )

        contract_blocker = "public contract change lacks explicit approval"
        self.assertIn(
            {"id": "CONTRACT-1", "provenance": "derived"}, blocked["context"]
        )
        self.assertIn(contract_blocker, blocked["blockers"])
        self.assertEqual(
            [item for item in blocked["blockers"] if item != contract_blocker],
            approved["blockers"],
        )

    def test_impact_provenance_tracks_each_path_and_keeps_strongest(self):
        module = self.module()
        checkpoint = {
            "nodes": [
                {
                    "id": identifier,
                    "type": "code_symbol",
                    "source": {"path": path, "line": 1},
                }
                for identifier, path in (
                    ("ORIGIN", "origin.py"),
                    ("DIRECT", "direct.py"),
                    ("DERIVED", "derived.py"),
                    ("SHARED", "shared.py"),
                )
            ],
            "edges": [
                {
                    "id": "EDGE-DIRECT",
                    "from": "ORIGIN",
                    "to": "DIRECT",
                    "provenance": "direct",
                },
                {
                    "id": "EDGE-DERIVED",
                    "from": "ORIGIN",
                    "to": "DERIVED",
                    "provenance": "derived",
                },
                {
                    "id": "EDGE-SHARED-DERIVED",
                    "from": "DERIVED",
                    "to": "SHARED",
                    "provenance": "direct",
                },
                {
                    "id": "EDGE-SHARED-DIRECT",
                    "from": "ORIGIN",
                    "to": "SHARED",
                    "provenance": "direct",
                },
            ],
        }

        impact = module._context_impact(checkpoint, ["ORIGIN"])

        self.assertEqual(
            {
                "derived.py": "derived",
                "direct.py": "direct",
                "origin.py": "direct",
                "shared.py": "direct",
            },
            {item["id"]: item["provenance"] for item in impact},
        )
        self.assertEqual(
            sorted(item["id"] for item in impact),
            [item["id"] for item in impact],
        )
        self.assertEqual(impact, module._context_impact(checkpoint, ["ORIGIN"]))

    def test_prepare_cli_query_failure_is_bounded_without_traceback(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-cli-query-failure")
        self.set_base_graph_nodes(
            root, [{"id": "REQ-1", "label": "Synthetic requirement"}]
        )
        fake_graphify = self.write_fake_graphify()

        with patch.dict(os.environ, {"PYTHONPATH": str(fake_graphify)}, clear=False):
            result = self.run_cli(
                "prepare",
                root,
                "change REQ-1",
                "--scope-json",
                json.dumps({"scope": ["README.md"], "forbidden": []}),
            )

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual("blocked", json.loads(result.stdout)["readiness"])
        self.assertNotIn("Traceback", result.stderr)
        self.assertLess(len(result.stderr), 512)

    def test_prepare_redacts_credentials_and_rejects_them_in_authorization(self):
        module = self.module()
        root, _ = self.prepared_repo("prepare-credentials")
        intent = (
            'change REQ-1 with Authorization: Bearer abc.def.ghi, '
            'password is "two word secret", api_key=sk-synthetic123456789'
        )

        result = module.prepare(
            root,
            intent,
            {"scope": ["README.md"], "forbidden": []},
            None,
        )
        retained = (
            module.common_graph_dir(root)
            / "runs"
            / result["run_id"]
            / "preparation.json"
        ).read_text(encoding="utf-8")
        for secret in ("abc.def.ghi", "two word secret", "sk-synthetic123456789"):
            self.assertNotIn(secret, result["intent"])
            self.assertNotIn(secret, retained)
        for key, value in (
            ("scope", ["password: secret value"]),
            ("forbidden", ["Bearer secret-token"]),
        ):
            with self.subTest(key=key), self.assertRaisesRegex(
                module.EngineeringError, "credential"
            ):
                module.prepare(
                    root,
                    "change REQ-1",
                    {"scope": value if key == "scope" else ["README.md"],
                     "forbidden": value if key == "forbidden" else []},
                    None,
                )
        with self.assertRaisesRegex(module.EngineeringError, "bounded"):
            module.prepare(
                root,
                "change REQ-1",
                {"scope": ["a" * 513], "forbidden": []},
                None,
            )
        with self.assertRaisesRegex(module.EngineeringError, "credential"):
            module.prepare(
                root,
                "change authentication",
                {
                    "scope": ["README.md"],
                    "forbidden": [],
                    "context_ids": ["ghp_synthetic123456789"],
                },
                None,
            )

    def test_credential_predicate_preserves_legitimate_repeated_space_paths(self):
        module = self.module()
        value = "docs/password  reset guide.md"

        authorization = module._scope_envelope(
            {"scope": [value], "forbidden": []}
        )

        self.assertEqual([value], authorization["scope"])

    def test_integrity_failure_retains_previous_atomic_checkpoint(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root)
        first_commit = self.commit_all(root, "covered overlay")
        first_path = module.construct_checkpoint(root, first_commit, None)
        first_bytes = first_path.read_bytes()
        links = root / "docs" / "engineering-traceability" / "links.json"
        value = json.loads(links.read_text(encoding="utf-8"))
        value["nodes"] = []
        value["edges"] = []
        links.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        second_commit = self.commit_all(root, "unexpected shrink")

        with self.assertRaisesRegex(module.EngineeringError, "Unexpected shrink"):
            module.construct_checkpoint(root, second_commit, first_commit)

        self.assertEqual(first_bytes, first_path.read_bytes())
        with self.assertRaises(module.EngineeringError):
            module._checkpoint_path(root, second_commit)

    def test_rebuild_failure_retains_previous_atomic_checkpoint(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root)
        first_commit = self.commit_all(root, "covered overlay")
        self.git(root, "update-ref", "refs/remotes/origin/main", first_commit)
        fake_graphify = self.write_fake_graphify()
        environment = {
            "PYTHONPATH": str(fake_graphify),
        }
        with patch.dict(os.environ, environment, clear=False):
            first_path = module.rebuild(root, first_commit, sys.executable)
        first_checkpoint = first_path.read_bytes()
        first_graph = (first_path.parent / "graph.json").read_bytes()
        (root / "README.md").write_text("# Changed\n", encoding="utf-8")
        second_commit = self.commit_all(root, "changed source")

        with patch.dict(
            os.environ,
            {**environment, "FAKE_GRAPHIFY_FAIL": "1"},
            clear=False,
        ):
            with self.assertRaises(module.EngineeringError):
                module.rebuild(root, second_commit, sys.executable)

        self.assertEqual(first_checkpoint, first_path.read_bytes())
        self.assertEqual(first_graph, (first_path.parent / "graph.json").read_bytes())
        expected = (
            module._common_graph_dir(root)
            / "features"
            / "main"
            / second_commit
        )
        self.assertFalse(expected.exists())

    def test_all_provenance_classes_have_exact_coverage_semantics(self):
        module = self.module()
        expected = {
            "direct": (True, ["DEC-1", "CODE-1", "TEST-1"], []),
            "derived": (True, ["DEC-1", "CODE-1", "TEST-1"], []),
            "inferred": (False, [], ["DEC-1", "CODE-1", "TEST-1"]),
            "missing": (False, [], []),
        }
        for provenance, (covered, exact, suggested) in expected.items():
            with self.subTest(provenance=provenance):
                root = self.init_repo(provenance)
                self.write_controls(root, provenance=provenance)
                commit = self.commit_all(root, f"{provenance} overlay")
                module.construct_checkpoint(root, commit, None)
                checkpoint = module._load_checkpoint(root, commit)

                coverage = module.coverage(checkpoint)
                impact = module.query_result("impact", checkpoint, "REQ-1")

                self.assertEqual(covered, coverage[0]["covered"])
                self.assertEqual(exact, impact["exact"])
                self.assertEqual(suggested, impact["suggested"])

    def test_hook_project_identity_uses_tracked_manifest(self):
        module = self.module()
        resolver = getattr(module, "resolve_hook_project", None)
        self.assertTrue(callable(resolver))
        for generation in ("v1", "v2"):
            with self.subTest(generation=generation):
                root = self.init_repo(generation)
                self.write_controls(root, generation=generation)
                manifest_path, _ = self.control_paths(root, generation)
                self.assertIsNone(resolver(root))
                self.git(root, "add", manifest_path.name)
                self.assertEqual(root.resolve(), resolver(root).root)

    def test_hook_downstream_operations_use_indexed_manifest_identity(self):
        module = self.module()
        fake_graphify = self.write_fake_graphify()
        for generation in ("v1", "v2"):
            for event in ("post-commit", "pre-push"):
                with self.subTest(generation=generation, event=event):
                    root = self.init_repo(f"{generation}-{event}")
                    self.write_controls(root, generation=generation)
                    commit = self.commit_all(root, f"tracked {generation} controls")
                    environment = {"PYTHONPATH": str(fake_graphify)}
                    if event == "pre-push":
                        with patch.dict(os.environ, environment, clear=False):
                            module.rebuild(root, commit, sys.executable)
                    opposite = "v2" if generation == "v1" else "v1"
                    opposite_manifest, _ = self.control_paths(root, opposite)
                    opposite_manifest.write_text(
                        '{"version": 1}\n', encoding="utf-8"
                    )

                    with patch.dict(os.environ, environment, clear=False):
                        result = module.handle_hook(event, root, sys.executable)

                    if event == "post-commit":
                        self.assertEqual("stale", result["action"])
                        self.assertEqual("hook_budget_exceeded", result["reason"])
                        self.assertEqual(commit, result["commit"])
                    else:
                        self.assertEqual("validate", result["action"])
                        self.assertIn(commit, result["checkpoint"])

    def test_local_pre_commit_does_not_require_remote_head(self):
        module = self.module()
        root = self.init_repo()
        self.write_controls(root, generation="v2")
        self.commit_all(root, "local controls")
        self.git(root, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        self.git(root, "update-ref", "-d", "refs/remotes/origin/main")

        result = module.handle_hook("pre-commit", root, sys.executable)

        self.assertEqual({"event": "pre-commit", "action": "validate"}, result)

    def test_post_merge_rejects_missing_or_invalid_default_branch(self):
        module = self.module()
        invalid_values = (("missing", None), ("empty", ""), ("non-string", 7))
        for generation in ("v1", "v2"):
            for case, value in invalid_values:
                with self.subTest(generation=generation, case=case):
                    root = self.init_repo(f"{generation}-{case}")
                    self.write_controls(root, generation=generation)
                    manifest_path, _ = self.control_paths(root, generation)
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if case == "missing":
                        manifest["project"].pop("default_branch")
                    else:
                        manifest["project"]["default_branch"] = value
                    manifest_path.write_text(
                        json.dumps(manifest), encoding="utf-8"
                    )
                    self.git(root, "add", "-A")

                    with self.assertRaisesRegex(
                        module.EngineeringError,
                        "invalid_manifest.*default_branch",
                    ):
                        module.handle_hook("post-merge", root, sys.executable)

    def test_hook_is_no_op_for_sanitized_and_export_repositories(self):
        module = self.module()
        for kind in ("sanitized", "export"):
            with self.subTest(kind=kind):
                root = self.init_repo(kind)

                result = module.handle_hook("pre-commit", root, sys.executable)

                self.assertEqual(
                    {
                        "event": "pre-commit",
                        "action": "no_op",
                        "reason": "manifest_not_tracked",
                    },
                    result,
                )

    def test_hook_is_no_op_for_manifest_free_peer_worktree(self):
        module = self.module()
        root = self.init_repo("main")
        self.write_controls(root)
        self.commit_all(root, "main controls")
        peer = Path(self.temporary_directory.name) / "peer"
        self.git(root, "worktree", "add", "-b", "peer", str(peer))
        self.addCleanup(
            lambda: subprocess.run(
                ["git", "-C", str(root), "worktree", "remove", "--force", str(peer)],
                capture_output=True,
                text=True,
            )
        )
        manifest_path, trace_dir = self.control_paths(peer, "v1")
        manifest_path.unlink()
        shutil.rmtree(trace_dir)
        self.git(peer, "add", "-A")

        result = module.handle_hook("pre-commit", peer, sys.executable)

        self.assertEqual("manifest_not_tracked", result["reason"])

    def test_hook_fails_closed_for_invalid_tracked_controls(self):
        module = self.module()
        defects = (
            "invalid_manifest",
            "missing_ledger",
            "invalid_ledger",
            "missing_links",
            "invalid_links",
            "missing_governed_artifact",
            "invalid_governed_artifact",
        )
        for generation in ("v1", "v2"):
            for defect in defects:
                with self.subTest(generation=generation, defect=defect):
                    root = self.init_repo(f"{generation}-{defect}")
                    self.write_controls(root, generation=generation)
                    manifest_path, trace_dir = self.control_paths(root, generation)
                    if defect == "invalid_manifest":
                        manifest_path.write_text("{", encoding="utf-8")
                    elif defect == "missing_ledger":
                        (trace_dir / "decision-ledger.md").unlink()
                    elif defect == "invalid_ledger":
                        (trace_dir / "decision-ledger.md").write_text(
                            "not a heading\n", encoding="utf-8"
                        )
                    elif defect == "missing_links":
                        (trace_dir / "links.json").unlink()
                    elif defect == "invalid_links":
                        (trace_dir / "links.json").write_text("{", encoding="utf-8")
                    elif defect == "missing_governed_artifact":
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        manifest["inputs"].append("governed.txt")
                        manifest_path.write_text(
                            json.dumps(manifest), encoding="utf-8"
                        )
                    else:
                        links_path = trace_dir / "links.json"
                        links = json.loads(links_path.read_text(encoding="utf-8"))
                        links["nodes"][0]["source"]["line"] = 999
                        links_path.write_text(json.dumps(links), encoding="utf-8")
                    self.git(root, "add", "-A")

                    with self.assertRaisesRegex(module.EngineeringError, defect):
                        module.handle_hook("pre-commit", root, sys.executable)

    def test_canonical_and_feature_checkpoints_remain_separate(self):
        module = self.module()
        root = self.init_repo("main")
        self.write_controls(root)
        main_commit = self.commit_all(root, "main overlay")
        self.git(root, "update-ref", "refs/remotes/origin/main", main_commit)
        canonical = module.construct_checkpoint(root, main_commit, None)
        linked = Path(self.temporary_directory.name) / "linked"
        self.git(root, "worktree", "add", "-b", "feature/example", str(linked))
        self.addCleanup(
            lambda: subprocess.run(
                ["git", "-C", str(root), "worktree", "remove", "--force", str(linked)],
                capture_output=True,
                text=True,
            )
        )
        (linked / "README.md").write_text("# Feature\n", encoding="utf-8")
        feature_commit = self.commit_all(linked, "feature change")
        feature = module.construct_checkpoint(linked, feature_commit, None)

        self.assertIn("main", canonical.parts)
        self.assertIn("features", feature.parts)
        self.assertNotEqual(canonical, feature)


class Task3ContractTests(unittest.TestCase):
    setUp = Task2ContractTests.setUp
    module = Task2ContractTests.module
    init_repo = Task2ContractTests.init_repo
    git = Task2ContractTests.git
    commit_all = Task2ContractTests.commit_all
    write_controls = Task2ContractTests.write_controls
    write_fake_graphify = Task2ContractTests.write_fake_graphify

    def graphify_environment(self, fake_graphify: Path, **extra: str) -> dict[str, str]:
        return {"PYTHONPATH": str(fake_graphify), **extra}

    def governed_repo(self, name: str = "governed") -> Path:
        root = self.init_repo(name)
        self.write_controls(root, generation="v2")
        commit = self.commit_all(root, "engineering controls")
        self.git(root, "update-ref", "refs/remotes/origin/main", commit)
        return root

    def add_linked_worktree(self, root: Path, branch: str = "feature/example") -> Path:
        linked = Path(self.temporary_directory.name) / branch.replace("/", "-")
        self.git(root, "worktree", "add", "-b", branch, str(linked))
        self.addCleanup(
            lambda: subprocess.run(
                ["git", "-C", str(root), "worktree", "remove", "--force", str(linked)],
                capture_output=True,
                text=True,
            )
        )
        return linked

    def commit_file(self, root: Path, relative: str, content: str) -> str:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return self.commit_all(root, f"change {relative}")

    def cold_checkpoint(self, root: Path) -> tuple[Path, dict[str, str]]:
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            result = self.module().rebuild(root, sys.executable)
        self.assertEqual("full", result["mode"])
        return fake, environment

    def test_all_worktrees_share_one_git_common_graph_root(self):
        module = self.module()
        root = self.governed_repo()
        linked = self.add_linked_worktree(root)

        self.assertEqual(
            module.common_graph_dir(root),
            module.common_graph_dir(linked),
        )

    def test_three_worktrees_share_one_common_cache_root(self):
        module = self.module()
        root = self.governed_repo()
        first = self.add_linked_worktree(root, "feature/one")
        second = self.add_linked_worktree(root, "feature/two")

        self.assertEqual(
            {module.common_graph_dir(root)},
            {
                module.common_graph_dir(root),
                module.common_graph_dir(first),
                module.common_graph_dir(second),
            },
        )

    def test_feature_rebuild_never_publishes_canonical(self):
        module = self.module()
        root = self.governed_repo()
        feature = self.add_linked_worktree(root)
        fake = self.write_fake_graphify()

        with patch.dict(
            os.environ, self.graphify_environment(fake), clear=False
        ):
            result = module.rebuild(feature, sys.executable)

        checkpoint = Path(result["checkpoint"])
        self.assertIn("features", checkpoint.parts)
        self.assertNotIn("main", checkpoint.parts)

    def test_exact_checkpoint_hit_skips_graphify_update(self):
        module = self.module()
        root = self.governed_repo()
        fake = self.write_fake_graphify()
        record = Path(self.temporary_directory.name) / "graphify-record.jsonl"
        environment = self.graphify_environment(
            fake, FAKE_GRAPHIFY_RECORD=str(record)
        )

        with patch.dict(os.environ, environment, clear=False):
            first = module.rebuild(root, sys.executable)
        first_calls = record.read_text(encoding="utf-8").splitlines()
        with patch.dict(
            os.environ,
            {**environment, "FAKE_GRAPHIFY_FAIL": "1"},
            clear=False,
        ):
            second = module.rebuild(root, sys.executable)

        self.assertEqual(first["checkpoint"], second["checkpoint"])
        self.assertEqual("exact_cache", second["mode"])
        self.assertEqual(first_calls, record.read_text(encoding="utf-8").splitlines())

    def test_nearest_compatible_ancestor_uses_update_for_changed_code(self):
        module = self.module()
        root = self.governed_repo()
        fake, environment = self.cold_checkpoint(root)
        record = Path(self.temporary_directory.name) / "incremental.jsonl"
        self.commit_file(root, "src/example.py", "changed = True\n")

        with patch.dict(
            os.environ,
            {**environment, "FAKE_GRAPHIFY_RECORD": str(record)},
            clear=False,
        ):
            result = module.rebuild(root, sys.executable)

        self.assertEqual("changed_path_adapter", result["mode"])
        self.assertEqual([], result["argv"])
        self.assertEqual(["src/example.py"], result["changed_files"])
        recorded = json.loads(record.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual("private_rebuild_code", recorded[0])
        self.assertEqual("src/example.py", recorded[-1].replace("\\", "/"))

    def test_hook_defers_semantic_and_document_media_changes(self):
        module = self.module()
        root = self.governed_repo()
        manifest_path = root / "engineering.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["graphify"]["hook_budget_seconds"] = 60
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.commit_all(root, "configure measured hook budget")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "docs/design.md", "# Changed meaning\n")

        with patch.dict(os.environ, environment, clear=False):
            result = module.dispatch_hook(
                root, "post-commit", graphify_python=sys.executable
            )

        self.assertEqual("stale", result["freshness"])
        self.assertEqual("semantic_update_deferred", result["reason"])

    def test_hook_budget_preserves_prior_checkpoint_and_marks_stale(self):
        module = self.module()
        root = self.governed_repo()
        fake, environment = self.cold_checkpoint(root)
        prior = module._checkpoint_path(root, self.git(root, "rev-parse", "HEAD"))
        self.commit_file(root, "src/example.py", "changed = True\n")

        with patch.dict(
            os.environ,
            {**environment, "FAKE_GRAPHIFY_SLOW": "0.2"},
            clear=False,
        ):
            result = module.rebuild(
                root,
                sys.executable,
                hook_budget_seconds=0.01,
            )

        self.assertEqual("stale", result["freshness"])
        self.assertEqual("hook_budget_exceeded", result["reason"])
        self.assertTrue(result["previous_checkpoint_preserved"])
        self.assertTrue(prior.exists())

    def test_post_commit_uses_only_the_configured_hook_budget(self):
        module = self.module()
        root = self.governed_repo()
        manifest_path = root / "engineering.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["graphify"]["hook_budget_seconds"] = 60
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.commit_all(root, "configure measured hook budget")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/budgeted.py", "budgeted = True\n")

        with patch.dict(os.environ, environment, clear=False):
            result = module.dispatch_hook(
                root, "post-commit", graphify_python=sys.executable
            )

        self.assertEqual("changed_path_adapter", result["mode"])
        self.assertEqual("current", result["freshness"])

    def test_post_commit_never_runs_a_cold_full_rebuild(self):
        module = self.module()
        root = self.governed_repo()
        fake = self.write_fake_graphify()

        with patch.dict(
            os.environ, self.graphify_environment(fake), clear=False
        ):
            result = module.dispatch_hook(
                root, "post-commit", graphify_python=sys.executable
            )

        self.assertNotEqual("full", result["mode"])
        self.assertEqual("stale", result["freshness"])

    def test_two_clones_recreate_local_checkpoints_from_tracked_sources(self):
        module = self.module()
        source = self.governed_repo("source")
        first = Path(self.temporary_directory.name) / "clone-one"
        second = Path(self.temporary_directory.name) / "clone-two"
        self.git(source, "clone", str(source), str(first))
        self.git(source, "clone", str(source), str(second))

        self.assertNotEqual(
            module.common_graph_dir(first),
            module.common_graph_dir(second),
        )
        self.assertEqual(
            module.overlay_fingerprints(first),
            module.overlay_fingerprints(second),
        )

    def test_v2_has_no_enterprise_graph_import_config_or_argv_surface(self):
        source = ENGINEERING_SCRIPT.read_text(encoding="utf-8")
        imports = {
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        manifest = MANIFEST.read_text(encoding="utf-8").lower()

        self.assertFalse(any("enterprise" in item.lower() for item in imports))
        self.assertNotIn("enterprise_endpoint", source.lower())
        self.assertNotIn("enterprise_client", source.lower())
        self.assertNotIn("prefer-enterprise", manifest)
        self.assertNotIn("require-enterprise", manifest)

    def test_no_remote_uses_configured_local_default_branch(self):
        module = self.module()
        root = self.governed_repo()
        local_main = self.commit_file(root, "src/local.py", "local = True\n")

        result = module.reconcile_canonical(root, refresh_remote=False)

        self.assertEqual("not_configured", result["freshness"])
        self.assertEqual(local_main, result["commit"])

    def test_ambiguous_remotes_block_canonical_publication(self):
        module = self.module()
        root = self.governed_repo()
        self.git(root, "remote", "add", "origin", "https://example.test/one.git")
        self.git(root, "remote", "add", "upstream", "https://example.test/two.git")

        with self.assertRaisesRegex(module.EngineeringError, "remote"):
            module.reconcile_canonical(root, refresh_remote=False)

    def test_advanced_origin_main_rebuilds_without_active_main_worktree(self):
        module = self.module()
        root = self.governed_repo()
        feature = self.add_linked_worktree(root)
        self.git(root, "remote", "add", "origin", "https://example.test/origin.git")
        self.git(root, "checkout", "-b", "advance-main")
        advanced = self.commit_file(root, "src/advanced.py", "advanced = True\n")
        self.git(root, "update-ref", "refs/remotes/origin/main", advanced)
        fake = self.write_fake_graphify()

        with patch.dict(
            os.environ, self.graphify_environment(fake), clear=False
        ):
            result = module.reconcile_canonical(
                feature,
                refresh_remote=False,
                graphify_python=sys.executable,
            )

        self.assertEqual("unknown", result["freshness"])
        self.assertFalse(result["canonical_published"])

    def test_ci_rejects_stale_inexact_and_commit_mismatched_checkpoints(self):
        module = self.module()
        for state in ("stale", "inexact", "commit_mismatch"):
            with self.subTest(state=state):
                root = self.governed_repo(state)
                fake, _ = self.cold_checkpoint(root)
                if state == "stale":
                    module._record_stale(root, self.git(root, "rev-parse", "HEAD"), "test")
                elif state == "inexact":
                    Path(module._checkpoint_path(root, self.git(root, "rev-parse", "HEAD")).parent / "graph.json").unlink()
                else:
                    path = module._checkpoint_path(root, self.git(root, "rev-parse", "HEAD"))
                    checkpoint = json.loads(path.read_text(encoding="utf-8"))
                    checkpoint["metadata"]["commit"] = "0" * 40
                    path.write_text(json.dumps(checkpoint), encoding="utf-8")

                result = module.check_merge_readiness(root)

                self.assertFalse(result["ready"])
                expected = {
                    "stale": "stale",
                    "inexact": "invalid_json",
                    "commit_mismatch": "commit_mismatch",
                }[state]
                self.assertEqual(expected, result["reason"])

    def test_ci_accepts_exact_current_commit_checkpoint(self):
        module = self.module()
        root = self.governed_repo()
        self.cold_checkpoint(root)

        result = module.check_merge_readiness(root)

        self.assertTrue(result["ready"])

    def test_legacy_cleanup_requires_recognized_files_and_replacement(self):
        module = self.module()
        root = self.governed_repo()
        self.cold_checkpoint(root)
        exclude = Path(self.git(root, "rev-parse", "--git-path", "info/exclude"))
        if not exclude.is_absolute():
            exclude = root / exclude
        exclude.write_text("graphify-out/\n", encoding="utf-8")
        legacy = root / "graphify-out"
        legacy.mkdir()
        (legacy / "graph.json").write_text("{}\n", encoding="utf-8")
        (legacy / "graph.html").write_text("<html></html>\n", encoding="utf-8")

        candidate = module.inventory_legacy_outputs(root)[0]

        self.assertTrue(candidate["safe_generated"])
        self.assertTrue(module.clean_legacy_output(root, Path(candidate["path"])))
        self.assertFalse(legacy.exists())

    def test_unignored_legacy_output_is_never_deleted(self):
        module = self.module()
        root = self.governed_repo()
        self.cold_checkpoint(root)
        legacy = root / "graphify-out"
        legacy.mkdir()
        (legacy / "graph.json").write_text("{}\n", encoding="utf-8")

        candidate = module.inventory_legacy_outputs(root)[0]

        self.assertFalse(candidate["safe_generated"])
        self.assertFalse(module.clean_legacy_output(root, Path(candidate["path"])))
        self.assertTrue(legacy.exists())

    def test_unknown_legacy_output_is_preserved_and_queued(self):
        module = self.module()
        root = self.governed_repo()
        self.cold_checkpoint(root)
        legacy = root / "graphify-out"
        legacy.mkdir()
        (legacy / "graph.json").write_text("{}\n", encoding="utf-8")
        (legacy / "notes.txt").write_text("keep me\n", encoding="utf-8")

        candidate = module.inventory_legacy_outputs(root)[0]
        result = module.reconcile_legacy_outputs(root)

        self.assertFalse(candidate["safe_generated"])
        self.assertFalse(module.clean_legacy_output(root, Path(candidate["path"])))
        self.assertTrue((legacy / "notes.txt").exists())
        self.assertEqual("legacy_graph_ambiguous", result["maintenance"][0]["kind"])

    def test_cold_incremental_and_exact_cache_wall_times_are_recordable(self):
        module = self.module()
        root = self.governed_repo()
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)

        started = time.perf_counter()
        with patch.dict(os.environ, environment, clear=False):
            cold = module.rebuild(root, sys.executable)
        cold_seconds = time.perf_counter() - started
        self.commit_file(root, "src/timed.py", "value = 1\n")
        started = time.perf_counter()
        with patch.dict(os.environ, environment, clear=False):
            incremental = module.rebuild(root, sys.executable)
        incremental_seconds = time.perf_counter() - started
        started = time.perf_counter()
        with patch.dict(os.environ, environment, clear=False):
            exact = module.rebuild(root, sys.executable)
        exact_seconds = time.perf_counter() - started

        self.assertEqual(("full", "changed_path_adapter", "exact_cache"), (
            cold["mode"], incremental["mode"], exact["mode"]
        ))
        self.assertTrue(all(value >= 0 for value in (
            cold_seconds, incremental_seconds, exact_seconds
        )))
        print(
            "TASK3_CONTROLLER_STUB_PERF "
            f"cold={cold_seconds:.6f}s "
            f"incremental={incremental_seconds:.6f}s "
            f"exact_cache={exact_seconds:.6f}s"
        )


class Task3AmendedContractTests(unittest.TestCase):
    setUp = Task3ContractTests.setUp
    module = Task3ContractTests.module
    init_repo = Task3ContractTests.init_repo
    git = Task3ContractTests.git
    commit_all = Task3ContractTests.commit_all
    write_controls = Task3ContractTests.write_controls
    write_fake_graphify = Task3ContractTests.write_fake_graphify
    graphify_environment = Task3ContractTests.graphify_environment
    governed_repo = Task3ContractTests.governed_repo
    add_linked_worktree = Task3ContractTests.add_linked_worktree
    commit_file = Task3ContractTests.commit_file
    cold_checkpoint = Task3ContractTests.cold_checkpoint

    def create_test_reparse(self, link: Path, target: Path, *, directory: bool) -> bool:
        try:
            os.symlink(target, link, target_is_directory=directory)
            return True
        except OSError:
            if os.name != "nt" or not directory:
                return False
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        return created.returncode == 0

    def remove_test_reparse(self, link: Path, *, directory: bool) -> None:
        if not (link.exists() or link.is_symlink()):
            return
        if link.is_symlink() or not directory:
            link.unlink()
        else:
            os.rmdir(link)

    def semantic_suffix_source(self, suffix: str, version: int) -> str:
        name = f"semantic_symbol_{version}"
        normalized = suffix.lower()
        if normalized == ".json":
            return json.dumps({name: {"value": version}}) + "\n"
        if normalized in {".csproj", ".fsproj", ".vbproj"}:
            return (
                "<Project><PropertyGroup>"
                f"<AssemblyName>{name}</AssemblyName>"
                "</PropertyGroup></Project>\n"
            )
        if normalized == ".sln":
            return (
                "Microsoft Visual Studio Solution File, Format Version 12.00\n"
                f'Project("{{00000000-0000-0000-0000-000000000001}}") = '
                f'"{name}", "{name}.csproj", '
                '"{00000000-0000-0000-0000-000000000002}"\nEndProject\n'
            )
        if normalized == ".slnx":
            return f'<Solution><Project Path="{name}.csproj" /></Solution>\n'
        if normalized == ".xaml":
            return (
                f'<Window x:Class="Example.{name}" '
                'xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
                'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" />\n'
            )
        if normalized in {".py", ".rb", ".jl"}:
            return f"def {name}():\n    return {version}\n"
        if normalized == ".r":
            return f"{name} <- function() {{ {version} }}\n"
        if normalized in {".sh", ".bash"}:
            return f"{name}() {{ echo {version}; }}\n"
        if normalized in {".ps1", ".psm1"}:
            return f"function {name} {{ return {version} }}\n"
        if normalized == ".psd1":
            return f"@{{ RootModule = '{name}.psm1'; ModuleVersion = '1.0.{version}' }}\n"
        if normalized == ".sql":
            return f"CREATE TABLE {name} (id INTEGER);\n"
        if normalized in {
            ".vue", ".svelte", ".astro", ".razor", ".cshtml", ".ejs"
        }:
            return f"<script>function {name}() {{ return {version}; }}</script>\n"
        if normalized in {
            ".f", ".f03", ".f08", ".f90", ".f95"
        }:
            return f"subroutine {name}()\nend subroutine {name}\n"
        if normalized in {
            ".pas", ".pp", ".dpr", ".dpk", ".lpr", ".inc"
        }:
            return f"procedure {name}; begin end;\n"
        if normalized in {".tf", ".hcl"}:
            return f'resource "example" "{name}" {{ value = {version} }}\n'
        if normalized == ".tfvars":
            return f'{name} = "{version}"\n'
        if normalized == ".go":
            return f"package sample\nfunc {name}() int {{ return {version} }}\n"
        if normalized in {".js", ".jsx", ".mjs", ".ts", ".tsx", ".ets"}:
            return f"export function {name}() {{ return {version}; }}\n"
        if normalized == ".rs":
            return f"fn {name}() -> i32 {{ {version} }}\n"
        return f"int {name}(void) {{ return {version}; }}\n"

    def timed_out_registered_worker(self, module):
        test_case = self

        class TimedOutProcess:
            pid = 2_147_000_000

            def __init__(self, command):
                self.command = command
                self.dead = False

            def communicate(self, timeout=None):
                test_case.worker_timeout_seconds = timeout
                raise subprocess.TimeoutExpired(self.command, timeout)

            def poll(self):
                return 0 if self.dead else None

            def wait(self, timeout=None):
                self.dead = True
                return 0

            def kill(self):
                self.dead = True

            terminate = kill

        def start(command):
            root, operation_id = command[-2:]
            record_path = (
                module.common_graph_dir(Path(root))
                / "state"
                / "operations"
                / operation_id
                / "resources.json"
            )
            record = json.loads(record_path.read_text(encoding="utf-8"))
            worktree = Path(record["worktree_path"])
            stage = Path(record["staging_path"])
            worktree.mkdir()
            stage.mkdir()
            return TimedOutProcess(command)

        return start

    def test_pinned_changed_path_adapter_signature_is_exact(self):
        identity, _ = self.module()._verify_graphify_adapter_in_process()

        self.assertEqual("0.9.5", identity["version"])
        self.assertEqual(
            "d89ec68af95e0cad801b56d88df383991e659823",
            identity["commit"],
        )
        self.assertEqual(
            [
                "watch_path",
                "changed_paths",
                "follow_symlinks",
                "force",
                "no_cluster",
                "acquire_lock",
                "block_on_lock",
            ],
            identity["parameters"],
        )
        self.assertTrue(identity["changed_paths_keyword_only"])

    def test_incremental_refresh_has_no_suffix_table_or_per_file_public_cli(self):
        module = self.module()
        source = ENGINEERING_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertFalse(hasattr(module, "CODE_SUFFIXES"))
        self.assertIn("_rebuild_code", source)
        self.assertIn("changed_paths=[Path(path) for path in changed]", source)
        self.assertIn("run_full_graph_maintenance", source)

    def test_stub_incremental_adapter_receives_git_a_m_d_r_paths_once(self):
        module = self.module()
        root = self.governed_repo()
        (root / "src").mkdir()
        (root / "src" / "modify.py").write_text("value = 1\n", encoding="utf-8")
        (root / "src" / "delete.py").write_text("gone = 1\n", encoding="utf-8")
        (root / "src" / "rename.py").write_text("old = 1\n", encoding="utf-8")
        self.commit_all(root, "baseline code")
        fake, environment = self.cold_checkpoint(root)
        record = Path(self.temporary_directory.name) / "private-adapter.jsonl"
        (root / "src" / "add.mjs").write_text("export const added = 1;\n", encoding="utf-8")
        (root / "src" / "modify.py").write_text("value = 2\n", encoding="utf-8")
        (root / "src" / "delete.py").unlink()
        self.git(root, "mv", "src/rename.py", "src/renamed.py")
        target = self.commit_all(root, "a m d r")

        with patch.dict(
            os.environ,
            {**environment, "FAKE_GRAPHIFY_RECORD": str(record)},
            clear=False,
        ):
            result = module.rebuild(root, sys.executable, target_commit=target)

        self.assertTrue(record.is_file(), result)
        adapter_call = json.loads(record.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual("changed_path_adapter", result["mode"])
        self.assertEqual("private_rebuild_code", adapter_call[0])
        self.assertEqual(
            {
                "src/add.mjs",
                "src/delete.py",
                "src/modify.py",
                "src/rename.py",
                "src/renamed.py",
            },
            set(result["changed_paths"]),
        )
        self.assertEqual(target, result["built_at_commit"])
        self.assertEqual(Path(result["snapshot"]), Path(result["child_cwd"]))

    def test_real_pinned_adapter_matches_cold_graph_for_a_m_d_r(self):
        module = self.module()
        root = self.governed_repo("real-adapter")
        (root / "src").mkdir()
        (root / "src" / "modify.py").write_text(
            "def modify(value):\n    return value + 1\n", encoding="utf-8"
        )
        (root / "src" / "delete.py").write_text(
            "def deleted():\n    return True\n", encoding="utf-8"
        )
        (root / "src" / "rename.py").write_text(
            "def renamed():\n    return 'old'\n", encoding="utf-8"
        )
        self.commit_all(root, "real graph baseline")
        module.rebuild(root, sys.executable)
        (root / "src" / "add.py").write_text(
            "def added():\n    return 1\n", encoding="utf-8"
        )
        (root / "src" / "modify.py").write_text(
            "def modify(value):\n    return value + 2\n", encoding="utf-8"
        )
        (root / "src" / "delete.py").unlink()
        self.git(root, "mv", "src/rename.py", "src/renamed.py")
        target = self.commit_all(root, "real a m d r")

        started = time.monotonic()
        incremental = module.rebuild(root, sys.executable)
        incremental_seconds = time.monotonic() - started
        cold_root = Path(self.temporary_directory.name) / "real-cold"
        self.git(root, "clone", str(root), str(cold_root))
        started = time.monotonic()
        cold = module.rebuild(cold_root, sys.executable)
        cold_seconds = time.monotonic() - started
        started = time.monotonic()
        exact = module.rebuild(root, sys.executable)
        exact_seconds = time.monotonic() - started

        def digest(result):
            graph = json.loads(
                (Path(result["checkpoint"]).parent / "graph.json").read_text(
                    encoding="utf-8"
                )
            )
            comparable = {
                "nodes": sorted(
                    graph["nodes"], key=lambda item: json.dumps(item, sort_keys=True)
                ),
                "links": sorted(
                    graph.get("links", graph.get("edges", [])),
                    key=lambda item: json.dumps(item, sort_keys=True),
                ),
            }
            return hashlib.sha256(
                json.dumps(comparable, sort_keys=True).encode("utf-8")
            ).hexdigest()

        self.assertEqual(
            "changed_path_adapter", incremental["mode"], incremental
        )
        self.assertEqual(target, incremental["built_at_commit"])
        self.assertEqual(
            {
                "src/add.py",
                "src/delete.py",
                "src/modify.py",
                "src/rename.py",
                "src/renamed.py",
            },
            set(incremental["changed_paths"]),
        )
        self.assertEqual(digest(cold), digest(incremental))
        self.assertEqual("exact_cache", exact["mode"])
        print(
            "TASK3_REAL_GRAPHIFY_PERF "
            f"cold={cold_seconds:.6f}s "
            f"changed_path_adapter={incremental_seconds:.6f}s "
            f"exact_cache={exact_seconds:.6f}s"
        )

    def test_real_pinned_adapter_covers_every_supported_suffix_and_matches_cold(self):
        module = self.module()
        identity, _ = module._verify_graphify_adapter_in_process()
        root = self.governed_repo("all-suffixes")
        suffix_root = root / "suffixes"
        suffix_root.mkdir()
        (suffix_root / "anchor.py").write_text(
            "def anchor():\n    return 1\n", encoding="utf-8"
        )
        paths = []
        for index, suffix in enumerate(identity["code_extensions"]):
            paths.append(suffix_root / f"sample_{index:03d}{suffix}")
        self.commit_all(root, "all suffix baseline")
        baseline_result = module.rebuild(root, sys.executable)
        baseline_graph = json.loads(
            (Path(baseline_result["checkpoint"]).parent / "graph.json").read_text(
                encoding="utf-8"
            )
        )
        for path, suffix in zip(paths, identity["code_extensions"]):
            path.write_text(
                self.semantic_suffix_source(suffix, 1), encoding="utf-8"
            )
        target = self.commit_all(root, "add every supported suffix")

        incremental = module.rebuild(root, sys.executable)
        cold_root = Path(self.temporary_directory.name) / "all-suffixes-cold"
        self.git(root, "clone", str(root), str(cold_root))
        cold = module.rebuild(cold_root, sys.executable)
        cold_graph = json.loads(
            (Path(cold["checkpoint"]).parent / "graph.json").read_text(
                encoding="utf-8"
            )
        )

        def semantic_graph(graph):
            node_semantics = {
                item["id"]: {
                    key: value
                    for key, value in item.items()
                    if key not in {"id", "community", "community_name"}
                }
                for item in graph["nodes"]
            }
            links = []
            for item in graph.get("links", graph.get("edges", [])):
                projected = {
                    key: value
                    for key, value in item.items()
                    if key not in {"source", "target"}
                }
                projected["source_semantics"] = node_semantics[item["source"]]
                projected["target_semantics"] = node_semantics[item["target"]]
                links.append(projected)
            return {"nodes": list(node_semantics.values()), "links": links}

        def graph_digest(result):
            graph = json.loads(
                (Path(result["checkpoint"]).parent / "graph.json").read_text(
                    encoding="utf-8"
                )
            )
            semantics = semantic_graph(graph)
            comparable = {
                "nodes": sorted(
                    semantics["nodes"],
                    key=lambda item: json.dumps(item, sort_keys=True),
                ),
                "links": sorted(
                    semantics["links"],
                    key=lambda item: json.dumps(item, sort_keys=True),
                ),
            }
            return hashlib.sha256(
                json.dumps(comparable, sort_keys=True).encode("utf-8")
            ).hexdigest()

        self.assertEqual(
            "changed_path_adapter", incremental["mode"], incremental
        )
        self.assertEqual(target, incremental["built_at_commit"])
        self.assertEqual(
            {path.relative_to(root).as_posix() for path in paths},
            set(incremental["changed_paths"]),
        )
        incremental_graph = json.loads(
            (Path(incremental["checkpoint"]).parent / "graph.json").read_text(
                encoding="utf-8"
            )
        )
        incremental_semantics = semantic_graph(incremental_graph)
        cold_semantics = semantic_graph(cold_graph)
        for path in paths:
            relative = path.relative_to(root).as_posix()
            before = [
                item
                for collection in ("nodes", "links")
                for item in baseline_graph.get(collection, [])
                if item.get("source_file") == relative
            ]
            after = [
                item
                for collection in ("nodes", "links")
                for item in incremental_semantics[collection]
                if item.get("source_file") == relative
            ]
            cold_after = [
                item
                for collection in ("nodes", "links")
                for item in cold_semantics[collection]
                if item.get("source_file") == relative
            ]
            with self.subTest(suffix=path.suffix):
                self.assertEqual([], before, relative)
                self.assertEqual(
                    sorted(cold_after, key=lambda item: json.dumps(item, sort_keys=True)),
                    sorted(after, key=lambda item: json.dumps(item, sort_keys=True)),
                    relative,
                )
        self.assertEqual(graph_digest(cold), graph_digest(incremental))

    def test_checkpoint_identity_is_clone_and_worktree_stable(self):
        module = self.module()
        source = self.governed_repo("stable-identity")
        first = Path(self.temporary_directory.name) / "identity-one"
        second = Path(self.temporary_directory.name) / "identity-two"
        self.git(source, "clone", str(source), str(first))
        self.git(source, "clone", str(source), str(second))
        linked = self.add_linked_worktree(first, "feature/identity")

        self.assertEqual(
            module.checkpoint_identity(first),
            module.checkpoint_identity(second),
        )
        self.assertEqual(
            module.checkpoint_identity(first),
            module.checkpoint_identity(linked),
        )

    def test_mixed_code_and_document_changes_require_semantic_completion(self):
        module = self.module()
        root = self.governed_repo()
        (root / "src").mkdir()
        (root / "src" / "base.py").write_text("value = 1\n", encoding="utf-8")
        self.commit_all(root, "baseline source")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/base.py", "value = 2\n")
        self.commit_file(root, "docs/meaning.md", "# New meaning\n")

        with patch.dict(os.environ, environment, clear=False):
            result = module.rebuild(root, sys.executable)

        self.assertEqual("stale", result["freshness"])
        self.assertEqual("semantic_completion_required", result["reason"])
        self.assertFalse(module.check_merge_readiness(root)["ready"])

    def test_base_graph_integrity_binds_parse_schema_commit_root_and_digest(self):
        module = self.module()
        defects = (
            "invalid_json",
            "invalid_schema",
            "commit_mismatch",
            "root_binding_mismatch",
            "digest_mismatch",
        )
        for defect in defects:
            with self.subTest(defect=defect):
                root = self.governed_repo(f"graph-{defect}")
                fake, environment = self.cold_checkpoint(root)
                commit = self.git(root, "rev-parse", "HEAD")
                checkpoint = module._checkpoint_path(root, commit)
                graph_path = checkpoint.parent / "graph.json"
                metadata = json.loads(checkpoint.read_text(encoding="utf-8"))
                if defect == "invalid_json":
                    graph_path.write_text("{", encoding="utf-8")
                elif defect == "invalid_schema":
                    graph_path.write_text('{"nodes": "wrong", "links": []}', encoding="utf-8")
                elif defect == "commit_mismatch":
                    graph = json.loads(graph_path.read_text(encoding="utf-8"))
                    graph["built_at_commit"] = "0" * 40
                    graph_path.write_text(json.dumps(graph), encoding="utf-8")
                elif defect == "root_binding_mismatch":
                    metadata["metadata"]["project_identity"] = "wrong"
                    checkpoint.write_text(json.dumps(metadata), encoding="utf-8")
                else:
                    metadata["metadata"]["graph_digest"] = "0" * 64
                    checkpoint.write_text(json.dumps(metadata), encoding="utf-8")

                validation = module.validate_checkpoint(root, checkpoint, commit)
                self.assertFalse(validation["valid"])
                self.assertEqual(defect, validation["reason"])
                self.assertFalse(module.check_merge_readiness(root)["ready"])
                with patch.dict(os.environ, environment, clear=False):
                    rebuilt = module.rebuild(root, sys.executable)
                self.assertNotEqual("exact_cache", rebuilt["mode"])

    def test_configured_remote_requires_successful_exact_destination_refresh(self):
        module = self.module()
        root = self.governed_repo()
        remote = Path(self.temporary_directory.name) / "authority.git"
        self.git(root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "config", "--unset-all", "remote.origin.fetch")
        self.git(
            root,
            "config",
            "--add",
            "remote.origin.fetch",
            "+refs/heads/main:refs/heads/main",
        )

        rejected = module.reconcile_canonical(root, refresh_remote=True)
        self.assertEqual("unknown", rejected["freshness"])
        self.assertFalse(rejected["canonical_published"])
        self.assertEqual([], rejected["fetch_argv"])

        self.git(root, "config", "--unset-all", "remote.origin.fetch")
        self.git(
            root,
            "config",
            "--add",
            "remote.origin.fetch",
            "+refs/heads/main:refs/remotes/origin/main",
        )
        without_refresh = module.reconcile_canonical(root, refresh_remote=False)
        self.assertEqual("unknown", without_refresh["freshness"])
        self.assertFalse(without_refresh["canonical_published"])

    def test_canonical_authority_binds_and_revalidates_remote_url(self):
        module = self.module()
        root = self.governed_repo("remote-url-authority")
        remote = Path(self.temporary_directory.name) / "remote-url-authority.git"
        self.git(root, "init", "--bare", str(remote))
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "push", "-u", "origin", "main")

        authority = module._canonical_authority_details(root, refresh_remote=False)
        self.assertRegex(authority["remote_url_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(module._worker_authority_valid(root, authority, authority.get("commit") or self.git(root, "rev-parse", "refs/remotes/origin/main")))

        replacement = Path(self.temporary_directory.name) / "replacement.git"
        self.git(root, "init", "--bare", str(replacement))
        self.git(root, "remote", "set-url", "origin", str(replacement))
        self.assertFalse(
            module._worker_authority_valid(
                root, authority, self.git(root, "rev-parse", "refs/remotes/origin/main")
            )
        )

    def test_two_clone_push_fetch_reconcile_advance_and_ci(self):
        module = self.module()
        source = self.governed_repo("publisher")
        (source / "src").mkdir()
        (source / "src" / "value.py").write_text(
            "def value():\n    return 1\n", encoding="utf-8"
        )
        baseline = self.commit_all(source, "baseline source")
        remote = Path(self.temporary_directory.name) / "team.git"
        self.git(source, "init", "--bare", str(remote))
        self.git(source, "remote", "add", "origin", str(remote))
        self.git(source, "push", "-u", "origin", "main")
        self.git(source, "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
        receiver = Path(self.temporary_directory.name) / "receiver"
        self.git(source, "clone", str(remote), str(receiver))
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            first = module.reconcile_canonical(
                receiver, refresh_remote=True, graphify_python=sys.executable
            )
        self.assertEqual(baseline, first["commit"])
        (source / "src" / "value.py").write_text(
            "def value():\n    return 2\n", encoding="utf-8"
        )
        correction = self.commit_all(source, "correct value")
        self.git(source, "push", "origin", "main")

        self.assertEqual(
            "stale", module.status(receiver, target_commit=correction)["freshness"]
        )
        with patch.dict(os.environ, environment, clear=False):
            reconciled = module.reconcile_canonical(
                receiver, refresh_remote=True, graphify_python=sys.executable
            )
        self.assertEqual(correction, reconciled["commit"])
        self.assertEqual(correction, reconciled["fetched_commit"])
        self.assertEqual(
            "refs/remotes/origin/main", reconciled["fetched_destination"]
        )
        self.assertTrue(reconciled["authority_revalidated_before_publication"])
        self.git(receiver, "merge", "--ff-only", "refs/remotes/origin/main")
        self.assertEqual(correction, self.git(receiver, "rev-parse", "HEAD"))
        self.assertTrue(module.check_merge_readiness(receiver)["ready"])

    def test_legacy_cleanup_revalidates_inventory_and_replacement(self):
        module = self.module()
        root = self.governed_repo()
        self.cold_checkpoint(root)
        exclude = Path(self.git(root, "rev-parse", "--git-path", "info/exclude"))
        if not exclude.is_absolute():
            exclude = root / exclude
        exclude.write_text("graphify-out/\n", encoding="utf-8")
        legacy = root / "graphify-out"
        legacy.mkdir()
        (legacy / "graph.json").write_text("{}\n", encoding="utf-8")
        (legacy / "graph.html").write_text("<html></html>\n", encoding="utf-8")
        candidate = module.inventory_legacy_outputs(root)[0]
        (legacy / "private.txt").write_text("must survive\n", encoding="utf-8")

        self.assertFalse(module.clean_legacy_output(root, Path(candidate["path"])))
        self.assertTrue(legacy.exists())

        (legacy / "private.txt").unlink()
        module._record_stale(root, self.git(root, "rev-parse", "HEAD"), "test")
        self.assertFalse(module.clean_legacy_output(root, legacy))
        self.assertTrue(legacy.exists())

    def test_non_positive_hook_budget_starts_no_operation_or_worker(self):
        module = self.module()
        root = self.governed_repo()

        result = module.dispatch_hook(
            root,
            "post-commit",
            graphify_python=sys.executable,
            hook_budget_seconds=0,
        )

        self.assertEqual("stale", result["freshness"])
        self.assertEqual("hook_budget_exceeded", result["reason"])
        operations = module.common_graph_dir(root) / "state" / "operations"
        self.assertFalse(operations.exists())

    def test_hook_operation_uses_one_exact_repository_lock_and_bound_paths(self):
        module = self.module()
        root = self.governed_repo()

        operation = module.register_hook_operation(root)

        operation_root = Path(operation["operation_root"]).resolve()
        self.assertTrue(Path(operation["record_path"]).resolve().is_relative_to(operation_root))
        self.assertTrue(Path(operation["worktree_path"]).resolve().is_relative_to(operation_root))
        self.assertTrue(Path(operation["staging_path"]).resolve().is_relative_to(operation_root))
        self.assertEqual(
            module.common_graph_dir(root) / "state" / "lock",
            Path(operation["repository_lock_path"]),
        )
        self.assertFalse((operation_root / "lock").exists())

    def test_live_registered_operation_survives_second_controller_reconciliation(self):
        module = self.module()
        root = self.governed_repo("registration-barrier")
        barrier = threading.Barrier(2)
        holder = {}

        def register_controller():
            holder["operation"] = module.register_hook_operation(root)
            barrier.wait()
            barrier.wait()

        thread = threading.Thread(target=register_controller)
        thread.start()
        barrier.wait()
        operation = holder["operation"]
        try:
            reconciled = module.reconcile_orphaned_operations(
                root, timeout_seconds=1
            )

            self.assertTrue(Path(operation["record_path"]).is_file())
            self.assertIn(operation["operation_id"], reconciled["live"])
            self.assertEqual([], reconciled["reconciled"])
        finally:
            barrier.wait()
            thread.join()

    def test_operation_record_rejects_every_tampered_serialized_path(self):
        module = self.module()
        root = self.governed_repo("tampered-operation-paths")
        outside = Path(self.temporary_directory.name) / "outside-sentinel"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("keep\n", encoding="utf-8")
        operation = module.register_hook_operation(root)
        original = json.loads(
            Path(operation["record_path"]).read_text(encoding="utf-8")
        )

        for key in (
            "operation_root",
            "record_path",
            "worktree_path",
            "staging_path",
            "repository_lock_path",
            "result_path",
        ):
            with self.subTest(key=key):
                tampered = dict(original)
                tampered[key] = str(outside / key)
                Path(operation["record_path"]).write_text(
                    json.dumps(tampered), encoding="utf-8"
                )
                with self.assertRaisesRegex(
                    module.EngineeringError,
                    "invalid_hook_operation_(record|boundary)",
                ):
                    module._read_operation(root, operation["operation_id"])
                self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))
                Path(operation["record_path"]).write_text(
                    json.dumps(original), encoding="utf-8"
                )

    def test_cleanup_never_uses_tampered_operation_root_for_deletion(self):
        module = self.module()
        root = self.governed_repo("tampered-deletion-root")
        outside = Path(self.temporary_directory.name) / "deletion-sentinel"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("keep\n", encoding="utf-8")
        operation = module.register_hook_operation(root)
        record = json.loads(
            Path(operation["record_path"]).read_text(encoding="utf-8")
        )
        record.update(
            operation_root=str(outside),
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        Path(operation["record_path"]).write_text(
            json.dumps(record), encoding="utf-8"
        )

        result = module.cleanup_hook_operation(
            root, operation["operation_id"], timeout_seconds=5
        )

        self.assertFalse(result["completed"])
        self.assertEqual("invalid_hook_operation_record", result["reason"])
        self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))

    def test_child_reparse_plus_resolved_serialized_path_is_rejected(self):
        module = self.module()
        fields = {
            "worktree_path": True,
            "staging_path": True,
            "repository_lock_path": True,
            "record_path": False,
            "result_path": False,
        }
        tested = []
        for field, directory in fields.items():
            with self.subTest(field=field):
                root = self.governed_repo(f"child-reparse-{field}")
                operation = module.register_hook_operation(root)
                record_path = Path(operation["record_path"])
                record = json.loads(record_path.read_text(encoding="utf-8"))
                link = Path(operation[field])
                outside = (
                    Path(self.temporary_directory.name)
                    / f"outside-{field}"
                )
                if directory:
                    outside.mkdir()
                    sentinel = outside / "keep.txt"
                    sentinel.write_text("keep\n", encoding="utf-8")
                else:
                    sentinel = outside
                record[field] = str(outside.resolve())
                if field == "record_path":
                    outside.write_text(json.dumps(record), encoding="utf-8")
                    record_path.unlink()
                else:
                    record_path.write_text(json.dumps(record), encoding="utf-8")
                    if field == "result_path":
                        outside.write_text("keep\n", encoding="utf-8")
                if not self.create_test_reparse(
                    link, outside, directory=directory
                ):
                    continue
                tested.append(field)

                try:
                    with self.assertRaisesRegex(
                        module.EngineeringError,
                        "invalid_hook_operation_(record|boundary)",
                    ):
                        module._read_operation(root, operation["operation_id"])
                    self.assertTrue(sentinel.exists())
                finally:
                    self.remove_test_reparse(link, directory=directory)
        if not tested:
            self.skipTest("reparse-point fixtures unavailable")
        self.assertIn("worktree_path", tested)

    def test_every_existing_registered_resource_is_checked_for_reparse(self):
        module = self.module()
        root = self.governed_repo("every-resource-reparse")
        operation = module.register_hook_operation(root)
        Path(operation["worktree_path"]).mkdir()
        Path(operation["staging_path"]).mkdir()
        Path(operation["repository_lock_path"]).mkdir()
        Path(operation["result_path"]).write_text("{}\n", encoding="utf-8")

        for field in (
            "operation_root",
            "record_path",
            "worktree_path",
            "staging_path",
            "repository_lock_path",
            "result_path",
        ):
            expected = Path(operation[field])
            with self.subTest(field=field), patch.object(
                module,
                "_is_reparse_point",
                side_effect=lambda path, expected=expected: path == expected,
            ):
                with self.assertRaisesRegex(
                    module.EngineeringError, "invalid_hook_operation_boundary"
                ):
                    module._read_operation(root, operation["operation_id"])

    def test_intermediate_state_and_operations_reparse_ancestors_are_rejected(self):
        module = self.module()
        tested = []
        for ancestor_name in ("state", "operations"):
            with self.subTest(ancestor=ancestor_name):
                root = self.governed_repo(f"ancestor-{ancestor_name}")
                operation = module.register_hook_operation(root)
                state = module.common_graph_dir(root) / "state"
                ancestor = state if ancestor_name == "state" else state / "operations"
                outside = (
                    Path(self.temporary_directory.name)
                    / f"outside-{ancestor_name}"
                )
                shutil.move(ancestor, outside)
                sentinel = outside / "keep.txt"
                sentinel.write_text("keep\n", encoding="utf-8")
                if not self.create_test_reparse(
                    ancestor, outside, directory=True
                ):
                    shutil.move(outside, ancestor)
                    continue
                tested.append(ancestor_name)
                try:
                    with self.assertRaisesRegex(
                        module.EngineeringError,
                        "invalid_hook_operation_boundary",
                    ):
                        module._read_operation(root, operation["operation_id"])
                    self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))
                finally:
                    self.remove_test_reparse(ancestor, directory=True)
        if not tested:
            self.skipTest("reparse-point fixtures unavailable")
        self.assertEqual(["state", "operations"], tested)

    def test_operation_root_symlink_is_rejected_without_touching_target(self):
        module = self.module()
        root = self.governed_repo("symlink-operation-root")
        operation = module.register_hook_operation(root)
        operation_root = Path(operation["operation_root"])
        target = Path(self.temporary_directory.name) / "symlink-target"
        target.mkdir()
        sentinel = target / "keep.txt"
        sentinel.write_text("keep\n", encoding="utf-8")
        shutil.rmtree(operation_root)
        try:
            os.symlink(target, operation_root, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"directory symlink unavailable: {error}")
        (target / "resources.json").write_text(
            json.dumps(operation), encoding="utf-8"
        )
        record = json.loads((target / "resources.json").read_text(encoding="utf-8"))
        record.update(owner_pid=-1, worker_process_tree_dead=True, phase="orphaned")
        (target / "resources.json").write_text(json.dumps(record), encoding="utf-8")

        result = module.cleanup_hook_operation(
            root, operation["operation_id"], timeout_seconds=1
        )

        self.assertFalse(result["completed"])
        self.assertEqual("invalid_hook_operation_boundary", result["reason"])
        self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))

    def test_operation_root_reparse_point_is_rejected(self):
        module = self.module()
        root = self.governed_repo("reparse-operation-root")
        operation = module.register_hook_operation(root)

        with patch.object(module, "_is_reparse_point", return_value=True):
            with self.assertRaisesRegex(
                module.EngineeringError, "invalid_hook_operation_boundary"
            ):
                module._read_operation(root, operation["operation_id"])

    def test_every_dead_in_flight_phase_is_orphaned_then_recovered(self):
        module = self.module()
        phases = (
            "registered",
            "worktree_created",
            "staging_ready",
            "validating",
            "published",
        )
        for phase in phases:
            with self.subTest(phase=phase):
                root = self.governed_repo(f"recover-{phase}")
                operation = module.register_hook_operation(root)
                record = module._read_operation(root, operation["operation_id"])
                record.update(
                    owner_pid=-1,
                    worker_process_tree_dead=True,
                    phase=phase,
                    created_at=(
                        time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1
                    ),
                )
                module._write_operation(record)

                result = module.reconcile_orphaned_operations(
                    root, timeout_seconds=30
                )

                self.assertEqual([operation["operation_id"]], result["reconciled"])
                self.assertFalse(Path(operation["record_path"]).exists())

    def test_cleanup_wait_recomputes_deadline_after_process_start(self):
        module = self.module()
        marker = Path(self.temporary_directory.name) / "cleanup-started"
        command = [
            sys.executable,
            "-c",
            (
                "import pathlib,sys,time;"
                "pathlib.Path(sys.argv[1]).write_text('started');"
                "time.sleep(30)"
            ),
            str(marker),
        ]
        started = time.monotonic()

        completed, reason, surviving_pid = module._bounded_cleanup_command(
            command, started + 5
        )
        elapsed = time.monotonic() - started

        self.assertFalse(completed)
        self.assertEqual("cleanup_timeout", reason)
        self.assertIsNone(surviving_pid)
        self.assertEqual("started", marker.read_text(encoding="utf-8"))
        self.assertLess(elapsed, 6)

    def test_cleanup_wait_uses_post_start_remaining_time(self):
        module = self.module()
        process = Mock(returncode=0)
        process.communicate.return_value = ("", "")

        with (
            patch.object(module.time, "monotonic", side_effect=[1.0, 4.0]),
            patch.object(module, "_start_cleanup", return_value=process),
        ):
            completed, reason, surviving_pid = module._bounded_cleanup_command(
                ["python", "cleanup"], deadline=10.0
            )

        self.assertTrue(completed)
        self.assertEqual("clean", reason)
        self.assertIsNone(surviving_pid)
        process.communicate.assert_called_once_with(timeout=5.75)

    def test_cleanup_timeout_kills_and_reaps_a_started_process(self):
        module = self.module()
        process = Mock(returncode=None)
        process.communicate.return_value = ("", "")

        with (
            patch.object(module.time, "monotonic", side_effect=[1.0, 9.9]),
            patch.object(module, "_start_cleanup", return_value=process),
        ):
            completed, reason, surviving_pid = module._bounded_cleanup_command(
                ["python", "cleanup"], deadline=10.0
            )

        self.assertFalse(completed)
        self.assertEqual("cleanup_timeout", reason)
        self.assertIsNone(surviving_pid)
        process.kill.assert_called_once_with()
        process.wait.assert_called_once()
        self.assertAlmostEqual(
            0.1, process.wait.call_args.kwargs["timeout"]
        )
        process.communicate.assert_not_called()

    def test_cleanup_child_only_deletes_staging_payload(self):
        module = self.module()
        root = self.governed_repo("cleanup-child-scope")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        staging = Path(record["staging_path"])
        staging.mkdir()
        (staging / "large.bin").write_bytes(b"payload")
        captured = []
        real_rmtree_argv = module._rmtree_argv

        def record_rmtree(*paths):
            captured.append(paths)
            return real_rmtree_argv(*paths)

        with patch.object(module, "_rmtree_argv", side_effect=record_rmtree):
            result = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        self.assertTrue(result["completed"], result)
        self.assertEqual([(staging,)], captured)
        self.assertFalse(Path(record["operation_root"]).exists())

    def test_cleanup_revalidates_lock_ancestry_before_child_spawn(self):
        module = self.module()
        root = self.governed_repo("cleanup-lock-race")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        lock = Path(record["repository_lock_path"])
        outside = Path(self.temporary_directory.name) / "outside-lock-race"
        real_read = module._read_operation
        swapped = False

        def read_then_swap(*args):
            nonlocal swapped
            current = real_read(*args)
            if not swapped:
                shutil.move(lock, outside)
                self.assertTrue(
                    self.create_test_reparse(lock, outside, directory=True)
                )
                swapped = True
            return current

        with (
            patch.object(module, "_read_operation", side_effect=read_then_swap),
            patch.object(
                module,
                "_bounded_worktree_remove",
                return_value=(False, "unexpected_child_spawn", None),
            ),
        ):
            try:
                result = module.cleanup_hook_operation(
                    root, operation["operation_id"], timeout_seconds=30
                )
            finally:
                self.remove_test_reparse(lock, directory=True)

        self.assertFalse(result["completed"])
        self.assertEqual("invalid_hook_operation_boundary", result["reason"])
        self.assertTrue((outside / "owner.json").is_file())

    def test_cleanup_revalidates_after_child_before_parent_unlink(self):
        module = self.module()
        root = self.governed_repo("cleanup-parent-race")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        staging = Path(record["staging_path"])
        staging.mkdir()
        result_path = Path(record["result_path"])
        result_path.write_text("keep\n", encoding="utf-8")
        operations = Path(record["operation_root"]).parent
        outside = Path(self.temporary_directory.name) / "outside-parent-race"
        swapped = False

        def remove_then_swap(paths, _deadline):
            nonlocal swapped
            self.assertEqual([staging], paths)
            shutil.rmtree(staging)
            shutil.move(operations, outside)
            self.assertTrue(
                self.create_test_reparse(operations, outside, directory=True)
            )
            swapped = True
            return True, "clean", None

        with patch.object(
            module, "_bounded_rmtree_many", side_effect=remove_then_swap
        ):
            try:
                result = module.cleanup_hook_operation(
                    root, operation["operation_id"], timeout_seconds=30
                )
            finally:
                if swapped:
                    self.remove_test_reparse(operations, directory=True)

        outside_result = outside / operation["operation_id"] / "result.json"
        self.assertFalse(result["completed"])
        self.assertEqual("invalid_hook_operation_boundary", result["reason"])
        self.assertEqual("keep\n", outside_result.read_text(encoding="utf-8"))

    def test_cleanup_revalidates_between_parent_removals(self):
        module = self.module()
        root = self.governed_repo("cleanup-between-parent-removals")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        self.assertTrue(module._acquire_repository_lock(record))
        result_path = Path(record["result_path"])
        result_path.write_text("result\n", encoding="utf-8")
        lock = Path(record["repository_lock_path"])
        outside = Path(self.temporary_directory.name) / "outside-between-removals"
        real_unlink = Path.unlink
        swapped = False

        def unlink_then_swap(path, *args, **kwargs):
            nonlocal swapped
            value = real_unlink(path, *args, **kwargs)
            if path == result_path and not swapped:
                shutil.move(lock, outside)
                self.assertTrue(
                    self.create_test_reparse(lock, outside, directory=True)
                )
                swapped = True
            return value

        with patch.object(Path, "unlink", new=unlink_then_swap):
            try:
                result = module.cleanup_hook_operation(
                    root, operation["operation_id"], timeout_seconds=30
                )
            finally:
                if swapped:
                    self.remove_test_reparse(lock, directory=True)

        self.assertFalse(result["completed"])
        self.assertEqual("invalid_hook_operation_boundary", result["reason"])
        self.assertTrue((outside / "owner.json").is_file())

    def test_child_failure_revalidates_orphan_write_after_path_swap(self):
        module = self.module()
        for swapped_path in ("operations", "worktree"):
            with self.subTest(swapped_path=swapped_path):
                root = self.governed_repo(f"orphan-write-{swapped_path}")
                operation = module.register_hook_operation(root)
                record = module._read_operation(root, operation["operation_id"])
                record.update(
                    owner_pid=-1,
                    worker_process_tree_dead=True,
                    phase="worktree_created",
                )
                module._write_operation(record)
                worktree = Path(record["worktree_path"])
                worktree.mkdir()
                operations = Path(record["operation_root"]).parent
                selected = operations if swapped_path == "operations" else worktree
                outside = (
                    Path(self.temporary_directory.name)
                    / f"outside-orphan-write-{swapped_path}"
                )
                sentinel = None

                def fail_after_swap(_root, _worktree, _deadline):
                    nonlocal sentinel
                    shutil.move(selected, outside)
                    self.assertTrue(
                        self.create_test_reparse(selected, outside, directory=True)
                    )
                    sentinel = (
                        outside / operation["operation_id"] / "resources.json"
                        if swapped_path == "operations"
                        else Path(record["record_path"])
                    )
                    sentinel.write_text("outside sentinel\n", encoding="utf-8")
                    return False, "registered_worktree_remove_failed", None

                with patch.object(
                    module,
                    "_bounded_worktree_remove",
                    side_effect=fail_after_swap,
                ):
                    try:
                        result = module.cleanup_hook_operation(
                            root,
                            operation["operation_id"],
                            timeout_seconds=30,
                        )
                    finally:
                        self.remove_test_reparse(selected, directory=True)

                self.assertFalse(result["completed"])
                self.assertEqual(
                    "invalid_hook_operation_boundary", result["reason"]
                )
                self.assertEqual(
                    "outside sentinel\n", sentinel.read_text(encoding="utf-8")
                )

    def test_windows_shaped_exited_worker_without_confirmation_blocks(self):
        module = self.module()
        root = self.governed_repo("windows-shaped-worker-recovery")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=2_147_000_100,
            worker_pid=2_147_000_100,
            phase="orphaned",
        )
        record.pop("worker_process_tree_dead", None)
        module._write_operation(record)

        with patch.object(module, "_process_alive", return_value=False):
            result = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        self.assertFalse(result["completed"])
        self.assertEqual("live_worker_process_tree", result["reason"])
        self.assertTrue(Path(record["record_path"]).is_file())

    def test_posix_recovery_blocks_while_saved_group_exists(self):
        module = self.module()
        root = self.governed_repo("posix-live-group-recovery")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=4242,
            worker_pid=4242,
            worker_pgid=4242,
            phase="orphaned",
        )
        record.pop("worker_process_tree_dead", None)
        module._write_operation(record)

        with (
            patch.object(module.os, "killpg", return_value=None, create=True),
            patch.object(module, "_process_alive", return_value=False),
        ):
            result = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        self.assertFalse(result["completed"])
        self.assertEqual("live_worker_process_tree", result["reason"])
        self.assertTrue(Path(record["record_path"]).is_file())

    def test_posix_recovery_marks_absent_saved_group_before_cleanup(self):
        module = self.module()
        root = self.governed_repo("posix-absent-group-recovery")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=4242,
            worker_pid=4242,
            worker_pgid=4242,
            phase="orphaned",
        )
        record.pop("worker_process_tree_dead", None)
        module._write_operation(record)
        worktree = Path(record["worktree_path"])
        worktree.mkdir()

        with (
            patch.object(
                module.os,
                "killpg",
                side_effect=ProcessLookupError,
                create=True,
            ),
            patch.object(module, "_process_alive", return_value=False),
            patch.object(
                module,
                "_bounded_worktree_remove",
                return_value=(False, "registered_worktree_remove_failed", None),
            ),
        ):
            result = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        retained = json.loads(
            Path(record["record_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual("registered_worktree_remove_failed", result["reason"])
        self.assertTrue(retained.get("worker_process_tree_dead"))

    def test_parent_cleanup_preserves_unregistered_operation_payload(self):
        module = self.module()
        root = self.governed_repo("parent-cleanup-scope")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        unexpected = Path(record["operation_root"]) / "unexpected"
        unexpected.mkdir()
        sentinel = unexpected / "keep.txt"
        sentinel.write_text("keep\n", encoding="utf-8")

        result = module.cleanup_hook_operation(
            root, operation["operation_id"], timeout_seconds=30
        )

        self.assertFalse(result["completed"])
        self.assertEqual("registered_operation_remove_failed", result["reason"])
        self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))
        self.assertTrue(Path(record["record_path"]).exists())

    def test_surviving_cleanup_child_retains_record_and_blocks_recovery(self):
        module = self.module()
        root = self.governed_repo("surviving-cleanup-child")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record.update(
            owner_pid=-1,
            worker_process_tree_dead=True,
            phase="orphaned",
        )
        module._write_operation(record)
        staging = Path(record["staging_path"])
        staging.mkdir()
        (staging / "large.bin").write_bytes(b"payload")

        class SurvivingProcess:
            pid = 2_147_000_001
            returncode = None
            stdout = None
            stderr = None

            def communicate(self, timeout=None):
                raise subprocess.TimeoutExpired("cleanup", timeout)

            def kill(self):
                pass

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("cleanup", timeout)

        with patch.object(
            module, "_start_cleanup", return_value=SurvivingProcess()
        ):
            first = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=30
            )

        retained = json.loads(
            Path(record["record_path"]).read_text(encoding="utf-8")
        )
        self.assertFalse(first["completed"])
        self.assertEqual("cleanup_timeout", first["reason"])
        self.assertEqual(SurvivingProcess.pid, retained.get("cleanup_pid"))
        self.assertFalse(retained.get("cleanup_process_dead", True))
        self.assertTrue(staging.exists())

        with patch.object(
            module,
            "_process_alive",
            side_effect=lambda pid: pid == SurvivingProcess.pid,
        ):
            blocked = module.reconcile_orphaned_operations(
                root, timeout_seconds=1
            )

        self.assertEqual([operation["operation_id"]], blocked["live"])
        self.assertTrue(Path(record["record_path"]).exists())

        retained["created_at"] = (
            time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1
        )
        Path(record["record_path"]).write_text(
            json.dumps(retained), encoding="utf-8"
        )
        owner_path = Path(record["repository_lock_path"]) / "owner.json"
        if owner_path.is_file():
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            owner["created_at"] = retained["created_at"]
            owner_path.write_text(json.dumps(owner), encoding="utf-8")

        with patch.object(module, "_process_alive", return_value=False):
            recovered = module.reconcile_orphaned_operations(
                root, timeout_seconds=30
            )

        self.assertEqual([operation["operation_id"]], recovered["reconciled"])
        self.assertFalse(Path(record["operation_root"]).exists())

    def test_one_deleted_source_cannot_waive_adversarial_graph_shrink(self):
        module = self.module()
        previous = {
            "nodes": [
                {
                    "id": f"node-{index}",
                    "source_file": (
                        "src/deleted.py" if index == 0 else f"src/kept-{index}.py"
                    ),
                }
                for index in range(100)
            ]
        }
        current = {"nodes": [previous["nodes"][0]]}

        with self.assertRaisesRegex(module.EngineeringError, "unexpected_shrink"):
            module._guard_base_graph(
                current,
                previous,
                ratio=0.8,
                deleted_sources={"src/deleted.py"},
            )

    def test_cleanup_deadline_bounds_rmtree_and_leaves_durable_orphan(self):
        module = self.module()
        root = self.governed_repo("cleanup-deadline")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        record["owner_pid"] = -1
        record["worker_process_tree_dead"] = True
        record["phase"] = "orphaned"
        module._write_operation(record)
        stage = Path(record["staging_path"])
        stage.mkdir()
        (stage / "owned.tmp").write_text("owned\n", encoding="utf-8")
        slow = [
            sys.executable,
            "-c",
            "import time; time.sleep(1)",
        ]
        started = time.monotonic()
        with patch.object(module, "_rmtree_argv", return_value=slow):
            result = module.cleanup_hook_operation(
                root, operation["operation_id"], timeout_seconds=0.01
            )
        elapsed = time.monotonic() - started

        self.assertFalse(result["completed"])
        self.assertEqual("cleanup_timeout", result["reason"])
        self.assertLess(elapsed, 0.5)
        self.assertTrue(Path(record["record_path"]).is_file())
        self.assertEqual(
            "orphaned",
            json.loads(Path(record["record_path"]).read_text(encoding="utf-8"))[
                "phase"
            ],
        )

    def test_reconcile_same_valid_canonical_commit_is_exact_cache(self):
        module = self.module()
        root = self.governed_repo("canonical-cache")
        fake = self.write_fake_graphify()
        environment = self.graphify_environment(fake)
        with patch.dict(os.environ, environment, clear=False):
            first = module.reconcile_canonical(
                root, refresh_remote=False, graphify_python=sys.executable
            )
            with patch.object(
                module,
                "_run_graph_operation",
                side_effect=AssertionError("exact cache must not start a worker"),
            ):
                second = module.reconcile_canonical(
                    root, refresh_remote=False, graphify_python=sys.executable
                )

        self.assertTrue(first["canonical_published"])
        self.assertEqual("exact_cache", second["mode"])
        self.assertEqual(first["checkpoint"], second["checkpoint"])
        self.assertTrue(second["authority_revalidated_before_publication"])

    def test_non_object_checkpoint_is_invalid_for_cache_ancestor_and_ci(self):
        module = self.module()
        root = self.governed_repo("non-object-checkpoint")
        fake, environment = self.cold_checkpoint(root)
        commit = self.git(root, "rev-parse", "HEAD")
        checkpoint = module._checkpoint_path(root, commit)
        checkpoint.write_text("[]\n", encoding="utf-8")

        validation = module.validate_checkpoint(root, checkpoint, commit)
        self.assertFalse(validation["valid"])
        self.assertEqual("invalid_schema", validation["reason"])
        self.assertFalse(module.check_merge_readiness(root)["ready"])
        self.commit_file(root, "src/next.py", "def next_value():\n    return 1\n")
        with patch.dict(os.environ, environment, clear=False):
            result = module.rebuild(root, sys.executable)
        self.assertEqual("full", result["mode"])

    def test_base_graph_requires_unique_nodes_and_resolved_link_endpoints(self):
        module = self.module()
        defects = {
            "missing_node_id": {
                "nodes": [{"source_file": "src/a.py"}],
                "links": [],
            },
            "duplicate_node_id": {
                "nodes": [{"id": "same"}, {"id": "same"}],
                "links": [],
            },
            "dangling_link": {
                "nodes": [{"id": "present"}],
                "links": [{"source": "present", "target": "missing"}],
            },
            "duplicate_link": {
                "nodes": [{"id": "source"}, {"id": "target"}],
                "links": [
                    {
                        "source": "source",
                        "target": "target",
                        "relation": "calls",
                        "confidence": "EXTRACTED",
                        "source_file": "src/source.py",
                        "source_location": "L7",
                    },
                    {
                        "source": "source",
                        "target": "target",
                        "relation": "calls",
                        "confidence": "EXTRACTED",
                        "source_file": "src/source.py",
                        "source_location": "L7",
                    },
                ],
            },
        }
        for defect, replacement in defects.items():
            with self.subTest(defect=defect):
                root = self.governed_repo(f"base-{defect}")
                self.cold_checkpoint(root)
                commit = self.git(root, "rev-parse", "HEAD")
                checkpoint_path = module._checkpoint_path(root, commit)
                graph_path = checkpoint_path.parent / "graph.json"
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
                graph.update(replacement)
                graph_path.write_text(json.dumps(graph), encoding="utf-8")
                checkpoint = json.loads(
                    checkpoint_path.read_text(encoding="utf-8")
                )
                checkpoint["metadata"]["graph_digest"] = hashlib.sha256(
                    graph_path.read_bytes()
                ).hexdigest()
                checkpoint_path.write_text(
                    json.dumps(checkpoint), encoding="utf-8"
                )

                result = module.validate_checkpoint(
                    root, checkpoint_path, commit
                )

                self.assertFalse(result["valid"])
                self.assertEqual("invalid_schema", result["reason"])

    def test_same_graphify_relation_at_distinct_locations_is_not_duplicate(self):
        module = self.module()
        graph_path = Path(self.temporary_directory.name) / "distinct-links.json"
        graph_path.write_text(
            json.dumps(
                {
                    "nodes": [{"id": "source"}, {"id": "target"}],
                    "links": [
                        {
                            "source": "source",
                            "target": "target",
                            "relation": "calls",
                            "confidence": "EXTRACTED",
                            "source_file": "src/source.py",
                            "source_location": "L7",
                        },
                        {
                            "source": "source",
                            "target": "target",
                            "relation": "calls",
                            "confidence": "EXTRACTED",
                            "source_file": "src/source.py",
                            "source_location": "L9",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        graph = module._read_base_graph(graph_path)

        self.assertEqual(2, len(graph["links"]))

    def test_checkpoint_recompiles_and_compares_exact_overlay(self):
        module = self.module()
        defects = ("nodes", "edges", "integrity", "input_digest")
        for defect in defects:
            with self.subTest(defect=defect):
                root = self.governed_repo(f"overlay-{defect}")
                self.cold_checkpoint(root)
                commit = self.git(root, "rev-parse", "HEAD")
                checkpoint_path = module._checkpoint_path(root, commit)
                checkpoint = json.loads(
                    checkpoint_path.read_text(encoding="utf-8")
                )
                if defect == "nodes":
                    checkpoint["nodes"] = []
                elif defect == "edges":
                    checkpoint["edges"] = "not-a-list"
                elif defect == "integrity":
                    checkpoint["integrity"]["nodes"] += 1
                else:
                    checkpoint["metadata"]["input_digest"] = "0" * 64
                checkpoint_path.write_text(
                    json.dumps(checkpoint), encoding="utf-8"
                )

                validation = module.validate_checkpoint(
                    root, checkpoint_path, commit
                )

                self.assertFalse(validation["valid"])
                self.assertIn(
                    validation["reason"], {"invalid_schema", "overlay_mismatch"}
                )
                self.assertFalse(module.check_merge_readiness(root)["ready"])

    def test_executed_argv_is_allowlisted_across_graph_paths(self):
        module = self.module()
        root = self.governed_repo("argv-local")
        (root / "src").mkdir()
        (root / "src" / "value.py").write_text(
            "def value():\n    return 1\n", encoding="utf-8"
        )
        self.commit_all(root, "argv baseline")
        remote_root = self.governed_repo("argv-remote")
        remote = Path(self.temporary_directory.name) / "argv.git"
        self.git(remote_root, "init", "--bare", str(remote))
        self.git(remote_root, "remote", "add", "origin", str(remote))
        self.git(remote_root, "push", "-u", "origin", "main")
        fake = self.write_fake_graphify()
        record = Path(self.temporary_directory.name) / "argv-graphify.jsonl"
        child_audit = Path(self.temporary_directory.name) / "argv-child.jsonl"
        (fake / "sitecustomize.py").write_text(
            "import json,os,pathlib,subprocess,sys\n"
            "sink=pathlib.Path(os.environ['ENGINEERING_ARGV_AUDIT'])\n"
            "def emit(argv):\n"
            "    sink.open('a',encoding='utf-8').write(json.dumps(list(map(str,argv)))+'\\n')\n"
            "emit([sys.executable,*sys.argv])\n"
            "real_run=subprocess.run\n"
            "real_popen=subprocess.Popen\n"
            "def run(argv,*args,**kwargs):\n"
            "    emit(argv); return real_run(argv,*args,**kwargs)\n"
            "def popen(argv,*args,**kwargs):\n"
            "    emit(argv); return real_popen(argv,*args,**kwargs)\n"
            "subprocess.run=run\n"
            "subprocess.Popen=popen\n",
            encoding="utf-8",
        )
        environment = self.graphify_environment(
            fake,
            FAKE_GRAPHIFY_RECORD=str(record),
            ENGINEERING_ARGV_AUDIT=str(child_audit),
        )
        real_run = subprocess.run
        real_start_worker = module._start_worker
        real_start_cleanup = module._start_cleanup
        executed = []

        def recording_run(command, *args, **kwargs):
            executed.append(list(command))
            return real_run(command, *args, **kwargs)

        def recording_worker(command):
            executed.append(list(command))
            return real_start_worker(command)

        def recording_cleanup(command):
            executed.append(list(command))
            return real_start_cleanup(command)

        with (
            patch.object(module.subprocess, "run", side_effect=recording_run),
            patch.object(module, "_start_worker", side_effect=recording_worker),
            patch.object(module, "_start_cleanup", side_effect=recording_cleanup),
            patch.dict(os.environ, environment, clear=False),
        ):
            module.rebuild(root, sys.executable)
            self.commit_file(root, "src/value.py", "def value():\n    return 2\n")
            module.rebuild(root, sys.executable)
            module.rebuild(root, sys.executable)
            module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=0,
            )
            module.reconcile_canonical(
                remote_root,
                refresh_remote=True,
                graphify_python=sys.executable,
            )

        executed.extend(
            json.loads(line)
            for line in child_audit.read_text(encoding="utf-8").splitlines()
        )

        allowed = re.compile(r"(?:git|python(?:\d+(?:\.\d+)*)?)(?:\.exe)?$")
        self.assertTrue(executed)
        self.assertTrue(
            all(allowed.fullmatch(Path(command[0]).name.lower()) for command in executed),
            executed,
        )
        self.assertTrue(
            any(
                "fetch" in command
                and any(
                    "refs/heads/main:refs/remotes/origin/main" in argument
                    for argument in command
                )
                for command in executed
            )
        )
        self.assertTrue(
            any("_graph-worker" in command for command in executed), executed
        )
        self.assertTrue(
            any(
                "worktree" in command and "add" in command
                for command in executed
            ),
            executed,
        )
        self.assertTrue(
            any(
                "-m" in command and "graphify" in command
                for command in executed
            ),
            executed,
        )
        cleanup_commands = [
            command
            for command in executed
            if len(command) > 2
            and command[1] == "-c"
            and "shutil.rmtree" in command[2]
        ]
        self.assertTrue(
            all(
                Path(path).name == "staging"
                for command in cleanup_commands
                for path in command[3:]
            ),
            cleanup_commands,
        )
        graphify_calls = [
            json.loads(line)
            for line in record.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            {"update", "private_rebuild_code"},
            {call[0] for call in graphify_calls},
        )
        forbidden = (
            "enterprise_endpoint",
            "enterprise_client",
            "enterprise_upload",
            "enterprise_autodetect",
            "enterprise_switch",
        )
        audit_text = json.dumps({"argv": executed, "graphify": graphify_calls}).lower()
        self.assertFalse(any(item in audit_text for item in forbidden))

    def test_timed_out_worker_is_killed_and_exact_resources_are_cleaned(self):
        module = self.module()
        root = self.governed_repo("slow-worker")
        (root / "src").mkdir()
        (root / "src" / "slow.py").write_text(
            "def slow():\n    return 1\n", encoding="utf-8"
        )
        self.commit_all(root, "slow baseline")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/slow.py", "def slow():\n    return 2\n")
        before = self.git(root, "worktree", "list", "--porcelain")
        def remove_fixture(_root, worktree, _deadline):
            shutil.rmtree(worktree)
            return True, "clean", None

        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                module,
                "_start_worker",
                side_effect=self.timed_out_registered_worker(module),
            ),
            patch.object(
                module,
                "_terminate_process_tree",
                side_effect=lambda process, _pgid: (process.kill(), True)[1],
            ),
            patch.object(
                module,
                "_bounded_worktree_remove",
                side_effect=remove_fixture,
            ),
            patch.object(module.os, "killpg", return_value=None, create=True),
        ):
            result = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=10,
                cleanup_timeout_seconds=5,
            )
        self.assertEqual("hook_budget_exceeded", result["reason"])
        self.assertTrue(result["worker_process_tree_terminated"])
        self.assertTrue(result["cleanup"]["completed"])
        self.assertGreater(self.worker_timeout_seconds, 0)
        self.assertLessEqual(self.worker_timeout_seconds, 10)
        self.assertEqual(before, self.git(root, "worktree", "list", "--porcelain"))
        self.assertFalse(Path(result["operation"]["worktree_path"]).exists())
        self.assertFalse(Path(result["operation"]["staging_path"]).exists())
        self.assertFalse(
            (module.common_graph_dir(root) / "state" / "lock").exists()
        )

    def test_posix_timeout_escalates_saved_process_group_after_leader_exit(self):
        module = self.module()
        process = Mock()
        process.pid = 4242
        process.poll.return_value = 0
        group = {"alive": True}
        sigkill = getattr(signal, "SIGKILL", 9)

        def kill_group(pgid, selected_signal):
            self.assertEqual(4242, pgid)
            if selected_signal == sigkill:
                group["alive"] = False
            elif selected_signal == 0 and not group["alive"]:
                raise ProcessLookupError

        with (
            patch.object(module.os, "name", "posix"),
            patch.object(
                module.os, "killpg", side_effect=kill_group, create=True
            ) as killpg,
            patch.object(module.time, "sleep", return_value=None),
            patch.object(
                module.time, "monotonic", side_effect=[0.0, 3.0, 3.0, 3.0]
            ),
        ):
            try:
                terminated = module._terminate_process_tree(process, 4242)
            except TypeError as error:
                self.fail(f"saved process group was not accepted: {error}")

        self.assertFalse(group["alive"])
        self.assertTrue(terminated)
        calls = [call.args for call in killpg.call_args_list]
        self.assertIn((4242, signal.SIGTERM), calls)
        self.assertIn((4242, sigkill), calls)

    def test_worker_tree_dead_requires_termination_confirmation(self):
        module = self.module()
        root = self.governed_repo("unconfirmed-process-tree")
        (root / "src").mkdir()
        (root / "src" / "slow.py").write_text(
            "def slow():\n    return 1\n", encoding="utf-8"
        )
        self.commit_all(root, "unconfirmed baseline")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/slow.py", "def slow():\n    return 2\n")

        def unconfirmed(process, *_saved_group):
            process.kill()
            return False

        def remove_fixture(_root, worktree, _deadline):
            shutil.rmtree(worktree)
            return True, "clean", None

        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                module,
                "_start_worker",
                side_effect=self.timed_out_registered_worker(module),
            ),
            patch.object(
                module, "_terminate_process_tree", side_effect=unconfirmed
            ),
            patch.object(
                module,
                "_bounded_worktree_remove",
                side_effect=remove_fixture,
            ),
            patch.object(module, "_recover_worker_tree_state", return_value=None),
        ):
            result = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=10,
                cleanup_timeout_seconds=5,
            )

        self.assertFalse(result["worker_process_tree_terminated"])
        self.assertFalse(result["operation"]["worker_process_tree_dead"])
        self.assertEqual(2_147_000_000, result["operation"].get("worker_pid"))
        if os.name == "nt":
            self.assertNotIn("worker_pgid", result["operation"])
        else:
            self.assertEqual(2_147_000_000, result["operation"].get("worker_pgid"))
        self.assertFalse(result["cleanup"]["completed"])
        self.assertEqual("live_worker_process_tree", result["cleanup"]["reason"])

    @unittest.skipUnless(os.name == "posix", "real POSIX process-group proof")
    def test_real_posix_timeout_kills_descendant_that_ignores_sigterm(self):
        module = self.module()
        child_pid_path = Path(self.temporary_directory.name) / "posix-child.pid"
        worker = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,signal,subprocess,sys,time;"
                    "child=subprocess.Popen([sys.executable,'-c',"
                    "'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)']);"
                    "pathlib.Path(sys.argv[1]).write_text(str(child.pid));"
                    "time.sleep(120)"
                ),
                str(child_pid_path),
            ],
            start_new_session=True,
        )
        deadline = time.monotonic() + 10
        while not child_pid_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(child_pid_path.is_file())
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))

        terminated = module._terminate_process_tree(worker, worker.pid)

        self.assertTrue(terminated)
        self.assertFalse(module._process_alive(child_pid))

    def test_real_process_tree_termination_closes_inherited_pipe_handles(self):
        module = self.module()
        child_pid_path = Path(self.temporary_directory.name) / "pipe-child.pid"
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,subprocess,sys,time;"
                    "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],"
                    "stdout=sys.stdout,stderr=sys.stderr);"
                    "pathlib.Path(sys.argv[1]).write_text(str(child.pid));"
                    "time.sleep(120)"
                ),
                str(child_pid_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=(os.name != "nt"),
        )
        deadline = time.monotonic() + 10
        while not child_pid_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(child_pid_path.is_file())
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))

        terminated = module._terminate_process_tree(
            process, process.pid if os.name != "nt" else None
        )
        process.communicate(timeout=5)

        self.assertTrue(terminated)
        self.assertFalse(module._process_alive(child_pid))

    def test_windows_timeout_uses_taskkill_process_tree(self):
        module = self.module()
        process = Mock()
        process.pid = 4242
        process.poll.side_effect = [None, 0]
        process.wait.return_value = 0

        with (
            patch.object(module.os, "name", "nt"),
            patch.object(module.subprocess, "run") as run,
        ):
            terminated = module._terminate_process_tree(process)

        self.assertTrue(terminated)
        run.assert_called_once_with(
            ["taskkill", "/PID", "4242", "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=2,
        )

    def test_windows_first_poll_exited_keeps_process_tree_unconfirmed(self):
        module = self.module()
        process = Mock()
        process.pid = 4242
        process.poll.return_value = 0

        with (
            patch.object(module.os, "name", "nt"),
            patch.object(module.subprocess, "run"),
        ):
            terminated = module._terminate_process_tree(process)

        self.assertFalse(terminated)

    def test_crash_after_spawn_before_identity_write_blocks_recovery(self):
        module = self.module()
        root = self.governed_repo("crash-before-worker-identity")

        class SimulatedParentCrash(RuntimeError):
            pass

        class SpawnedProcess:
            @property
            def pid(self):
                raise SimulatedParentCrash("after Popen before identity write")

        with (
            patch.object(module, "_start_worker", return_value=SpawnedProcess()),
            self.assertRaisesRegex(
                SimulatedParentCrash, "after Popen before identity write"
            ),
        ):
            module._run_graph_operation(
                root,
                graphify_python=sys.executable,
                commit=self.git(root, "rev-parse", "HEAD"),
                branch="main",
                kind="feature",
                manifest_name="engineering-traceability.json",
                hook=True,
                timeout_seconds=30,
                cleanup_timeout_seconds=30,
            )

        operations = module.common_graph_dir(root) / "state" / "operations"
        operation_root = next(operations.iterdir())
        record_path = operation_root / "resources.json"
        retained = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertTrue(retained.get("worker_start_pending"))
        self.assertFalse(retained.get("worker_process_tree_dead"))
        self.assertNotIn("worker_pid", retained)

        with patch.object(module, "_process_alive", return_value=False):
            recovery = module.reconcile_orphaned_operations(
                root, timeout_seconds=30
            )

        self.assertEqual([operation_root.name], recovery["unresolved"])
        self.assertTrue(record_path.is_file())

    def test_popen_failure_clears_pending_state_without_false_blocker(self):
        module = self.module()
        root = self.governed_repo("popen-failure-clears-pending")
        observed = {}

        def fail_start(command):
            operation_id = command[-1]
            record = module._read_operation(root, operation_id)
            observed.update(record)
            raise OSError("round-seven Popen failure")

        with (
            patch.object(module, "_start_worker", side_effect=fail_start),
            self.assertRaisesRegex(OSError, "round-seven Popen failure"),
        ):
            module._run_graph_operation(
                root,
                graphify_python=sys.executable,
                commit=self.git(root, "rev-parse", "HEAD"),
                branch="main",
                kind="feature",
                manifest_name="engineering-traceability.json",
                hook=True,
                timeout_seconds=30,
                cleanup_timeout_seconds=30,
            )

        self.assertTrue(observed.get("worker_start_pending"))
        self.assertFalse(observed.get("worker_process_tree_dead"))
        self.assertEqual(
            {"reconciled": [], "unresolved": [], "live": []},
            module.reconcile_orphaned_operations(root, timeout_seconds=30),
        )

    def test_real_graph_worker_timeout_kills_descendant_and_cleans_git_registry(self):
        module = self.module()
        root = self.governed_repo("real-process-tree")
        (root / "src").mkdir()
        (root / "src" / "value.py").write_text(
            "def value():\n    return 1\n", encoding="utf-8"
        )
        self.commit_all(root, "process baseline")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/value.py", "def value():\n    return 2\n")
        child_pid_path = Path(self.temporary_directory.name) / "descendant.pid"
        before = self.git(root, "worktree", "list", "--porcelain")

        with patch.dict(
            os.environ,
            {
                **environment,
                "FAKE_GRAPHIFY_SLOW": "120",
                "FAKE_GRAPHIFY_CHILD_PID": str(child_pid_path),
            },
            clear=False,
        ):
            result = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=30,
                cleanup_timeout_seconds=10,
            )

        self.assertEqual("hook_budget_exceeded", result["reason"])
        self.assertTrue(child_pid_path.is_file())
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        self.assertFalse(module._process_alive(child_pid))
        self.assertTrue(result["cleanup"]["completed"])
        registry = self.git(root, "worktree", "list", "--porcelain")
        self.assertNotIn("engineering-graphs/state/operations", registry.replace("\\", "/"))

    def test_orphan_blocks_next_worker_then_exact_recovery_allows_rebuild(self):
        module = self.module()
        root = self.governed_repo("orphan-recovery")
        (root / "src").mkdir()
        (root / "src" / "orphan.py").write_text(
            "def value():\n    return 1\n", encoding="utf-8"
        )
        self.commit_all(root, "orphan baseline")
        fake, environment = self.cold_checkpoint(root)
        self.commit_file(root, "src/orphan.py", "def value():\n    return 2\n")
        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                module,
                "_start_worker",
                side_effect=self.timed_out_registered_worker(module),
            ),
            patch.object(
                module,
                "_terminate_process_tree",
                side_effect=lambda process, _pgid: (process.kill(), True)[1],
            ),
            patch.object(
                module,
                "_bounded_worktree_remove",
                return_value=(False, "registered_worktree_remove_failed", None),
            ),
        ):
            first = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=120,
                cleanup_timeout_seconds=5,
            )
        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                module,
                "_bounded_worktree_remove",
                return_value=(False, "registered_worktree_remove_failed", None),
            ),
        ):
            blocked = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=120,
                cleanup_timeout_seconds=5,
            )
        operation_record = Path(first["operation"]["record_path"])
        orphan = json.loads(operation_record.read_text(encoding="utf-8"))
        orphan["created_at"] = (
            time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1
        )
        operation_record.write_text(
            json.dumps(orphan, indent=2) + "\n", encoding="utf-8"
        )
        owner_path = Path(orphan["repository_lock_path"]) / "owner.json"
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        owner["created_at"] = time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1
        owner_path.write_text(
            json.dumps(owner, indent=2) + "\n", encoding="utf-8"
        )
        real_remove = module._bounded_worktree_remove

        def recover_fixture(root, worktree, deadline):
            if not (worktree / ".git").exists():
                shutil.rmtree(worktree)
                return True, "clean", None
            return real_remove(root, worktree, deadline)

        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(
                module,
                "_bounded_worktree_remove",
                side_effect=recover_fixture,
            ),
        ):
            recovered = module.dispatch_hook(
                root,
                "post-commit",
                graphify_python=sys.executable,
                hook_budget_seconds=120,
                cleanup_timeout_seconds=5,
            )

        record = Path(first["operation"]["record_path"])
        self.assertEqual("unresolved_hook_worker_orphan", first["reason"])
        self.assertEqual("blocked", blocked["readiness"])
        self.assertEqual("unresolved_hook_worker_orphan", blocked["reason"])
        self.assertTrue(recovered["orphan_reconciled_before_worker"])
        self.assertEqual("current", recovered["freshness"])
        self.assertFalse(record.exists())

    def test_enterprise_absence_is_proved_from_imports_config_and_argv(self):
        source = ENGINEERING_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        forbidden = ("enterprise_endpoint", "enterprise_client", "enterprise_upload")

        self.assertFalse(any("enterprise" in name.lower() for name in imports))
        self.assertFalse(any(key in json.dumps(manifest).lower() for key in forbidden))
        self.assertFalse(any(key in source.lower() for key in forbidden))


class Task5ContractTests(unittest.TestCase):
    init_repo = Task2ContractTests.init_repo
    git = Task2ContractTests.git
    commit_all = Task2ContractTests.commit_all
    run_cli = Task2ContractTests.run_cli
    write_controls = Task2ContractTests.write_controls
    write_fake_graphify = Task2ContractTests.write_fake_graphify
    prepared_repo = Task2ContractTests.prepared_repo

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def prepared_run(
        self,
        name: str,
        *,
        scope: list[str],
        source_body: str | None = None,
    ) -> tuple[Path, dict]:
        root, _ = self.prepared_repo(name, source_body=source_body)
        self.module().approve_checks(root)
        prepared = self.module().prepare(
            root,
            "change REQ-1",
            {"scope": scope, "forbidden": ["publish", "deploy"]},
        )
        self.assertNotEqual("blocked", prepared["readiness"])
        return root, prepared

    def green_receipts(self, prepared: dict) -> list[dict]:
        module = self.module()
        return [
            {
                "schema": "engineering.check.v1",
                "command_id": module._check_identity(argv),
                "exit_code": 0,
                "duration_seconds": 0.01,
                "output_digest": "sha256:" + "0" * 64,
            }
            for argv in prepared["required_checks"]
        ]

    def test_complete_rejects_scope_expansion(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-scope", scope=["src/auth.py"]
        )
        (root / "src").mkdir()
        (root / "src" / "payments.py").write_text(
            "changed = True\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(module.EngineeringError, "scope"):
            module.complete(root, prepared["run_id"], receipts=[])

    def test_complete_is_idempotent_for_same_run_and_tree(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-replay", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        first = module.complete(root, prepared["run_id"], receipts=[])
        second = module.complete(root, prepared["run_id"], receipts=[])

        self.assertEqual(first, second)
        self.assertEqual("engineering.complete.v1", first["schema"])

    def test_complete_rejects_replay_after_the_tree_changes(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-replay-conflict", scope=["README.md"]
        )
        (root / "README.md").write_text("# First\n", encoding="utf-8")
        module.complete(root, prepared["run_id"], receipts=[])
        (root / "README.md").write_text("# Second\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "replay"):
            module.complete(root, prepared["run_id"], receipts=[])

    def test_complete_rejects_a_corrupt_retained_manifest(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-corrupt-replay", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        result = module.complete(root, prepared["run_id"], receipts=[])
        manifest = Path(result["manifest"])
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["schema"] = "corrupt"
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "manifest"):
            module.complete(root, prepared["run_id"], receipts=[])

    def test_complete_rejects_tampered_replay_owned_fields_and_schema(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-tampered-replay", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        result = module.complete(root, prepared["run_id"], receipts=[])
        manifest = Path(result["manifest"])
        original = json.loads(manifest.read_text(encoding="utf-8"))

        def authorization(payload):
            payload["authorization"]["scope"].append("outside.txt")

        def context(payload):
            payload["context"] = []

        def impact(payload):
            payload["actual_impact"] = []

        def check(payload):
            payload["checks"][0]["exit_code"] = 1

        def checkpoint(payload):
            payload["checkpoint"]["status"] = "current"

        def advisory(payload):
            payload["advisories"] = [{"code": "invented"}]

        def extra(payload):
            payload["unexpected"] = True

        def missing(payload):
            payload.pop("maintenance")

        for label, tamper in (
            ("authorization", authorization),
            ("context", context),
            ("impact", impact),
            ("check", check),
            ("checkpoint", checkpoint),
            ("advisory", advisory),
            ("extra", extra),
            ("missing", missing),
        ):
            with self.subTest(label=label):
                payload = json.loads(json.dumps(original))
                tamper(payload)
                manifest.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(module.EngineeringError, "manifest"):
                    module.complete(root, prepared["run_id"], receipts=[])
        manifest.write_text(json.dumps(original), encoding="utf-8")

    def test_dirty_identity_rejects_reparse_artifacts(self):
        module = self.module()
        root = self.init_repo("complete-reparse")
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        with patch.object(module, "_is_reparse_point", return_value=True):
            with self.assertRaisesRegex(module.EngineeringError, "reparse"):
                module._working_state_identity(root)

    def test_context_bodies_never_enter_manifest(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-private",
            scope=["README.md"],
            source_body="PRIVATE SYNTHETIC BODY",
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        result = module.complete(root, prepared["run_id"], receipts=[])
        text = Path(result["manifest"]).read_text(encoding="utf-8")

        self.assertNotIn("PRIVATE SYNTHETIC BODY", text)
        self.assertNotIn(str(root), text)

    def test_complete_executes_only_prepared_argv_without_shell(self):
        module = self.module()
        argv = [sys.executable, "-c", "print('synthetic')"]

        with patch.object(
            module.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(argv, 0, "ok\n", ""),
        ) as runner:
            receipt = module._execute_check(argv, timeout_seconds=5)

        self.assertEqual(0, receipt["exit_code"])
        self.assertRegex(receipt["output_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(argv, runner.call_args.args[0])
        self.assertIs(False, runner.call_args.kwargs["shell"])
        self.assertNotIn("ok", json.dumps(receipt))

    def test_complete_rejects_forged_green_receipt_for_prepared_command(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-forged-receipt", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "caller.*receipt"):
            module.complete(
                root,
                prepared["run_id"],
                receipts=self.green_receipts(prepared),
            )

    def test_changed_paths_include_both_rename_ends_and_block_old_path(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-rename-scope", scope=["renamed.md"]
        )
        (root / "README.md").rename(root / "renamed.md")
        self.git(root, "add", "-A")

        self.assertEqual(
            ["README.md", "renamed.md"],
            module._changed_paths_since(root, prepared["project"]["commit"]),
        )
        with self.assertRaisesRegex(module.EngineeringError, "scope"):
            module.complete(root, prepared["run_id"], receipts=[])

    def test_changed_paths_include_both_copy_ends(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-copy-paths", scope=["README.md", "copied.md"]
        )
        shutil.copyfile(root / "README.md", root / "copied.md")
        self.git(root, "add", "copied.md")

        self.assertEqual(
            ["README.md", "copied.md"],
            module._changed_paths_since(root, prepared["project"]["commit"]),
        )

    def test_changed_paths_include_unstaged_exact_copy_source(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-unstaged-copy", scope=["README.md", "copied.md"]
        )
        shutil.copyfile(root / "README.md", root / "copied.md")

        self.assertEqual(
            ["README.md", "copied.md"],
            module._changed_paths_since(root, prepared["project"]["commit"]),
        )

    def test_untracked_copy_provenance_fails_closed_on_unmerged_index(self):
        module = self.module()
        root = self.init_repo("complete-ambiguous-copy")
        shutil.copyfile(root / "README.md", root / "copied.md")
        original = module._git_bytes

        def ambiguous_index(project_root, *arguments):
            if arguments == ("ls-files", "--stage", "-z"):
                return b"100644 " + b"0" * 40 + b" 2\tREADME.md\0"
            return original(project_root, *arguments)

        with patch.object(module, "_git_bytes", side_effect=ambiguous_index):
            with self.assertRaisesRegex(module.EngineeringError, "ambiguous"):
                module._changed_paths_since(
                    root, self.git(root, "rev-parse", "HEAD")
                )

    def test_changed_paths_include_committed_exact_copy_source(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-committed-copy", scope=["README.md", "copied.md"]
        )
        shutil.copyfile(root / "README.md", root / "copied.md")
        self.commit_all(root, "copy README")

        self.assertEqual(
            ["README.md", "copied.md"],
            module._changed_paths_since(root, prepared["project"]["commit"]),
        )

    def test_complete_blocks_new_public_contract_in_dirty_overlay(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-dirty-contract",
            scope=["api.md", "docs/engineering-traceability/links.json"],
        )
        links_path = root / "docs" / "engineering-traceability" / "links.json"
        links = json.loads(links_path.read_text(encoding="utf-8"))
        links["nodes"].append(
            {
                "id": "CONTRACT-DIRTY",
                "type": "contract",
                "title": "Dirty synthetic contract",
                "source": {"path": "api.md", "line": 1},
            }
        )
        links_path.write_text(json.dumps(links), encoding="utf-8")
        (root / "api.md").write_text("# New contract\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "contract"):
            module.complete(root, prepared["run_id"], receipts=[])

    def test_dirty_identity_includes_index_only_changes(self):
        module = self.module()
        root = self.init_repo("complete-index-identity")
        clean = module._working_state_identity(root)
        (root / "README.md").write_text("# Staged\n", encoding="utf-8")
        self.git(root, "add", "README.md")
        self.git(root, "restore", "--worktree", "README.md")

        staged = module._working_state_identity(root)

        self.assertNotEqual(clean, staged)
        self.assertEqual(self.git(root, "rev-parse", "HEAD"), staged["head"])

    def test_dirty_identity_includes_staged_executable_mode(self):
        module = self.module()
        root = self.init_repo("complete-index-mode")
        before = module._working_state_identity(root)
        self.git(root, "update-index", "--chmod=+x", "README.md")

        self.assertNotEqual(before, module._working_state_identity(root))

    def test_dirty_identity_includes_submodule_head(self):
        module = self.module()
        root = self.init_repo("complete-submodule-parent")
        source = self.init_repo("complete-submodule-source")
        self.git(
            root,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(source),
            "vendor/sub",
        )
        self.commit_all(root, "add submodule")
        before = module._working_state_identity(root)
        checkout = root / "vendor" / "sub"
        self.git(checkout, "config", "user.email", "synthetic")
        self.git(checkout, "config", "user.name", "Synthetic Test")
        (checkout / "README.md").write_text("# New submodule head\n", encoding="utf-8")
        self.commit_all(checkout, "advance submodule")

        self.assertNotEqual(before, module._working_state_identity(root))

    @unittest.skipIf(os.name == "nt", "Git executable-mode changes are not portable on Windows")
    def test_dirty_identity_includes_unstaged_executable_mode(self):
        module = self.module()
        root = self.init_repo("complete-mode-identity")
        before = module._working_state_identity(root)
        os.chmod(root / "README.md", 0o755)

        self.assertNotEqual(before, module._working_state_identity(root))

    @unittest.skipIf(os.name == "nt", "POSIX executable mode is not portable on Windows")
    def test_dirty_identity_includes_untracked_executable_mode(self):
        module = self.module()
        root = self.init_repo("complete-untracked-mode-identity")
        artifact = root / "tool.sh"
        artifact.write_text("#!/bin/sh\n", encoding="utf-8")
        os.chmod(artifact, 0o644)
        before = module._working_state_identity(root)
        os.chmod(artifact, 0o755)

        self.assertNotEqual(before, module._working_state_identity(root))

    def test_complete_rechecks_state_after_checks_before_publication(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-check-race", scope=["README.md"]
        )
        (root / "README.md").write_text("# Before check\n", encoding="utf-8")

        def mutate(argv, *, timeout_seconds, cwd=None):
            (root / "README.md").write_text("# During check\n", encoding="utf-8")
            return {
                "schema": "engineering.check.v1",
                "command_id": module._check_identity(argv),
                "exit_code": 0,
                "duration_seconds": 0.01,
                "output_digest": "sha256:" + "0" * 64,
            }

        with patch.object(module, "_execute_check", side_effect=mutate):
            with self.assertRaisesRegex(module.EngineeringError, "changed during checks"):
                module.complete(root, prepared["run_id"], receipts=[])

    def test_complete_rejects_mutation_between_path_capture_and_initial_state(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-initial-snapshot-race", scope=["README.md"]
        )
        (root / "README.md").write_text("# Authorized dirty change\n", encoding="utf-8")
        original = module._changed_paths_since
        calls = 0

        def mutate_after_capture(project_root, commit):
            nonlocal calls
            calls += 1
            paths = original(project_root, commit)
            if calls == 1:
                (root / "outside.txt").write_text(
                    "unauthorized second write\n", encoding="utf-8"
                )
            return paths

        with patch.object(
            module, "_changed_paths_since", side_effect=mutate_after_capture
        ):
            with self.assertRaisesRegex(
                module.EngineeringError, "initial working state changed"
            ):
                module.complete(root, prepared["run_id"], receipts=[])

    def test_complete_rechecks_state_immediately_before_publication(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-publish-race", scope=["README.md"]
        )
        (root / "README.md").write_text("# Initial state\n", encoding="utf-8")
        original = module._working_state_identity
        calls = 0

        def mutate_before_publish(project_root):
            nonlocal calls
            calls += 1
            if calls == 4:
                (root / "README.md").write_text("# Publish race\n", encoding="utf-8")
            return original(project_root)

        def green_check(argv, *, timeout_seconds, cwd=None):
            return {
                "schema": "engineering.check.v1",
                "command_id": module._check_identity(argv),
                "exit_code": 0,
                "duration_seconds": 0.01,
                "output_digest": "sha256:" + "0" * 64,
            }

        with (
            patch.object(
                module, "_working_state_identity", side_effect=mutate_before_publish
            ),
            patch.object(module, "_execute_check", side_effect=green_check),
        ):
            with self.assertRaisesRegex(module.EngineeringError, "before publication"):
                module.complete(root, prepared["run_id"], receipts=[])

    def test_just_created_dead_owner_is_not_reclaimed(self):
        module = self.module()
        root = self.init_repo("complete-young-orphan")
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        self.assertTrue(module._acquire_repository_lock(record))

        with patch.object(module, "_process_alive", return_value=False):
            result = module.reconcile_orphaned_operations(root, timeout_seconds=5)

        self.assertEqual([operation["operation_id"]], result["unresolved"])
        self.assertTrue(Path(record["repository_lock_path"]).exists())
        current = module._read_operation(root, operation["operation_id"])
        current.update(phase="orphaned", worker_process_tree_dead=True)
        module._write_operation(current)
        self.addCleanup(
            module.cleanup_hook_operation,
            root,
            operation["operation_id"],
            timeout_seconds=5,
        )

    def test_invalid_or_future_orphan_timestamps_are_not_reclaimed(self):
        module = self.module()
        for label, timestamp in (("invalid", float("-inf")), ("future", time.time() + 60)):
            with self.subTest(label=label):
                root = self.init_repo(f"complete-{label}-orphan")
                operation = module.register_hook_operation(root)
                record = module._read_operation(root, operation["operation_id"])
                self.assertTrue(module._acquire_repository_lock(record))
                record["created_at"] = timestamp
                module._write_operation(record)
                owner_path = Path(record["repository_lock_path"]) / "owner.json"
                owner = json.loads(owner_path.read_text(encoding="utf-8"))
                owner["created_at"] = timestamp
                owner_path.write_text(json.dumps(owner), encoding="utf-8")

                with patch.object(module, "_process_alive", return_value=False):
                    result = module.reconcile_orphaned_operations(
                        root, timeout_seconds=5
                    )

                self.assertEqual([operation["operation_id"]], result["unresolved"])
                current = module._read_operation(root, operation["operation_id"])
                current.update(
                    phase="orphaned",
                    worker_process_tree_dead=True,
                    created_at=time.time() - module.ORPHAN_MINIMUM_AGE_SECONDS - 1,
                )
                module._write_operation(current)
                owner["created_at"] = current["created_at"]
                owner_path.write_text(json.dumps(owner), encoding="utf-8")
                self.addCleanup(
                    module.cleanup_hook_operation,
                    root,
                    operation["operation_id"],
                    timeout_seconds=5,
                )

    def test_complete_blocks_unpredicted_public_contract_change(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-contract",
            scope=["api.md", "docs/engineering-traceability/links.json"],
        )
        links_path = root / "docs" / "engineering-traceability" / "links.json"
        links = json.loads(links_path.read_text(encoding="utf-8"))
        links["nodes"].append(
            {
                "id": "CONTRACT-UNPREDICTED",
                "type": "contract",
                "title": "Synthetic public contract",
                "source": {"path": "api.md", "line": 1},
            }
        )
        links_path.write_text(json.dumps(links), encoding="utf-8")
        (root / "api.md").write_text("# Changed contract\n", encoding="utf-8")
        (root / "docs" / "extra.md").write_text("# Unrelated follow-up\n", encoding="utf-8")
        self.commit_all(root, "unpredicted public contract")
        fake_graphify = self.write_fake_graphify()
        maintenance = module.common_graph_dir(root) / "state" / "maintenance.json"

        with patch.dict(os.environ, {"PYTHONPATH": str(fake_graphify)}, clear=False):
            with self.assertRaisesRegex(module.EngineeringError, "contract"):
                module.complete(
                    root,
                    prepared["run_id"],
                    receipts=[],
                )
        self.assertFalse(maintenance.exists())

    def test_complete_uses_the_single_repository_lock_and_cleans_it(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-lock", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        result = module.complete(root, prepared["run_id"], receipts=[])

        common = module.common_graph_dir(root)
        self.assertEqual(
            str(common / "runs" / prepared["run_id"] / "completion.json"),
            result["manifest"],
        )
        self.assertFalse((common / "state" / "lock").exists())
        self.assertEqual([], list((common / "state" / "operations").glob("*")))

    def test_completion_lock_records_exact_owner_identity(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-lock-owner", scope=["README.md"]
        )
        record = module._begin_completion(root, prepared["run_id"])
        self.addCleanup(module._end_completion, root, record)
        owner = module._lock_owner(record)

        self.assertEqual(prepared["run_id"], owner["run_id"])
        self.assertEqual(record["operation_id"], owner["operation_id"])
        self.assertEqual(record["lock_token"], owner["lock_token"])
        self.assertEqual(os.getpid(), owner["owner_pid"])
        self.assertIsInstance(owner["created_at"], float)

    def test_concurrent_live_repository_lock_blocks_without_replacing_owner(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-concurrent", scope=["README.md"]
        )
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        self.assertTrue(module._acquire_repository_lock(record))
        owner_before = module._lock_owner(record)
        self.addCleanup(
            lambda: (
                module._write_operation(
                    {
                        **module._read_operation(root, operation["operation_id"]),
                        "phase": "orphaned",
                        "worker_process_tree_dead": True,
                    }
                ),
                module.cleanup_hook_operation(
                    root, operation["operation_id"], timeout_seconds=5
                ),
            )
        )

        with self.assertRaisesRegex(module.EngineeringError, "lock"):
            module.complete(
                root,
                prepared["run_id"],
                receipts=[],
            )

        self.assertEqual(owner_before, module._lock_owner(record))

    def test_complete_refreshes_the_exact_clean_feature_checkpoint(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "complete-checkpoint", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        commit = self.commit_all(root, "authorized change")
        fake_graphify = self.write_fake_graphify()

        with patch.dict(os.environ, {"PYTHONPATH": str(fake_graphify)}, clear=False):
            result = module.complete(
                root,
                prepared["run_id"],
                receipts=[],
            )

        self.assertEqual({"commit": commit, "status": "current"}, result["checkpoint"])

    def test_complete_cli_emits_the_bounded_manifest(self):
        root, prepared = self.prepared_run(
            "complete-cli", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")

        result = self.run_cli(
            "complete",
            root,
            prepared["run_id"],
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("engineering.complete.v1", payload["schema"])
        self.assertEqual(
            {
                "schema",
                "run_id",
                "project",
                "intent",
                "authorization",
                "autonomy",
                "context",
                "changed_artifacts",
                "predicted_impact",
                "actual_impact",
                "traceability",
                "checks",
                "advisories",
                "maintenance",
                "checkpoint",
                "result_identity",
                "manifest",
            },
            set(payload),
        )

    def test_skill_requires_automatic_completion_before_readiness(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())

        self.assertIn("Engineering completion runs automatically", text)
        self.assertIn("before claiming non-trivial work is ready", text)
        self.assertIn("diagnostics and CI", text)


class Task6ContractTests(unittest.TestCase):
    init_repo = Task2ContractTests.init_repo
    git = Task2ContractTests.git
    commit_all = Task2ContractTests.commit_all
    run_cli = Task2ContractTests.run_cli
    write_controls = Task2ContractTests.write_controls
    write_fake_graphify = Task2ContractTests.write_fake_graphify
    prepared_repo = Task2ContractTests.prepared_repo
    prepared_run = Task5ContractTests.prepared_run
    governed_repo = Task3ContractTests.governed_repo
    cold_checkpoint = Task3ContractTests.cold_checkpoint
    commit_file = Task3ContractTests.commit_file
    graphify_environment = Task3ContractTests.graphify_environment

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def queue(self, root: Path, **item) -> dict:
        return self.module().queue_maintenance(
            root,
            {
                "area": "docs",
                "artifact": "checkpoint",
                "kind": "checkpoint_stale",
                "impact": "routine",
                **item,
            },
        )

    def test_collaborative_is_default_and_explained_once(self):
        module = self.module()
        root = self.init_repo("autonomy-default")
        self.write_controls(root, generation="v2")

        first = module._ensure_autonomy(root)
        second = module._ensure_autonomy(root)

        self.assertEqual("collaborative", first["autonomy"])
        self.assertTrue(first["explain_autonomy"])
        self.assertFalse(second["explain_autonomy"])
        config = json.loads((root / "engineering.json").read_text(encoding="utf-8"))
        self.assertEqual("collaborative", config["autonomy"])
        self.assertTrue(config["autonomy_explained"])

    def test_saved_autonomy_and_task_override_are_separate(self):
        module = self.module()
        root, _ = self.prepared_repo("autonomy-override")

        changed = module.set_autonomy(root, "guided")
        prepared = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": ["publish"]},
            "steward",
        )

        self.assertEqual("guided", changed["autonomy"])
        self.assertEqual("guided", module.get_autonomy(root))
        self.assertEqual("steward", prepared["autonomy"])
        retained = json.loads(
            (
                module.common_graph_dir(root)
                / "runs"
                / prepared["run_id"]
                / "preparation.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("steward", retained["autonomy"])
        self.assertEqual("guided", module.get_autonomy(root))
        with self.assertRaisesRegex(module.EngineeringError, "autonomy"):
            module.set_autonomy(root, "automatic")

    def test_autonomy_change_records_bounded_replay_safe_project_history(self):
        module = self.module()
        root, _ = self.prepared_repo("autonomy-history")

        confirmed = module.set_autonomy(root, "collaborative")
        confirmed_replay = module.set_autonomy(root, "collaborative")
        first = module.set_autonomy(root, "guided")
        retained = module.set_autonomy(root, "guided")
        config = json.loads(
            (root / "engineering-traceability.json").read_text(encoding="utf-8")
        )

        self.assertEqual(confirmed, confirmed_replay)
        self.assertEqual(first, retained)
        self.assertEqual(
            [
                {
                    "kind": "autonomy_change",
                    "previous": "collaborative",
                    "new": "collaborative",
                    "changed_at": confirmed["changed_at"],
                    "origin": "engineering",
                    "reason": "saved autonomy changed",
                },
                {
                    "kind": "autonomy_change",
                    "previous": "collaborative",
                    "new": "guided",
                    "changed_at": first["changed_at"],
                    "origin": "engineering",
                    "reason": "saved autonomy changed",
                }
            ],
            config["autonomy_history"],
        )
        self.assertNotIn(str(root), json.dumps(config["autonomy_history"]))

    def test_autonomy_history_migrates_and_preserves_unrelated_history(self):
        module = self.module()
        root, _ = self.prepared_repo("autonomy-history-migration")
        path = root / "engineering-traceability.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        unrelated = [{"kind": "decision", "id": index} for index in range(60)]
        legacy = {
            "kind": "autonomy_change",
            "previous": "collaborative",
            "new": "guided",
            "changed_at": "2026-01-01T00:00:00Z",
            "origin": "engineering",
            "reason": "saved autonomy changed",
        }
        config.update(autonomy="guided", history=[*unrelated, legacy])
        config["autonomy_history"] = [
            {
                **legacy,
                "previous": "guided" if index else "collaborative",
                "new": "guided",
                "changed_at": f"2026-01-01T00:00:{index:02d}Z",
            }
            for index in range(55)
        ]
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        first = module.set_autonomy(root, "guided")
        bytes_after_first = path.read_bytes()
        second = module.set_autonomy(root, "guided")
        retained = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(first, second)
        self.assertEqual(bytes_after_first, path.read_bytes())
        self.assertEqual(unrelated, retained["history"])
        self.assertEqual(50, len(retained["autonomy_history"]))
        self.assertEqual("guided", retained["autonomy_history"][-1]["new"])

    def test_steward_preserves_publication_and_deployment_gates(self):
        module = self.module()
        root, _ = self.prepared_repo("autonomy-gates")
        module.set_autonomy(root, "steward")

        result = module.prepare(
            root,
            "publish and deploy the synthetic package",
            {
                "scope": ["README.md"],
                "forbidden": ["publish", "deploy"],
            },
            None,
        )

        self.assertEqual("blocked", result["readiness"])
        self.assertEqual(["publish", "deploy"], result["authorization"]["forbidden"])

    def test_autonomy_change_respects_the_single_live_repository_lock(self):
        module = self.module()
        root, _ = self.prepared_repo("autonomy-lock")
        path = root / "engineering-traceability.json"
        before = path.read_bytes()
        operation = module.register_hook_operation(root)
        record = module._read_operation(root, operation["operation_id"])
        self.assertTrue(module._acquire_repository_lock(record))
        self.addCleanup(
            lambda: (
                module._write_operation(
                    {
                        **module._read_operation(root, operation["operation_id"]),
                        "phase": "orphaned",
                        "worker_process_tree_dead": True,
                    }
                ),
                module.cleanup_hook_operation(
                    root, operation["operation_id"], timeout_seconds=5
                ),
            )
        )

        with self.assertRaisesRegex(module.EngineeringError, "lock"):
            module.set_autonomy(root, "steward")

        self.assertEqual(before, path.read_bytes())
        self.assertEqual(record["lock_token"], module._lock_owner(record)["lock_token"])

    def test_maintenance_deduplicates_and_escalates_impact_durably(self):
        module = self.module()
        root = self.init_repo("maintenance-dedupe")
        first = self.queue(root)
        second = self.queue(root, impact="blocking")

        self.assertEqual(first["id"], second["id"])
        status = module.maintenance_status(root)
        self.assertEqual(1, status["counts"]["pending"])
        self.assertEqual(1, status["counts"]["blocked"])
        self.assertEqual(0, status["counts"]["safe"])
        self.assertEqual("blocking", status["groups"][0]["highest_impact"])
        self.assertTrue(
            (
                module.common_graph_dir(root) / "state" / "maintenance.json"
            ).is_file()
        )

    def test_maintenance_reports_age_once_and_compact_grouped_counts(self):
        module = self.module()
        root = self.init_repo("maintenance-aging")
        self.queue(root, area="docs", artifact="checkpoint")
        self.queue(root, area="tests", artifact="checkpoint")
        path = module.common_graph_dir(root) / "state" / "maintenance.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        old = "2026-01-01T00:00:00Z"
        payload["items"][0]["created_at"] = old
        path.write_text(json.dumps(payload), encoding="utf-8")

        first = module.maintenance_status(root)
        second = module.maintenance_status(root)

        self.assertEqual(2, first["counts"]["pending"])
        self.assertEqual(1, first["counts"]["aged"])
        self.assertEqual(1, first["newly_escalated"])
        self.assertEqual(0, second["newly_escalated"])
        self.assertEqual(["docs", "tests"], [item["area"] for item in first["groups"]])
        self.assertNotIn(str(root), json.dumps(first))

    def test_one_off_maintenance_processes_only_safe_selected_area(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-area")
        self.queue(root, area="docs", artifact="checkpoint")
        self.queue(root, area="tests", artifact="checkpoint")
        self.queue(
            root,
            area="docs",
            artifact="docs/contract.md",
            kind="stale_artifact",
            impact="consequential",
        )

        result = module.run_maintenance(root, "docs")
        status = module.maintenance_status(root)

        self.assertEqual(1, result["processed"])
        self.assertEqual(1, result["blocked"])
        self.assertEqual(2, status["counts"]["pending"])
        self.assertEqual({"docs", "tests"}, {item["area"] for item in status["groups"]})
        self.assertEqual("collaborative", module.get_autonomy(root))

    def test_ambiguous_and_consequential_items_never_process(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-unsafe")
        self.queue(root, artifact="docs/ambiguous.md", kind="stale_artifact", impact="ambiguous")
        self.queue(root, artifact="docs/consequential.md", kind="stale_artifact", impact="consequential")

        result = module.run_maintenance(root, None)

        self.assertEqual(0, result["processed"])
        self.assertEqual(2, result["blocked"])
        self.assertEqual(2, module.maintenance_status(root)["counts"]["pending"])

    def test_failed_safe_repair_escalates_once_and_is_not_retried(self):
        module = self.module()
        root = self.init_repo("maintenance-failed-safe")
        self.queue(root, artifact="checkpoint")

        first = module.run_maintenance(root, None)
        status = module.maintenance_status(root)
        second = module.run_maintenance(root, None)

        self.assertEqual(1, first["blocked"])
        self.assertEqual(1, status["counts"]["blocked"])
        self.assertEqual("blocking", status["items"][0]["impact"])
        self.assertEqual(1, second["blocked"])
        self.assertEqual(0, second["processed"])

    def test_relevant_blocked_maintenance_blocks_preparation(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-relevant-blocker")
        self.queue(
            root,
            artifact="README.md",
            kind="stale_artifact",
            impact="blocking",
        )

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )

        self.assertEqual("blocked", result["readiness"])
        self.assertIn("dirty work exists outside the authorized scope", result["blockers"])

    def test_collaborative_explains_one_off_maintenance_command(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-collaborative")
        self.queue(root)

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )

        self.assertTrue(any("engineering maintain" in item for item in result["advisories"]))
        self.assertEqual(1, module.maintenance_status(root)["counts"]["pending"])

    def test_steward_runs_safe_maintenance_only_during_prepare(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-steward")
        module.set_autonomy(root, "steward")
        self.queue(root, artifact="checkpoint")
        self.queue(root, artifact="docs/review.md", kind="stale_artifact", impact="ambiguous")

        result = module.prepare(
            root,
            "change REQ-1",
            {"scope": ["README.md"], "forbidden": []},
            None,
        )

        self.assertEqual("steward", result["autonomy"])
        status = module.maintenance_status(root)
        self.assertEqual(1, status["counts"]["pending"])
        self.assertEqual(1, status["counts"]["blocked"])

    def test_maintain_cli_supports_status_all_and_area(self):
        module = self.module()
        root, _ = self.prepared_repo("maintenance-cli")
        self.queue(root, area="docs", artifact="checkpoint")
        self.queue(root, area="tests", artifact="checkpoint")

        status = self.run_cli("maintain", "status", root)
        area = self.run_cli("maintain", root, "--area", "docs")

        self.assertEqual(0, status.returncode, status.stderr)
        self.assertEqual(2, json.loads(status.stdout)["counts"]["pending"])
        self.assertEqual(0, area.returncode, area.stderr)
        self.assertEqual(1, json.loads(area.stdout)["processed"])
        self.assertEqual(1, module.maintenance_status(root)["counts"]["pending"])

    def test_maintenance_has_no_background_or_service_execution(self):
        module = self.module()
        source = ENGINEERING_SCRIPT.read_text(encoding="utf-8")
        imports = {
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }

        self.assertFalse({"sched", "threading"} & imports)
        self.assertFalse(module.maintenance_status(self.init_repo("foreground"))["background"])

    def test_maintenance_rejects_credential_shaped_or_unbounded_identity(self):
        module = self.module()
        root = self.init_repo("maintenance-private")

        with self.assertRaisesRegex(module.EngineeringError, "maintenance item"):
            self.queue(root, artifact="docs/password=synthetic-secret")
        with self.assertRaisesRegex(module.EngineeringError, "maintenance item"):
            self.queue(root, area="x" * 129)

        path = module.common_graph_dir(root) / "state" / "maintenance.json"
        self.assertFalse(path.exists())

    def test_maintenance_fails_closed_for_malformed_existing_state(self):
        module = self.module()
        root = self.init_repo("maintenance-malformed-state")
        path = module.common_graph_dir(root) / "state" / "maintenance.json"
        path.parent.mkdir(parents=True)

        tampered_item = {
            "id": "maintenance-3f7a1f8ad181",
            "area": "docs",
            "artifact": "docs/review.md",
            "kind": "stale_artifact",
            "impact": "routine",
            "safe": True,
            "created_at": "2026-01-01T00:00:00Z",
            "last_seen_at": "2026-01-01T00:00:00Z",
            "escalated_at": None,
        }
        for payload in (
            {"items": []},
            {"schema": "engineering.maintenance.v1"},
            {
                "schema": "engineering.maintenance.v1",
                "items": [tampered_item],
                "history": [],
            },
        ):
            with self.subTest(payload=payload):
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(module.EngineeringError, "state"):
                    module._maintenance_pending(root)

    def test_maintenance_rejects_nonlocal_or_control_shaped_artifacts(self):
        module = self.module()
        root = self.init_repo("maintenance-artifact-boundary")

        for artifact in (
            "https://example.invalid/file",
            "docs/file.md?download=1",
            "docs/file.md#fragment",
            "docs/control\nvalue.md",
            "../outside.md",
            "C:/outside.md",
            "token=synthetic-value",
        ):
            with self.subTest(artifact=artifact):
                with self.assertRaisesRegex(module.EngineeringError, "maintenance item"):
                    self.queue(root, artifact=artifact)

    def test_maintenance_rejects_inconsistent_or_future_timestamps(self):
        module = self.module()
        root = self.init_repo("maintenance-time-boundary")
        future = "2999-01-01T00:00:00Z"

        with self.assertRaisesRegex(module.EngineeringError, "timestamp"):
            self.queue(root, created_at=future, last_seen_at=future)
        with self.assertRaisesRegex(module.EngineeringError, "timestamp"):
            self.queue(
                root,
                created_at="2026-01-02T00:00:00Z",
                last_seen_at="2026-01-01T00:00:00Z",
            )

    def test_completion_batches_maintenance_once_and_retains_opaque_ids(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "maintenance-completion-producer", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / "follow-up.md").write_text("# Follow up\n", encoding="utf-8")

        first = module.complete(root, prepared["run_id"], receipts=[])

        state_before = (
            module.common_graph_dir(root) / "state" / "maintenance.json"
        ).read_bytes()
        second = module.complete(root, prepared["run_id"], receipts=[])

        self.assertEqual(2, len(first["maintenance"]))
        self.assertTrue(
            all(re.fullmatch(r"maintenance-[0-9a-f]{12}", item) for item in first["maintenance"])
        )
        self.assertEqual(first, second)
        self.assertEqual(
            state_before,
            (module.common_graph_dir(root) / "state" / "maintenance.json").read_bytes(),
        )

    def test_completion_replay_does_not_readd_consumed_maintenance(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "maintenance-consumed-replay", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        first = module.complete(root, prepared["run_id"], receipts=[])
        state_path = module.common_graph_dir(root) / "state" / "maintenance.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["history"].append(
            {"id": state["items"][0]["id"], "completed_at": module._utc_now()}
        )
        state["items"] = []
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        consumed = state_path.read_bytes()

        replay = module.complete(root, prepared["run_id"], receipts=[])

        self.assertEqual(first, replay)
        self.assertEqual(consumed, state_path.read_bytes())

    def test_failed_check_does_not_publish_maintenance(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "maintenance-failed-check", scope=["README.md"]
        )
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        state_path = module.common_graph_dir(root) / "state" / "maintenance.json"
        failed = {
            "schema": "engineering.check.v1",
            "command_id": module._check_identity(prepared["required_checks"][0]),
            "exit_code": 1,
            "duration_seconds": 0.01,
            "output_digest": "sha256:" + "0" * 64,
        }

        with (
            patch.object(module, "_execute_check", return_value=failed),
            self.assertRaisesRegex(module.EngineeringError, "check failed"),
        ):
            module.complete(root, prepared["run_id"], receipts=[])

        self.assertFalse(state_path.exists())

    def test_manifest_failure_restores_exact_prior_maintenance(self):
        module = self.module()
        root, prepared = self.prepared_run(
            "maintenance-manifest-rollback", scope=["README.md"]
        )
        self.queue(
            root,
            artifact="docs/prior.md",
            kind="stale_artifact",
            impact="ambiguous",
        )
        state_path = module.common_graph_dir(root) / "state" / "maintenance.json"
        before = state_path.read_bytes()
        (root / "README.md").write_text("# Updated\n", encoding="utf-8")
        real_private_atomic = module._private_atomic_bytes

        def fail_manifest(path, content):
            if Path(path).name.startswith(".completion.json.stage-"):
                raise OSError("synthetic manifest publication failure")
            return real_private_atomic(path, content)

        with (
            patch.object(module, "_private_atomic_bytes", side_effect=fail_manifest),
            self.assertRaisesRegex(OSError, "manifest publication"),
        ):
            module.complete(root, prepared["run_id"], receipts=[])

        self.assertEqual(before, state_path.read_bytes())

    def test_failed_checkpoint_repair_resolves_after_exact_publication_once(self):
        module = self.module()
        root = self.governed_repo("maintenance-checkpoint-resolution")
        self.queue(root, artifact="checkpoint")
        failed = module.run_maintenance(root, None)

        _, environment = self.cold_checkpoint(root)
        first = module.maintenance_status(root)
        history_path = module.common_graph_dir(root) / "state" / "maintenance.json"
        history_once = history_path.read_bytes()
        with patch.dict(os.environ, environment, clear=False):
            module.rebuild(root, sys.executable)
        second = module.maintenance_status(root)

        self.assertEqual(1, failed["blocked"])
        self.assertEqual(0, first["counts"]["pending"])
        self.assertEqual(history_once, history_path.read_bytes())
        self.assertEqual(0, second["counts"]["pending"])
        history = json.loads(history_path.read_text(encoding="utf-8"))["history"]
        self.assertEqual(1, len(history))

    def test_checkpoint_maintenance_is_scoped_to_worktree_lineage(self):
        module = self.module()
        root = self.governed_repo("maintenance-lineage-a")
        other = Path(self.temporary_directory.name) / "maintenance-lineage-b"
        self.git(root, "worktree", "add", "-b", "feature/lineage-b", str(other))
        stale_a = self.queue(root, artifact="checkpoint")
        stale_b = self.queue(other, artifact="checkpoint")
        unrelated = self.queue(
            root,
            artifact="docs/unrelated.md",
            kind="stale_artifact",
            impact="ambiguous",
        )
        state_path = module.common_graph_dir(root) / "state" / "maintenance.json"
        initial = json.loads(state_path.read_text(encoding="utf-8"))
        checkpoint_items = [
            item for item in initial["items"] if item["kind"] == "checkpoint_stale"
        ]

        self.assertNotEqual(stale_a["id"], stale_b["id"])
        self.assertEqual(2, len(checkpoint_items))
        self.assertEqual(2, len({item["target"]["lineage"] for item in checkpoint_items}))
        self.assertNotIn(str(root), json.dumps(checkpoint_items))
        self.assertNotIn(str(other), json.dumps(checkpoint_items))

        _, environment = self.cold_checkpoint(other)
        after_b = module.maintenance_status(root)
        remaining_checkpoint = [
            item for item in after_b["items"] if item["kind"] == "checkpoint_stale"
        ]
        self.assertEqual([stale_a["id"]], [item["id"] for item in remaining_checkpoint])
        self.assertIn(unrelated["id"], {item["id"] for item in after_b["items"]})

        wrong_worktree = module.run_maintenance(other, None)
        after_wrong_worktree = module.maintenance_status(root)
        self.assertEqual(0, wrong_worktree["processed"])
        self.assertEqual(
            [stale_a["id"]],
            [
                item["id"]
                for item in after_wrong_worktree["items"]
                if item["kind"] == "checkpoint_stale"
            ],
        )

        self.commit_file(root, "src/successor.py", "VALUE = 1\n")
        with patch.dict(os.environ, environment, clear=False):
            published_a = module.rebuild(root, sys.executable)
        self.assertEqual("current", published_a["freshness"])
        after_a = module.maintenance_status(root)
        self.assertEqual([unrelated["id"]], [item["id"] for item in after_a["items"]])
        history = json.loads(state_path.read_text(encoding="utf-8"))["history"]
        self.assertEqual(2, len(history))

    def test_batch_mutation_reuses_one_existing_lock_and_writes_once(self):
        module = self.module()
        root = self.init_repo("maintenance-single-lock-batch")
        operation = module._begin_completion(root, "maintenance-batch-test")
        try:
            with (
                patch.object(module, "_begin_completion", wraps=module._begin_completion) as begin,
                patch.object(module, "_write_maintenance", wraps=module._write_maintenance) as write,
            ):
                queued = module._queue_maintenance_locked(
                    root,
                    [
                        {
                            "area": "docs",
                            "artifact": "docs/one.md",
                            "kind": "stale_artifact",
                            "impact": "routine",
                        },
                        {
                            "area": "tests",
                            "artifact": "tests/test_one.py",
                            "kind": "stale_artifact",
                            "impact": "ambiguous",
                        },
                    ],
                    operation,
                )
            self.assertEqual(0, begin.call_count)
            self.assertEqual(1, write.call_count)
            self.assertEqual(2, len(queued))
        finally:
            module._end_completion(root, operation)

    def test_semantic_hook_and_legacy_reconciliation_persist_maintenance(self):
        module = self.module()
        root = self.governed_repo("maintenance-producers")
        manifest_path = root / "engineering.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["graphify"]["hook_budget_seconds"] = 60
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.commit_all(root, "configure hook")
        _, environment = self.cold_checkpoint(root)
        self.commit_file(root, "docs/design.md", "# Changed meaning\n")

        with patch.dict(os.environ, environment, clear=False):
            hook = module.dispatch_hook(root, "post-commit", graphify_python=sys.executable)

        legacy = root / "graphify-out"
        legacy.mkdir()
        (legacy / "graph.json").write_text("{}\n", encoding="utf-8")
        (legacy / "notes.txt").write_text("keep\n", encoding="utf-8")
        reconciled = module.reconcile_legacy_outputs(root)
        status = module.maintenance_status(root)

        self.assertEqual("semantic_update_deferred", hook["reason"])
        self.assertEqual(2, status["counts"]["pending"])
        self.assertEqual(
            {"checkpoint_stale", "legacy_graph_ambiguous"},
            {item["kind"] for item in status["items"]},
        )
        self.assertEqual(1, len(reconciled["maintenance"]))

    def test_skill_explains_maintain_and_level_two_vs_three(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())

        self.assertIn("Collaborative", text)
        self.assertIn("Steward", text)
        self.assertIn("does not run in the background", text)
        self.assertIn("process safe queued work once", text)
        self.assertIn("does not change the saved autonomy level", text)
        self.assertIn("engineering maintain <root> --area <stable-area>", text)
        self.assertNotIn("engineering maintain <area>", text)


class Task7ContractTests(unittest.TestCase):
    init_repo = Task2ContractTests.init_repo
    git = Task2ContractTests.git
    commit_all = Task2ContractTests.commit_all
    run_cli = Task2ContractTests.run_cli
    write_controls = Task2ContractTests.write_controls
    write_fake_graphify = Task2ContractTests.write_fake_graphify
    prepared_repo = Task2ContractTests.prepared_repo
    prepared_run = Task5ContractTests.prepared_run

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.home = Path(self.temporary_directory.name) / "home"
        self.home.mkdir()
        self.environment = patch.dict(
            os.environ,
            {"ENGINEERING_USER_HOME": str(self.home)},
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.real_owner_private = engineering._enforce_owner_private
        self.private_files = patch.object(
            engineering,
            "_enforce_owner_private",
            side_effect=lambda path: os.chmod(path, 0o700 if Path(path).is_dir() else 0o600),
        )
        self.private_files.start()
        self.addCleanup(self.private_files.stop)
        self.private_verifier = patch.object(
            engineering, "_verify_owner_private", return_value=None
        )
        self.private_verifier.start()
        self.addCleanup(self.private_verifier.stop)
        self.governed_installer_guard = patch.object(
            engineering,
            "_run_governed_graphify_install",
            side_effect=AssertionError(
                "Unit tests must mock the governed installer boundary; "
                "real installation is temp-venv-only."
            ),
        )
        self.governed_installer_guard.start()
        self.addCleanup(self.governed_installer_guard.stop)

    def module(self):
        if engineering is None:
            self.fail("scripts/engineering.py must exist")
        return engineering

    def terminal_completion(self, name="learning-source"):
        module = self.module()
        root, prepared = self.prepared_run(name, scope=["README.md"])
        return root, module.complete(root, prepared["run_id"], receipts=[])

    def forged_promoted_item(self, module, candidate, project_digest=None):
        project_digest = project_digest or candidate["project_digest"]
        identifier = "candidate-" + hashlib.sha256(
            f"{project_digest}\0{candidate['source_digest']}\0{candidate['kind']}".encode()
        ).hexdigest()[:12]
        evaluation_project = "sha256:" + "4" * 64
        if evaluation_project == project_digest:
            evaluation_project = "sha256:" + "5" * 64
        evaluation_digest = "sha256:" + "6" * 64
        evaluation = {
            "id": "evaluation-" + hashlib.sha256(
                f"{identifier}\0{evaluation_project}\0{evaluation_digest}".encode()
            ).hexdigest()[:12],
            "project_digest": evaluation_project,
            "source_reference": "completion:run-a1b2c3",
            "source_digest": evaluation_digest,
            "result": "passed",
        }
        return {
            **candidate,
            "id": identifier,
            "project_digest": project_digest,
            "state": "promoted",
            "evidence": [evaluation],
            "review": {
                "approval": {
                    "id": "approval-" + hashlib.sha256(
                        f"{identifier}\0approved".encode()
                    ).hexdigest()[:12],
                    "decision": "approved",
                }
            },
            "history": [
                module._lifecycle_record(identifier, state)
                for state in (
                    "proposed",
                    "evaluating",
                    "approved_for_promotion",
                    "promoted",
                )
            ],
        }

    def bundle_repo(self, name="bundle"):
        root = Path(self.temporary_directory.name) / name
        source = root / ".agents" / "skills" / "engineering"
        shutil.copytree(SKILL_DIR, source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.git(root, "init", "-b", "main")
        self.git(root, "config", "user.email", "synthetic")
        self.git(root, "config", "user.name", "Engineering Tests")
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", "bundle")
        return source

    def update_bundle(self, source, version="2.1.1"):
        skill = source / "SKILL.md"
        skill.write_bytes(skill.read_bytes() + f"\n<!-- version {version} -->\n".encode())
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        manifest["version"] = version
        (source / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        root = Path(self.git(source, "rev-parse", "--show-toplevel"))
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", f"bundle {version}")

    def managed_snapshot(self, module, home):
        paths = module._install_paths(home)
        snapshot = {}
        for key in ("canonical", "previous", "claude", "shim", "receipt", "previous_receipt"):
            path = paths[key]
            snapshot[key] = (
                ("tree", module._tree_digest(path))
                if path.is_dir()
                else (("file", hashlib.sha256(path.read_bytes()).hexdigest()) if path.is_file() else None)
            )
        return snapshot

    def byte_snapshot(self, *paths):
        return {
            str(path): path.read_bytes() if path.is_file() else None
            for path in paths
        }

    def fail_once_on_target(self, module, target):
        real_replace = module._replace_install_path
        failed = False

        def replace(
            source,
            destination,
            expected_pre_state=None,
            *,
            preimage_path=None,
        ):
            nonlocal failed
            if not failed and Path(destination).resolve() == Path(target).resolve():
                failed = True
                raise OSError("synthetic transactional publication failure")
            return real_replace(
                source,
                destination,
                expected_pre_state,
                preimage_path=preimage_path,
            )

        return replace

    def test_candidate_requires_terminal_verified_completion(self):
        module = self.module()
        root = self.init_repo("incomplete-learning")

        with self.assertRaisesRegex(module.EngineeringError, "terminal"):
            module.propose_learning(root, "run-a1b2c3", "failure_lesson")

    def test_candidate_rejects_fabricated_shallow_completion(self):
        module = self.module()
        root, completion = self.terminal_completion("fabricated-completion")
        path = Path(completion["manifest"])
        path.write_text(
            json.dumps(
                {
                    "schema": "engineering.complete.v1",
                    "run_id": completion["run_id"],
                    "checks": [{"schema": "engineering.check.v1", "exit_code": 0}],
                    "checkpoint": completion["checkpoint"],
                    "result_identity": completion["result_identity"],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(module.EngineeringError, "terminal"):
            module.propose_learning(root, completion["run_id"], "reusable_test")

    def test_candidate_rejects_full_shape_completion_without_controller_attestation(self):
        module = self.module()
        root, prepared = self.prepared_run("forged-full-completion", scope=["README.md"])
        preparation = module._load_preparation(root, prepared["run_id"])
        head = self.git(root, "rev-parse", "HEAD")
        checks = [
            {
                "schema": "engineering.check.v1",
                "command_id": module._check_identity(argv),
                "exit_code": 0,
                "duration_seconds": 0.01,
                "output_digest": "sha256:" + "7" * 64,
            }
            for argv in preparation["required_checks"]
        ]
        payload = module._completion_payload(
            preparation,
            [],
            {"commit": head, "dirty_tree_digest": None},
            {"commit": head, "ready": True},
            False,
            checks,
            [],
        )
        manifest = module._common_graph_dir(root) / "runs" / prepared["run_id"] / "completion.json"
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "attestation|terminal"):
            module.propose_learning(root, prepared["run_id"], "reusable_test")

    def test_repository_identity_is_immutable_git_lineage_across_clones_and_worktrees(self):
        module = self.module()
        root, completion = self.terminal_completion("repository-identity")
        first = module._project_contribution_digest(root)
        self.git(root, "remote", "add", "origin", "https://example.invalid/first.git")
        self.git(root, "remote", "set-url", "origin", "https://example.invalid/changed.git")
        self.assertEqual(first, module._project_contribution_digest(root))

        linked = Path(self.temporary_directory.name) / "repository-identity-linked"
        self.git(root, "worktree", "add", "--detach", str(linked), "HEAD")
        try:
            self.assertEqual(first, module._project_contribution_digest(linked))
        finally:
            self.git(root, "worktree", "remove", "--force", str(linked))

        clone = Path(self.temporary_directory.name) / "repository-identity-clone"
        subprocess.run(
            ["git", "clone", "--quiet", str(root), str(clone)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(first, module._project_contribution_digest(clone))

        independent = Path(self.temporary_directory.name) / "repository-identity-independent"
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(independent)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.git(independent, "config", "user.email", "synthetic")
        self.git(independent, "config", "user.name", "Independent Test")
        (independent / "README.md").write_text("# Different lineage\n", encoding="utf-8")
        self.git(independent, "add", "README.md")
        self.git(independent, "commit", "-m", "independent root")
        self.assertNotEqual(first, module._project_contribution_digest(independent))

        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        with self.assertRaisesRegex(module.EngineeringError, "second project"):
            module.evaluate_learning(candidate["id"], root, completion["run_id"])

    def test_proposal_transaction_never_partially_publishes_queue_local_or_index(self):
        module = self.module()
        root, completion = self.terminal_completion("proposal-transaction")
        _, source_digest = module._terminal_completion(root, completion["run_id"])
        project_digest = module._project_contribution_digest(root)
        identifier = "candidate-" + hashlib.sha256(
            f"{project_digest}\0{source_digest}\0reusable_test".encode()
        ).hexdigest()[:12]
        paths = (
            module._contribution_queue_path(),
            module.common_graph_dir(root) / "contributions" / f"{identifier}.json",
            module._contribution_index_path(),
            module._controller_key_path(module._promotion_controller_dir()),
        )
        for target in paths:
            with self.subTest(target=target.name):
                with (
                    patch.object(
                        module,
                        "_replace_install_path",
                        side_effect=self.fail_once_on_target(module, target),
                    ),
                    self.assertRaisesRegex(OSError, "transactional publication"),
                ):
                    module.propose_learning(root, completion["run_id"], "reusable_test")
                self.assertEqual({str(path): None for path in paths}, self.byte_snapshot(*paths))

    def test_lifecycle_transactions_restore_queue_local_registry_and_key(self):
        module = self.module()
        root, completion = self.terminal_completion("lifecycle-transaction-source")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        second_root, second_completion = self.terminal_completion("lifecycle-transaction-second")
        queue = module._contribution_queue_path()
        local = module.common_graph_dir(root) / "contributions" / f"{candidate['id']}.json"

        for operation in ("evaluate", "approve"):
            for target in (queue, local):
                with self.subTest(operation=operation, target=target.name):
                    before = self.byte_snapshot(queue, local)
                    with (
                        patch.object(
                            module,
                            "_replace_install_path",
                            side_effect=self.fail_once_on_target(module, target),
                        ),
                        self.assertRaisesRegex(OSError, "transactional publication"),
                    ):
                        if operation == "evaluate":
                            module.evaluate_learning(
                                candidate["id"], second_root, second_completion["run_id"]
                            )
                        else:
                            module.record_learning_approval(candidate["id"], approved=True)
                    self.assertEqual(before, self.byte_snapshot(queue, local))
            if operation == "evaluate":
                evaluation = module.evaluate_learning(
                    candidate["id"], second_root, second_completion["run_id"]
                )
            else:
                module.record_learning_approval(candidate["id"], approved=True)

        controller = module._promotion_controller_dir()
        registry = module._promotion_attestation_path()
        key = module._controller_key_path(controller)
        for target in (queue, local, registry):
            with self.subTest(operation="promote", target=target.name):
                before = self.byte_snapshot(queue, local, registry, key)
                with (
                    patch.object(
                        module,
                        "_replace_install_path",
                        side_effect=self.fail_once_on_target(module, target),
                    ),
                    self.assertRaisesRegex(OSError, "transactional publication"),
                ):
                    module.promote_learning(
                        candidate["id"], [{"evaluation_id": evaluation["id"]}], approved=True
                    )
                self.assertEqual(before, self.byte_snapshot(queue, local, registry, key))

    def test_contribution_index_cannot_redirect_to_another_project(self):
        module = self.module()
        root, completion = self.terminal_completion("index-source")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        second_root, second_completion = self.terminal_completion("index-second")
        redirect = (
            module.common_graph_dir(second_root)
            / "contributions"
            / f"{candidate['id']}.json"
        )
        redirect.parent.mkdir(parents=True, exist_ok=True)
        local = module.common_graph_dir(root) / "contributions" / f"{candidate['id']}.json"
        redirect.write_bytes(local.read_bytes())
        index_path = module._contribution_index_path()
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["items"][0]["local_record"] = str(redirect)
        index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "index|pointer|signature"):
            module.evaluate_learning(candidate["id"], second_root, second_completion["run_id"])

    def test_windows_private_acl_is_applied_and_verified_or_fails_closed(self):
        module = self.module()
        target = self.home / "controller.json"
        target.write_text("{}", encoding="utf-8")
        private = {
            "protected": True,
            "owner_sid": "S-1-5-21-1",
            "current_sid": "S-1-5-21-1",
            "access": [
                {
                    "sid": "S-1-5-21-1",
                    "type": "Allow",
                    "inherited": False,
                    "inheritance": "None",
                    "propagation": "None",
                }
            ],
        }
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(private), stderr="")
        with (
            patch.object(module.os, "name", "nt"),
            patch.object(module.subprocess, "run", return_value=completed) as run,
        ):
            self.real_owner_private(target)
        self.assertEqual(1, run.call_count)
        self.assertEqual("powershell.exe", run.call_args.args[0][0])
        self.assertEqual(str(target), run.call_args.args[0][-3])
        self.assertEqual("$true", run.call_args.args[0][-2])
        self.assertEqual("$false", run.call_args.args[0][-1])

        system_private = {
            **private,
            "access": [
                *private["access"],
                {
                    "sid": "S-1-5-18",
                    "type": "Allow",
                    "inherited": False,
                    "inheritance": "None",
                    "propagation": "None",
                },
            ],
        }
        result = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(system_private), stderr=""
        )
        with (
            patch.object(module.os, "name", "nt"),
            patch.object(module.subprocess, "run", return_value=result),
        ):
            self.real_owner_private(target)

        for change in (
            {"protected": False},
            {
                "access": [
                    *private["access"],
                    {
                        "sid": "S-1-1-0",
                        "type": "Allow",
                        "inherited": False,
                        "inheritance": "None",
                        "propagation": "None",
                    },
                ]
            },
            {
                "access": [
                    {
                        "sid": "S-1-5-21-1",
                        "type": "Allow",
                        "inherited": True,
                        "inheritance": "None",
                        "propagation": "None",
                    }
                ]
            },
        ):
            permissive = {**private, **change}
            result = subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(permissive), stderr=""
            )
            with (
                patch.object(module.os, "name", "nt"),
                patch.object(module.subprocess, "run", return_value=result),
                self.assertRaisesRegex(module.EngineeringError, "owner-private"),
            ):
                self.real_owner_private(target)

    def test_private_atomic_publication_keeps_existing_private_sibling_readable(self):
        module = self.module()
        parent = self.home / "private-transaction"
        parent.mkdir()
        retained = parent / "preparation.json"
        retained.write_text('{"schema":"engineering.prepare.v1"}\n', encoding="utf-8")

        with patch.object(
            module, "_enforce_owner_private", side_effect=self.real_owner_private
        ):
            module._private_atomic_bytes(parent / "completion.json", b"{}\n")

        self.assertEqual(
            '{"schema":"engineering.prepare.v1"}\n',
            retained.read_text(encoding="utf-8"),
        )
        nested = parent / "nested" / "future.json"
        nested.parent.mkdir()
        nested.write_text("first\n", encoding="utf-8")
        self.assertEqual("first\n", nested.read_text(encoding="utf-8"))
        nested.write_text("second\n", encoding="utf-8")
        self.assertEqual("second\n", nested.read_text(encoding="utf-8"))

    def test_windows_private_directory_acl_is_inheritable_and_owner_only(self):
        module = self.module()
        target = self.home / "controller"
        target.mkdir()
        private = {
            "protected": True,
            "owner_sid": "S-1-5-21-1",
            "current_sid": "S-1-5-21-1",
            "access": [
                {
                    "sid": "S-1-5-21-1",
                    "type": "Allow",
                    "inherited": False,
                    "inheritance": "ContainerInherit, ObjectInherit",
                    "propagation": "None",
                }
            ],
        }
        completed = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(private), stderr=""
        )
        with (
            patch.object(module.os, "name", "nt"),
            patch.object(module.subprocess, "run", return_value=completed) as run,
        ):
            self.real_owner_private(target)

        self.assertEqual(str(target), run.call_args.args[0][-3])
        self.assertEqual("$true", run.call_args.args[0][-2])
        self.assertEqual("$true", run.call_args.args[0][-1])

    def test_proposed_candidate_is_project_local_and_not_discoverable(self):
        module = self.module()
        root, completion = self.terminal_completion()

        candidate = module.propose_learning(
            root, completion["run_id"], "reusable_test"
        )

        self.assertEqual("proposed", candidate["state"])
        self.assertNotIn(candidate["id"], module.discover_shared_skills())
        local = module.common_graph_dir(root) / "contributions" / f"{candidate['id']}.json"
        self.assertTrue(local.is_file())
        queue = (self.home / ".agents" / "engineering" / "contribution-queue.json")
        queue_text = queue.read_text(encoding="utf-8")
        self.assertNotIn(str(root), queue_text)
        self.assertNotIn("PRIVATE", queue_text)

    def test_promotion_requires_distinct_second_project_and_explicit_approval(self):
        module = self.module()
        root, completion = self.terminal_completion("promotion-source")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        local = module.common_graph_dir(root) / "contributions" / f"{candidate['id']}.json"
        self.assertEqual("proposed", json.loads(local.read_text(encoding="utf-8"))["state"])

        with self.assertRaisesRegex(module.EngineeringError, "evaluation"):
            module.promote_learning(candidate["id"], [], approved=True)
        with self.assertRaisesRegex(module.EngineeringError, "evaluation"):
            module.promote_learning(
                candidate["id"],
                [{"project_digest": candidate["project_digest"], "result": "passed"}],
                approved=True,
            )
        with self.assertRaisesRegex(module.EngineeringError, "second project"):
            module.evaluate_learning(candidate["id"], root, completion["run_id"])

        second_root, second_completion = self.terminal_completion("promotion-second")
        evaluation = module.evaluate_learning(
            candidate["id"], second_root, second_completion["run_id"]
        )
        self.assertEqual("evaluating", json.loads(local.read_text(encoding="utf-8"))["state"])
        with self.assertRaisesRegex(module.EngineeringError, "approval"):
            module.promote_learning(
                candidate["id"],
                [{"evaluation_id": evaluation["id"]}],
                approved=False,
            )
        module.record_learning_approval(candidate["id"], approved=True)
        self.assertEqual(
            "approved_for_promotion", json.loads(local.read_text(encoding="utf-8"))["state"]
        )

        promoted = module.promote_learning(
            candidate["id"],
            [{"evaluation_id": evaluation["id"]}],
            approved=True,
        )
        self.assertEqual("promoted", promoted["state"])
        self.assertEqual(
            ["proposed", "evaluating", "approved_for_promotion", "promoted"],
            [item["state"] for item in promoted["history"]],
        )
        self.assertIn(candidate["id"], module.discover_shared_skills())
        self.assertEqual("promoted", json.loads(local.read_text(encoding="utf-8"))["state"])

    def test_well_formed_forged_promotion_without_attestation_never_discovers(self):
        module = self.module()
        root, completion = self.terminal_completion("forged-shaped-promotion")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        queue_path = module._contribution_queue_path()
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        queue["items"] = [self.forged_promoted_item(module, candidate)]
        queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "attestation|promotion"):
            module.discover_shared_skills()

    def test_tampered_attestation_and_cross_project_replay_fail_closed(self):
        module = self.module()
        root, completion = self.terminal_completion("attested-source")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        second_root, second_completion = self.terminal_completion("attested-second")
        evaluation = module.evaluate_learning(candidate["id"], second_root, second_completion["run_id"])
        module.record_learning_approval(candidate["id"], approved=True)
        module.promote_learning(
            candidate["id"], [{"evaluation_id": evaluation["id"]}], approved=True
        )
        registry_path = module._promotion_attestation_path()
        original_registry = registry_path.read_text(encoding="utf-8")
        registry = json.loads(original_registry)
        registry["items"][0]["signature"] = "hmac-sha256:" + "0" * 64
        registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(module.EngineeringError, "attestation"):
            module.discover_shared_skills()

        registry_path.write_text(original_registry, encoding="utf-8")
        queue_path = module._contribution_queue_path()
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        queue["items"] = [
            self.forged_promoted_item(
                module, candidate, project_digest="sha256:" + "9" * 64
            )
        ]
        queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(module.EngineeringError, "attestation|promotion"):
            module.discover_shared_skills()

    def test_contribution_home_reparse_parent_fails_before_resolution(self):
        module = self.module()
        root, completion = self.terminal_completion("contribution-reparse")
        managed = self.home / ".agents"
        managed.mkdir()
        real = module._is_reparse_point

        with (
            patch.object(
                module,
                "_is_reparse_point",
                side_effect=lambda path: Path(path).name == managed.name or real(path),
            ),
            self.assertRaisesRegex(module.EngineeringError, "reparse|boundary"),
        ):
            module.propose_learning(root, completion["run_id"], "reusable_test")

    def test_forged_promoted_state_and_missing_lifecycle_never_discover(self):
        module = self.module()
        root, completion = self.terminal_completion("forged-promotion")
        candidate = module.propose_learning(root, completion["run_id"], "reusable_test")
        path = self.home / ".agents" / "engineering" / "contribution-queue.json"
        queue = json.loads(path.read_text(encoding="utf-8"))
        queue["items"][0].update(
            state="promoted",
            history=["proposed", "evaluating", "approved_for_promotion", "promoted"],
            evidence=[{"project_digest": "sha256:" + "4" * 64, "result": "passed"}],
            review={"explicit_approval": True},
        )
        path.write_text(json.dumps(queue), encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "queue"):
            module.discover_shared_skills()
        self.assertNotIn(candidate["id"], [])

    def test_install_creates_one_canonical_skill_and_thin_agent_forwarders(self):
        module = self.module()
        source = self.bundle_repo()

        receipt = module.install_bundle(source, self.home)

        canonical = self.home / ".agents" / "skills" / "engineering" / "SKILL.md"
        claude = self.home / ".claude" / "skills" / "engineering" / "SKILL.md"
        shim = self.home / ".agents" / "skills" / "engineering-traceability" / "SKILL.md"
        self.assertEqual(SKILL.read_bytes(), canonical.read_bytes())
        self.assertIn("~/.agents/skills/engineering/SKILL.md", claude.read_text(encoding="utf-8"))
        self.assertIn("~/.agents/skills/engineering/SKILL.md", shim.read_text(encoding="utf-8"))
        self.assertNotIn(str(source), claude.read_text(encoding="utf-8"))
        self.assertEqual("2.1.0", receipt["skill_version"])
        self.assertRegex(receipt["source_git_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            "d89ec68af95e0cad801b56d88df383991e659823",
            receipt["graphify_commit"],
        )
        self.assertEqual(receipt["codex_parity_hash"], receipt["claude_parity_hash"])
        receipt_text = (
            self.home / ".agents" / "engineering" / "install-receipt.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn(str(source), receipt_text)

    def test_install_replay_is_exact_and_known_good_rollback_restores_prior(self):
        module = self.module()
        source = self.bundle_repo()
        first = module.install_bundle(source, self.home)
        canonical = self.home / ".agents" / "skills" / "engineering" / "SKILL.md"
        prior_bytes = canonical.read_bytes()
        self.update_bundle(source)

        second = module.install_bundle(source, self.home)
        replay = module.install_bundle(source, self.home)
        rolled_back = module.rollback_install(self.home)

        self.assertEqual(second, replay)
        self.assertEqual(prior_bytes, canonical.read_bytes())
        self.assertEqual("rolled_back", rolled_back["status"])
        self.assertEqual(first["skill_version"], rolled_back["skill_version"])

    def test_tampered_installed_script_or_prior_bundle_is_never_known_good(self):
        module = self.module()
        source = self.bundle_repo()
        module.install_bundle(source, self.home)
        paths = module._install_paths(self.home)
        (paths["canonical"] / "scripts" / "engineering.py").write_text(
            "tampered = True\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(module.EngineeringError, "receipt"):
            module.install_bundle(source, self.home)

        second_home = Path(self.temporary_directory.name) / "second-home"
        second_home.mkdir()
        self.update_bundle(source)
        with patch.dict(
            os.environ, {"ENGINEERING_USER_HOME": str(second_home)}, clear=False
        ):
            module.install_bundle(source, second_home)
            self.update_bundle(source, "2.0.2")
            module.install_bundle(source, second_home)
            paths = module._install_paths(second_home)
            (paths["previous"] / "references" / "controller-contract.md").write_text(
                "tampered\n", encoding="utf-8"
            )
            current = module._tree_digest(paths["canonical"])
            with self.assertRaisesRegex(module.EngineeringError, "known-good"):
                module.rollback_install(second_home)
            self.assertEqual(current, module._tree_digest(paths["canonical"]))

    def test_install_rejects_source_symlink_and_preserves_existing_install(self):
        module = self.module()
        source = self.bundle_repo()
        module.install_bundle(source, self.home)
        canonical = self.home / ".agents" / "skills" / "engineering" / "SKILL.md"
        before = canonical.read_bytes()
        unsafe = Path(self.temporary_directory.name) / "unsafe-bundle"
        shutil.copytree(source, unsafe)
        outside = Path(self.temporary_directory.name) / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        try:
            (unsafe / "escape.txt").symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation is unavailable")

        with self.assertRaisesRegex(module.EngineeringError, "link|reparse"):
            module.install_bundle(unsafe, self.home)

        self.assertEqual(before, canonical.read_bytes())

    def test_install_lock_fails_closed_without_mutating_target(self):
        module = self.module()
        source = self.bundle_repo()
        module.install_bundle(source, self.home)
        canonical = self.home / ".agents" / "skills" / "engineering" / "SKILL.md"
        before = canonical.read_bytes()
        lock = self.home / ".agents" / "engineering" / "install.lock"
        lock.mkdir()
        (lock / "owner.json").write_text(
            json.dumps(
                {
                    "schema": "engineering.directory-lock.v1",
                    "owner_pid": os.getpid(),
                    "created_at": "2000-01-01T00:00:00Z",
                    "operation_id": "operation-" + "1" * 32,
                    "token": "2" * 32,
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(module.EngineeringError, "install.*progress"):
            module.install_bundle(source, self.home)

        self.assertEqual(before, canonical.read_bytes())

    def test_dead_install_lock_is_recovered_but_live_or_mismatched_is_preserved(self):
        module = self.module()
        source = self.bundle_repo()
        lock = self.home / ".agents" / "engineering" / "install.lock"
        lock.mkdir(parents=True)
        owner = {
            "schema": "engineering.directory-lock.v1",
            "owner_pid": 2_147_000_000,
            "created_at": "2000-01-01T00:00:00Z",
            "operation_id": "operation-" + "1" * 32,
            "token": "2" * 32,
        }
        (lock / "owner.json").write_text(json.dumps(owner), encoding="utf-8")

        with patch.object(module, "_process_alive", return_value=False):
            receipt = module.install_bundle(source, self.home)

        self.assertEqual("installed", receipt["status"])
        self.assertFalse(lock.exists())

    def test_project_lineage_rejects_shallow_replace_and_graft_state(self):
        module = self.module()
        source = self.bundle_repo("lineage-source")
        repository = Path(self.git(source, "rev-parse", "--show-toplevel"))
        shallow = Path(self.temporary_directory.name) / "shallow"
        subprocess.run(
            ["git", "clone", "--depth", "1", repository.as_uri(), str(shallow)],
            check=True,
            capture_output=True,
            text=True,
        )
        with self.assertRaisesRegex(module.EngineeringError, "lineage|shallow"):
            module._project_contribution_digest(shallow)

        (repository / "second.txt").write_text("second\n", encoding="utf-8")
        self.git(repository, "add", "second.txt")
        self.git(repository, "commit", "-m", "second")
        root_commit = self.git(repository, "rev-list", "--max-parents=0", "HEAD")
        self.git(repository, "replace", "HEAD", root_commit)
        with self.assertRaisesRegex(module.EngineeringError, "lineage|replace"):
            module._project_contribution_digest(repository)
        self.git(repository, "replace", "-d", "HEAD")

        graft = Path(self.git(repository, "rev-parse", "--git-path", "info/grafts"))
        if not graft.is_absolute():
            graft = repository / graft
        graft.parent.mkdir(parents=True, exist_ok=True)
        graft.write_text(self.git(repository, "rev-parse", "HEAD") + "\n", encoding="ascii")
        with self.assertRaisesRegex(module.EngineeringError, "lineage|graft"):
            module._project_contribution_digest(repository)

    def test_project_lineage_ignores_dangerous_git_environment_injection(self):
        module = self.module()
        source = self.bundle_repo("identity-source")
        repository = Path(self.git(source, "rev-parse", "--show-toplevel"))
        other = self.bundle_repo("identity-other")
        other_repository = Path(self.git(other, "rev-parse", "--show-toplevel"))
        expected = module._project_contribution_digest(repository)
        injected = {
            "GIT_DIR": str(other_repository / ".git"),
            "GIT_WORK_TREE": str(other_repository),
            "GIT_OBJECT_DIRECTORY": str(other_repository / ".git" / "objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(other_repository / ".git" / "objects"),
            "GIT_REPLACE_REF_BASE": "refs/heads",
            "GIT_CONFIG_GLOBAL": str(other_repository / "hostile.gitconfig"),
        }
        with patch.dict(os.environ, injected, clear=False):
            self.assertEqual(expected, module._project_contribution_digest(repository))

    def test_controller_key_permissions_are_verified_on_every_read(self):
        module = self.module()
        controller = self.home / ".agents" / "engineering" / "controller"
        controller.mkdir(parents=True)
        key = controller / "attestation.key"
        key.write_text("1" * 64 + "\n", encoding="ascii")

        with patch.object(module, "_verify_owner_private") as verify:
            self.assertEqual(bytes.fromhex("1" * 64), module._controller_key(controller, required=True))

        self.assertEqual([((controller,), {"directory": True}), ((key,), {"directory": False})], verify.call_args_list)

    def test_forged_previous_install_receipt_cannot_drive_rollback(self):
        module = self.module()
        source = self.bundle_repo("signed-receipts")
        module.install_bundle(source, self.home)
        self.update_bundle(source, "2.1.1")
        module.install_bundle(source, self.home)
        previous = self.home / ".agents" / "engineering" / "previous-install-receipt.json"
        payload = json.loads(previous.read_text(encoding="utf-8"))
        payload["status"] = "rolled_back"
        previous.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "receipt|signature"):
            module.rollback_install(self.home)

    def test_first_install_holds_lock_before_initializing_signing_key(self):
        module = self.module()
        source = self.bundle_repo("first-install-lock")
        entered = threading.Event()
        release = threading.Event()
        real_key = module._install_key
        outcomes = []

        def delayed_key(home):
            if threading.current_thread().name == "winning-install":
                entered.set()
                self.assertTrue(release.wait(10))
            return real_key(home)

        def install():
            try:
                outcomes.append(module.install_bundle(source, self.home))
            except Exception as error:
                outcomes.append(error)

        with patch.object(module, "_install_key", side_effect=delayed_key):
            winner = threading.Thread(target=install, name="winning-install")
            winner.start()
            self.assertTrue(entered.wait(10))
            with self.assertRaisesRegex(module.EngineeringError, "install.*progress"):
                module.install_bundle(source, self.home)
            release.set()
            winner.join(30)

        self.assertFalse(winner.is_alive())
        self.assertEqual(1, len(outcomes))
        self.assertIsInstance(outcomes[0], dict)
        key = module._install_key(self.home)
        receipt = module._load_install_receipt(module._install_paths(self.home)["receipt"], key)
        self.assertEqual(outcomes[0], receipt)

    def test_lock_owner_publication_failure_never_leaves_unowned_lock(self):
        module = self.module()
        lock = self.home / ".agents" / "engineering" / "install.lock"
        with (
            patch.object(module, "_atomic_text", side_effect=OSError("synthetic crash")),
            self.assertRaises(OSError),
        ):
            module._acquire_directory_lock(lock, "locked")
        self.assertFalse(lock.exists())

    def test_lock_reclaim_rejects_reparse_leaf_before_read_or_delete(self):
        module = self.module()
        lock = self.home / ".agents" / "engineering" / "install.lock"
        lock.mkdir(parents=True)
        (lock / "owner.json").write_text("{}", encoding="utf-8")
        real = module._is_reparse_point

        def mark_lock(path):
            return Path(path) == lock or real(path)

        with (
            patch.object(module, "_is_reparse_point", side_effect=mark_lock),
            self.assertRaisesRegex(module.EngineeringError, "reparse|boundary|locked"),
        ):
            module._acquire_directory_lock(lock, "locked")
        self.assertTrue(lock.exists())

    def test_managed_parent_reparse_point_is_rejected_before_resolution(self):
        module = self.module()
        source = self.bundle_repo()
        agents = self.home / ".agents"
        agents.mkdir()

        real = module._is_reparse_point

        def mark_agents(path):
            return Path(path) == agents or real(path)

        with (
            patch.object(module, "_is_reparse_point", side_effect=mark_agents),
            self.assertRaisesRegex(module.EngineeringError, "boundary|reparse"),
        ):
            module.install_bundle(source, self.home)

        self.assertFalse((agents / "skills" / "engineering").exists())

    def test_install_rejects_dirty_source_closure(self):
        module = self.module()
        source = self.bundle_repo()
        (source / "SKILL.md").write_text("changed after commit\n", encoding="utf-8")

        with self.assertRaisesRegex(module.EngineeringError, "exact Git source"):
            module.install_bundle(source, self.home)

        self.assertFalse((self.home / ".agents" / "skills" / "engineering").exists())

    def test_partial_loader_publication_restores_every_prior_surface(self):
        module = self.module()
        source = self.bundle_repo()
        module.install_bundle(source, self.home)
        paths = module._install_paths(self.home)
        before = {key: module._tree_digest(paths[key]) for key in ("canonical", "claude", "shim")}
        receipt_before = paths["receipt"].read_bytes()
        self.update_bundle(source)
        with (
            patch.object(
                module,
                "_replace_install_path",
                side_effect=self.fail_once_on_target(module, paths["receipt"]),
            ),
            self.assertRaisesRegex(OSError, "transactional publication"),
        ):
            module.install_bundle(source, self.home)

        self.assertEqual(
            before,
            {key: module._tree_digest(paths[key]) for key in ("canonical", "claude", "shim")},
        )
        self.assertEqual(receipt_before, paths["receipt"].read_bytes())

    def test_every_late_install_publication_failure_restores_exact_state(self):
        module = self.module()
        for index, key in enumerate(("claude", "shim", "receipt", "previous", "previous_receipt")):
            with self.subTest(key=key):
                source = self.bundle_repo(f"install-fault-{index}")
                home = Path(self.temporary_directory.name) / f"install-home-{index}"
                home.mkdir()
                with patch.dict(
                    os.environ, {"ENGINEERING_USER_HOME": str(home)}, clear=False
                ):
                    module.install_bundle(source, home)
                    self.update_bundle(source)
                    before = self.managed_snapshot(module, home)
                    target = module._install_paths(home)[key]
                    with (
                        patch.object(module, "_replace_install_path", side_effect=self.fail_once_on_target(module, target)),
                        self.assertRaisesRegex(OSError, "transactional publication"),
                    ):
                        module.install_bundle(source, home)
                    self.assertEqual(before, self.managed_snapshot(module, home))

    def test_every_late_rollback_publication_failure_restores_exact_state(self):
        module = self.module()
        for index, key in enumerate(("claude", "shim", "receipt", "previous", "previous_receipt")):
            with self.subTest(key=key):
                source = self.bundle_repo(f"rollback-fault-{index}")
                home = Path(self.temporary_directory.name) / f"rollback-home-{index}"
                home.mkdir()
                with patch.dict(
                    os.environ, {"ENGINEERING_USER_HOME": str(home)}, clear=False
                ):
                    module.install_bundle(source, home)
                    self.update_bundle(source)
                    module.install_bundle(source, home)
                    before = self.managed_snapshot(module, home)
                    target = module._install_paths(home)[key]
                    with (
                        patch.object(module, "_replace_install_path", side_effect=self.fail_once_on_target(module, target)),
                        self.assertRaisesRegex(OSError, "transactional publication"),
                    ):
                        module.rollback_install(home)
                    self.assertEqual(before, self.managed_snapshot(module, home))

    def test_setup_preview_is_read_only_and_names_both_missing_approvals(self):
        module = self.module()
        root = self.init_repo("setup-preview")
        before = module._working_state_identity(root)
        missing = module.EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        )

        with patch.object(module, "verify_graphify", side_effect=missing):
            result = module.setup(root, sys.executable)

        self.assertEqual("proposal", result["readiness"])
        self.assertEqual(
            ["graphify_install", "project_controls"],
            result["approvals_required"],
        )
        self.assertEqual(
            module._governed_graphify_install_argv(
                result["graphify"]["interpreter"]
            ),
            result["graphify"]["install_argv"],
        )
        self.assertIn("missing", result["graphify"]["reason"].lower())
        self.assertIn(
            "hook installation as one bundle",
            result["project_plan"]["approval_scope"],
        )
        self.assertFalse(result["writes_applied"])
        self.assertEqual(before, module._working_state_identity(root))
        self.assertFalse((root / "engineering.json").exists())

    def test_setup_requires_all_current_approvals_before_any_write(self):
        module = self.module()
        missing = module.EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        )
        for index, scopes in enumerate(
            (("project_controls",), ("graphify_install",))
        ):
            with self.subTest(scopes=scopes):
                root = self.init_repo(f"setup-partial-{index}")
                before = module._working_state_identity(root)
                with patch.object(module, "verify_graphify", side_effect=missing):
                    preview = module.setup(root, sys.executable)
                with (
                    patch.object(module, "verify_graphify", side_effect=missing),
                    patch.object(module, "_run_governed_graphify_install") as runner,
                    patch.object(module, "_install_hooks_authorized") as hooks,
                ):
                    module.approve_setup(
                        root,
                        sys.executable,
                        preview["project_plan_digest"],
                        scopes=list(scopes),
                        graphify_plan_digest=(
                            preview["graphify_plan_digest"]
                            if "graphify_install" in scopes
                            else None
                        ),
                    )
                    result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
                self.assertFalse(result["writes_applied"])
                runner.assert_not_called()
                hooks.assert_not_called()
                self.assertEqual(before, module._working_state_identity(root))

    def test_setup_applies_exact_graphify_command_and_project_contract(self):
        module = self.module()
        root = self.init_repo("setup-approved")
        identity = module.GraphifyIdentity(
            executable=Path(sys.executable),
            repository=module.GRAPHIFY_REPOSITORY,
            version=module.GRAPHIFY_VERSION,
            commit=module.GRAPHIFY_COMMIT,
            required_commands=module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        missing = module.EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        )
        installed = {"value": False}

        def verify(_python):
            if not installed["value"]:
                raise missing
            return identity

        def install(_argv, _interpreter):
            installed["value"] = True

        with (
            patch.object(module, "verify_graphify", side_effect=verify),
            patch.object(module, "_run_governed_graphify_install", side_effect=install) as runner,
        ):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls", "graphify_install"],
                graphify_plan_digest=preview["graphify_plan_digest"],
            )
            result = module.setup(root, sys.executable)

        self.assertEqual("applied", result["readiness"])
        self.assertTrue(result["writes_applied"])
        runner.assert_called_once_with(
            preview["graphify"]["install_argv"],
            preview["graphify"]["interpreter"],
        )
        self.assertTrue((root / "engineering.json").is_file())
        self.assertIn("engineering-managed-start", (root / "AGENTS.md").read_text())
        self.assertIn("engineering-managed-start", (root / "CLAUDE.md").read_text())
        self.assertEqual("/graphify-out/\n", (root / ".gitignore").read_text())
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        self.assertIn("engineering-traceability-hook", (hooks / "pre-commit").read_text())

    def test_setup_preserves_midflight_instructions_ignores_and_custom_hook(self):
        module = self.module()
        root = self.init_repo("setup-midflight")
        (root / "AGENTS.md").write_text("# Team rules\n\nKeep this.\n", encoding="utf-8")
        (root / "CLAUDE.md").write_text("# Claude rules\n\nKeep this too.\n", encoding="utf-8")
        (root / ".gitignore").write_text("private.local\n", encoding="utf-8")
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\nprintf 'custom\\n' >> \"$PWD/custom-hook.log\"\n",
            encoding="utf-8",
        )
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )

        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            result = module.setup(root, sys.executable)

        self.assertEqual("applied", result["readiness"])
        self.assertIn("Keep this.", (root / "AGENTS.md").read_text())
        self.assertIn("Keep this too.", (root / "CLAUDE.md").read_text())
        self.assertEqual(
            "private.local\n/graphify-out/\n", (root / ".gitignore").read_text()
        )
        preserved = hooks / "engineering-traceability-preserved" / "pre-commit"
        self.assertIn("custom-hook.log", preserved.read_text())

    def test_setup_is_idempotent_after_success(self):
        module = self.module()
        root = self.init_repo("setup-idempotent")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            module.setup(root, sys.executable)
            first = module._working_state_identity(root)
            result = module.setup(root, sys.executable)
            second = module._working_state_identity(root)

        self.assertEqual(first, second)
        self.assertEqual("ready", result["readiness"])
        self.assertFalse(result["writes_applied"])
        self.assertEqual(1, (root / "AGENTS.md").read_text().count("engineering-managed-start"))

    def test_failed_graphify_install_leaves_no_project_or_hook_setup(self):
        module = self.module()
        root = self.init_repo("setup-install-failure")
        missing = module.EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        )
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        before = module._working_state_identity(root)
        with patch.object(module, "verify_graphify", side_effect=missing):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls", "graphify_install"],
                graphify_plan_digest=preview["graphify_plan_digest"],
            )
        with (
            patch.object(module, "verify_graphify", side_effect=missing),
            patch.object(
                module,
                "_run_governed_graphify_install",
                side_effect=module.EngineeringError("install failed"),
            ),
            self.assertRaisesRegex(
                module.EngineeringError,
                "recovery: project files, baseline, and hooks were not written",
            ),
        ):
            module.setup(root, sys.executable)
        self.assertEqual(before, module._working_state_identity(root))
        self.assertFalse((root / "engineering.json").exists())
        self.assertFalse((hooks / "engineering-traceability-dispatcher").exists())

    def test_late_setup_failure_restores_custom_files_and_hooks(self):
        module = self.module()
        root = self.init_repo("setup-rollback")
        (root / "AGENTS.md").write_text("original agent\n", encoding="utf-8")
        (root / ".gitignore").write_text("original.ignore\n", encoding="utf-8")
        hooks = Path(self.git(root, "rev-parse", "--git-path", "hooks"))
        if not hooks.is_absolute():
            hooks = (root / hooks).resolve()
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        before_hook = (hooks / "pre-commit").read_bytes()
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
        with (
            patch.object(module, "verify_graphify", return_value=identity),
            patch.object(
                module,
                "_transactional_project_documents",
                side_effect=OSError("late setup publication"),
            ),
            self.assertRaisesRegex(OSError, "late setup publication"),
        ):
            module.setup(root, sys.executable)

        self.assertEqual("original agent\n", (root / "AGENTS.md").read_text())
        self.assertEqual("original.ignore\n", (root / ".gitignore").read_text())
        self.assertFalse((root / "CLAUDE.md").exists())
        self.assertFalse((root / "engineering.json").exists())
        self.assertEqual(before_hook, (hooks / "pre-commit").read_bytes())
        self.assertFalse((hooks / "engineering-traceability-dispatcher").exists())

    def test_existing_invalid_controls_fail_closed_before_setup(self):
        module = self.module()
        root = self.init_repo("setup-invalid")
        (root / "engineering.json").write_text("{}\n", encoding="utf-8")
        self.git(root, "add", "engineering.json")
        self.commit_all(root, "invalid controls")
        before = module._working_state_identity(root)

        with self.assertRaises(module.EngineeringError):
            module.setup(root, sys.executable)

        self.assertEqual(before, module._working_state_identity(root))

    def test_setup_rejects_mismatched_preview_digest_without_writes(self):
        module = self.module()
        root = self.init_repo("setup-mismatched-digest")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        before = module._working_state_identity(root)
        with patch.object(module, "verify_graphify", return_value=identity):
            with self.assertRaisesRegex(
                module.EngineeringError, "plan changed before approval"
            ):
                module.approve_setup(
                    root,
                    sys.executable,
                    "sha256:" + "0" * 64,
                    scopes=["project_controls"],
                )
        self.assertEqual(before, module._working_state_identity(root))

    def test_setup_rejects_malformed_managed_block_without_writes(self):
        module = self.module()
        root = self.init_repo("setup-malformed-block")
        (root / "AGENTS.md").write_text(
            "custom\n<!-- engineering-managed-start -->\nunterminated\n",
            encoding="utf-8",
        )
        before = module._working_state_identity(root)
        with self.assertRaisesRegex(module.EngineeringError, "block is malformed"):
            module.setup(root, sys.executable)
        self.assertEqual(before, module._working_state_identity(root))

    def test_setup_cli_exposes_digest_bound_approval_flags(self):
        result = self.run_cli("approve-setup", "--help")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--project-plan-digest", result.stdout)
        self.assertIn("--graphify-plan-digest", result.stdout)
        self.assertIn("--scope", result.stdout)
        setup = self.run_cli("setup", "--help")
        self.assertNotIn("--approve-project-controls", setup.stdout)
        self.assertNotIn("--approve-graphify-install", setup.stdout)

    def test_skill_explains_setup_preview_and_separate_approvals(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())

        self.assertIn("engineering setup", text)
        self.assertIn("preview", text.lower())
        self.assertIn("project-controls approval", text)
        self.assertIn("Graphify-install approval", text)
        self.assertIn("AGENTS.md", text)
        self.assertIn("CLAUDE.md", text)

    def test_verified_graphify_is_retained_when_late_project_setup_fails(self):
        module = self.module()
        root = self.init_repo("setup-graphify-retained")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        missing = module.EngineeringError(
            "Graphify is missing from the selected Python interpreter."
        )
        installed = {"value": False}

        def verify(_python):
            if not installed["value"]:
                raise missing
            return identity

        def install(_argv, _interpreter):
            installed["value"] = True

        with (
            patch.object(module, "verify_graphify", side_effect=verify),
            patch.object(module, "_run_governed_graphify_install", side_effect=install),
            patch.object(
                module,
                "_transactional_project_documents",
                side_effect=OSError("project publication failed"),
            ),
            self.assertRaisesRegex(
                module.EngineeringError,
                "graphify_installed_project_setup_failed.*retained",
            ),
        ):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls", "graphify_install"],
                graphify_plan_digest=preview["graphify_plan_digest"],
            )
            module.setup(root, sys.executable)
        self.assertFalse((root / "engineering.json").exists())

    def test_setup_digest_echo_cannot_apply_without_controller_attestation(self):
        module = self.module()
        root = self.init_repo("setup-echo-bypass")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            with self.assertRaises(TypeError):
                module.setup(
                    root,
                    sys.executable,
                    approve_project_controls=preview["project_plan_digest"],
                )
        self.assertFalse((root / "engineering.json").exists())

    def test_approve_setup_creates_hmac_attestation_and_setup_consumes_once(self):
        module = self.module()
        root = self.init_repo("setup-attested")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            approval = module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            result = module.setup(root, sys.executable)
        self.assertRegex(approval["approval_id"], r"^attestation-")
        self.assertEqual("applied", result["readiness"])
        with self.assertRaisesRegex(module.EngineeringError, "missing or mismatched"):
            module._require_attestation(
                module._project_controller_dir(root),
                "setup",
                approval["claims"],
            )

    def test_setup_approval_becomes_stale_when_project_or_hook_changes(self):
        module = self.module()
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        for index, change in enumerate(("project", "hook")):
            with self.subTest(change=change):
                root = self.init_repo(f"setup-stale-{index}")
                hooks = module._hooks_dir(root)
                hooks.mkdir(parents=True, exist_ok=True)
                (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                with patch.object(module, "verify_graphify", return_value=identity):
                    preview = module.setup(root, sys.executable)
                    module.approve_setup(
                        root,
                        sys.executable,
                        preview["project_plan_digest"],
                        scopes=["project_controls"],
                    )
                    if change == "project":
                        (root / "AGENTS.md").write_text("changed\n", encoding="utf-8")
                    else:
                        (hooks / "pre-commit").write_text(
                            "#!/bin/sh\nprintf changed\n", encoding="utf-8"
                        )
                    result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
                self.assertFalse((root / "engineering.json").exists())

    def test_setup_scope_mismatch_and_failed_attempt_consume_no_authority(self):
        module = self.module()
        root = self.init_repo("setup-scope-replay")
        missing = module.EngineeringError("Graphify is missing")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", side_effect=missing):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            result = module.setup(root, sys.executable)
        self.assertEqual("proposal", result["readiness"])
        with patch.object(module, "verify_graphify", return_value=identity):
            fresh = module.setup(root, sys.executable)
        self.assertEqual("proposal", fresh["readiness"])

    def test_hook_destination_rejects_external_core_hooks_path(self):
        module = self.module()
        root = self.init_repo("setup-external-hooks")
        external = Path(self.temporary_directory.name) / "external-hooks"
        external.mkdir()
        self.git(root, "config", "core.hooksPath", str(external))

        with self.assertRaisesRegex(module.EngineeringError, "unsupported core.hooksPath"):
            module.setup(root, sys.executable)
        self.assertEqual([], list(external.iterdir()))

    def test_hook_destination_rejects_reparse_common_hooks_directory(self):
        module = self.module()
        root = self.init_repo("setup-reparse-hooks")
        common = Path(self.git(root, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = root / common
        hooks = common.resolve() / "hooks"
        real = module._is_reparse_point

        def mark_hooks(path):
            return Path(path).absolute() == hooks.absolute() or real(path)

        with (
            patch.object(module, "_is_reparse_point", side_effect=mark_hooks),
            self.assertRaisesRegex(module.EngineeringError, "reparse|boundary"),
        ):
            module.setup(root, sys.executable)

    def test_direct_hook_installer_cannot_bypass_setup_attestation(self):
        module = self.module()
        root = self.init_repo("setup-direct-hook-bypass")
        before = module._working_state_identity(root)

        with self.assertRaisesRegex(module.EngineeringError, "Direct hook mutation"):
            module.install_hooks(root, sys.executable, ENGINEERING_SCRIPT)

        self.assertEqual(before, module._working_state_identity(root))

    def test_tampered_setup_attestation_fails_closed_without_project_writes(self):
        module = self.module()
        root = self.init_repo("setup-tampered-attestation")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
        registry_path = module._attestation_path(
            module._project_controller_dir(root)
        )
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["items"][0]["claims"]["scopes"] = ["graphify_install"]
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch.object(module, "verify_graphify", return_value=identity),
            self.assertRaisesRegex(module.EngineeringError, "HMAC|attestation"),
        ):
            module.setup(root, sys.executable)
        self.assertFalse((root / "engineering.json").exists())

    def test_forged_managed_hook_markers_are_not_treated_as_installed(self):
        module = self.module()
        root = self.init_repo("setup-forged-hook")
        hooks = module._hooks_dir(root)
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "engineering-traceability-dispatcher").write_text(
            "#!/bin/sh\n# engineering-traceability-dispatcher\nexit 0\n",
            encoding="utf-8",
        )
        for event in module.HOOK_EVENTS:
            (hooks / event).write_text(
                "#!/bin/sh\n# engineering-traceability-hook\nexit 0\n",
                encoding="utf-8",
            )
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
        self.assertTrue(preview["project_plan"]["hook_installation"]["required"])
        self.assertTrue(preview["project_plan"]["hook_installation"]["existing"])

    def test_preserved_hook_mutation_after_approval_stales_setup(self):
        module = self.module()
        root = self.init_repo("setup-preserved-stale")
        hooks = module._hooks_dir(root)
        preserved = hooks / "engineering-traceability-preserved"
        preserved.mkdir(parents=True)
        hook = preserved / "pre-commit"
        hook.write_text("#!/bin/sh\nprintf first\n", encoding="utf-8")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            hook.write_text("#!/bin/sh\nprintf changed\n", encoding="utf-8")
            result = module.setup(root, sys.executable)
        self.assertEqual("proposal", result["readiness"])
        self.assertFalse((root / "engineering.json").exists())

    def assert_legacy_preserved_stales_setup(self, change):
        module = self.module()
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        root = self.init_repo(f"setup-legacy-preserved-{change}")
        legacy = module._hooks_dir(root) / "engineering-preserved"
        legacy.mkdir(parents=True)
        hook = legacy / "pre-commit"
        hook.write_text("#!/bin/sh\nprintf first\n", encoding="utf-8")
        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            if change == "change":
                hook.write_text("#!/bin/sh\nprintf changed\n", encoding="utf-8")
                result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
            elif change == "add":
                (legacy / "post-merge").write_text(
                    "#!/bin/sh\nprintf added\n", encoding="utf-8"
                )
                result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
            elif change == "remove":
                hook.unlink()
                result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
            else:
                real = module._is_reparse_point

                def mark_hook(path):
                    return Path(path).absolute() == hook.absolute() or real(path)

                with (
                    patch.object(module, "_is_reparse_point", side_effect=mark_hook),
                    self.assertRaisesRegex(
                        module.EngineeringError, "link|reparse|boundary"
                    ),
                ):
                    module.setup(root, sys.executable)
        self.assertFalse((root / "engineering.json").exists())

    def test_legacy_preserved_change_stales_setup(self):
        self.assert_legacy_preserved_stales_setup("change")

    def test_legacy_preserved_addition_stales_setup(self):
        self.assert_legacy_preserved_stales_setup("add")

    def test_legacy_preserved_removal_stales_setup(self):
        self.assert_legacy_preserved_stales_setup("remove")

    def test_legacy_preserved_reparse_stales_setup(self):
        self.assert_legacy_preserved_stales_setup("reparse")

    def test_installer_rechecks_exact_hook_state_at_mutation_seam(self):
        module = self.module()
        root = self.init_repo("setup-hook-seam-race")
        hooks = module._hooks_dir(root)
        legacy = hooks / "engineering-preserved"
        legacy.mkdir(parents=True)
        preserved = legacy / "pre-commit"
        original = b"#!/bin/sh\nprintf original\n"
        preserved.write_bytes(original)
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\n# engineering-hook\n"
            'exec "$(dirname -- "$0")/engineering-dispatcher" pre-commit "$@"\n',
            encoding="utf-8",
        )
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        original_installer = module._install_hooks_authorized

        def inject_drift(project, graphify_python, script_path, approved_state):
            preserved.write_bytes(b"#!/bin/sh\nprintf raced\n")
            return original_installer(
                project, graphify_python, script_path, approved_state
            )

        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            with (
                patch.object(
                    module,
                    "_install_hooks_authorized",
                    side_effect=inject_drift,
                ),
                self.assertRaisesRegex(
                    module.EngineeringError, "hook state changed before mutation"
                ),
            ):
                module.setup(root, sys.executable)
        self.assertEqual(original, preserved.read_bytes())
        self.assertFalse((root / "engineering.json").exists())

    def test_hook_final_replace_cas_rejects_concurrent_target_change(self):
        module = self.module()
        root = self.init_repo("setup-hook-final-cas")
        hooks = module._hooks_dir(root)
        hooks.mkdir(parents=True, exist_ok=True)
        hook = hooks / "pre-commit"
        hook.write_bytes(b"#!/bin/sh\nprintf original\n")
        approved = module._hook_plan_state(root)
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        original_replace = module._replace_install_path
        injected = False

        def inject_change(
            source, target, expected_pre_state=None, *, preimage_path=None
        ):
            nonlocal injected
            if target == hook and not injected:
                injected = True
                hook.write_bytes(b"#!/bin/sh\nprintf concurrent\n")
            return original_replace(
                source,
                target,
                expected_pre_state,
                preimage_path=preimage_path,
            )

        with (
            patch.object(module, "verify_graphify", return_value=identity),
            patch.object(module, "_replace_install_path", side_effect=inject_change),
            self.assertRaisesRegex(module.EngineeringError, "changed before publication"),
        ):
            module._install_hooks_authorized(
                root, sys.executable, ENGINEERING_SCRIPT, approved
            )
        self.assertEqual(b"#!/bin/sh\nprintf concurrent\n", hook.read_bytes())

    def test_hook_migration_uses_approved_bytes_after_source_race(self):
        module = self.module()
        root = self.init_repo("setup-hook-approved-bytes")
        hooks = module._hooks_dir(root)
        legacy = hooks / "engineering-preserved"
        legacy.mkdir(parents=True)
        source = legacy / "pre-commit"
        approved_bytes = b"#!/bin/sh\nprintf approved\n"
        source.write_bytes(approved_bytes)
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\n# engineering-hook\n"
            'exec "$(dirname -- "$0")/engineering-dispatcher" pre-commit "$@"\n',
            encoding="utf-8",
            newline="\n",
        )
        approved = module._hook_plan_state(root)
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        original_replace = module._replace_install_path
        injected = False

        def inject_change(
            stage, target, expected_pre_state=None, *, preimage_path=None
        ):
            nonlocal injected
            if not injected:
                injected = True
                source.write_bytes(b"#!/bin/sh\nprintf raced\n")
            return original_replace(
                stage,
                target,
                expected_pre_state,
                preimage_path=preimage_path,
            )

        with (
            patch.object(module, "verify_graphify", return_value=identity),
            patch.object(module, "_replace_install_path", side_effect=inject_change),
        ):
            module._install_hooks_authorized(
                root, sys.executable, ENGINEERING_SCRIPT, approved
            )
        self.assertEqual(
            approved_bytes,
            (hooks / module.PRESERVED_HOOK_DIRECTORY / "pre-commit").read_bytes(),
        )

    def test_project_document_final_replace_cas_rejects_concurrent_change(self):
        module = self.module()
        root = self.init_repo("setup-document-final-cas")
        target = root / "AGENTS.md"
        target.write_text("original\n", encoding="utf-8")
        expected = module._project_document_state(root, target)
        original_replace = module._replace_install_path
        injected = False

        def inject_change(
            source, destination, expected_pre_state=None, *, preimage_path=None
        ):
            nonlocal injected
            if destination == target and not injected:
                injected = True
                target.write_text("concurrent\n", encoding="utf-8")
            return original_replace(
                source,
                destination,
                expected_pre_state,
                preimage_path=preimage_path,
            )

        with (
            patch.object(module, "_replace_install_path", side_effect=inject_change),
            self.assertRaisesRegex(module.EngineeringError, "changed before publication"),
        ):
            module._transactional_project_documents(
                root, [(target, b"managed\n")], {"AGENTS.md": expected}
            )
        self.assertEqual("concurrent\n", target.read_text(encoding="utf-8"))

    def test_post_publication_verification_failure_restores_exact_preimage(self):
        module = self.module()
        root = self.init_repo("setup-post-publication-rollback")
        target = root / "managed-hook"
        original = b"#!/bin/sh\nprintf original\n"
        target.write_bytes(original)
        expected = module._project_document_state(root, target)
        stage = root / "managed-hook.stage"
        stage.write_bytes(b"#!/bin/sh\nprintf managed\n")

        def fail_verification():
            target.write_bytes(b"#!/bin/sh\nprintf tampered\n")
            raise module.EngineeringError("synthetic post-publication mismatch")

        with self.assertRaisesRegex(
            module.EngineeringError, "post-publication mismatch"
        ):
            module._transactional_replace(
                [(stage, target)],
                "post-publication-test",
                {target: expected},
                after_publication=fail_verification,
            )
        self.assertEqual(original, target.read_bytes())
        self.assertFalse(
            target.with_name(".managed-hook.backup-post-publication-test").exists()
        )

    def test_project_document_cas_preserves_concurrent_instruction_change(self):
        module = self.module()
        root = self.init_repo("setup-project-document-race")
        instruction = root / "AGENTS.md"
        instruction.write_text("original instruction\n", encoding="utf-8")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        original_publication = module._transactional_project_documents

        def inject_change(project, documents, expected_pre_states):
            instruction.write_text("concurrent instruction\n", encoding="utf-8")
            return original_publication(project, documents, expected_pre_states)

        with patch.object(module, "verify_graphify", return_value=identity):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                scopes=["project_controls"],
            )
            hook_state = module._hook_plan_state(root)
            with (
                patch.object(
                    module,
                    "_transactional_project_documents",
                    side_effect=inject_change,
                ),
                self.assertRaisesRegex(
                    module.EngineeringError,
                    "project document changed before staging",
                ),
            ):
                module.setup(root, sys.executable)
        self.assertEqual("concurrent instruction\n", instruction.read_text())
        self.assertEqual(hook_state, module._hook_plan_state(root))
        self.assertFalse((root / "engineering.json").exists())
        self.assertFalse((root / "CLAUDE.md").exists())
        self.assertFalse((root / ".gitignore").exists())

    def test_preserved_hook_change_removal_and_addition_break_readiness(self):
        module = self.module()
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        for index, change in enumerate(("change", "remove", "add")):
            with self.subTest(change=change):
                root = self.init_repo(f"setup-preserved-readiness-{index}")
                hooks = module._hooks_dir(root)
                hooks.mkdir(parents=True, exist_ok=True)
                (hooks / "pre-commit").write_text(
                    "#!/bin/sh\nprintf original\n", encoding="utf-8"
                )
                with patch.object(module, "verify_graphify", return_value=identity):
                    preview = module.setup(root, sys.executable)
                    module.approve_setup(
                        root,
                        sys.executable,
                        preview["project_plan_digest"],
                        scopes=["project_controls"],
                    )
                    module.setup(root, sys.executable)
                    self.assertEqual(
                        "ready", module.setup(root, sys.executable)["readiness"]
                    )
                    preserved = (
                        hooks / "engineering-traceability-preserved" / "pre-commit"
                    )
                    if change == "change":
                        preserved.write_text(
                            "#!/bin/sh\nprintf changed\n", encoding="utf-8"
                        )
                    elif change == "remove":
                        preserved.unlink()
                    else:
                        (preserved.parent / "post-merge").write_text(
                            "#!/bin/sh\nprintf added\n", encoding="utf-8"
                        )
                    result = module.setup(root, sys.executable)
                self.assertEqual("proposal", result["readiness"])
                self.assertIn("project_controls", result["approvals_required"])

    def test_preserved_hook_symlink_poison_fails_closed(self):
        module = self.module()
        root = self.init_repo("setup-preserved-symlink")
        preserved = module._hooks_dir(root) / "engineering-traceability-preserved"
        preserved.mkdir(parents=True)
        outside = Path(self.temporary_directory.name) / "outside-hook"
        outside.write_text("#!/bin/sh\n", encoding="utf-8")
        poisoned = preserved / "pre-commit"
        try:
            poisoned.symlink_to(outside)
        except OSError:
            poisoned.write_text("#!/bin/sh\n", encoding="utf-8")
            real = module._is_reparse_point

            def mark_poison(path):
                return Path(path).absolute() == poisoned.absolute() or real(path)

            with (
                patch.object(module, "_is_reparse_point", side_effect=mark_poison),
                self.assertRaisesRegex(
                    module.EngineeringError, "link|reparse|boundary"
                ),
            ):
                module.setup(root, sys.executable)
        else:
            with self.assertRaisesRegex(
                module.EngineeringError, "link|reparse|boundary"
            ):
                module.setup(root, sys.executable)

    def test_setup_rejects_reparse_instruction_before_reading_external_content(self):
        module = self.module()
        root = self.init_repo("setup-instruction-reparse")
        instruction = root / "AGENTS.md"
        secret = "external-content-must-not-be-read"
        instruction.write_text(secret, encoding="utf-8")
        before = module._working_state_identity(root)
        real_reparse = module._is_reparse_point
        real_managed_instruction = module._managed_instruction_text

        def mark_instruction(path):
            return Path(path).name == "AGENTS.md" or real_reparse(path)

        def reject_instruction_read(path):
            if Path(path).absolute() == instruction.absolute():
                raise AssertionError("unsafe instruction content was read")
            return real_managed_instruction(path)

        with (
            patch.object(module, "_is_reparse_point", side_effect=mark_instruction),
            patch.object(
                module,
                "_managed_instruction_text",
                side_effect=reject_instruction_read,
            ),
            self.assertRaisesRegex(module.EngineeringError, "reparse|boundary") as error,
        ):
            module.setup(root, sys.executable)
        self.assertNotIn(secret, str(error.exception))
        self.assertEqual(before, module._working_state_identity(root))

    def test_setup_rejects_every_noncanonical_managed_marker_shape(self):
        module = self.module()
        shapes = (
            "<!-- engineering-managed-end -->\n<!-- engineering-managed-start -->\n",
            "<!-- engineering-managed-start -->\nx\n<!-- engineering-managed-end -->\n<!-- engineering-managed-start -->\n",
            "stray <!-- engineering-managed-end -->\n",
        )
        for index, content in enumerate(shapes):
            with self.subTest(index=index):
                root = self.init_repo(f"setup-marker-shape-{index}")
                (root / "AGENTS.md").write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(module.EngineeringError, "block is malformed"):
                    module.setup(root, sys.executable)

    def test_governed_graphify_plan_binds_exact_external_interpreter(self):
        module = self.module()
        root = self.init_repo("setup-interpreter-plan")
        missing = module.EngineeringError("Graphify is missing")
        with patch.object(module, "verify_graphify", side_effect=missing):
            preview = module.setup(root, sys.executable)
        interpreter = preview["graphify"]["interpreter"]
        self.assertEqual(str(Path(sys.executable).resolve()), interpreter["path"])
        self.assertRegex(interpreter["sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            [
                str(Path(sys.executable).resolve()),
                "-m",
                "pip",
                "install",
                "git+https://github.com/safishamsi/graphify.git"
                "@d89ec68af95e0cad801b56d88df383991e659823",
            ],
            preview["graphify"]["install_argv"],
        )

    def test_legacy_mutation_commands_are_read_only_setup_forwarders(self):
        module = self.module()
        root = self.init_repo("setup-legacy-forwarders")
        identity = module.GraphifyIdentity(
            Path(sys.executable), module.GRAPHIFY_REPOSITORY,
            module.GRAPHIFY_VERSION, module.GRAPHIFY_COMMIT,
            module.REQUIRED_GRAPHIFY_COMMANDS,
        )
        before = module._working_state_identity(root)
        with patch.object(module, "verify_graphify", return_value=identity):
            for command in ("bootstrap", "reconstruct", "install-hooks"):
                result = module.legacy_setup_forwarder(root, sys.executable, command)
                self.assertEqual("proposal", result["readiness"])
        self.assertEqual(before, module._working_state_identity(root))

    def test_successful_installer_with_failed_verification_reports_external_change(self):
        module = self.module()
        root = self.init_repo("setup-external-unverified")
        missing = module.EngineeringError("Graphify is missing")
        with patch.object(module, "verify_graphify", side_effect=missing):
            preview = module.setup(root, sys.executable)
            module.approve_setup(
                root,
                sys.executable,
                preview["project_plan_digest"],
                graphify_plan_digest=preview["graphify_plan_digest"],
                scopes=["project_controls", "graphify_install"],
            )
        with (
            patch.object(module, "verify_graphify", side_effect=missing),
            patch.object(module, "_run_governed_graphify_install"),
            self.assertRaisesRegex(
                module.EngineeringError,
                "external_change_unverified.*no project setup",
            ),
        ):
            module.setup(root, sys.executable)
        self.assertFalse((root / "engineering.json").exists())

    def test_skill_explains_quarantine_promotion_and_dual_agent_install(self):
        text = " ".join(SKILL.read_text(encoding="utf-8").split())

        self.assertIn("project-local", text)
        self.assertIn("second project", text)
        self.assertIn("explicit approval", text)
        self.assertIn("~/.agents/skills/engineering/", text)
        self.assertIn("Codex and Claude", text)
        self.assertIn("known-good rollback", text)
        self.assertIn("Promote means apply", text)
        self.assertIn("never rewrites itself", text)

    def test_learning_practice_contract(self):
        module = self.module()
        practice = {
            "schema": "engineering.practice.v1",
            "title": "Verify generated output before replacing a canonical checkpoint",
            "instruction": "Publish generated output only after identity and integrity checks pass.",
            "applies_to": ["completion", "maintenance"],
            "verification": "A failed rebuild retains the prior valid checkpoint.",
            "sanitized": True,
        }

        normalized = module._validate_practice(practice)
        self.assertEqual(practice, normalized)
        self.assertEqual(module._practice_digest(practice), module._practice_digest(dict(practice)))

        invalid = [
            {**practice, "extra": True},
            {**practice, "sanitized": False},
            {**practice, "applies_to": ["unknown"]},
            {**practice, "instruction": "Run curl https://example.invalid/install"},
            {**practice, "instruction": "Use C:\\Users\\someone\\private.txt"},
            {**practice, "title": "x" * 121},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(module.EngineeringError):
                module._validate_practice(payload)

    def test_learning_candidate_projection_is_bounded_and_private(self):
        module = self.module()
        practice = module._validate_practice(
            {
                "schema": "engineering.practice.v1",
                "title": "Retain the prior checkpoint when rebuilding fails",
                "instruction": "Publish a replacement only after integrity checks pass.",
                "applies_to": ["completion", "maintenance"],
                "verification": "A failed rebuild leaves the prior checkpoint readable.",
                "sanitized": True,
            }
        )
        candidate = {
            "id": "candidate-" + "a" * 12,
            "kind": "reusable_pattern",
            "state": "proposed",
            "practice": practice,
            "project_digest": "sha256:" + "1" * 64,
            "source_reference": "completion:run-a1b2c3",
            "source_digest": "sha256:" + "2" * 64,
        }

        projection = module._learning_candidate_projection(candidate)

        self.assertEqual(
            {
                "candidate_id": candidate["id"],
                "title": practice["title"],
                "kind": "reusable_pattern",
                "modules": ["completion", "maintenance"],
                "state": "proposed",
                "actions": ["keep", "inspect", "dismiss"],
            },
            projection,
        )
        self.assertNotIn("project_digest", projection)
        self.assertNotIn("source_reference", projection)

    def test_practice_candidate_is_retained_and_duplicate_suppressed(self):
        module = self.module()
        root, completion = self.terminal_completion("practice-candidate")
        practice = {
            "schema": "engineering.practice.v1",
            "title": "Retain a prior checkpoint after failed generation",
            "instruction": "Publish a replacement only after integrity checks pass.",
            "applies_to": ["completion", "maintenance"],
            "verification": "A failed rebuild leaves the prior checkpoint readable.",
            "sanitized": True,
        }

        first = module.propose_learning(
            root, completion["run_id"], "reusable_pattern", practice
        )
        second = module.propose_learning(
            root, completion["run_id"], "reusable_pattern", dict(practice)
        )

        self.assertEqual(first, second)
        self.assertEqual(module._practice_digest(practice), first["practice_digest"])
        self.assertEqual(practice, first["practice"])

    def test_promote_means_apply_and_disable_preserves_history(self):
        module = self.module()
        self.assertTrue(hasattr(module, "promote_and_apply"))
        self.assertTrue(hasattr(module, "disable_applied_practice"))
        source_root, source_completion = self.terminal_completion("applied-source")
        practice = {
            "schema": "engineering.practice.v1",
            "title": "Retain a prior checkpoint after failed generation",
            "instruction": "Publish a replacement only after integrity checks pass.",
            "applies_to": ["completion", "maintenance"],
            "verification": "A failed rebuild leaves the prior checkpoint readable.",
            "sanitized": True,
        }
        candidate = module.propose_learning(
            source_root,
            source_completion["run_id"],
            "reusable_pattern",
            practice,
        )
        second_root, second_completion = self.terminal_completion("applied-second")
        evaluation = module.evaluate_learning(
            candidate["id"], second_root, second_completion["run_id"]
        )

        local = module.common_graph_dir(source_root) / "contributions" / f"{candidate['id']}.json"
        transaction_paths = (
            module._contribution_queue_path(),
            local,
            module._promotion_attestation_path(),
            module._applied_practices_path(),
        )
        before = self.byte_snapshot(*transaction_paths)
        with (
            patch.object(
                module,
                "_replace_install_path",
                side_effect=self.fail_once_on_target(
                    module, module._applied_practices_path()
                ),
            ),
            self.assertRaisesRegex(OSError, "transactional publication"),
        ):
            module.promote_and_apply(
                candidate["id"], [evaluation["id"]], approved=True
            )
        self.assertEqual(before, self.byte_snapshot(*transaction_paths))

        applied = module.promote_and_apply(
            candidate["id"], [evaluation["id"]], approved=True
        )

        self.assertEqual("promoted_applied", applied["state"])
        ledger = module._load_applied_practices()
        self.assertEqual(1, len(ledger["items"]))
        self.assertEqual("active", ledger["items"][0]["state"])
        self.assertEqual(candidate["id"], ledger["items"][0]["candidate_id"])

        disabled = module.disable_applied_practice(candidate["id"], approved=True)
        self.assertEqual("disabled", disabled["state"])
        self.assertEqual("promoted_applied", module._candidate(module._load_contribution_queue(), candidate["id"])["state"])

    def test_applied_ledger_rejects_tamper_and_bounds(self):
        module = self.module()
        controller = module._promotion_controller_dir()
        controller.mkdir(parents=True)
        key = b"k" * 32
        module._controller_key_path(controller).write_text(key.hex() + "\n", encoding="ascii")
        practice = module._validate_practice(
            {
                "schema": "engineering.practice.v1",
                "title": "Retain a prior checkpoint after failed generation",
                "instruction": "Publish a replacement only after integrity checks pass.",
                "applies_to": ["completion", "maintenance"],
                "verification": "A failed rebuild leaves the prior checkpoint readable.",
                "sanitized": True,
            }
        )

        def entry(number):
            item = {
                "candidate_id": f"candidate-{number:012x}",
                "practice_digest": module._practice_digest(practice),
                "practice": practice,
                "state": "active",
                "skill_version": module._skill_version(),
                "disabled_reason": None,
            }
            item["signature"] = module._applied_practice_signature(key, item)
            return item

        ledger = {"schema": "engineering.applied-practices.v1", "items": [entry(1)]}
        module._applied_practices_path().write_text(
            json.dumps(ledger, indent=2) + "\n", encoding="utf-8"
        )
        self.assertEqual(ledger, module._load_applied_practices())

        ledger["items"][0]["practice"]["title"] = "Tampered"
        module._applied_practices_path().write_text(
            json.dumps(ledger, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(module.EngineeringError, "ledger"):
            module._load_applied_practices()

        too_many = {
            "schema": "engineering.applied-practices.v1",
            "items": [entry(number) for number in range(1, 130)],
        }
        with self.assertRaisesRegex(module.EngineeringError, "active limit"):
            module._validate_applied_ledger(too_many, key)
        with (
            patch.object(module, "MAX_APPLIED_LEDGER_BYTES", 64),
            self.assertRaisesRegex(module.EngineeringError, "size limit"),
        ):
            module._validate_applied_ledger(
                {"schema": "engineering.applied-practices.v1", "items": [entry(2)]},
                key,
            )

    def test_applied_practice_relevance_and_skill_immutability(self):
        module = self.module()
        controller = module._promotion_controller_dir()
        controller.mkdir(parents=True)
        key = b"p" * 32
        module._controller_key_path(controller).write_text(key.hex() + "\n", encoding="ascii")
        practice = module._validate_practice(
            {
                "schema": "engineering.practice.v1",
                "title": "Retain a prior checkpoint after failed generation",
                "instruction": "Publish a replacement only after integrity checks pass.",
                "applies_to": ["completion", "maintenance"],
                "verification": "A failed rebuild leaves the prior checkpoint readable.",
                "sanitized": True,
            }
        )
        item = {
            "candidate_id": "candidate-" + "b" * 12,
            "practice_digest": module._practice_digest(practice),
            "practice": practice,
            "state": "active",
            "skill_version": module._skill_version(),
            "disabled_reason": None,
        }
        item["signature"] = module._applied_practice_signature(key, item)
        module._applied_practices_path().write_text(
            json.dumps(
                {"schema": "engineering.applied-practices.v1", "items": [item]},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        before = module._tree_digest(SKILL_DIR)

        selected = module.applicable_practices(
            "completion", manifest_version=module._skill_version()
        )

        self.assertEqual(1, len(selected))
        self.assertEqual(practice["instruction"], selected[0]["instruction"])
        self.assertEqual([], module.applicable_practices("setup", manifest_version=module._skill_version()))
        self.assertEqual(before, module._tree_digest(SKILL_DIR))
        preparation = {
            "run_id": "run-a1b2c3",
            "project": {"root_digest": "sha256:" + "1" * 64},
            "intent": "verify",
            "authorization": {"scope": []},
            "autonomy": "collaborative",
            "context": [],
            "impact": [],
            "completion_applied_practices": selected,
            "completion_practice_status": {"status": "active", "count": 1},
        }
        completion = module._completion_payload(
            preparation,
            [],
            {"commit": "a" * 40, "dirty_tree_digest": None},
            {"commit": "a" * 40, "ready": True},
            False,
            [],
            [],
        )
        self.assertEqual(selected, completion["applied_practices"])
        self.assertEqual({"status": "active", "count": 1}, completion["practice_status"])
        with self.assertRaisesRegex(module.EngineeringError, "version"):
            module.applicable_practices("completion", manifest_version="3.0.0")

    def test_learning_cli_binds_exact_combined_confirmation(self):
        module = self.module()
        candidate_id = "candidate-" + "c" * 12
        evaluation_id = "evaluation-" + "d" * 12
        output = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "engineering",
                    "learning-promote-apply",
                    candidate_id,
                    "--evaluation-id",
                    evaluation_id,
                    "--confirm",
                    f"Promote and apply {candidate_id}",
                ],
            ),
            patch.object(
                module,
                "promote_and_apply",
                return_value={"state": "promoted_applied"},
            ) as promote,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, module.main())

        promote.assert_called_once_with(candidate_id, [evaluation_id], True)
        self.assertEqual({"state": "promoted_applied"}, json.loads(output.getvalue()))

    def test_source_improvement_is_proposal_only(self):
        module = self.module()
        practice = module._validate_practice(
            {
                "schema": "engineering.practice.v1",
                "title": "Retain a prior checkpoint after failed generation",
                "instruction": "Publish a replacement only after integrity checks pass.",
                "applies_to": ["completion", "maintenance"],
                "verification": "A failed rebuild leaves the prior checkpoint readable.",
                "sanitized": True,
            }
        )
        candidate = {
            "id": "candidate-" + "e" * 12,
            "state": "promoted_applied",
            "practice": practice,
            "practice_digest": module._practice_digest(practice),
            "source_digest": "sha256:" + "1" * 64,
            "evidence": [{"source_digest": "sha256:" + "2" * 64}],
        }
        with (
            patch.object(
                module,
                "_load_contribution_queue",
                return_value={"schema": "engineering.contribution-queue.v1", "items": [candidate]},
            ),
            patch.object(module, "_require_promotion_attestation"),
        ):
            proposal = module.source_improvement_proposal(candidate["id"])

        self.assertEqual("engineering.source-improvement-proposal.v1", proposal["schema"])
        self.assertEqual(candidate["practice_digest"], proposal["practice_digest"])
        self.assertEqual(2, len(proposal["evidence_digests"]))
        self.assertNotIn("diff", proposal)
        self.assertNotIn("patch", proposal)
        self.assertNotIn("command", proposal)


if __name__ == "__main__":
    unittest.main()
