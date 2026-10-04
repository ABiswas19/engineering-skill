from __future__ import annotations

import importlib.util
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "engineering_metadata_projection", ROOT / "tools" / "metadata_projection.py"
)


def clone_fixture(source: Path) -> None:
    try:
        source_git_metadata_present = "true" if (ROOT / ".git").exists() else "false"
    except OSError:
        source_git_metadata_present = "unknown"
    try:
        destination_parent_is_dir = "true" if source.parent.is_dir() else "false"
    except OSError:
        destination_parent_is_dir = "unknown"
    try:
        destination_preexisted = "true" if source.exists() else "false"
    except OSError:
        destination_preexisted = "unknown"
    try:
        subprocess.run(["git", "clone", "--quiet", "--local", str(ROOT), str(source)],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as error:
        stderr_bytes = error.stderr or b""
        stderr = stderr_bytes.decode("utf-8", errors="replace").lower()
        cause = next((label for marker, label in (
            ("not a git repository", "source is not a Git repository"),
            ("permission denied", "permission denied"),
            ("already exists", "destination already exists"),
            ("filename too long", "path length exceeded"),
            ("dubious ownership", "Git ownership check failed"),
            ("invalid cross-device link", "cross-device clone failure"),
            ("hardlink", "hardlink clone failure"),
            ("access is denied", "access denied"),
            ("no such file", "source or destination unavailable"),
            ("could not create work tree dir", "Git could not create fixture files"),
            ("unable to create", "Git could not create fixture files"),
        ) if marker in stderr), "unclassified Git clone failure")
        if cause != "unclassified Git clone failure":
            raise AssertionError(f"fixture clone failed (exit {error.returncode}; {cause})") from None
        if not stderr_bytes:
            stderr_class = "empty"
        else:
            try:
                strict_stderr = stderr_bytes.decode("utf-8")
            except UnicodeDecodeError:
                stderr_class = "utf8_invalid"
            else:
                first_nonblank = next((line.strip().lower() for line in strict_stderr.splitlines()
                                       if line.strip()), "")
                if first_nonblank.startswith("fatal:"):
                    stderr_class = "fatal_prefix"
                elif first_nonblank.startswith("error:"):
                    stderr_class = "error_prefix"
                elif first_nonblank.startswith("warning:"):
                    stderr_class = "warning_prefix"
                else:
                    stderr_class = "other_nonempty"
        raise AssertionError(
            f"fixture clone failed (exit {error.returncode}; {cause}; "
            f"source_git_metadata_present={source_git_metadata_present}; "
            f"destination_parent_is_dir={destination_parent_is_dir}; "
            f"destination_preexisted={destination_preexisted}; stderr_class={stderr_class})"
        ) from None


class MetadataProjectionTests(unittest.TestCase):
    def test_clone_fixture_reports_only_sanitized_cause(self) -> None:
        for stderr, cause in (
            (b"fatal: permission denied: PRIVATE_MARKER", "permission denied"),
            (b"fatal: detected dubious ownership in PRIVATE_MARKER", "Git ownership check failed"),
            (b"fatal: invalid cross-device link PRIVATE_MARKER", "cross-device clone failure"),
            (b"fatal: unable to create file PRIVATE_MARKER", "Git could not create fixture files"),
            (b"fatal: could not create work tree dir PRIVATE_MARKER", "Git could not create fixture files"),
            (b"fatal: could not create work tree dir PRIVATE_MARKER\xff", "Git could not create fixture files"),
        ):
            with self.subTest(cause=cause):
                error = subprocess.CalledProcessError(128, ["git"], stderr=stderr)
                with patch("subprocess.run", side_effect=error), self.assertRaises(
                    AssertionError
                ) as caught:
                    clone_fixture(Path("synthetic"))
                self.assertEqual(f"fixture clone failed (exit 128; {cause})", str(caught.exception))
                self.assertNotIn("PRIVATE_MARKER", str(caught.exception))

        error = subprocess.CalledProcessError(
            128, ["git"], stderr=b"fatal: unexpected failure PRIVATE_MARKER"
        )
        with patch("subprocess.run", side_effect=error), self.assertRaisesRegex(
            AssertionError, "exit 128; unclassified Git clone failure"
        ) as caught:
            clone_fixture(Path("synthetic"))
        self.assertNotIn("PRIVATE_MARKER", str(caught.exception))

    def test_clone_fixture_reports_sanitized_facets_for_unclassified_stderr(self) -> None:
        cases = (
            (b"", "empty", True, True, False, "file"),
            (b"PRIVATE_MARKER\xff", "utf8_invalid", False, True, True, "absent"),
            (b"\nFatal: PRIVATE_MARKER synthetic failure", "fatal_prefix", True, False, False, "directory"),
            (b"\n\nerror: PRIVATE_MARKER synthetic failure", "error_prefix", False, False, False, "absent"),
            (b"warning: PRIVATE_MARKER synthetic failure", "warning_prefix", True, True, True, "file"),
            (b"PRIVATE_MARKER", "other_nonempty", False, True, False, "absent"),
        )
        for stderr, stderr_class, git_metadata, parent_is_dir, destination_exists, git_kind in cases:
            with self.subTest(stderr_class=stderr_class):
                with tempfile.TemporaryDirectory() as temporary:
                    base = Path(temporary)
                    root = base / "source"
                    root.mkdir()
                    if git_metadata:
                        if git_kind == "directory":
                            (root / ".git").mkdir()
                        else:
                            (root / ".git").write_text("synthetic", encoding="utf-8")
                    parent = base / "destination-parent"
                    if parent_is_dir:
                        parent.mkdir()
                    destination = parent / "fixture"
                    if destination_exists:
                        destination.write_text("preexisting", encoding="utf-8")
                    error = subprocess.CalledProcessError(128, ["git"], stderr=stderr)
                    expected = (
                        "fixture clone failed (exit 128; unclassified Git clone failure; "
                        f"source_git_metadata_present={str(git_metadata).lower()}; "
                        f"destination_parent_is_dir={str(parent_is_dir).lower()}; "
                        f"destination_preexisted={str(destination_exists).lower()}; "
                        f"stderr_class={stderr_class})"
                    )
                    with patch.object(sys.modules[__name__], "ROOT", root), patch(
                        "subprocess.run", side_effect=error
                    ) as run, self.assertRaises(AssertionError) as caught:
                        clone_fixture(destination)
                    self.assertEqual(expected, str(caught.exception))
                    self.assertNotIn("PRIVATE_MARKER", str(caught.exception))
                    run.assert_called_once_with(
                        ["git", "clone", "--quiet", "--local", str(root), str(destination)],
                        check=True,
                        capture_output=True,
                    )

    def test_clone_fixture_stat_oserror_is_sanitized_and_clone_still_runs(self) -> None:
        for facet in (
            "source_git_metadata_present",
            "destination_parent_is_dir",
            "destination_preexisted",
        ):
            with self.subTest(facet=facet):
                with tempfile.TemporaryDirectory() as temporary:
                    base = Path(temporary)
                    root = base / "source"
                    root.mkdir()
                    git_metadata = root / ".git"
                    git_metadata.write_text("synthetic", encoding="utf-8")
                    parent = base / "destination-parent"
                    parent.mkdir()
                    destination = parent / "fixture"
                    error = subprocess.CalledProcessError(
                        128, ["git"], stderr=b"fatal: PRIVATE_MARKER synthetic failure"
                    )
                    real_exists = Path.exists
                    real_is_dir = Path.is_dir

                    def exists(path: Path) -> bool:
                        if facet == "source_git_metadata_present" and path == git_metadata:
                            raise OSError("PRIVATE_MARKER")
                        if facet == "destination_preexisted" and path == destination:
                            raise OSError("PRIVATE_MARKER")
                        return real_exists(path)

                    def is_dir(path: Path) -> bool:
                        if facet == "destination_parent_is_dir" and path == parent:
                            raise OSError("PRIVATE_MARKER")
                        return real_is_dir(path)

                    expected_values = {
                        "source_git_metadata_present": "unknown",
                        "destination_parent_is_dir": "unknown",
                        "destination_preexisted": "unknown",
                    }
                    with patch.object(sys.modules[__name__], "ROOT", root), patch.object(
                        Path, "exists", new=exists
                    ), patch.object(Path, "is_dir", new=is_dir), patch(
                        "subprocess.run", side_effect=error
                    ) as run, self.assertRaises(AssertionError) as caught:
                        clone_fixture(destination)
                    observed = {
                        "source_git_metadata_present": "true",
                        "destination_parent_is_dir": "true",
                        "destination_preexisted": "false",
                    }
                    observed[facet] = expected_values[facet]
                    expected = (
                        "fixture clone failed (exit 128; unclassified Git clone failure; "
                        f"source_git_metadata_present={observed['source_git_metadata_present']}; "
                        f"destination_parent_is_dir={observed['destination_parent_is_dir']}; "
                        f"destination_preexisted={observed['destination_preexisted']}; "
                        "stderr_class=fatal_prefix)"
                    )
                    self.assertEqual(expected, str(caught.exception))
                    self.assertNotIn("PRIVATE_MARKER", str(caught.exception))
                    run.assert_called_once_with(
                        ["git", "clone", "--quiet", "--local", str(root), str(destination)],
                        check=True,
                        capture_output=True,
                    )

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = importlib.util.module_from_spec(SPEC)
        sys.modules[SPEC.name] = cls.module
        SPEC.loader.exec_module(cls.module)

    @staticmethod
    def synthetic_audience_policy(module, markers: list[str]) -> dict:
        return module._validated_policy({
            "schema": module.POLICY_SCHEMA,
            "audiences": {name: {"forbidden_markers": sorted(set(markers), key=str.casefold),
                                  "security_route": {"state": "unknown", "mechanism": None}}
                          for name in module.AUDIENCES},
            "surfaces": {"tree": ["manifests", "tree", "workflows"],
                         "history": ["reachable_history"],
                         "metadata": ["comments", "issues", "pull_requests", "releases", "reviews"]},
            "export": {"mode": "byte_identical", "same_snapshot_required": True, "transformations": []},
            "literal_exceptions": [], "history_exceptions": [],
        })

    def make_empty_collection(self):
        surfaces = {name: [] for name in self.module.SURFACES}
        surfaces["pull_requests"].append({"number": 7})
        snapshot = {"schema": "engineering.audience-metadata-snapshot.v1", "audience": "source",
                    "source_commit": "a" * 40,
                    "surfaces": surfaces}
        coverage = [{"endpoint": name, "pr": None, "page": 1,
                     "item_count": 1 if name in {"repository", "pulls"} else 0, "terminal": True}
                    for name in ("repository", "issues", "pulls", "releases", "issue_comments")]
        coverage.extend({"endpoint": endpoint, "pr": 7, "page": 1,
                         "item_count": 1 if endpoint == "pull_detail" else 0, "terminal": True}
                        for endpoint in ("pull_detail", "pr_comments", "reviews"))
        coverage.append({"endpoint": "binding_readback", "pr": 7, "page": 1, "item_count": 1, "terminal": True})
        return self.module._issue_receipt(snapshot, b"synthetic response transcript", repository="org/repo",
                                          local_commit="a" * 40, remote_head="1" * 40, binding_pr=7,
                                          coverage=coverage, started_at="2026-10-02T00:00:00+00:00",
                                          completed_at="2026-10-02T00:00:01+00:00")

    def make_strict_user(self, login: str, user_id: int) -> dict:
        api = "https://api.github.com/user" + "s/" + login
        return {
            "id": user_id, "node_id": f"U{user_id}", "login": login, "type": "User",
            "site_admin": False, "avatar_url": f"https://avatars.githubusercontent.com/u/{user_id}",
            "gravatar_id": None, "url": api, "html_url": f"https://github.com/{login}",
            "followers_url": api + "/followers", "following_url": api + "/following{/other_user}",
            "gists_url": api + "/gists{/gist_id}", "starred_url": api + "/starred{/owner}{/repo}",
            "subscriptions_url": api + "/subscriptions", "organizations_url": api + "/orgs",
            "repos_url": api + "/repos", "events_url": api + "/events{/privacy}",
            "received_events_url": api + "/received_events",
        }

    def make_strict_repository(self, repository: str, repo_id: int) -> dict:
        api = f"https://api.github.com/repos/{repository}"
        tails = {
            "archive_url": "/{archive_format}{/ref}", "assignees_url": "/assignees{/user}",
            "blobs_url": "/git/blobs{/sha}", "branches_url": "/branches{/branch}",
            "collaborators_url": "/collaborators{/collaborator}", "comments_url": "/comments{/number}",
            "commits_url": "/commits{/sha}", "compare_url": "/compare/{base}...{head}",
            "contents_url": "/contents/{+path}", "contributors_url": "/contributors", "deployments_url": "/deployments",
            "downloads_url": "/downloads", "events_url": "/events", "forks_url": "/forks",
            "git_commits_url": "/git/commits{/sha}", "git_refs_url": "/git/refs{/sha}",
            "git_tags_url": "/git/tags{/sha}", "hooks_url": "/hooks", "issue_comment_url": "/issues/comments{/number}",
            "issue_events_url": "/issues/events{/number}", "issues_url": "/issues{/number}", "keys_url": "/keys{/key_id}",
            "labels_url": "/labels{/name}", "languages_url": "/languages", "merges_url": "/merges",
            "milestones_url": "/milestones{/number}", "notifications_url": "/notifications{?since,all,participating}",
            "pulls_url": "/pulls{/number}", "releases_url": "/releases{/id}", "stargazers_url": "/stargazers",
            "statuses_url": "/statuses/{sha}", "subscribers_url": "/subscribers", "subscription_url": "/subscription",
            "tags_url": "/tags", "teams_url": "/teams", "trees_url": "/git/trees{/sha}",
        }
        name = repository.split("/")[-1]
        value = {}
        for field in self.module.OPENAPI_REQUIRED_FIELDS["full-repository"]:
            if field in tails:
                value[field] = api + tails[field]
            elif field == "url":
                value[field] = api
            elif field == "html_url":
                value[field] = f"https://github.com/{repository}"
            elif field == "clone_url":
                value[field] = f"https://github.com/{repository}.git"
            elif field == "ssh_url":
                value[field] = "git" + "@github.com:" + f"{repository}.git"
            elif field == "git_url":
                value[field] = f"git://github.com/{repository}.git"
            elif field == "svn_url":
                value[field] = f"https://github.com/{repository}"
            elif field == "owner":
                value[field] = self.make_strict_user("org", repo_id + 100)
            elif field == "id":
                value[field] = repo_id
            elif field == "node_id":
                value[field] = f"R{repo_id}"
            elif field == "name":
                value[field] = name
            elif field == "full_name":
                value[field] = repository
            elif field == "default_branch":
                value[field] = "main"
            elif field in {"created_at", "updated_at", "pushed_at"}:
                value[field] = "2026-01-01T00:00:00Z"
            elif field in self.module.TOP_LEVEL_STRUCTURAL_FIELD_TYPES:
                expected = self.module.TOP_LEVEL_STRUCTURAL_FIELD_TYPES[field]
                value[field] = False if expected is bool else 0 if expected is int else "safe"
            else:
                value[field] = None
        return value

    def make_strict_pull_branch_repository(self, repository: str, repo_id: int) -> dict:
        value = self.make_strict_repository(repository, repo_id)
        # The pinned pull head/base uses Repository, which requires has_downloads but
        # does not require the full-repository-only network/subscriber counters.
        value.pop("network_count", None)
        value.pop("subscribers_count", None)
        value["has_downloads"] = False
        owner = repository.split("/", 1)[0]
        value["owner"] = self.make_strict_user(owner, repo_id + 100)
        return value

    def test_repository_embedded_simple_users_accept_user_organization_and_nested_repositories(self) -> None:
        repository = self.make_strict_repository("org/repo", 1)
        projected = self.module._project_repository(repository, "org/repo", strict_required=True)
        self.assertEqual([], projected["repository"]["topics"])

        organization = self.make_strict_user("org", 101)
        organization["type"] = "Organization"
        organization["email"] = "owner" + "@" + "example.invalid"
        repository["owner"] = organization
        repository["organization"] = dict(organization)
        projected = self.module._project_repository(repository, "org/repo", strict_required=True)
        self.assertIn("owner" + "@" + "example.invalid", projected["repository"]["nested_text"])

        nested_full = self.make_strict_repository("other/nested", 2)
        nested_required = self.module.OPENAPI_REQUIRED_FIELDS["nullable-repository"]
        nested = {field: nested_full[field] for field in nested_full
                  if field in self.module.OPENAPI_OBJECT_SCHEMAS["nullable-repository"]}
        for field in nested_required - nested.keys():
            expected = self.module.TOP_LEVEL_STRUCTURAL_FIELD_TYPES.get(field)
            nested[field] = False if expected is bool else 0 if expected is int else "safe" if expected is str else None
        nested["owner"] = self.make_strict_user("other", 102)
        repository = self.make_strict_repository("org/repo", 3)
        repository["source"] = nested
        projected = self.module._project_repository(repository, "org/repo", strict_required=True)
        self.assertEqual("nested", projected["repository"]["source"]["name"])

    def test_repository_embedded_simple_user_authored_name_and_email_reach_audit_without_identity_projection(self) -> None:
        repository = self.make_strict_repository("org/repo", 1)
        owner = repository["owner"]
        owner.update({"name": "Owner authored name", "email": "owner" + "@" + "example.invalid"})
        result = self.module._project_repository(repository, "org/repo", strict_required=True)["repository"]
        self.assertIn("Owner authored name", result["nested_text"])
        self.assertIn("owner" + "@" + "example.invalid", result["nested_text"])
        self.assertNotIn("owner", result)

    def test_repository_embedded_owner_and_organization_fail_closed_on_shape_identity_and_privacy(self) -> None:
        repository = self.make_strict_repository("org/repo", 1)
        organization = self.make_strict_user("org", 101)
        organization["type"] = "Organization"
        repository["owner"] = organization
        repository["organization"] = dict(organization)
        invalid = []
        missing_required = json.loads(json.dumps(repository))
        del missing_required["owner"]["repos_url"]
        invalid.append(missing_required)
        wrong_type = json.loads(json.dumps(repository))
        wrong_type["owner"]["id"] = True
        invalid.append(wrong_type)
        unknown = json.loads(json.dumps(repository))
        unknown["owner"]["private_email"] = "private" + "@" + "example.invalid"
        invalid.append(unknown)
        unsafe_url = json.loads(json.dumps(repository))
        unsafe_url["owner"]["url"] = "https://attacker.invalid/user" + "s/org"
        invalid.append(unsafe_url)
        cross_owner = json.loads(json.dumps(repository))
        cross_owner["owner"]["login"] = "other"
        cross_owner["owner"]["url"] = "https://api.github.com/user" + "s/" + "other"
        cross_owner["owner"]["html_url"] = "https://github.com/other"
        for field in ("followers_url", "following_url", "gists_url", "starred_url", "subscriptions_url",
                      "organizations_url", "repos_url", "events_url", "received_events_url"):
            if field in cross_owner["owner"]:
                cross_owner["owner"][field] = cross_owner["owner"][field].replace("/org", "/other", 1)
        invalid.append(cross_owner)
        user_owner = json.loads(json.dumps(repository))
        user_owner["owner"]["type"] = "User"
        invalid.append(user_owner)
        mismatched_identity = json.loads(json.dumps(repository))
        mismatched_identity["organization"]["id"] += 1
        invalid.append(mismatched_identity)
        mismatched_node = json.loads(json.dumps(repository))
        mismatched_node["organization"]["node_id"] = "O999"
        invalid.append(mismatched_node)
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(self.module.MetadataProjectionError):
                self.module._project_repository(candidate, "org/repo", strict_required=True)

    def test_repository_git_and_svn_urls_require_canonical_host_and_repository(self) -> None:
        expected = {
            "git_url": "git://github.com/org/repo.git",
            "svn_url": "https://github.com/org/repo",
        }
        for field, canonical in expected.items():
            with self.subTest(field=field, case="canonical"):
                repository = self.make_strict_repository("org/repo", 1)
                repository[field] = canonical
                self.module._project_repository(repository, "org/repo", strict_required=True)
            for replacement in (canonical.replace("github.com", "example.invalid"),
                                canonical.replace("org/repo", "org/other")):
                with self.subTest(field=field, replacement=replacement):
                    repository = self.make_strict_repository("org/repo", 1)
                    repository[field] = replacement
                    with self.assertRaises(self.module.MetadataProjectionError):
                        self.module._project_repository(repository, "org/repo", strict_required=True)

    def make_strict_pull(self, repository: str, head_sha: str, *, detail: bool) -> dict:
        api = f"https://api.github.com/repos/{repository}"
        number = 7
        web = f"https://github.com/{repository}/pull/{number}"
        values = {
            "url": f"{api}/pulls/{number}", "html_url": web, "diff_url": web + ".diff",
            "patch_url": web + ".patch", "issue_url": f"{api}/issues/{number}",
            "commits_url": f"{api}/pulls/{number}/commits", "review_comments_url": f"{api}/pulls/{number}/comments",
            "review_comment_url": f"{api}/pulls/comments{{/number}}", "comments_url": f"{api}/issues/{number}/comments",
            "statuses_url": f"{api}/statuses/{head_sha}", "number": number, "id": number,
            "node_id": "PR7", "title": "safe", "body": None, "state": "open", "locked": False,
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
            "closed_at": None, "merged_at": None, "merge_commit_sha": None, "author_association": "MEMBER",
            "auto_merge": None, "assignee": None, "labels": [], "milestone": None,
            "head": {"sha": head_sha, "ref": "topic", "label": "org:topic",
                     "user": self.make_strict_user("synthetic-user", 3),
                     "repo": self.make_strict_pull_branch_repository(repository, 1)},
            "base": {"sha": "2" * 40, "ref": "main", "label": "org:main",
                     "user": self.make_strict_user("synthetic-user", 4),
                     "repo": self.make_strict_pull_branch_repository(repository, 1)},
            "user": self.make_strict_user("synthetic-user", 2),
            "_links": {
                "self": {"href": f"{api}/pulls/{number}"}, "html": {"href": web},
                "issue": {"href": f"{api}/issues/{number}"},
                "comments": {"href": f"{api}/issues/{number}/comments"},
                "review_comments": {"href": f"{api}/pulls/{number}/comments"},
                "review_comment": {"href": f"{api}/pulls/comments{{/number}}"},
                "commits": {"href": f"{api}/pulls/{number}/commits"},
                "statuses": {"href": f"{api}/statuses/{head_sha}"},
            },
        }
        if detail:
            values.update({"merged": False, "mergeable": None, "mergeable_state": "unknown", "merged_by": None,
                           "comments": 0, "review_comments": 0, "maintainer_can_modify": False,
                           "commits": 0, "additions": 0, "deletions": 0, "changed_files": 0})
        component = "pull-request" if detail else "pull-request-simple"
        return {field: values.get(field) for field in self.module.OPENAPI_REQUIRED_FIELDS[component]}

    def test_receipt_requires_complete_page_coverage_and_explicit_empty(self) -> None:
        snapshot = {"schema": "engineering.audience-metadata-snapshot.v1", "audience": "source",
                    "source_commit": "a" * 40,
                    "surfaces": {name: [] for name in self.module.SURFACES}}
        incomplete = [{"endpoint": "issues", "pr": None, "page": 1,
                       "item_count": 0, "terminal": True}]
        self.assertIsNone(self.module._issue_receipt(
            snapshot, b"raw", repository="org/repo", local_commit="a" * 40,
            remote_head="1" * 40, binding_pr=7, coverage=incomplete,
            started_at="2026-10-02T00:00:00+00:00", completed_at="2026-10-02T00:00:01+00:00",
        ))

    def test_complete_coverage_issues_single_use_process_local_receipt(self) -> None:
        collection = self.make_empty_collection()
        self.assertTrue(self.module.verify_collection(collection, "source", "org/repo", "a" * 40, "1" * 40, 7))
        self.assertIsNotNone(self.module.consume_collection(collection, "source", "org/repo", "a" * 40, "1" * 40, 7))
        self.assertFalse(self.module.verify_collection(collection, "source", "org/repo", "a" * 40, "1" * 40, 7))

    def test_pull_coverage_item_total_must_match_snapshot_pull_numbers(self) -> None:
        collection = self.make_empty_collection()
        coverage = [dict(page) for page in collection.receipt["coverage"]]
        self.assertTrue(self.module._coverage_complete(coverage, [7], 7))

        for mismatched_count in (0, 2):
            with self.subTest(pull_item_count=mismatched_count):
                mismatched = [dict(page) for page in coverage]
                next(page for page in mismatched if page["endpoint"] == "pulls")["item_count"] = mismatched_count
                self.assertFalse(self.module._coverage_complete(mismatched, [7], 7))

    def test_receipt_issuer_has_no_caller_production_promotion_arguments(self) -> None:
        surfaces = {name: [] for name in self.module.SURFACES}
        surfaces["pull_requests"].append({"number": 7})
        snapshot = {"schema": "engineering.audience-metadata-snapshot.v1", "audience": "source",
                    "source_commit": "a" * 40, "surfaces": surfaces}
        coverage = [{"endpoint": name, "pr": None, "page": 1,
                     "item_count": 1 if name in {"repository", "pulls"} else 0, "terminal": True}
                    for name in ("repository", "issues", "pulls", "releases", "issue_comments")]
        coverage.extend({"endpoint": endpoint, "pr": 7, "page": 1,
                         "item_count": 1 if endpoint == "pull_detail" else 0, "terminal": True}
                        for endpoint in ("pull_detail", "pr_comments", "reviews"))
        coverage.append({"endpoint": "binding_readback", "pr": 7, "page": 1,
                         "item_count": 1, "terminal": True})

        transport = self.module.GitHubTransport("synthetic-account", "org/repo", lambda: "synthetic-token")
        transport._identity_verified = True
        transport.identity_transcript = b"synthetic verified identity"
        raw = b"synthetic production transcript"
        with self.assertRaises(TypeError):
            self.module._issue_receipt(
                snapshot, raw, repository="org/repo", local_commit="a" * 40,
                remote_head="a" * 40, binding_pr=7, coverage=coverage,
                started_at="2026-10-02T00:00:00+00:00", completed_at="2026-10-02T00:00:01+00:00",
                head_repository="org/repo", head_ref="topic", production_verified=True,
                transport_identity_sha256=self.module._digest(b"synthetic-account"),
                production_transport=transport,
            )

    def test_authenticated_collection_rejects_commit_mismatch_before_transport(self) -> None:
        with patch.object(self.module.GitHubTransport, "verify_identity",
                          side_effect=AssertionError("transport must not run")):
            with self.assertRaisesRegex(self.module.MetadataProjectionError, "metadata_binding_unknown"):
                self.module.collect_authenticated_metadata(
                    "source", "org/repo", "a" * 40, "1" * 40, 7,
                    "synthetic-account", "org/repo", "topic",
                )

    def test_unknown_nested_authored_field_fails_closed(self) -> None:
        value = {"title": "safe", "user": {"login": "synthetic", "description": "forbidden"}}
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.project_record("issue", value)

    def test_actor_transport_is_validated_but_unknown_actor_text_is_not_exempt(self) -> None:
        record = {"title": "safe", "user": {"login": "synthetic", "url": "https://api.github.com/us" + "ers/synthetic"}}
        projected = self.module.project_record("issue", record)
        self.assertEqual("safe", projected["title"])
        self.assertNotIn(record["user"]["url"], projected.get("nested_text", []))
        audience_spec = importlib.util.spec_from_file_location(
            "engineering_metadata_projection_actor_audience", ROOT / "tools" / "check_audience.py"
        )
        audience_module = importlib.util.module_from_spec(audience_spec)
        audience_spec.loader.exec_module(audience_module)
        policy = self.synthetic_audience_policy(audience_module, ["synthetic marker"])
        surfaces = {name: [] for name in self.module.SURFACES}
        surfaces["issues"].append(projected)
        snapshot = {"schema": "engineering.audience-metadata-snapshot.v1", "audience": "source",
                    "source_commit": "a" * 40, "surfaces": surfaces}
        self.assertEqual([], audience_module.audit_metadata(policy, snapshot, "source", "a" * 40))
        record["user"]["url"] = "https://api.github.com/us" + "ers/other"
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.project_record("issue", record)

    def test_nested_authored_text_is_retained_for_the_unchanged_content_audit(self) -> None:
        issue = self.module.project_record("issue", {
            "title": "safe", "body": None,
            "labels": [{"name": "phi" + "lips-internal/engineering-skill", "description": "ABis" + "was19/engineering-skill"}],
            "milestone": {"title": "Phil" + "ips", "description": "description"},
        }, "org/repo")
        self.assertIn("phi" + "lips-internal/engineering-skill", issue["nested_text"])
        self.assertIn("ABis" + "was19/engineering-skill", issue["nested_text"])
        self.assertIn("Phil" + "ips", issue["nested_text"])
        release = self.module.project_record("release", {
            "name": "safe", "body": None, "tag_name": "v1", "target_commitish": "main",
            "assets": [{"id": 1, "node_id": "A1", "name": "Phil" + "ips artifact", "label": "safe",
                        "state": "uploaded", "content_type": "application/octet-stream", "size": 1,
                        "digest": "sha256:" + "a" * 64, "download_count": 0,
                        "created_at": "2026-10-02T00:00:00Z", "updated_at": "2026-10-02T00:00:00Z",
                        "uploader": {"id": 11, "login": "synthetic", "type": "User"},
                        "url": "https://api.github.com/repos/org/repo/releases/assets/1",
                        "browser_download_url": "https://github.com/org/repo/releases/download/v1/Phil" + "ips%20artifact"}],
        }, "org/repo")
        self.assertIn("Phil" + "ips artifact", release["nested_text"])

    def test_repository_envelope_uses_closed_templates_and_scans_license_text(self) -> None:
        base = "https://api.github.com/repos/org/repo"
        value = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                 "url": base, "html_url": "https://github.com/org/repo", "description": None,
                 "homepage": None, "default_branch": "main", "topics": [],
                 "archive_url": base + "/{archive_format}{/ref}",
                 "notifications_url": base + "/notifications{?since,all,participating}",
                 "owner": {**self.make_strict_user("org", 2), "type": "Organization"},
                 "license": {"key": "mit", "name": "MIT License", "spdx_id": "MIT",
                             "url": "https://api.github.com/licenses/mit"}}
        projected = self.module._project_repository(value, "org/repo")
        self.assertEqual("MIT License", projected["repository"]["license"]["name"])
        bad = dict(value)
        bad["archive_url"] = base + "/{unrecognized}"
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._project_repository(bad, "org/repo")

    def test_pull_head_and_base_repository_relationship_is_checked(self) -> None:
        base_url = "https://api.github.com/repos/org/repo"
        repo = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                "url": base_url, "html_url": "https://github.com/org/repo", "description": "safe",
                "homepage": None, "default_branch": "main", "topics": []}
        pull = {"number": 7, "title": "safe", "body": None,
                "head": {"sha": "1" * 40, "ref": "topic", "label": "org:topic", "repo": repo},
                "base": {"sha": "2" * 40, "ref": "main", "label": "org:main", "repo": repo}}
        projected = self.module._project_pull(pull, "org/repo")
        self.assertIn("safe", projected["nested_text"])
        pull["base"]["repo"] = dict(repo, full_name="other/repo")
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._project_pull(pull, "org/repo")

    def test_every_supported_surface_still_reaches_marker_and_personal_path_scanner(self) -> None:
        audience_spec = importlib.util.spec_from_file_location(
            "engineering_metadata_projection_audience", ROOT / "tools" / "check_audience.py"
        )
        audience_module = importlib.util.module_from_spec(audience_spec)
        audience_spec.loader.exec_module(audience_module)
        marker = "ABis" + "was19/engineering-skill"
        policy = self.synthetic_audience_policy(audience_module, [marker])
        personal_path = "C:" + chr(92) + "Us" + "ers" + chr(92) + "fixture" + chr(92) + "x"
        cases = [
            ("issue", {"title": marker, "labels": [{"name": "safe", "description": personal_path}]}),
            ("pull", {"title": "safe", "body": personal_path, "head": {"sha": "1" * 40, "ref": marker}}),
            ("release", {"name": marker, "tag_name": "v1", "assets": [{
                "id": 1, "node_id": "A1", "name": personal_path, "label": marker, "state": "uploaded",
                "content_type": "application/octet-stream", "size": 1, "digest": None, "download_count": 0,
                "created_at": "2026-10-02T00:00:00Z", "updated_at": "2026-10-02T00:00:00Z",
                "uploader": {"id": 12, "login": "synthetic", "type": "User"},
                "url": "https://api.github.com/repos/org/repo/releases/assets/1",
                "browser_download_url": ("https://github.com/org/repo/releases/download/v1/C%3A%5CUs" +
                                          "ers%5Cfixture%5Cx"),
            }]}),
            ("comment", {"body": marker, "diff_hunk": personal_path, "path": "safe.py"}),
            ("review", {"body": marker + " " + personal_path}),
        ]
        for kind, record in cases:
            with self.subTest(kind=kind):
                projected = (self.module._project_pull(record, "org/repo") if kind == "pull"
                             else self.module.project_record(kind, record, "org/repo"))
                surfaces = {name: [] for name in self.module.SURFACES}
                surface = {"issue": "issues", "pull": "pull_requests", "release": "releases",
                           "comment": "comments", "review": "reviews"}[kind]
                surfaces[surface].append(projected)
                snapshot = {"schema": "engineering.audience-metadata-snapshot.v1", "audience": "source",
                            "source_commit": "a" * 40, "surfaces": surfaces}
                blockers = audience_module.audit_metadata(policy, snapshot, "source", "a" * 40)
                self.assertIn("metadata_marker_crossflow", blockers)
                self.assertIn("metadata_personal_path", blockers)

    def test_generated_url_requires_expected_repository_route(self) -> None:
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.validate_transport_url(
                "html_url", "https://github.com/other/repo/issues/1", "org/repo", 1
            )

    def test_issue_labels_url_allows_only_exact_terminal_name_template(self) -> None:
        expected = "https://api.github.com/repos/org/repo/issues/7/labels{/name}"
        self.assertTrue(self.module.validate_transport_url(
            "labels_url", expected, "org/repo", pr_number=7, schema_endpoint="issues"
        ))
        invalid = (
            (expected, "org/repo", None),
            (expected.replace("api.github.com", "example.com"), "org/repo", 7),
            (expected.replace("/org/repo/", "/other/repo/"), "org/repo", 7),
            (expected.replace("/issues/7/", "/milestones/7/"), "org/repo", 7),
            (expected.replace("{/name}", "{/type}"), "org/repo", 7),
            (expected.replace("{/name}", "{/name}{/extra}"), "org/repo", 7),
            (expected + "?page=1", "org/repo", 7),
            (expected + "#labels", "org/repo", 7),
            (expected.replace("/issues/7/", "/issues/8/"), "org/repo", 7),
            (expected.replace("{/name}", "{/other}"), "org/repo", 7),
        )
        for value, repository, number in invalid:
            with self.subTest(value=value), self.assertRaises(self.module.MetadataProjectionError):
                self.module.validate_transport_url(
                    "labels_url", value, repository, pr_number=number, schema_endpoint="issues"
                )

    def test_transport_url_rejects_encoded_path_tricks_and_userinfo(self) -> None:
        for value in (
            "https://user" + "@" + "github.com/org/repo/issues/1",
            "https://github.com/org/repo%2fother/issues/1",
            "https://github.com/org/repo/%252fissues/1",
            "https://github.com/org/repo/../other/issues/1",
        ):
            with self.subTest(value=value), self.assertRaises(self.module.MetadataProjectionError):
                self.module.validate_transport_url("html_url", value, "org/repo", 1)

    def test_exact_object_url_branches_reject_userinfo_and_nondefault_ports(self) -> None:
        bad_issue = "https://secret" + "@api.github.com:444/repos/org/repo/issues/7"
        bad_pull = "https://secret" + "@github.com:444/org/repo/pull/7"
        explicit_default_port = "https://api.github.com:443/repos/org/repo/issues/7"
        for field, value, kind in (("url", bad_issue, "issue"), ("html_url", bad_pull, "pull"),
                                   ("html_url", "https://github.com/org/repo/pull/7?token=secret", "pull"),
                                   ("url", explicit_default_port, "issue")):
            with self.subTest(field=field), self.assertRaises(self.module.MetadataProjectionError):
                self.module.validate_transport_url(field, value, "org/repo", pr_number=7, object_kind=kind)

    def test_top_level_statuses_url_binds_to_pull_head_sha(self) -> None:
        api = "https://api.github.com/repos/org/repo"
        head_sha = "a" * 40
        self.module.project_record("pull", {"number": 7, "statuses_url": api + "/statuses/" + head_sha},
                                   "org/repo", head_sha=head_sha)
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.project_record("pull", {"number": 7, "statuses_url": api + "/statuses/" + "b" * 40},
                                       "org/repo", head_sha=head_sha)

    def test_issue_state_is_enum_checked_before_structural_projection(self) -> None:
        self.module.project_record("issue", {"state": "open"}, "org/repo")
        personal_path = "C:" + chr(92) + "Users" + chr(92) + "fixture"
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.project_record("issue", {"state": personal_path}, "org/repo")

    def test_organization_description_and_team_permission_reach_authored_audit(self) -> None:
        marker = "ABis" + "was19/engineering-skill"
        actor = self.make_strict_user("org", 2)
        actor.update({"type": "Organization", "name": marker + " name",
                      "email": "owner" + "@" + "example.invalid"})
        for kind, record, field in (
            ("issue", {"title": "safe", "user": actor}, "user"),
            ("comment", {"body": "safe", "user": actor}, "user"),
            ("pull", {"title": "safe", "user": actor}, "user"),
            ("release", {"name": "safe", "author": actor}, "author"),
            ("review", {"body": "safe", "user": actor}, "user"),
        ):
            with self.subTest(kind=kind, field=field):
                projected = self.module.project_record(kind, record, "org/repo")
                self.assertIn(marker + " name", projected["nested_text"])
                self.assertIn("owner" + "@" + "example.invalid", projected["nested_text"])

        organization_profile = {"id": 2, "node_id": "O2", "login": "org", "type": "Organization",
                                "description": marker, "url": "https://api.github.com/orgs/org",
                                "html_url": "https://github.com/org"}
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.project_record("issue", {"title": "safe", "user": organization_profile}, "org/repo")
        team = {"id": 3, "node_id": "T3", "organization_id": 2, "slug": "maintainers",
                "name": "maintainers", "description": None, "permission": marker,
                "privacy": "closed", "notification_setting": "notifications_enabled",
                "type": "organization", "url": "https://api.github.com/organizations/2/team/3",
                "members_url": "https://api.github.com/organizations/2/team/3/members{/member}",
                "repositories_url": "https://api.github.com/organizations/2/team/3/repos",
                "html_url": "https://github.com/orgs/org/teams/maintainers"}
        pull = self.module.project_record("pull", {"title": "safe", "requested_teams": [team]}, "org/repo")
        self.assertIn(marker, pull["nested_text"])

    def test_repository_organization_description_reaches_authored_audit(self) -> None:
        marker = "ABis" + "was19/engineering-skill"
        organization = self.make_strict_user("org", 2)
        organization.update({"type": "Organization", "name": marker + " name",
                              "email": "owner" + "@" + "example.invalid"})
        repository = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo",
                      "private": True, "url": "https://api.github.com/repos/org/repo",
                      "html_url": "https://github.com/org/repo", "owner": organization,
                      "organization": dict(organization)}
        projected = self.module._project_repository(repository, "org/repo")["repository"]
        self.assertIn(marker + " name", projected["nested_text"])
        self.assertIn("owner" + "@" + "example.invalid", projected["nested_text"])
        bad_organization = {**organization, "description": marker + " org-only"}
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._project_repository({**repository, "organization": bad_organization}, "org/repo")

    def test_root_repository_name_reaches_authored_content_scan(self) -> None:
        marker = "ABis" + "was19/engineering-skill"
        base = "https://api.github.com/repos/org/repo"
        repository = self.make_strict_repository("org/repo", 1)
        repository["name"] = marker
        head_sha = "1" * 40
        summary = self.make_strict_pull("org/repo", head_sha, detail=False)
        detail = self.make_strict_pull("org/repo", head_sha, detail=True)
        responses = {
            base: repository,
            f"{base}/issues?state=all&per_page=100": [],
            f"{base}/pulls?state=all&per_page=100": [summary],
            f"{base}/pulls/7": detail,
            f"{base}/releases?per_page=100": [],
            f"{base}/issues/comments?per_page=100": [],
            f"{base}/pulls/7/comments?per_page=100": [],
            f"{base}/pulls/7/reviews?per_page=100": [],
        }

        def fetch(url: str):
            return 200, {}, json.dumps(responses[url]).encode("utf-8")

        collection = self.module.collect_metadata("source", "org/repo", "a" * 40, head_sha, 7, fetch)
        projected = collection.snapshot["surfaces"]["issues"][-1]
        self.assertIn(marker, self.module._text_leaves(projected))
        self.assertIn("org/repo", self.module._text_leaves(projected))
        repository["full_name"] = "org/other"
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._project_repository(repository, "org/repo", include_identity_text=True)

    def test_all_top_level_schemas_reject_null_or_wrong_typed_structural_values(self) -> None:
        components = {"repository": "full-repository", "issues": "issue", "pulls": "pull-request-simple",
                      "pull_detail": "pull-request", "releases": "release", "issue_comments": "issue-comment",
                      "pr_comments": "pull-request-review-comment", "reviews": "pull-request-review"}
        self.assertEqual(set(self.module.ENDPOINT_SCHEMAS), set(components))
        for endpoint, component in components.items():
            required = self.module.OPENAPI_REQUIRED_FIELDS[component]
            fields = required & set(self.module.TOP_LEVEL_STRUCTURAL_FIELD_TYPES)
            with self.subTest(endpoint=endpoint):
                self.assertTrue(fields)
                for field in fields:
                    if field not in self.module.TOP_LEVEL_NULLABLE_STRUCTURAL_FIELDS[component]:
                        with self.subTest(field=field), self.assertRaises(self.module.MetadataProjectionError):
                            self.module._validate_required_structural_fields(component, {field: None})
                    else:
                        self.module._validate_required_structural_fields(component, {field: None})
                    expected = self.module.TOP_LEVEL_STRUCTURAL_FIELD_TYPES[field]
                    wrong = [] if expected is str else "wrong-type"
                    with self.subTest(field=field, wrong=wrong), self.assertRaises(self.module.MetadataProjectionError):
                        self.module._validate_required_structural_fields(component, {field: wrong})

    def test_organization_simple_user_authored_name_email_are_audited_and_org_only_fields_rejected(self) -> None:
        marker = "ABis" + "was19/engineering-skill"
        organization = self.make_strict_user("org", 2)
        organization.update({"type": "Organization", "name": marker + " name",
                             "email": "safe" + "@" + "example.invalid"})
        projected = self.module.project_record("issue", {"title": "safe", "user": organization}, "org/repo")
        self.assertIn(organization["name"], projected["nested_text"])
        self.assertIn(organization["email"], projected["nested_text"])
        for field in ("description", "company", "blog", "location", "twitter_username"):
            with self.subTest(field=field), self.assertRaises(self.module.MetadataProjectionError):
                self.module.project_record(
                    "issue", {"title": "safe", "user": {**organization, field: marker + " org-only"}}, "org/repo")

    def test_code_of_conduct_urls_bind_to_canonical_catalogue_and_repository_routes(self) -> None:
        repository = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                      "url": "https://api.github.com/repos/org/repo", "html_url": "https://github.com/org/repo",
                      "default_branch": "main", "code_of_conduct": {
                          "url": "https://api.github.com/codes_of_conduct/contributor_covenant",
                          "key": "contributor_covenant", "name": "Contributor Covenant",
                          "html_url": "https://github.com/org/repo/blob/main/CODE_OF_CONDUCT.md"}}
        self.module._project_repository(repository, "org/repo")
        for field, bad in (("url", "https://api.github.com/codes_of_conduct/other"),
                           ("url", "https://secret" + "@api.github.com:444/codes_of_conduct/contributor_covenant"),
                           ("html_url", "https://github.com/other/repo/blob/main/CODE_OF_CONDUCT.md")):
            candidate = {**repository, "code_of_conduct": {**repository["code_of_conduct"], field: bad}}
            with self.subTest(field=field), self.assertRaises(self.module.MetadataProjectionError):
                self.module._project_repository(candidate, "org/repo")

    def test_cli_collects_both_authenticated_receipts_before_export(self) -> None:
        spec = importlib.util.spec_from_file_location("engineering_public_export_cli_test", ROOT / "tools" / "export_public.py")
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)
        source_commit, distribution_commit = "a" * 40, "b" * 40
        source_collection, distribution_collection = object(), object()
        calls = []

        class Collector:
            @staticmethod
            def collect_authenticated_metadata(*args):
                calls.append(args)
                return source_collection if args[0] == "source" else distribution_collection

        exported = {}
        with patch.object(exporter, "_metadata_module", return_value=Collector), \
                patch.object(exporter, "_origin_repository", side_effect=["internal/engineering", "public/engineering"]), \
                patch.object(exporter, "_source_commit", side_effect=[source_commit, distribution_commit]), \
                patch.object(exporter, "export_tree", side_effect=lambda *a, **kw: exported.update(args=a, kwargs=kw) or
                             {"publication_ready": True, "blockers": []}), \
                patch.object(sys, "argv", ["export-public", "source", "destination", "--verified-account", "synthetic-user",
                                            "--source-pr", "7", "--source-head", source_commit,
                                            "--source-head-repository", "internal/engineering", "--source-head-ref", "topic",
                                            "--distribution-pr", "15", "--distribution-head", distribution_commit,
                                            "--distribution-head-repository", "public/engineering", "--distribution-head-ref", "main"]), \
                patch("sys.stdout", new_callable=__import__("io").StringIO):
            self.assertEqual(0, exporter.main())
        self.assertEqual([
            ("source", "internal/engineering", source_commit, source_commit, 7, "synthetic-user", "internal/engineering", "topic"),
            ("distribution", "public/engineering", distribution_commit, distribution_commit, 15, "synthetic-user", "public/engineering", "main"),
        ], calls)
        self.assertIs(exported["kwargs"]["metadata"]["source"], source_collection)
        self.assertIs(exported["kwargs"]["metadata"]["distribution"], distribution_collection)

    def test_cli_rejects_partial_metadata_binding_before_collection_or_export(self) -> None:
        spec = importlib.util.spec_from_file_location("engineering_public_export_partial_cli_test", ROOT / "tools" / "export_public.py")
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)
        collector = type("Collector", (), {"collect_authenticated_metadata": staticmethod(lambda *_args: self.fail("must not collect"))})
        with patch.object(exporter, "_metadata_module", return_value=collector), \
                patch.object(exporter, "export_tree", side_effect=lambda *_a, **_k: self.fail("must not export")), \
                patch.object(sys, "argv", ["export-public", "source", "destination", "--verified-account", "synthetic-user",
                                            "--source-pr", "7"]), \
                patch("sys.stdout", new_callable=__import__("io").StringIO):
            self.assertEqual(2, exporter.main())

    def test_organization_urls_reject_userinfo_and_any_explicit_port(self) -> None:
        for url in ("https://secret" + "@api.github.com:444/orgs/org",
                    "https://api.github.com:443/orgs/org"):
            organization = {"id": 2, "node_id": "O2", "login": "org", "url": url}
            with self.subTest(url=url), self.assertRaises(self.module.MetadataProjectionError):
                self.module._validate_organization(organization)

    def test_security_reviewer_requires_schema_required_identity_fields(self) -> None:
        repository = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                      "url": "https://api.github.com/repos/org/repo", "html_url": "https://github.com/org/repo",
                      "security_and_analysis": {"secret_scanning_delegated_bypass_options": {"reviewers": [{}]}}}
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._project_repository(repository, "org/repo")

    def test_secret_scanning_validity_checks_is_optional_closed_and_not_projected(self) -> None:
        repository = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                      "url": "https://api.github.com/repos/org/repo", "html_url": "https://github.com/org/repo"}
        absent = self.module._project_repository(repository, "org/repo")["repository"]
        self.assertNotIn("security_and_analysis", absent)
        for status in ("enabled", "disabled"):
            with self.subTest(status=status):
                candidate = {**repository, "security_and_analysis": {
                    "secret_scanning_validity_checks": {"status": status}}}
                projected = self.module._project_repository(candidate, "org/repo")["repository"]
                self.assertNotIn("security_and_analysis", projected)
                self.assertNotIn(status, projected.get("nested_text", []))
        for setting in (None, "enabled", [], {}, {"status": True}, {"status": "not_set"},
                        {"status": "enabled", "extra": "ignored"}):
            with self.subTest(setting_type=type(setting).__name__), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_repository(
                    {**repository, "security_and_analysis": {"secret_scanning_validity_checks": setting}},
                    "org/repo",
                )
        for feature in ("unknown_feature",):
            with self.subTest(feature=feature), self.assertRaises(self.module.MetadataProjectionError):
                self.module._project_repository(
                    {**repository, "security_and_analysis": {feature: {"status": "enabled"}}}, "org/repo"
                )

    def test_full_pull_projection_validates_head_base_before_reduced_projection(self) -> None:
        base = "https://api.github.com/repos/org/repo"
        sha = "a" * 40
        user_api = "https://api.github.com/us" + "ers/synthetic"
        user = {"id": 2, "node_id": "U2", "login": "synthetic", "avatar_url": "https://avatars.githubusercontent.com/u/2",
                "events_url": user_api + "/events{/privacy}", "followers_url": user_api + "/followers",
                "following_url": user_api + "/following{/other_user}", "gists_url": user_api + "/gists{/gist_id}",
                "gravatar_id": None, "html_url": "https://github.com/synthetic", "organizations_url": user_api + "/orgs",
                "received_events_url": user_api + "/received_events", "repos_url": user_api + "/repos",
                "site_admin": False, "starred_url": user_api + "/starred{/owner}{/repo}",
                "subscriptions_url": user_api + "/subscriptions", "type": "User", "url": user_api}
        links = {"self": {"href": base + "/pulls/7"}, "html": {"href": "https://github.com/org/repo/pull/7"},
                 "issue": {"href": base + "/issues/7"}, "comments": {"href": base + "/issues/7/comments"},
                 "review_comments": {"href": base + "/pulls/7/comments"}, "review_comment": {"href": base + "/pulls/comments{/number}"},
                 "commits": {"href": base + "/pulls/7/commits"}, "statuses": {"href": base + "/statuses/" + sha}}
        branch_actor = self.make_strict_user("branchorg", 8)
        branch_actor["type"] = "Organization"
        branch_actor["name"] = "authored branch organization name"
        branch_actor["email"] = "authored-branch" + "@" + "example.invalid"
        head_repository = self.make_strict_pull_branch_repository("fork/repo", 2)
        head_repository["description"] = "fork repository authored description"
        base_repository = self.make_strict_pull_branch_repository("org/repo", 1)
        base_repository["description"] = "base repository authored description"
        pull = {"url": base + "/pulls/7", "id": 7, "node_id": "PR7", "html_url": "https://github.com/org/repo/pull/7",
                "diff_url": "https://github.com/org/repo/pull/7.diff", "patch_url": "https://github.com/org/repo/pull/7.patch",
                "issue_url": base + "/issues/7", "commits_url": base + "/pulls/7/commits",
                "review_comments_url": base + "/pulls/7/comments", "review_comment_url": base + "/pulls/comments{/number}",
                "comments_url": base + "/issues/7/comments", "statuses_url": base + "/statuses/" + sha,
                "number": 7, "state": "open", "locked": False, "title": "safe", "user": user, "body": None,
                "labels": [], "milestone": None, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
                "closed_at": None, "merged_at": None, "merge_commit_sha": None, "assignee": None,
                "head": {"sha": sha, "ref": "topic", "label": "fork:topic", "user": branch_actor,
                         "repo": head_repository},
                "base": {"sha": "b" * 40, "ref": "main", "label": "org:main", "user": dict(branch_actor),
                         "repo": base_repository}, "_links": links,
                "author_association": "MEMBER", "auto_merge": None, "merged": False, "mergeable": None,
                "mergeable_state": "unknown", "merged_by": None, "comments": 0, "review_comments": 0,
                "maintainer_can_modify": False, "commits": 0, "additions": 0, "deletions": 0, "changed_files": 0}
        projected = self.module._project_pull(pull, "org/repo", strict_required=True)
        self.assertIn("authored branch organization name", projected["nested_text"])
        self.assertIn("authored-branch" + "@" + "example.invalid", projected["nested_text"])
        self.assertIn("fork repository authored description", projected["nested_text"])
        self.assertIn("base repository authored description", projected["nested_text"])

        simple_pull = {key: value for key, value in pull.items() if key not in {
            "merged", "mergeable", "rebaseable", "mergeable_state", "merged_by", "comments",
            "review_comments", "maintainer_can_modify", "commits", "additions", "deletions", "changed_files",
        }}
        simple_projection = self.module._project_pull(
            simple_pull, "org/repo", schema_component="pull-request-simple", strict_required=True)
        self.assertIn("authored branch organization name", simple_projection["nested_text"])
        self.assertIn("authored-branch" + "@" + "example.invalid", simple_projection["nested_text"])
        for branch in ("head", "base"):
            nullable_simple = {**simple_pull, branch: {**simple_pull[branch], "user": None}}
            self.module._project_pull(nullable_simple, "org/repo", schema_component="pull-request-simple",
                                      strict_required=True)

        for branch in ("head", "base"):
            for required_key in ("label", "ref", "sha", "user", "repo"):
                incomplete = {**pull, branch: {key: value for key, value in pull[branch].items()
                                                if key != required_key}}
                with self.subTest(branch=branch, case=f"missing {required_key}"), self.assertRaises(
                        self.module.MetadataProjectionError):
                    self.module._project_pull(incomplete, "org/repo", strict_required=True)
            with self.subTest(branch=branch, case="null branch object"), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_pull({**pull, branch: None}, "org/repo", strict_required=True)
            wrong_sha_type = {**pull, branch: {**pull[branch], "sha": 10 ** 39}}
            with self.subTest(branch=branch, case="branch SHA wire type"), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_pull(wrong_sha_type, "org/repo", strict_required=True)
            for field, invalid_repo in (
                ("missing", {key: value for key, value in pull[branch].items() if key != "repo"}),
                ("null", {**pull[branch], "repo": None}),
                ("wrong_type", {**pull[branch], "repo": []}),
            ):
                malformed = {**pull, branch: invalid_repo}
                with self.subTest(branch=branch, case=f"repo {field}"), self.assertRaises(
                        self.module.MetadataProjectionError):
                    self.module._project_pull(malformed, "org/repo", strict_required=True)
            wrong_target_repo = self.make_strict_pull_branch_repository("elsewhere/repo", 3)
            malformed_base = {**pull, "base": {**pull["base"], "label": "elsewhere:main",
                                                 "repo": wrong_target_repo}}
            with self.subTest(branch=branch, case="base target binding"), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_pull(malformed_base, "org/repo", strict_required=True)
            invalid_repo = {**pull[branch]["repo"], "unexpected": "unsafe"}
            malformed_repo = {**pull, branch: {**pull[branch], "repo": invalid_repo}}
            with self.subTest(branch=branch, case="unknown repo property"), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_pull(malformed_repo, "org/repo", strict_required=True)
            invalid_repo_type = {**pull[branch]["repo"], "private": "true"}
            malformed_type = {**pull, branch: {**pull[branch], "repo": invalid_repo_type}}
            with self.subTest(branch=branch, case="repo property type"), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_pull(malformed_type, "org/repo", strict_required=True)
            bad_repo_url = {**pull[branch]["repo"], "url": "https://api.github.com/repos/other/repo"}
            malformed_url = {**pull, branch: {**pull[branch], "repo": bad_repo_url}}
            with self.subTest(branch=branch, case="repo URL identity"), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_pull(malformed_url, "org/repo", strict_required=True)
            bad_owner = {**pull[branch]["repo"],
                         "owner": {**pull[branch]["repo"]["owner"], "login": "other"}}
            malformed_owner = {**pull, branch: {**pull[branch], "repo": bad_owner}}
            with self.subTest(branch=branch, case="repo owner identity"), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_pull(malformed_owner, "org/repo", strict_required=True)
            wrong_label = {**pull, branch: {**pull[branch], "label": "wrong:topic"}}
            with self.subTest(branch=branch, case="fork label binding"), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_pull(wrong_label, "org/repo", strict_required=True)
            missing_user = {**pull, branch: {key: value for key, value in pull[branch].items() if key != "user"}}
            with self.subTest(branch=branch, case="missing required user"), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_pull(missing_user, "org/repo", strict_required=True)
            null_detail_user = {**pull, branch: {**pull[branch], "user": None}}
            with self.subTest(branch=branch, case="detail user is not nullable"), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module._project_pull(null_detail_user, "org/repo", strict_required=True)
            for field, bad_value in (("id", "8"), ("unexpected", "unsafe"),
                                      ("url", "https://api.github.com/user" + "s/" + "other"),
                                     ("html_url", "https://github.com/other")):
                bad_actor = {**branch_actor, field: bad_value}
                malformed = {**pull, branch: {**pull[branch], "user": bad_actor}}
                with self.subTest(branch=branch, field=field), self.assertRaises(
                        self.module.MetadataProjectionError):
                    self.module._project_pull(malformed, "org/repo", strict_required=True)

    def test_pull_request_simple_accepts_nullable_and_organization_branch_users(self) -> None:
        actor = self.make_strict_user("branchorg", 8)
        actor["type"] = "Organization"
        actor["name"] = "authored branch organization name"
        actor["email"] = "authored-branch" + "@" + "example.invalid"

        for head_user, base_user in ((actor, actor), (None, actor), (actor, None), (None, None)):
            pull = {"head": {"sha": "a" * 40, "ref": "topic", "user": head_user,
                             "repo": self.make_strict_pull_branch_repository("fork/repo", 2)},
                    "base": {"sha": "b" * 40, "ref": "main", "user": base_user,
                             "repo": self.make_strict_pull_branch_repository("org/repo", 1)}}
            with self.subTest(head_is_null=head_user is None, base_is_null=base_user is None):
                projected = self.module._project_pull(
                    pull, "org/repo", schema_component="pull-request-simple")
                if head_user is not None or base_user is not None:
                    self.assertIn("authored branch organization name", projected["nested_text"])

    def test_mocked_collector_covers_all_surfaces_and_pr_endpoints(self) -> None:
        base = "https://api.github.com/repos/org/repo"
        repo = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                "url": base, "html_url": "https://github.com/org/repo", "description": None,
                "homepage": None, "topics": [], "default_branch": "main"}
        pr = {"id": 7, "number": 7, "title": "safe", "body": None,
              "head": {"sha": "1" * 40, "ref": "topic", "label": "org:topic", "repo": repo},
              "base": {"sha": "2" * 40, "ref": "main", "label": "org:main", "repo": repo},
              "url": f"{base}/pulls/7", "html_url": "https://github.com/org/repo/pull/7"}
        responses = {
            "https://api.github.com/user": {"login": "synthetic-account"},
            f"{base}": {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo",
                         "private": True, "description": None, "homepage": None, "topics": [],
                         "default_branch": "main", "url": base, "html_url": "https://github.com/org/repo"},
            f"{base}/issues?state=all&per_page=100": [
                {"number": 4, "title": "safe issue", "body": None,
                 "url": f"{base}/issues/4", "html_url": "https://github.com/org/repo/issues/4"},
                {"number": 7, "title": "safe pull issue", "body": None,
                 "url": f"{base}/issues/7", "html_url": "https://github.com/org/repo/pull/7",
                 "pull_request": {"url": f"{base}/pulls/7", "html_url": "https://github.com/org/repo/pull/7",
                                  "diff_url": "https://github.com/org/repo/pull/7.diff",
                                  "patch_url": "https://github.com/org/repo/pull/7.patch", "merged_at": None}},
            ],
            f"{base}/pulls?state=all&per_page=100": [pr],
            f"{base}/pulls/7": pr,
            f"{base}/releases?per_page=100": [],
            f"{base}/issues/comments?per_page=100": [],
            f"{base}/pulls/7/comments?per_page=100": [],
            f"{base}/pulls/7/reviews?per_page=100": [],
        }
        calls = []

        class Response:
            status = 200
            headers = {}
            def __init__(self, body): self.body = body
            def read(self, limit): return self.body[:limit]
            def __enter__(self): return self
            def __exit__(self, *_args): return False

        class Opener:
            def open(self, request, timeout):
                self_outer.assertEqual(20, timeout)
                self_outer.assertEqual("GET", request.method)
                self_outer.assertEqual("application/vnd.github+json", request.get_header("Accept"))
                self_outer.assertEqual("2022-11-28", request.get_header("X-github-api-version"))
                self_outer.assertEqual("Bearer synthetic-token", request.get_header("Authorization"))
                url = request.full_url
                calls.append(url)
                return Response(json.dumps(responses[url]).encode("utf-8"))

        self_outer = self
        transport = self.module.GitHubTransport("synthetic-account", "org/repo", lambda: "synthetic-token")
        transport._opener = Opener()

        injected = self.module.collect_metadata(
            "source", "org/repo", "1" * 40, "1" * 40, 7, transport,
            head_repository="org/repo", head_ref="topic",
        )
        self.assertFalse(injected.production_verified)
        self.assertTrue(self.module.verify_collection(
            injected, "source", "org/repo", "1" * 40, "1" * 40, 7,
            head_repository="org/repo", head_ref="topic",
        ))
        self.assertFalse(self.module.verify_collection(
            injected, "source", "org/repo", "1" * 40, "1" * 40, 7,
            head_repository="org/repo", head_ref="topic", require_production=True,
        ))
        calls.clear()
        with patch.object(self.module.GitHubTransport, "gh_token_provider", return_value=lambda: "synthetic-token"), \
                patch.object(self.module.urllib.request, "build_opener", return_value=Opener()):
            with self.assertRaisesRegex(self.module.MetadataProjectionError, "metadata_schema_unknown"):
                self.module.collect_authenticated_metadata(
                    "source", "org/repo", "1" * 40, "1" * 40, 7,
                    "synthetic-account", "org/repo", "topic",
                )
        self.assertEqual(["https://api.github.com/user", base], calls)
        calls.clear()

        def fetch(url: str):
            calls.append(url)
            return 200, {}, json.dumps(responses[url]).encode("utf-8")

        collection = self.module.collect_metadata("source", "org/repo", "a" * 40, "1" * 40, 7, fetch)
        self.assertIsNotNone(collection)
        self.assertEqual(9, len(calls))
        self.assertFalse(collection.production_verified)
        self.assertFalse(self.module.verify_collection(collection, "source", "org/repo", "a" * 40, "1" * 40, 7,
                                                       head_repository=None, head_ref=None, require_production=True))
        self.assertEqual([], collection.snapshot["surfaces"]["releases"])
        self.assertEqual([], collection.snapshot["surfaces"]["reviews"])
        issue_rows = [row for row in collection.snapshot["surfaces"]["issues"] if "number" in row]
        self.assertEqual([4, 7], [row["number"] for row in issue_rows])
        self.assertEqual("safe pull issue", next(row["title"] for row in issue_rows if row["number"] == 7))
        self.assertEqual([7], [row["number"] for row in collection.snapshot["surfaces"]["pull_requests"]])
        self.assertTrue(any(page["endpoint"] == "binding_readback" and page["pr"] == 7
                            for page in collection.receipt["coverage"]))
        self.assertTrue(any(page["endpoint"] == "releases" and page["verified_empty"]
                            for page in collection.receipt["coverage_summary"]))
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.collect_metadata("source", "org/repo", "a" * 40, "2" * 40, 7, fetch)
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.collect_metadata("source", "org/repo", "a" * 40, "1" * 40, 7, fetch,
                                         head_repository="other/repo", head_ref="topic")

    def test_mocked_collector_fails_closed_on_unknown_nested_schema(self) -> None:
        base = "https://api.github.com/repos/org/repo"
        responses = {
            base: {"id": 1, "name": "repo", "full_name": "org/repo", "unexpected": "synthetic"},
        }

        def fetch(url: str):
            return 200, {}, json.dumps(responses[url]).encode("utf-8")

        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.collect_metadata("source", "org/repo", "a" * 40, "1" * 40, 7, fetch)

    def test_export_wrapper_accepts_only_bound_collector_capabilities(self) -> None:
        export_spec = importlib.util.spec_from_file_location(
            "engineering_public_export_metadata_test", ROOT / "tools" / "export_public.py"
        )
        exporter = importlib.util.module_from_spec(export_spec)
        export_spec.loader.exec_module(exporter)
        base = "https://api.github.com/repos/org/repo"
        responses = {}

        def strict_responses(head_sha: str) -> dict:
            summary = self.make_strict_pull("org/repo", head_sha, detail=False)
            detail = self.make_strict_pull("org/repo", head_sha, detail=True)
            return {
                "https://api.github.com/user": self.make_strict_user("synthetic-account", 99),
                base: self.make_strict_repository("org/repo", 1),
                f"{base}/issues?state=all&per_page=100": [],
                f"{base}/pulls?state=all&per_page=100": [summary],
                f"{base}/pulls/7": detail,
                f"{base}/releases?per_page=100": [],
                f"{base}/issues/comments?per_page=100": [],
                f"{base}/pulls/7/comments?per_page=100": [],
                f"{base}/pulls/7/reviews?per_page=100": [],
            }

        class Response:
            status = 200
            headers = {}
            def __init__(self, body): self.body = body
            def read(self, limit): return self.body[:limit]
            def __enter__(self): return self
            def __exit__(self, *_args): return False

        class Opener:
            def open(self, request, timeout):
                self_outer.assertEqual(20, timeout)
                self_outer.assertEqual("GET", request.method)
                self_outer.assertEqual("application/vnd.github+json", request.get_header("Accept"))
                self_outer.assertEqual("2022-11-28", request.get_header("X-github-api-version"))
                return Response(json.dumps(responses[request.full_url]).encode("utf-8"))

        self_outer = self

        def injected_transport():
            transport = self.module.GitHubTransport("synthetic-account", "org/repo", lambda: "synthetic-token")
            transport._opener = Opener()
            return transport

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            destination = Path(temporary) / "distribution"
            clone_fixture(source)
            subprocess.run(["git", "-C", str(source), "remote", "set-url", "origin",
                            "https://github.com/org/repo.git"], check=True, capture_output=True)
            subprocess.run(["git", "init", "--initial-branch=main", str(destination)], check=True,
                           capture_output=True)
            subprocess.run(["git", "-C", str(destination), "config", "user.name", "Synthetic"], check=True)
            subprocess.run(["git", "-C", str(destination), "config", "user.email", "synthetic"], check=True)
            subprocess.run(["git", "-C", str(destination), "remote", "add", "origin",
                            "https://github.com/org/repo.git"], check=True)
            (destination / "SECURITY.md").write_text("synthetic fixture\n", encoding="utf-8")
            overlay = destination / "docs" / "public-contributing.md"
            overlay.parent.mkdir(parents=True, exist_ok=True)
            overlay.write_text("# Synthetic public contribution route\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(destination), "add", "SECURITY.md"], check=True)
            subprocess.run(["git", "-C", str(destination), "commit", "-m", "fixture"], check=True,
                           capture_output=True)
            source_commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True,
                                           capture_output=True, text=True).stdout.strip()
            distribution_commit = subprocess.run(["git", "-C", str(destination), "rev-parse", "HEAD"], check=True,
                                                 capture_output=True, text=True).stdout.strip()
            responses.update(strict_responses(source_commit))
            with patch.object(self.module.GitHubTransport, "gh_token_provider", return_value=lambda: "synthetic-token"), \
                    patch.object(self.module.urllib.request, "build_opener", return_value=Opener()):
                authenticated = self.module.collect_authenticated_metadata(
                    "source", "org/repo", source_commit, source_commit, 7,
                    "synthetic-account", "org/repo", "topic",
                )
            self.assertTrue(self.module.verify_collection(
                authenticated, "source", "org/repo", source_commit, source_commit, 7,
                head_repository="org/repo", head_ref="topic", require_production=True,
            ))
            source_collection = self.module.collect_metadata(
                "source", "org/repo", source_commit, source_commit, 7, injected_transport(),
                head_repository="org/repo", head_ref="topic",
            )
            responses.update(strict_responses(distribution_commit))
            distribution_collection = self.module.collect_metadata(
                "distribution", "org/repo", distribution_commit, distribution_commit, 7, injected_transport(),
                head_repository="org/repo", head_ref="topic",
            )
            self.assertFalse(source_collection.production_verified)
            self.assertFalse(distribution_collection.production_verified)
            snapshots = {}

            def record_policy(_source, _destination, _files, metadata):
                snapshots.update(metadata)
                return None, []

            with patch.object(exporter, "_assert_clean_head_snapshot"), \
                    patch.object(exporter, "_audience_policy", side_effect=record_policy):
                result = exporter.export_tree(
                    source, destination,
                    metadata={"source": source_collection, "distribution": distribution_collection},
                    metadata_bindings={"source": {"pr": 7, "head": source_commit,
                                                   "head_repository": "org/repo", "head_ref": "topic"},
                                       "distribution": {"pr": 7, "head": distribution_commit,
                                                        "head_repository": "org/repo", "head_ref": "topic"}},
                )
            self.assertIn("metadata_receipt_unverified", result["blockers"])
            self.assertEqual({}, snapshots)
            self.assertFalse(result["publication_ready"])
            export_receipt = json.loads((destination / ".git" / "engineering-public-export.json").read_text())
            self.assertEqual({}, export_receipt.get("metadata_collection_receipts", {}))

    def test_pagination_requires_sequential_next_and_terminal_empty_page(self) -> None:
        first = "https://api.github.com/repos/org/repo/issues?state=all&per_page=100"
        second = first + "&page=2"
        first_page = first + "&page=1"
        seen = []

        def fetch(url: str):
            seen.append(url)
            if url == first:
                return 200, {"Link": f'<{second}>; rel="next"'}, b'[{"title":"one"}]'
            if url == second:
                return 200, {}, b'[]'
            raise AssertionError("unexpected URL")

        rows, coverage, transcript = self.module._fetch_pages(first, "issues", None, fetch)
        self.assertEqual(1, len(rows))
        self.assertEqual([False, True], [page["terminal"] for page in coverage])
        self.assertEqual([1, 0], [page["item_count"] for page in coverage])
        self.assertEqual(2, len(seen))
        self.assertTrue(transcript)

    def test_transport_and_schema_errors_do_not_leak_raw_details(self) -> None:
        def fetch(_url: str):
            raise RuntimeError("synthetic-secret-token")

        with self.assertRaises(self.module.MetadataProjectionError) as raised:
            self.module._fetch_pages("https://api.github.com/repos/org/repo/issues", "issues", None, fetch)
        self.assertEqual("metadata_transport_unknown", str(raised.exception))
        self.assertNotIn("synthetic-secret-token", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_truncated_pagination_is_not_accepted_as_terminal(self) -> None:
        first = "https://api.github.com/repos/org/repo/issues?state=all&per_page=100"

        def fetch(url: str):
            self.assertEqual(first, url)
            return 503, {"Link": f'<{first}&page=2>; rel="next"'}, b"unavailable"

        with self.assertRaisesRegex(self.module.MetadataProjectionError, "metadata_transport_unknown"):
            self.module._fetch_pages(first, "issues", None, fetch)

    def test_pinned_openapi_catalogue_covers_all_collection_endpoint_components(self) -> None:
        self.assertEqual("fa705adfcb7e5c1e96a43a97838bd8daaab57049", self.module.OPENAPI_COMMIT)
        self.assertEqual("d3fb629730461a399929f5eb71406dd8b89e9ab7698918dfdb45f4b7b1d7c745",
                         self.module.OPENAPI_SHA256)
        self.assertEqual({"repository", "issues", "pulls", "pull_detail", "releases", "issue_comments",
                          "pr_comments", "reviews"}, set(self.module.ENDPOINT_SCHEMAS))
        self.assertIn("custom_properties", self.module.ENDPOINT_SCHEMAS["repository"])
        self.assertIn("body_text", self.module.ENDPOINT_SCHEMAS["issues"])
        self.assertIn("auto_merge", self.module.ENDPOINT_SCHEMAS["pull_detail"])

    def test_nested_catalogue_is_closed_and_machine_consistent(self) -> None:
        for component, schema in self.module.OPENAPI_NESTED_SCHEMAS.items():
            with self.subTest(component=component):
                allowed = self.module.OPENAPI_OBJECT_SCHEMAS[component]
                self.assertLessEqual(schema["required"], allowed)
                self.assertLessEqual(set(schema["types"]), allowed)
                self.assertLessEqual(set(schema["enums"]), allowed)
                for field, enum in schema["enums"].items():
                    self.assertIn(field, schema["types"])
                    self.assertTrue(enum)

    def test_runtime_sentinels_cover_omitted_top_level_and_nested_text(self) -> None:
        marker = "runtime-sentinel-encoding-audit"
        for kind, field in (("issue", "state_reason"), ("review", "state"),
                            ("pull", "mergeable_state")):
            with self.subTest(kind=kind, field=field):
                self.assertIn(marker, self.module.project_record(kind, {field: marker})["nested_text"])

        label = {"name": "safe", "color": marker}
        self.assertIn(marker, self.module.project_record("issue", {"labels": [label]})["nested_text"])
        team = {"slug": "maintainers", "name": "maintainers", "privacy": marker + "-privacy",
                "notification_setting": marker + "-notifications"}
        team_text = self.module.project_record("pull", {"requested_teams": [team]})["nested_text"]
        self.assertIn(marker + "-privacy", team_text)
        self.assertIn(marker + "-notifications", team_text)
        asset = {"id": 1, "node_id": "A1", "name": "safe", "label": None, "state": "uploaded",
                 "content_type": marker, "size": 1, "digest": None, "download_count": 0,
                 "created_at": "2026-10-02T00:00:00Z", "updated_at": "2026-10-02T00:00:00Z",
                 "uploader": None, "url": "https://api.github.com/repos/org/repo/releases/assets/1",
                 "browser_download_url": "https://github.com/org/repo/releases/download/v1/safe"}
        self.assertIn(marker, self.module.project_record("release", {"tag_name": "v1", "assets": [asset]}, "org/repo")["nested_text"])

    def test_all_validated_nested_string_leaves_reach_the_value_audit(self) -> None:
        marker = "validated-nested-runtime-sentinel"
        milestone = {"id": 5, "number": 5, "title": "safe", "description": None,
                     "state": "open", "url": "https://api.github.com/repos/org/repo/milestones/5",
                     "html_url": "https://github.com/org/repo/milestones/5",
                     "labels_url": "https://api.github.com/repos/org/repo/milestones/5/labels",
                     "created_at": marker, "updated_at": "2026-10-02T00:00:00Z"}
        projected = self.module.project_record("issue", {"title": "safe", "milestone": milestone}, "org/repo")
        self.assertIn(marker, projected["nested_text"])

    def test_each_top_level_authored_field_reaches_the_runtime_projection(self) -> None:
        marker = "top-level-runtime-sentinel"
        for kind, fields in self.module.TOP_LEVEL_AUTHORED_FIELDS.items():
            endpoint = {"issue": "issues", "pull": "pull_detail", "release": "releases",
                        "comment": "issue_comments", "review": "reviews"}[kind]
            reachable = fields & self.module.ENDPOINT_SCHEMAS[endpoint]
            with self.subTest(kind=kind):
                for field in reachable:
                    projected = self.module.project_record(kind, {field: marker})
                    self.assertTrue(projected.get(field) == marker or marker in projected.get("nested_text", []),
                                    f"{kind}.{field} did not reach the projected audit")

    def test_actor_url_fields_bind_to_their_canonical_host_and_reject_port_zero(self) -> None:
        cases = (
            ("url", "https://github.com/synthetic"),
            ("html_url", "https://api.github.com/us" + "ers/synthetic"),
            ("followers_url", "https://github.com/synthetic/followers"),
            ("url", "https://api.github.com:0/us" + "ers/synthetic"),
        )
        for field, url in cases:
            actor = {"id": 9, "login": "synthetic", "type": "User", field: url}
            with self.subTest(field=field, url=url), self.assertRaises(self.module.MetadataProjectionError):
                self.module.project_record("issue", {"user": actor})

    def test_bot_avatar_is_a_bounded_discarded_locator_not_actor_identity(self) -> None:
        avatar = "https://avatars.githubusercontent.com/automation-bot/987654321?v=4"
        actor = {"id": 8, "node_id": "BOT8", "login": "automation[bot]", "type": "Bot",
                 "name": "Automation", "avatar_url": avatar}
        projected = self.module.project_record("issue", {"user": actor})
        self.assertIn("Automation", projected["nested_text"])
        self.assertNotIn(avatar, projected["nested_text"])
        self.assertTrue(self.module.validate_actor_url("avatar_url", avatar, actor["login"], actor["id"]))
        self.assertTrue(self.module.validate_actor_url(
            "avatar_url", "https://github.com/images/error/automation_bot.gif", actor["login"], actor["id"]
        ))
        unsafe = (
            " " + avatar,
            avatar + " ",
            "\u00a0" + avatar,
            avatar + "\u00a0",
            avatar + "\u007f",
            "http://avatars.githubusercontent.com/automation-bot/987654321?v=4",
            "https://evil.example/automation-bot/987654321?v=4",
            "https://avatars.githubusercontent.com.evil.example/automation-bot/987654321?v=4",
            "https://avatars.githubusercontent.com:443/automation-bot/987654321?v=4",
            "https://avatars.githubusercontent.com:0/automation-bot/987654321?v=4",
            "https://@avatars.githubusercontent.com/automation-bot/987654321?v=4",
            "https://avatars.githubusercontent.com:/automation-bot/987654321?v=4",
            "https://avatars.githubusercontent.com/automation-bot/../987654321?v=4",
            "https://avatars.githubusercontent.com/automation-bot//987654321?v=4",
            "https://avatars.githubusercontent.com/automation-bot/987654321/extra?v=4",
            "https://avatars.githubusercontent.com/automation-bot/{id}?v=4",
            "https://avatars.githubusercontent.com/automation-bot/%39?v=4",
            "https://avatars.githubusercontent.com/automation-bot/987654321?v=4&v=5",
            "https://avatars.githubusercontent.com/automation-bot/987654321?size=64",
            "https://avatars.githubusercontent.com/automation-bot/987654321?v=4#avatar",
        )
        for value in unsafe:
            with self.subTest(value=value), self.assertRaises(self.module.MetadataProjectionError):
                self.module.validate_actor_url("avatar_url", value, actor["login"], actor["id"])
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.validate_actor_url("url", "https://api.github.com/user" + "s/" + "other",
                                           actor["login"], actor["id"])

    def test_bot_app_profile_route_is_type_gated_and_api_identity_stays_bound(self) -> None:
        for profile in ("https://github.com/apps/automation", "https://github.com/automation[bot]"):
            actor = {"id": 8, "node_id": "BOT8", "login": "automation[bot]", "type": "Bot",
                     "html_url": profile}
            projected = self.module.project_record("issue", {"user": actor})
            self.assertNotIn(profile, projected["nested_text"])
        unsafe = (
            "https://github.com/apps/", "https://github.com/apps/automation/extra",
            "https://github.com/apps/automation?tab=projects", "https://github.com/apps/automation#profile",
            "https://github.com/apps/{automation}", "https://github.com/apps/../automation",
            "https://github.com/apps/automation%2fother", "https://github.com:443/apps/automation",
            "https://@github.com/apps/automation", "https://github.com:/apps/automation",
        )
        for profile in unsafe:
            actor = {"id": 8, "node_id": "BOT8", "login": "automation[bot]", "type": "Bot",
                     "html_url": profile}
            with self.subTest(profile=profile), self.assertRaises(self.module.MetadataProjectionError):
                self.module.project_record("issue", {"user": actor})
        for actor_type in ("User", "Organization", "Unknown"):
            actor = {"id": 8, "node_id": "BOT8", "login": "automation[bot]", "type": actor_type,
                     "html_url": "https://github.com/apps/automation"}
            with self.subTest(actor_type=actor_type), self.assertRaises(self.module.MetadataProjectionError):
                self.module.project_record("issue", {"user": actor})
        actor_without_type = {"id": 8, "node_id": "BOT8", "login": "automation[bot]",
                              "html_url": "https://github.com/apps/automation"}
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.project_record("issue", {"user": actor_without_type})
        actor = {"id": 8, "node_id": "BOT8", "login": "automation[bot]", "type": "Bot",
                 "url": "https://api.github.com/user" + "s/" + "other",
                 "html_url": "https://github.com/apps/automation"}
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.project_record("issue", {"user": actor})

    def test_strict_issue_and_pull_request_as_issue_use_closed_nullable_pr_shape(self) -> None:
        repository = "org/repo"
        base = "https://api.github.com/repos/org/repo"

        def make_issue(*, is_pull: bool, pull_request: object = "standard") -> dict:
            number = 7
            html_path = f"https://github.com/org/repo/{'pull' if is_pull else 'issues'}/{number}"
            issue = {
                "id": 70, "node_id": "I70", "number": number, "title": "authored issue text",
                "state": "open", "locked": False, "comments": 0, "closed_at": None,
                "created_at": "2026-10-01T10:00:00Z", "updated_at": "2026-10-02T10:00:00Z",
                "url": base + f"/issues/{number}", "repository_url": base,
                "html_url": html_path, "comments_url": base + f"/issues/{number}/comments",
                "events_url": base + f"/issues/{number}/events",
                "labels_url": base + f"/issues/{number}/labels{{/name}}",
                "labels": [], "assignee": None, "milestone": None,
                "user": self.make_strict_user("author", 31),
            }
            if pull_request != "standard":
                issue["pull_request"] = pull_request
            elif is_pull:
                issue["pull_request"] = {
                    "url": base + f"/pulls/{number}",
                    "html_url": f"https://github.com/org/repo/pull/{number}",
                    "diff_url": f"https://github.com/org/repo/pull/{number}.diff",
                    "patch_url": f"https://github.com/org/repo/pull/{number}.patch",
                    "merged_at": None,
                }
            return issue

        ordinary = self.module.project_record("issue", make_issue(is_pull=False), repository,
                                              schema_endpoint="issues", strict_required=True)
        self.assertEqual(ordinary["title"], "authored issue text")
        full_links = {
            "url": base + "/pulls/7", "html_url": "https://github.com/org/repo/pull/7",
            "diff_url": "https://github.com/org/repo/pull/7.diff",
            "patch_url": "https://github.com/org/repo/pull/7.patch",
        }
        nullable_link_sets = ({}, *({key: None} for key in full_links), {key: None for key in full_links})
        for null_links in nullable_link_sets:
            nested = {**full_links, **null_links, "merged_at": None}
            row = make_issue(is_pull=True, pull_request=nested)
            projected = self.module.project_record("issue", row, repository,
                                                   schema_endpoint="issues", strict_required=True)
            self.assertEqual(projected["title"], "authored issue text")
        self.module.project_record("issue", make_issue(is_pull=True, pull_request=dict(full_links)), repository,
                                   schema_endpoint="issues", strict_required=True)
        date_nested = {**full_links, "merged_at": "2026-10-02T10:00:00Z"}
        self.module.project_record("issue", make_issue(is_pull=True, pull_request=date_nested), repository,
                                   schema_endpoint="issues", strict_required=True)

        invalid = []
        missing = make_issue(is_pull=True, pull_request=None)
        missing.pop("pull_request")
        invalid.append(missing)
        invalid.append(make_issue(is_pull=True, pull_request=None))
        invalid.append(make_issue(is_pull=True, pull_request="not-an-object"))
        for malformed in (
            {key: value for key, value in full_links.items() if key != "url"},
            {**full_links, "extra": "unexpected"},
            {**full_links, "url": 7},
            {**full_links, "url": base + "/pulls/8"},
            {**full_links, "html_url": "https://github.com/other/repo/pull/7"},
            {**full_links, "merged_at": "not-a-date"},
            {**full_links, "merged_at": 7},
        ):
            invalid.append(make_issue(is_pull=True, pull_request=malformed))
        contradictory = make_issue(is_pull=True)
        contradictory["html_url"] = "https://github.com/org/repo/issues/7"
        invalid.append(contradictory)
        for row in invalid:
            with self.subTest(pull_request_shape=type(row.get("pull_request")).__name__), \
                    self.assertRaises(self.module.MetadataProjectionError):
                self.module.project_record("issue", row, repository, schema_endpoint="issues", strict_required=True)

    def test_stack_base_sha_requires_a_full_commit_identifier(self) -> None:
        for sha in ("runtime-sentinel-encoding-audit", "a" * 39, "G" * 40):
            with self.subTest(sha=sha), self.assertRaises(self.module.MetadataProjectionError):
                self.module.project_record("pull", {"stack": {"base": {"sha": sha, "ref": "main"}}})

    def test_app_and_team_routes_reject_explicit_port_zero(self) -> None:
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._validate_app_url("https://github.com:0/apps/synthetic", "synthetic")
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._validate_team_url("html_url", "https://github.com:0/orgs/org/teams/team",
                                            "org", "team")

    def test_repository_organization_validation_receives_strict_requirement(self) -> None:
        repository = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo",
                     "private": True, "url": "https://api.github.com/repos/org/repo",
                     "html_url": "https://github.com/org/repo",
                     "organization": {"id": 2, "node_id": "O2", "login": "org", "type": "Organization",
                                       "url": "https://api.github.com/orgs/org",
                                       "html_url": "https://github.com/org"}}
        minimal_required = frozenset({"id", "node_id", "name", "full_name", "private", "url", "html_url"})
        with patch.dict(self.module.OPENAPI_REQUIRED_FIELDS, {"full-repository": minimal_required}), \
                self.assertRaises(self.module.MetadataProjectionError):
            self.module._project_repository(repository, "org/repo", strict_required=True)

    def test_nested_required_shapes_are_checked_when_component_is_admitted(self) -> None:
        for component, schema in self.module.OPENAPI_NESTED_SCHEMAS.items():
            for missing in schema["required"]:
                value = {field: self._schema_value(expected)
                         for field, expected in schema["types"].items()}
                value.update({field: next(iter(choices)) for field, choices in schema["enums"].items()})
                value.pop(missing, None)
                with self.subTest(component=component, missing=missing), self.assertRaises(
                        self.module.MetadataProjectionError):
                    self.module._validate_nested_schema(component, value, strict_required=True)

    def test_issue_field_option_nested_object_has_exact_pinned_shape(self) -> None:
        for option in ({"id": True, "name": "safe", "color": "red"},
                       {"id": 1, "name": "safe"},
                       {"id": 1, "name": "safe", "color": "red", "extra": "unknown"}):
            with self.subTest(option=option), self.assertRaises(self.module.MetadataProjectionError):
                self.module._validate_nested_schema("issue-field-option", option, strict_required=True)
        self.module._validate_nested_schema("issue-field-option",
                                            {"id": 1, "name": "safe", "color": "unconstrained"},
                                            strict_required=True)

    def test_referenced_nullable_user_component_is_not_a_nullable_object(self) -> None:
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._validate_nested_schema("nullable-milestone", {"creator": None})
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._validate_nested_schema("nullable-pinned-issue-comment",
                                                {"pinned_at": "2026-10-02T00:00:00Z", "pinned_by": None})
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._validate_nested_schema("release-asset", {"uploader": None})

    def test_issue_field_documented_union_and_nullable_options(self) -> None:
        options = {"id": 1, "name": "High", "color": "not-an-enum"}
        fields = [
            {"issue_field_id": 1, "node_id": "F1", "data_type": "text", "value": "marker"},
            {"issue_field_id": 2, "node_id": "F2", "data_type": "number", "value": 42},
            {"issue_field_id": 3, "node_id": "F3", "data_type": "number", "value": 42.5},
            {"issue_field_id": 4, "node_id": "F4", "data_type": "single_select", "value": None,
             "single_select_option": options},
            {"issue_field_id": 5, "node_id": "F5", "data_type": "multi_select", "value": None,
             "multi_select_options": [options]},
            {"issue_field_id": 6, "node_id": "F6", "data_type": "multi_select", "value": None,
             "multi_select_options": None},
        ]
        projected = self.module.project_record("issue", {"title": "safe", "issue_field_values": fields}, "org/repo")
        self.assertIn("marker", projected["nested_text"])
        for bad in (
            {"issue_field_id": 7, "node_id": "F7", "data_type": "number", "value": True},
            {"issue_field_id": 8, "node_id": "F8", "data_type": "single_select", "value": None,
             "single_select_option": {"id": 1, "name": "High"}},
            {"issue_field_id": 9, "node_id": "F9", "data_type": "multi_select", "value": None,
             "multi_select_options": {"id": 1, "name": "High", "color": "red"}},
        ):
            with self.subTest(bad=bad), self.assertRaises(self.module.MetadataProjectionError):
                self.module.project_record("issue", {"title": "safe", "issue_field_values": [bad]}, "org/repo")

    def test_milestone_generated_routes_bind_to_exact_milestone_number(self) -> None:
        milestone = {"closed_issues": 0, "creator": {"id": 2, "login": "synthetic", "type": "User"},
                     "description": None, "due_on": None, "closed_at": None, "id": 3, "node_id": "M3",
                     "labels_url": "https://api.github.com/repos/org/repo/milestones/7/labels",
                     "html_url": "https://github.com/org/repo/milestones/7", "number": 7,
                     "open_issues": 0, "state": "open", "title": "safe",
                     "url": "https://api.github.com/repos/org/repo/milestones/7",
                     "created_at": "2026-10-02T00:00:00Z", "updated_at": "2026-10-02T00:00:00Z"}
        self.module.project_record("issue", {"number": 7, "title": "safe", "milestone": milestone}, "org/repo")
        milestone["labels_url"] = "https://api.github.com/repos/org/repo/issues/7/labels"
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.project_record("issue", {"number": 7, "title": "safe", "milestone": milestone}, "org/repo")

    def test_pull_link_relations_bind_to_exact_routes_and_head_sha(self) -> None:
        api = "https://api.github.com/repos/org/repo"
        web = "https://github.com/org/repo"
        head_sha = "a" * 40
        links = {
            "self": {"href": api + "/pulls/12"},
            "html": {"href": web + "/pull/12"},
            "issue": {"href": api + "/issues/12"},
            "comments": {"href": api + "/issues/12/comments"},
            "review_comments": {"href": api + "/pulls/12/comments"},
            "review_comment": {"href": api + "/pulls/comments{/number}"},
            "commits": {"href": api + "/pulls/12/commits"},
            "statuses": {"href": api + "/statuses/" + head_sha},
        }
        repo = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                "url": api, "html_url": web}
        pull = {"number": 12, "title": "safe", "_links": links,
                "head": {"sha": head_sha, "ref": "feature", "repo": repo},
                "base": {"sha": "b" * 40, "ref": "main", "repo": repo}}
        projected = self.module._project_pull(pull, "org/repo")
        self.assertNotIn(head_sha, projected.get("nested_text", []))
        mutations = (
            ("comments", api + "/pulls/12/comments"),
            ("self", api + "/pulls/13"),
            ("statuses", api + "/statuses/" + "c" * 40),
            ("review_comment", api + "/pulls/comments/12"),
            ("commits", "https://attacker.invalid/repos/org/repo/pulls/12/commits"),
            ("issue", api + "/issues/12?x=1"),
            ("html", web + "/pull/12#other"),
            ("html", web + "/issues/12"),
        )
        for relation, href in mutations:
            broken = {key: dict(target) for key, target in links.items()}
            broken[relation]["href"] = href
            with self.subTest(relation=relation, href=href), self.assertRaises(self.module.MetadataProjectionError):
                self.module._project_pull({**pull, "_links": broken}, "org/repo")

    def test_review_and_review_comment_links_use_endpoint_specific_relations(self) -> None:
        api = "https://api.github.com/repos/org/repo"
        web = "https://github.com/org/repo"
        review_comment = {"id": 31, "body": "safe", "_links": {
            "self": {"href": api + "/pulls/comments/31"},
            "html": {"href": web + "/pull/12#discussion-diff-31"},
            "pull_request": {"href": api + "/pulls/12"},
        }}
        review = {"id": 41, "body": "safe", "_links": {
            "html": {"href": web + "/pull/12#pullrequestreview-41"},
            "pull_request": {"href": api + "/pulls/12"},
        }}
        self.module.project_record("comment", review_comment, "org/repo", schema_endpoint="pr_comments",
                                   parent_number=12)
        self.module.project_record("review", review, "org/repo", schema_endpoint="reviews",
                                   parent_number=12)
        for kind, endpoint, record, relation, href in (
            ("comment", "pr_comments", review_comment, "self", api + "/pulls/comments/32"),
            ("comment", "pr_comments", review_comment, "html", web + "/pull/12#discussion-diff-32"),
            ("review", "reviews", review, "html", web + "/pull/13#pullrequestreview-41"),
            ("review", "reviews", review, "self", api + "/pulls/12"),
        ):
            bad_links = {key: dict(target) for key, target in record["_links"].items()}
            bad_links.setdefault(relation, {})["href"] = href
            with self.subTest(endpoint=endpoint, relation=relation, href=href), self.assertRaises(
                    self.module.MetadataProjectionError):
                self.module.project_record(kind, {**record, "_links": bad_links}, "org/repo",
                                           schema_endpoint=endpoint, parent_number=12)

    def test_github_app_enterprise_owner_uses_pinned_owner_union(self) -> None:
        enterprise = {"id": 9, "node_id": "E9", "name": "Enterprise Name", "slug": "enterprise-name",
                      "html_url": "https://github.com/enterprises/enterprise-name",
                      "created_at": None, "updated_at": None, "avatar_url": "https://avatars.githubusercontent.com/u/9",
                      "description": "Enterprise description", "website_url": None}
        app = {"id": 4, "node_id": "I4", "owner": enterprise, "name": "App", "description": None,
               "external_url": "https://example.com", "html_url": "https://github.com/apps/example",
               "created_at": "2026-10-02T00:00:00Z", "updated_at": "2026-10-02T00:00:00Z",
               "permissions": {}, "events": [], "slug": "example"}
        projected = self.module.project_record("issue", {"title": "safe", "performed_via_github_app": app}, "org/repo")
        self.assertIn("Enterprise Name", projected["nested_text"])
        self.assertIn("Enterprise description", projected["nested_text"])
        enterprise["website_url"] = "https://example.invalid/company"
        projected = self.module.project_record("issue", {"title": "safe", "performed_via_github_app": app}, "org/repo")
        self.assertIn("https://example.invalid/company", projected["nested_text"])
        for avatar_url in (
                "https://avatars.githubusercontent.com/private/image?token=secret",
                "https://avatars.githubusercontent.com/u/9?redirect=https://attacker.invalid"):
            enterprise["avatar_url"] = avatar_url
            with self.subTest(avatar_url=avatar_url), self.assertRaises(self.module.MetadataProjectionError):
                self.module.project_record("issue", {"title": "safe", "performed_via_github_app": app}, "org/repo")
        enterprise["avatar_url"] = "https://avatars.githubusercontent.com/u/9"
        enterprise["html_url"] = "https://github.com/attacker/enterprise-name"
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.project_record("issue", {"title": "safe", "performed_via_github_app": app}, "org/repo")

    @staticmethod
    def _schema_value(expected):
        choices = expected if isinstance(expected, tuple) else (expected,)
        for candidate in choices:
            if candidate is str:
                return "safe"
            if candidate is int:
                return 1
            if candidate is bool:
                return False
            if candidate is dict:
                return {}
            if candidate is list:
                return []
            if candidate is type(None):
                return None
        raise AssertionError(f"unsupported fixture type: {choices!r}")

    def test_repository_optional_variants_and_custom_properties_are_scanned(self) -> None:
        base = "https://api.github.com/repos/org/repo"
        value = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                 "url": base, "html_url": "https://github.com/org/repo", "description": "safe", "topics": [],
                 "owner": {**self.make_strict_user("org", 2), "type": "Organization"},
                 "custom_properties": {"review_policy": "ABis" + "was19/engineering-skill",
                                       "allowed_modes": ["safe", "Phil" + "ips"]},
                 "security_and_analysis": {"advanced_security": {"status": "enabled"}},
                 "parent": {"id": 3, "node_id": "R3", "name": "parent", "full_name": "org/parent",
                            "url": "https://api.github.com/repos/org/parent",
                            "html_url": "https://github.com/org/parent", "private": True},
                 "source": {"id": 5, "node_id": "R5", "name": "source", "full_name": "org/source", "private": False,
                            "url": "https://api.github.com/repos/org/source", "html_url": "https://github.com/org/source",
                            "description": "source authored"},
                 "template_repository": {"id": 6, "node_id": "R6", "name": "template", "full_name": "org/template",
                                         "private": False, "url": "https://api.github.com/repos/org/template",
                                         "html_url": "https://github.com/org/template", "description": "template authored"},
                 "license": {"key": "mit", "name": "MIT License", "spdx_id": "MIT", "url": None}}
        projected = self.module._project_repository(value, "org/repo")["repository"]
        self.assertEqual("ABis" + "was19/engineering-skill", projected["custom_properties"]["review_policy"])
        self.assertEqual("Phil" + "ips", projected["custom_properties"]["allowed_modes"][1])
        self.assertEqual("org/parent", projected["parent"]["full_name"])
        self.assertEqual("org/source", projected["source"]["full_name"])
        self.assertEqual("template authored", projected["template_repository"]["description"])

    def test_custom_property_and_fork_repository_authored_text_reaches_content_audit(self) -> None:
        audience_spec = importlib.util.spec_from_file_location(
            "engineering_metadata_projection_custom_property_audience", ROOT / "tools" / "check_audience.py"
        )
        audience_module = importlib.util.module_from_spec(audience_spec)
        audience_spec.loader.exec_module(audience_module)
        base = "https://api.github.com/repos/org/repo"
        marker = "ABis" + "was19/engineering-skill"
        policy = self.synthetic_audience_policy(audience_module, [marker])
        repository = self.module._project_repository({
            "id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
            "url": base, "html_url": "https://github.com/org/repo", "description": "safe", "topics": [],
            "custom_properties": {"source": marker,
                                  "fixture": ["C:" + chr(92) + "Users" + chr(92) + "private"]},
        }, "org/repo")["repository"]
        snapshot = {"schema": "engineering.audience-metadata-snapshot.v1", "audience": "source",
                    "source_commit": "a" * 40, "surfaces": {name: [] for name in self.module.SURFACES}}
        snapshot["surfaces"]["issues"].append({"repository": repository})
        blockers = audience_module.audit_metadata(policy, snapshot, "source", "a" * 40)
        self.assertIn("metadata_marker_crossflow", blockers)
        self.assertIn("metadata_personal_path", blockers)

    def test_authored_nested_keys_and_actor_fields_reach_the_value_only_audit(self) -> None:
        projected = self.module._project_repository({
            "id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
            "url": "https://api.github.com/repos/org/repo", "html_url": "https://github.com/org/repo",
            "custom_properties": {"ABis" + "was19/engineering-skill": "safe"},
        }, "org/repo")["repository"]
        self.assertIn("ABis" + "was19/engineering-skill", projected.get("nested_text", []))
        issue = self.module.project_record("pull", {
            "title": "safe",
            "assignees": [{"id": 8, "login": "synthetic", "type": "User", "name": "Phil" + "ips",
                           "email": "private" + "@example.invalid"}],
            "requested_reviewers": [{"id": 9, "login": "reviewer", "type": "User",
                                     "name": "ABis" + "was19/engineering-skill"}],
            "requested_teams": [{"id": 3, "node_id": "T3", "organization_id": 2, "slug": "maintainers",
                                 "name": "maintainers", "description": None, "permission": "pull",
                                 "privacy": "closed", "notification_setting": "notifications_enabled",
                                 "type": "organization", "url": "https://api.github.com/organizations/2/team/3",
                                 "members_url": "https://api.github.com/organizations/2/team/3/members{/member}",
                                 "repositories_url": "https://api.github.com/organizations/2/team/3/repos",
                                 "html_url": "https://github.com/orgs/org/teams/maintainers",
                                 "ldap_dn": "Phil" + "ips"}],
        }, "org/repo")
        for authored in ("Phil" + "ips", "private" + "@example.invalid", "ABis" + "was19/engineering-skill"):
            self.assertIn(authored, issue["nested_text"])

    def test_nested_authored_pr_repository_keys_and_asset_uploader_fields_are_scanned(self) -> None:
        fork = {"id": 4, "node_id": "R4", "name": "fork", "full_name": "contributor/fork",
                "private": False, "url": "https://api.github.com/repos/contributor/fork",
                "html_url": "https://github.com/contributor/fork", "description": "Phil" + "ips"}
        base = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                "url": "https://api.github.com/repos/org/repo", "html_url": "https://github.com/org/repo"}
        projected = self.module._project_pull({
            "number": 7, "title": "safe", "head": {"sha": "1" * 40, "ref": "topic", "repo": fork},
            "base": {"sha": "2" * 40, "ref": "main", "repo": base},
        }, "org/repo")
        self.assertIn("Phil" + "ips", projected["nested_text"])
        invalid_fork = {**fork, "custom_properties": {"Phil" + "ips": "safe"}}
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._project_pull({
                "number": 7, "title": "safe", "head": {"sha": "1" * 40, "ref": "topic", "repo": invalid_fork},
                "base": {"sha": "2" * 40, "ref": "main", "repo": base},
            }, "org/repo")
        release = self.module.project_record("release", {
            "name": "safe", "assets": [{"id": 2, "name": "asset", "content_type": "application/octet-stream",
                "size": 1, "digest": None, "state": "uploaded", "url": "https://api.github.com/repos/org/repo/releases/assets/2",
                "node_id": "A2", "download_count": 0, "label": None, "created_at": None, "updated_at": None,
                "browser_download_url": "https://github.com/org/repo/releases/download/v1/asset",
                "uploader": {"id": 8, "login": "synthetic", "type": "User", "name": "Phil" + "ips",
                             "email": "private" + "@example.invalid"}}]}, "org/repo")
        self.assertIn("Phil" + "ips", release["nested_text"])
        self.assertIn("private" + "@example.invalid", release["nested_text"])

    def test_malformed_nested_authored_types_fail_closed(self) -> None:
        for value in (
            {"body": "safe", "minimized": {"reason": {"text": "smuggled"}}},
            {"title": "safe", "auto_merge": {"enabled_by": {"id": 1, "login": "synthetic", "type": "User"},
                                                 "merge_method": "squash", "commit_title": "safe",
                                                 "commit_message": {"text": "smuggled"}}},
        ):
            with self.subTest(value=value), self.assertRaises(self.module.MetadataProjectionError):
                self.module.project_record("comment" if "minimized" in value else "pull", value, "org/repo")
        self.assertEqual({"body": "safe"}, self.module.project_record(
            "comment", {"body": "safe", "minimized": {"reason": None}}, "org/repo"))

    def test_security_reviewer_nested_shape_fails_closed(self) -> None:
        value = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                 "url": "https://api.github.com/repos/org/repo", "html_url": "https://github.com/org/repo",
                 "security_and_analysis": {"code_security": {"status": "enabled", "reviewers": {"login": "unexpected"}}}}
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module._project_repository(value, "org/repo")

    def test_transport_relation_rejects_wrong_endpoint_for_same_repository_object(self) -> None:
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.validate_transport_url("comments_url", "https://api.github.com/repos/org/repo/issues/4/events",
                                                "org/repo", pr_number=4)
        with self.assertRaises(self.module.MetadataProjectionError):
            self.module.validate_transport_url("url", "https://api.github.com/repos/org/repo/issues/99",
                                                "org/repo", pr_number=4, object_kind="issue")

    def test_fork_head_repository_text_is_projected_but_base_stays_bound_to_target(self) -> None:
        base_url = "https://api.github.com/repos/org/repo"
        fork_url = "https://api.github.com/repos/contributor/fork"
        fork = {"id": 4, "node_id": "R4", "name": "fork", "full_name": "contributor/fork", "private": False,
                "url": fork_url, "html_url": "https://github.com/contributor/fork", "description": "Phil" + "ips"}
        base = {"id": 1, "node_id": "R1", "name": "repo", "full_name": "org/repo", "private": True,
                "url": base_url, "html_url": "https://github.com/org/repo", "description": "safe"}
        pull = {"number": 7, "title": "safe", "body": None,
                "head": {"sha": "1" * 40, "ref": "topic", "label": "contributor:topic", "repo": fork},
                "base": {"sha": "2" * 40, "ref": "main", "label": "org:main", "repo": base}}
        projected = self.module._project_pull(pull, "org/repo")
        self.assertIn("Phil" + "ips", projected["nested_text"])

    def test_documented_actor_email_and_bot_login_are_scanned(self) -> None:
        value = {"title": "safe", "body_text": "ABis" + "was19/engineering-skill",
                 "user": {"id": 8, "node_id": "U8", "login": "automation[bot]", "type": "Bot",
                          "name": "Phil" + "ips", "email": "hidden" + "@" + "example.invalid",
                          "avatar_url": "https://avatars.githubusercontent.com/u/8"}}
        projected = self.module.project_record("issue", value, "org/repo")
        self.assertIn("Phil" + "ips", projected["nested_text"])
        self.assertIn("hidden" + "@" + "example.invalid", projected["nested_text"])
        self.assertIn("ABis" + "was19/engineering-skill", projected["body_text"])

    def test_issue_documented_dynamic_text_variants_are_retained(self) -> None:
        value = {"number": 4, "title": "safe", "body": None,
                 "type": {"id": 1, "node_id": "T1", "name": "Phil" + "ips", "description": "safe",
                          "color": "blue", "is_enabled": True},
                 "issue_field_values": [{"issue_field_id": 2, "issue_field_name": "safe", "node_id": "F2",
                                         "data_type": "single_select", "value": None,
                                         "single_select_option": {"id": 3, "name": "ABis" + "was19/engineering-skill", "color": "blue"}}],
                 "sub_issues_summary": {"total": 1, "completed": 0, "percent_completed": 0},
                 "issue_dependencies_summary": {"blocked_by": 0, "blocking": 0, "total_blocked_by": 0,
                                                "total_blocking": 0},
                 "parent_issue_url": None, "pinned_comment": {"body": "safe"}}
        projected = self.module.project_record("issue", value, "org/repo")
        self.assertIn("Phil" + "ips", projected["nested_text"])
        self.assertIn("ABis" + "was19/engineering-skill", projected["nested_text"])

    def test_release_upload_template_and_comment_fragments_follow_object_identity(self) -> None:
        upload = "https://uploads.github.com/repos/org/repo/releases/2/assets{?name,label}"
        self.assertTrue(self.module.validate_transport_url("upload_url", upload, "org/repo"))
        self.assertTrue(self.module.validate_transport_url("html_url", "https://github.com/org/repo/issues/4#issuecomment-5",
                                                           "org/repo", 4, allow_fragment=True))

    def test_team_numeric_route_and_app_route_are_validated_independently(self) -> None:
        self.module._validate_team_url("url", "https://api.github.com/organizations/2/team/3", "org", "maintainers", 2, 3)
        self.module._validate_app_url("https://github.com/apps/automation", "automation")

    def test_issue_and_pull_summary_schema_variants_are_not_silently_discarded(self) -> None:
        self.assertEqual("Phil" + "ips", self.module.project_record(
            "issue", {"title": "safe", "body_html": "Phil" + "ips"}, "org/repo")["body_html"])
        self.assertEqual({"title": "safe"}, self.module.project_record(
            "pull", {"title": "safe", "auto_merge": None}, "org/repo"))

    def test_production_collection_uses_vetted_authenticated_adapter(self) -> None:
        adapter = self.module.GitHubTransport("verified-account", "org/repo", lambda: "synthetic-token")
        self.assertEqual("engineering.github-metadata-transport.v1", adapter.revision)
        self.assertTrue(adapter.redirects_rejected)
        with self.assertRaises(self.module.MetadataProjectionError):
            adapter.get("https://api.github.com.evil.invalid/repos/org/repo")

    def test_authenticated_adapter_rejects_identity_mismatch_and_hides_transport_errors(self) -> None:
        class Response:
            status = 200
            headers = {}
            def read(self, _limit): return b'{"login":"another-account"}'
            def __enter__(self): return self
            def __exit__(self, *_args): return False

        class WrongIdentityOpener:
            def open(self, request, timeout):
                self_outer.assertEqual(20, timeout)
                if request.full_url != "https://api.github.com/user":
                    raise AssertionError("collection request ran before identity verification")
                return Response()

        self_outer = self
        adapter = self.module.GitHubTransport("verified-account", "org/repo", lambda: "synthetic-token")
        adapter._opener = WrongIdentityOpener()
        with self.assertRaisesRegex(self.module.MetadataProjectionError, "metadata_auth_unknown"):
            adapter.verify_identity()

        class FailingOpener:
            def open(self, _request, _timeout):
                raise RuntimeError("synthetic-secret-token")

        adapter = self.module.GitHubTransport("verified-account", "org/repo", lambda: "synthetic-token")
        adapter._opener = FailingOpener()
        with self.assertRaisesRegex(self.module.MetadataProjectionError, "metadata_transport_unknown") as failure:
            adapter.verify_identity()
        self.assertNotIn("synthetic-secret-token", str(failure.exception))
        self.assertIsNone(failure.exception.__cause__)

    def test_duplicate_record_across_pages_is_rejected(self) -> None:
        first = "https://api.github.com/repos/org/repo/issues?state=all&per_page=100"
        next_page = first + "&page=2"

        def fetch(url: str):
            if url == first:
                return 200, {"Link": f'<{next_page}>; rel="next"'}, b'[{"id":1,"number":1}]'
            return 200, {}, b'[{"id":1,"number":1}]'

        with self.assertRaisesRegex(self.module.MetadataProjectionError, "metadata_pagination_unknown"):
            self.module._fetch_pages(first, "issues", None, fetch)

    def test_multiple_link_relations_and_consecutive_pages_are_accepted(self) -> None:
        first = "https://api.github.com/repos/org/repo/issues?state=all&per_page=100"
        second = first + "&page=2"
        first_page = first + "&page=1"

        def fetch(url: str):
            if url == first:
                return 200, {"Link": f'<{first_page}>; rel="first", <{second}>; rel="last", <{second}>; rel="next"'}, b'[{"id":1}]'
            if url == second:
                return 200, {"Link": f'<{first_page}>; rel="first", <{first_page}>; rel="prev", <{second}>; rel="last"'}, b'[{"id":2}]'
            raise AssertionError("unexpected request")

        rows, coverage, _transcript = self.module._fetch_pages(first, "issues", None, fetch)
        self.assertEqual([1, 2], [row["id"] for row in rows])
        self.assertEqual([False, True], [page["terminal"] for page in coverage])

    def test_schema_rejects_missing_required_and_duplicate_or_nonfinite_json(self) -> None:
        with self.assertRaisesRegex(self.module.MetadataProjectionError, "metadata_schema_unknown"):
            self.module.project_record("issue", {"title": "partial"}, "org/repo", strict_required=True)
        for body in (b'{"id":1,"id":2}', b'{"id":NaN}'):
            with self.subTest(body=body), self.assertRaisesRegex(self.module.MetadataProjectionError, "metadata_schema_unknown"):
                self.module._fetch_object("https://api.github.com/repos/org/repo", lambda _url: (200, {}, body))

    def test_raw_and_projection_substitution_cannot_reuse_receipt(self) -> None:
        collection = self.make_empty_collection()
        self.assertTrue(self.module.verify_collection(collection, "source", "org/repo", "a" * 40, "1" * 40, 7))
        collection.snapshot["surfaces"]["issues"].append({"title": "changed"})
        self.assertFalse(self.module.verify_collection(collection, "source", "org/repo", "a" * 40, "1" * 40, 7))
        collection = self.make_empty_collection()
        collection.raw_transcript += b"substitution"
        self.assertFalse(self.module.verify_collection(collection, "source", "org/repo", "a" * 40, "1" * 40, 7))


if __name__ == "__main__":
    unittest.main()
