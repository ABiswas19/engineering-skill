"""Fail-closed, process-local projection and receipt gate for GitHub metadata."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit
from urllib.parse import parse_qs


class MetadataProjectionError(ValueError):
    """Sanitized metadata collection or projection failure."""


SURFACES = ("comments", "issues", "pull_requests", "releases", "reviews")
_ISSUED: dict[str, tuple[str, str, str, str, str, str, int, str | None, str | None, bool, str]] = {}
OPENAPI_COMMIT = "fa705adfcb7e5c1e96a43a97838bd8daaab57049"
OPENAPI_SHA256 = "d3fb629730461a399929f5eb71406dd8b89e9ab7698918dfdb45f4b7b1d7c745"
# Response addendum observed 2026-10-02 with API version 2022-11-28; the pinned OpenAPI omits this member.
# GitHub documents the status contract at https://docs.github.com/en/enterprise-cloud@latest/rest/repos/repos?apiVersion=2026-03-10
OPENAPI_COMPONENTS = {
    "issue": "id node_id url repository_url labels_url comments_url events_url html_url number state state_reason title body user labels assignee assignees milestone locked active_lock_reason comments pull_request closed_at created_at updated_at draft closed_by body_html body_text timeline_url type repository performed_via_github_app author_association reactions sub_issues_summary parent_issue_url pinned_comment issue_dependencies_summary issue_field_values",
    "issue-pull-request": "url html_url diff_url patch_url merged_at",
    "pull-request-simple": "url id node_id html_url diff_url patch_url issue_url commits_url review_comments_url review_comment_url comments_url statuses_url number state locked title user body labels milestone active_lock_reason created_at updated_at closed_at merged_at merge_commit_sha assignee assignees requested_reviewers requested_teams head base _links author_association auto_merge stack draft",
    "pull-request": "url id node_id html_url diff_url patch_url issue_url commits_url review_comments_url review_comment_url comments_url statuses_url number state locked title user body labels milestone active_lock_reason created_at updated_at closed_at merged_at merge_commit_sha assignee assignees requested_reviewers requested_teams head base _links author_association auto_merge stack draft merged mergeable rebaseable mergeable_state merged_by comments review_comments maintainer_can_modify commits additions deletions changed_files",
    "release": "url html_url assets_url upload_url tarball_url zipball_url id node_id tag_name target_commitish name body draft prerelease immutable created_at published_at updated_at author assets body_html body_text mentions_count discussion_url reactions",
    "issue-comment": "id node_id url body body_text body_html html_url user created_at updated_at issue_url author_association performed_via_github_app reactions pin minimized",
    "pull-request-review-comment": "url pull_request_review_id id node_id diff_hunk path position original_position commit_id original_commit_id in_reply_to_id user body created_at updated_at html_url pull_request_url author_association _links start_line original_start_line start_side line original_line side subject_type reactions body_html body_text",
    "pull-request-review": "id node_id user body state html_url pull_request_url _links submitted_at commit_id body_html body_text author_association",
    "simple-user": "name email login id node_id avatar_url gravatar_id url html_url followers_url following_url gists_url starred_url subscriptions_url organizations_url repos_url events_url received_events_url type site_admin starred_at user_view_type",
    "organization-simple": "login url id node_id repos_url events_url hooks_url issues_url members_url public_members_url avatar_url description",
    "repository": "id node_id name full_name license forks permissions owner private html_url description fork url archive_url assignees_url blobs_url branches_url collaborators_url comments_url commits_url compare_url contents_url contributors_url deployments_url downloads_url events_url forks_url git_commits_url git_refs_url git_tags_url git_url issue_comment_url issue_events_url issues_url keys_url labels_url languages_url merges_url milestones_url notifications_url pulls_url releases_url ssh_url stargazers_url statuses_url subscribers_url subscription_url tags_url teams_url trees_url clone_url mirror_url hooks_url svn_url homepage language forks_count stargazers_count watchers_count size default_branch open_issues_count is_template topics has_issues has_projects has_wiki has_pages has_downloads has_discussions has_pull_requests pull_request_creation_policy archived disabled visibility pushed_at created_at updated_at allow_rebase_merge temp_clone_token allow_squash_merge allow_auto_merge delete_branch_on_merge allow_update_branch use_squash_pr_title_as_default squash_merge_commit_title squash_merge_commit_message merge_commit_title merge_commit_message allow_merge_commit allow_forking web_commit_signoff_required open_issues watchers master_branch starred_at anonymous_access_enabled code_search_index_status",
    "nullable-repository": "id node_id name full_name license forks permissions owner private html_url description fork url archive_url assignees_url blobs_url branches_url collaborators_url comments_url commits_url compare_url contents_url contributors_url deployments_url downloads_url events_url forks_url git_commits_url git_refs_url git_tags_url git_url issue_comment_url issue_events_url issues_url keys_url labels_url languages_url merges_url milestones_url notifications_url pulls_url releases_url ssh_url stargazers_url statuses_url subscribers_url subscription_url tags_url teams_url trees_url clone_url mirror_url hooks_url svn_url homepage language forks_count stargazers_count watchers_count size default_branch open_issues_count is_template topics has_issues has_projects has_wiki has_pages has_downloads has_discussions has_pull_requests pull_request_creation_policy archived disabled visibility pushed_at created_at updated_at allow_rebase_merge temp_clone_token allow_squash_merge allow_auto_merge delete_branch_on_merge allow_update_branch use_squash_pr_title_as_default squash_merge_commit_title squash_merge_commit_message merge_commit_title merge_commit_message allow_merge_commit allow_forking web_commit_signoff_required open_issues watchers master_branch starred_at anonymous_access_enabled code_search_index_status",
    "minimal-repository": "id node_id name full_name owner private html_url description fork url archive_url assignees_url blobs_url branches_url collaborators_url comments_url commits_url compare_url contents_url contributors_url deployments_url downloads_url events_url forks_url git_commits_url git_refs_url git_tags_url git_url issue_comment_url issue_events_url issues_url keys_url labels_url languages_url merges_url milestones_url notifications_url pulls_url releases_url ssh_url stargazers_url statuses_url subscribers_url subscription_url tags_url teams_url trees_url clone_url mirror_url hooks_url svn_url homepage language forks_count stargazers_count watchers_count size default_branch open_issues_count is_template topics has_issues has_projects has_wiki has_pages has_downloads has_discussions has_pull_requests pull_request_creation_policy archived disabled visibility pushed_at created_at updated_at permissions role_name temp_clone_token delete_branch_on_merge subscribers_count network_count code_of_conduct license forks open_issues watchers allow_forking web_commit_signoff_required security_and_analysis custom_properties",
    "nullable-simple-user": "name email login id node_id avatar_url gravatar_id url html_url followers_url following_url gists_url starred_url subscriptions_url organizations_url repos_url events_url received_events_url type site_admin starred_at user_view_type",
    "team-simple": "id node_id url members_url name description permission privacy notification_setting html_url repositories_url slug ldap_dn type organization_id enterprise_id",
    "integration": "id slug node_id client_id owner name description external_url html_url created_at updated_at permissions events installations_count",
    "issue-type": "id node_id name description color created_at updated_at is_enabled",
    "issue-field-value": "issue_field_id issue_field_name node_id data_type value single_select_option multi_select_options",
    "issue-field-option": "id name color",
    "reaction-rollup": "url total_count +1 -1 laugh confused heart hooray eyes rocket",
    "auto-merge": "enabled_by merge_method commit_title commit_message",
    "pull-request-stack": "base size position id number",
    "pull-request-stack-base": "sha ref",
    "release-asset": "url browser_download_url id node_id name label state content_type size digest download_count created_at updated_at uploader",
    "full-repository": "id node_id name full_name owner private html_url description fork url archive_url assignees_url blobs_url branches_url collaborators_url comments_url commits_url compare_url contents_url contributors_url deployments_url downloads_url events_url forks_url git_commits_url git_refs_url git_tags_url git_url issue_comment_url issue_events_url issues_url keys_url labels_url languages_url merges_url milestones_url notifications_url pulls_url releases_url ssh_url stargazers_url statuses_url subscribers_url subscription_url tags_url teams_url trees_url clone_url mirror_url hooks_url svn_url homepage language forks_count stargazers_count watchers_count size default_branch open_issues_count is_template topics has_issues has_projects has_wiki has_pages has_downloads has_discussions has_pull_requests pull_request_creation_policy archived disabled visibility pushed_at created_at updated_at permissions allow_rebase_merge template_repository temp_clone_token allow_squash_merge allow_auto_merge delete_branch_on_merge allow_merge_commit allow_update_branch use_squash_pr_title_as_default squash_merge_commit_title squash_merge_commit_message merge_commit_title merge_commit_message allow_forking web_commit_signoff_required subscribers_count network_count license organization parent source forks master_branch open_issues watchers anonymous_access_enabled code_of_conduct security_and_analysis custom_properties",
    "issue-dependencies-summary": "blocked_by blocking total_blocked_by total_blocking",
    "sub-issues-summary": "total completed percent_completed",
    "nullable-issue-comment": "id node_id url body body_text body_html html_url user created_at updated_at issue_url author_association performed_via_github_app reactions pin minimized",
    "nullable-pinned-issue-comment": "pinned_at pinned_by",
    "nullable-issue-comment-minimized": "reason",
    "nullable-milestone": "url html_url labels_url id node_id number state title description creator open_issues closed_issues created_at updated_at closed_at due_on",
    "nullable-license-simple": "key name url spdx_id node_id html_url",
    "security-and-analysis": "advanced_security code_security dependabot_security_updates secret_scanning secret_scanning_push_protection secret_scanning_non_provider_patterns secret_scanning_ai_detection secret_scanning_validity_checks secret_scanning_delegated_alert_dismissal secret_scanning_delegated_bypass secret_scanning_delegated_bypass_options",
    "security-and-analysis-validity-checks": "status",
    "security-and-analysis-setting": "status",
    "security-delegated-bypass-options": "reviewers",
    "security-delegated-bypass-reviewer": "reviewer_id reviewer_type mode",
    "code-of-conduct-simple": "url key name html_url",
    "enterprise": "description html_url website_url id node_id name slug created_at updated_at avatar_url",
    "link": "href",
    "label": "id node_id url name description color default archived_at archived_by",
    "nullable-integration": "id slug node_id client_id owner name description external_url html_url created_at updated_at permissions events installations_count",
    "nullable-team-simple": "id node_id url members_url name description permission privacy notification_setting html_url repositories_url slug ldap_dn type organization_id enterprise_id",
    "team": "id node_id name slug description privacy notification_setting permission permissions url html_url members_url repositories_url type access_source organization_id enterprise_id parent",
}
OPENAPI_OBJECT_SCHEMAS = {name: frozenset(fields.split()) for name, fields in OPENAPI_COMPONENTS.items()}
ENDPOINT_SCHEMAS = {
    "repository": OPENAPI_OBJECT_SCHEMAS["full-repository"],
    "issues": OPENAPI_OBJECT_SCHEMAS["issue"],
    "pulls": OPENAPI_OBJECT_SCHEMAS["pull-request-simple"],
    "pull_detail": OPENAPI_OBJECT_SCHEMAS["pull-request"],
    "releases": OPENAPI_OBJECT_SCHEMAS["release"],
    "issue_comments": OPENAPI_OBJECT_SCHEMAS["issue-comment"],
    "pr_comments": OPENAPI_OBJECT_SCHEMAS["pull-request-review-comment"],
    "reviews": OPENAPI_OBJECT_SCHEMAS["pull-request-review"],
}
OPENAPI_REQUIRED_FIELDS = {
    "repository": frozenset("archive_url archived assignees_url blobs_url branches_url clone_url collaborators_url comments_url commits_url compare_url contents_url contributors_url created_at default_branch deployments_url description disabled downloads_url events_url fork forks forks_count forks_url full_name git_commits_url git_refs_url git_tags_url git_url has_downloads has_issues has_pages has_projects has_wiki homepage hooks_url html_url id issue_comment_url issue_events_url issues_url keys_url labels_url language languages_url license merges_url milestones_url mirror_url name node_id notifications_url open_issues open_issues_count owner private pulls_url pushed_at releases_url size ssh_url stargazers_count stargazers_url statuses_url subscribers_url subscription_url svn_url tags_url teams_url trees_url updated_at url watchers watchers_count".split()),
    "minimal-repository": frozenset("archive_url assignees_url blobs_url branches_url collaborators_url comments_url commits_url compare_url contents_url contributors_url deployments_url description downloads_url events_url fork forks_url full_name git_commits_url git_refs_url git_tags_url hooks_url html_url id issue_comment_url issue_events_url issues_url keys_url labels_url languages_url merges_url milestones_url name notifications_url owner private pulls_url releases_url stargazers_url statuses_url subscribers_url subscription_url tags_url teams_url trees_url url node_id".split()),
    "nullable-repository": frozenset("archive_url archived assignees_url blobs_url branches_url clone_url collaborators_url comments_url commits_url compare_url contents_url contributors_url created_at default_branch deployments_url description disabled downloads_url events_url fork forks forks_count forks_url full_name git_commits_url git_refs_url git_tags_url git_url has_downloads has_issues has_pages has_projects has_wiki homepage hooks_url html_url id issue_comment_url issue_events_url issues_url keys_url labels_url language languages_url license merges_url milestones_url mirror_url name node_id notifications_url open_issues open_issues_count owner private pulls_url pushed_at releases_url size ssh_url stargazers_count stargazers_url statuses_url subscribers_url subscription_url svn_url tags_url teams_url trees_url updated_at url watchers watchers_count".split()),
    "full-repository": frozenset("archive_url assignees_url blobs_url branches_url collaborators_url comments_url commits_url compare_url contents_url contributors_url deployments_url description downloads_url events_url fork forks_url full_name git_commits_url git_refs_url git_tags_url hooks_url html_url id node_id issue_comment_url issue_events_url issues_url keys_url labels_url languages_url merges_url milestones_url name notifications_url owner private pulls_url releases_url stargazers_url statuses_url subscribers_url subscription_url tags_url teams_url trees_url url clone_url default_branch forks forks_count git_url has_issues has_projects has_wiki has_pages has_discussions homepage language archived disabled mirror_url open_issues open_issues_count license pushed_at size ssh_url stargazers_count svn_url watchers watchers_count created_at updated_at network_count subscribers_count".split()),
    "issue": frozenset("assignee closed_at comments comments_url events_url html_url id node_id labels labels_url milestone number repository_url state locked title url user created_at updated_at".split()),
    "pull-request-simple": frozenset("_links assignee labels base body closed_at comments_url commits_url created_at diff_url head html_url id node_id issue_url merge_commit_sha merged_at milestone number patch_url review_comment_url review_comments_url statuses_url state locked title updated_at url user author_association auto_merge".split()),
    "pull-request": frozenset("_links assignee labels base body closed_at comments_url commits_url created_at diff_url head html_url id node_id issue_url merge_commit_sha merged_at milestone number patch_url review_comment_url review_comments_url statuses_url state locked title updated_at url user author_association auto_merge additions changed_files comments commits deletions mergeable mergeable_state merged maintainer_can_modify merged_by review_comments".split()),
    "release": frozenset("assets_url upload_url tarball_url zipball_url created_at published_at draft id node_id author html_url name prerelease tag_name target_commitish assets url".split()),
    "issue-comment": frozenset("id node_id html_url issue_url user url created_at updated_at".split()),
    "pull-request-review-comment": frozenset("url id node_id pull_request_review_id diff_hunk path commit_id original_commit_id user body created_at updated_at html_url pull_request_url author_association _links".split()),
    "pull-request-review": frozenset("id node_id user body state commit_id html_url pull_request_url _links author_association".split()),
    "release-asset": frozenset("id name content_type size digest state url node_id download_count label uploader browser_download_url created_at updated_at".split()),
}
TOP_LEVEL_STRUCTURAL_FIELD_TYPES = {
    **{field: int for field in "id number comments review_comments commits additions deletions changed_files download_count size pull_request_review_id in_reply_to_id position original_position line original_line start_line original_start_line forks forks_count stargazers_count watchers_count watchers open_issues open_issues_count subscribers_count network_count".split()},
    **{field: bool for field in "locked draft merged mergeable rebaseable maintainer_can_modify immutable prerelease archived disabled private fork has_issues has_projects has_downloads has_wiki has_pages has_discussions has_pull_requests is_template anonymous_access_enabled allow_update_branch use_squash_pr_title_as_default allow_rebase_merge allow_squash_merge allow_auto_merge delete_branch_on_merge allow_merge_commit allow_forking web_commit_signoff_required".split()},
    **{field: str for field in "node_id state state_reason active_lock_reason mergeable_state author_association created_at updated_at closed_at merged_at published_at submitted_at content_type digest make_latest commit_id original_commit_id merge_commit_sha sha side start_side subject_type".split()},
}
TOP_LEVEL_NULLABLE_STRUCTURAL_FIELDS = {
    "repository": frozenset(),
    "full-repository": frozenset(),
    "nullable-repository": frozenset(),
    "issue": frozenset({"closed_at"}),
    "pull-request-simple": frozenset({"closed_at", "merged_at", "merge_commit_sha"}),
    "pull-request": frozenset({"closed_at", "merged_at", "merge_commit_sha", "mergeable"}),
    "release": frozenset({"published_at"}),
    "issue-comment": frozenset(),
    "pull-request-review-comment": frozenset({"in_reply_to_id", "position", "original_position", "line", "original_line", "start_line", "original_start_line", "side", "start_side"}),
    "pull-request-review": frozenset({"commit_id", "submitted_at"}),
}
TOP_LEVEL_AUTHORED_FIELDS = {
    "issue": frozenset({"title", "body", "body_text", "body_html"}),
    "pull": frozenset({"title", "body", "body_text", "body_html"}),
    "release": frozenset({"name", "body", "body_text", "body_html", "tag_name", "target_commitish", "discussion_url"}),
    "comment": frozenset({"body", "body_text", "body_html", "diff_hunk", "path"}),
    "review": frozenset({"body", "body_text", "body_html"}),
}


def _validate_required_structural_fields(component: str, value: dict) -> None:
    if component not in OPENAPI_REQUIRED_FIELDS or not isinstance(value, dict):
        raise MetadataProjectionError("metadata_schema_unknown")
    required_structural = OPENAPI_REQUIRED_FIELDS[component] & TOP_LEVEL_STRUCTURAL_FIELD_TYPES.keys()
    nullable = TOP_LEVEL_NULLABLE_STRUCTURAL_FIELDS[component]
    for field in required_structural:
        if field not in value:
            continue
        item = value[field]
        expected = TOP_LEVEL_STRUCTURAL_FIELD_TYPES[field]
        if item is None:
            if field not in nullable:
                raise MetadataProjectionError("metadata_shape_unknown")
        elif not isinstance(item, expected) or expected is int and isinstance(item, bool):
            raise MetadataProjectionError("metadata_shape_unknown")


OPENAPI_NESTED_SCHEMAS = {
    # Hand-transcribed nested schemas from the pinned OpenAPI components. Properties omitted here
    # are not admitted; present values must match the listed wire type and enum.
    "nullable-issue-comment-minimized": {
        "required": frozenset({"reason"}),
        "types": {"reason": (str, type(None))},
        "enums": {},
    },
    "issue-pull-request": {
        "required": frozenset({"url", "html_url", "diff_url", "patch_url"}),
        "types": {"url": (str, type(None)), "html_url": (str, type(None)),
                  "diff_url": (str, type(None)), "patch_url": (str, type(None)),
                  "merged_at": (str, type(None))},
        "enums": {},
    },
    "auto-merge": {
        "required": frozenset({"enabled_by", "merge_method", "commit_title", "commit_message"}),
        "types": {"enabled_by": dict, "merge_method": str, "commit_title": str, "commit_message": str},
        "enums": {"merge_method": frozenset({"merge", "squash", "rebase"})},
    },
    "security-and-analysis-setting": {
        "required": frozenset(),
        "types": {"status": str},
        "enums": {"status": frozenset({"enabled", "disabled"})},
    },
    "security-and-analysis-validity-checks": {
        "required": frozenset({"status"}),
        "types": {"status": str},
        "enums": {"status": frozenset({"enabled", "disabled"})},
    },
    "security-delegated-bypass-options": {
        "required": frozenset(),
        "types": {"reviewers": list},
        "enums": {},
    },
    "security-delegated-bypass-reviewer": {
        "required": frozenset({"reviewer_id", "reviewer_type"}),
        "types": {"reviewer_id": int, "reviewer_type": str, "mode": str},
        "enums": {"reviewer_type": frozenset({"TEAM", "ROLE"}), "mode": frozenset({"ALWAYS", "EXEMPT"})},
    },
    "team-simple": {
        "required": frozenset({"id", "node_id", "url", "members_url", "name", "description", "permission", "html_url", "repositories_url", "slug", "type"}),
        "types": {"id": int, "node_id": str, "url": str, "members_url": str, "name": str,
                  "description": (str, type(None)), "permission": str, "privacy": str,
                  "notification_setting": str, "html_url": str, "repositories_url": str, "slug": str,
                  "ldap_dn": str, "type": str, "organization_id": int,
                  "enterprise_id": int},
        "enums": {"type": frozenset({"enterprise", "organization"})},
    },
    "simple-user": {
        "required": frozenset("avatar_url events_url followers_url following_url gists_url gravatar_id html_url id node_id login organizations_url received_events_url repos_url site_admin starred_url subscriptions_url type url".split()),
        "types": {"name": (str, type(None)), "email": (str, type(None)), "login": str, "id": int,
                  "node_id": str, "avatar_url": str, "gravatar_id": (str, type(None)), "url": str,
                  "html_url": str, "followers_url": str, "following_url": str, "gists_url": str,
                  "starred_url": str, "subscriptions_url": str, "organizations_url": str, "repos_url": str,
                  "events_url": str, "received_events_url": str, "type": str, "site_admin": bool,
                  "starred_at": str, "user_view_type": str},
        "enums": {},
    },
    "organization-simple": {
        "required": frozenset("login url id node_id repos_url events_url hooks_url issues_url members_url public_members_url avatar_url description".split()),
        "types": {"login": str, "id": int, "node_id": str, "url": str, "repos_url": str, "events_url": str,
                  "hooks_url": str, "issues_url": str, "members_url": str, "public_members_url": str,
                  "avatar_url": str, "description": (str, type(None))},
        "enums": {},
    },
    "enterprise": {
        "required": frozenset("id node_id name slug html_url created_at updated_at avatar_url".split()),
        "types": {"id": int, "node_id": str, "name": str, "slug": str, "html_url": str,
                  "created_at": (str, type(None)), "updated_at": (str, type(None)), "avatar_url": str,
                  "description": (str, type(None)), "website_url": (str, type(None))},
        "enums": {},
    },
    "nullable-license-simple": {
        "required": frozenset("key name url spdx_id node_id".split()),
        "types": {"key": str, "name": str, "url": (str, type(None)), "spdx_id": (str, type(None)),
                  "node_id": str, "html_url": str},
        "enums": {},
    },
    "code-of-conduct-simple": {
        "required": frozenset({"url", "key", "name", "html_url"}),
        "types": {"url": str, "key": str, "name": str, "html_url": (str, type(None))},
        "enums": {},
    },
    "label": {
        "required": frozenset("id node_id url name description color default archived_at archived_by".split()),
        "types": {"id": int, "node_id": str, "url": str, "name": str, "description": (str, type(None)),
                  "color": str, "default": bool, "archived_at": (str, type(None)),
                  "archived_by": (dict, type(None))},
        "enums": {},
    },
    "nullable-milestone": {
        "required": frozenset("closed_issues creator description due_on closed_at id node_id labels_url html_url number open_issues state title url created_at updated_at".split()),
        "types": {"url": str, "html_url": str, "labels_url": str, "id": int, "node_id": str, "number": int,
                  "state": str, "title": str, "description": (str, type(None)), "creator": dict,
                  "open_issues": int, "closed_issues": int, "created_at": str, "updated_at": str,
                  "closed_at": (str, type(None)), "due_on": (str, type(None))},
        "enums": {"state": frozenset({"open", "closed"})},
    },
    "issue-type": {
        "required": frozenset({"id", "node_id", "name", "description"}),
        "types": {"id": int, "node_id": str, "name": str, "description": (str, type(None)),
                  "color": (str, type(None)), "created_at": str, "updated_at": str, "is_enabled": bool},
        "enums": {"color": frozenset({"gray", "blue", "green", "yellow", "orange", "red", "pink", "purple", None})},
    },
    "issue-field-value": {
        "required": frozenset({"issue_field_id", "node_id", "data_type", "value"}),
        "types": {"issue_field_id": int, "issue_field_name": str, "node_id": str, "data_type": str},
        "enums": {"data_type": frozenset({"text", "single_select", "multi_select", "number", "date"})},
    },
    "issue-field-option": {
        "required": frozenset({"id", "name", "color"}),
        "types": {"id": int, "name": str, "color": str},
        "enums": {},
    },
    "pull-request-stack": {
        "required": frozenset({"base"}),
        "types": {"base": dict, "size": int, "position": int, "id": int, "number": int},
        "enums": {},
    },
    "pull-request-stack-base": {
        "required": frozenset({"sha", "ref"}),
        "types": {"sha": str, "ref": str},
        "enums": {},
    },
    "reaction-rollup": {
        "required": frozenset("url total_count +1 -1 laugh confused heart hooray eyes rocket".split()),
        "types": {"url": str, "total_count": int, "+1": int, "-1": int, "laugh": int, "confused": int,
                  "heart": int, "hooray": int, "eyes": int, "rocket": int},
        "enums": {},
    },
    "sub-issues-summary": {
        "required": frozenset({"total", "completed", "percent_completed"}),
        "types": {"total": int, "completed": int, "percent_completed": int},
        "enums": {},
    },
    "issue-dependencies-summary": {
        "required": frozenset({"blocked_by", "blocking", "total_blocked_by", "total_blocking"}),
        "types": {"blocked_by": int, "blocking": int, "total_blocked_by": int, "total_blocking": int},
        "enums": {},
    },
    "nullable-pinned-issue-comment": {
        "required": frozenset({"pinned_at", "pinned_by"}),
        "types": {"pinned_at": str, "pinned_by": dict},
        "enums": {},
    },
    "nullable-integration": {
        "required": frozenset("id node_id owner name description external_url html_url created_at updated_at permissions events".split()),
        "types": {"id": int, "slug": str, "node_id": str, "client_id": str, "owner": dict, "name": str,
                  "description": (str, type(None)), "external_url": str, "html_url": str, "created_at": str,
                  "updated_at": str, "permissions": dict, "events": list, "installations_count": int},
        "enums": {},
    },
    "release-asset": {
        "required": frozenset("id name content_type size digest state url node_id download_count label uploader browser_download_url created_at updated_at".split()),
        "types": {"id": int, "name": str, "content_type": str, "size": int, "digest": (str, type(None)),
                  "state": str, "url": str, "node_id": str, "download_count": int, "label": (str, type(None)),
                  "uploader": dict, "browser_download_url": str, "created_at": str, "updated_at": str},
        "enums": {"state": frozenset({"uploaded", "open"})},
    },
}
OPENAPI_NESTED_SCHEMAS["nullable-simple-user"] = OPENAPI_NESTED_SCHEMAS["simple-user"]


def _validate_nested_schema(component: str, value: object, *, strict_required: bool = False,
                            allow_extra: bool = False) -> None:
    schema = OPENAPI_NESTED_SCHEMAS.get(component)
    allowed = OPENAPI_OBJECT_SCHEMAS.get(component)
    if schema is None or allowed is None or not isinstance(value, dict):
        raise MetadataProjectionError("metadata_shape_unknown")
    if (not allow_extra and set(value) - allowed) or strict_required and not schema["required"] <= set(value):
        raise MetadataProjectionError("metadata_shape_unknown")
    for field, expected_type in schema["types"].items():
        if field in value:
            item = value[field]
            if not isinstance(item, expected_type):
                raise MetadataProjectionError("metadata_shape_unknown")
            integer_types = ((expected_type,) if isinstance(expected_type, type) else expected_type)
            if int in integer_types and isinstance(item, bool):
                raise MetadataProjectionError("metadata_shape_unknown")
    for field, allowed_values in schema["enums"].items():
        if field in value and value[field] not in allowed_values:
            raise MetadataProjectionError("metadata_shape_unknown")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubTransport:
    """Small bounded GET adapter for the pinned GitHub metadata endpoint set."""
    revision = "engineering.github-metadata-transport.v1"
    redirects_rejected = True
    api_version = "2022-11-28"
    max_body_bytes = 5_000_000
    timeout_seconds = 20

    def __init__(self, verified_account: str, repository: str, token_provider) -> None:
        if not isinstance(verified_account, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", verified_account):
            raise MetadataProjectionError("metadata_binding_unknown")
        if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise MetadataProjectionError("metadata_binding_unknown")
        self.verified_account = verified_account
        self.repository = repository
        self._token_provider = token_provider
        self._token = None
        self._identity_verified = False
        self.identity_transcript = b""
        self._opener = urllib.request.build_opener(_RejectRedirects())

    @staticmethod
    def gh_token_provider(account: str):
        def provide() -> str:
            try:
                result = subprocess.run(["gh", "auth", "token", "--hostname", "github.com", "--user", account],
                                        capture_output=True, text=True, timeout=10, check=True)
            except Exception:
                raise MetadataProjectionError("metadata_auth_unknown") from None
            token = result.stdout.strip()
            if not token or any(ch.isspace() for ch in token):
                raise MetadataProjectionError("metadata_auth_unknown")
            return token
        return provide

    def _request(self, url: str):
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except (TypeError, ValueError):
            raise MetadataProjectionError("metadata_uri_invalid") from None
        if (parsed.scheme != "https" or parsed.hostname != "api.github.com" or parsed.username or parsed.password
                or port or parsed.fragment or "\\" in url or re.search(r"%2f|%5c|%25|\.{1,2}/", parsed.path, re.I)):
            raise MetadataProjectionError("metadata_uri_invalid")
        owner, repo = self.repository.split("/", 1)
        base = f"/repos/{owner}/{repo}"
        identity_route = parsed.path == "/user"
        collection_routes = {
            base: None, base + "/issues": {"state": ["all"], "per_page": ["100"]},
            base + "/pulls": {"state": ["all"], "per_page": ["100"]},
            base + "/releases": {"per_page": ["100"]},
            base + "/issues/comments": {"per_page": ["100"]},
        }
        match = re.fullmatch(re.escape(base) + r"/pulls/([1-9][0-9]*)(/comments|/reviews)?", parsed.path)
        known_path = identity_route or parsed.path in collection_routes or bool(match)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if identity_route:
            known_query = not query
        elif parsed.path in collection_routes:
            required_query = collection_routes[parsed.path]
            known_query = ((required_query is None and not query) or
                           (required_query is not None and all(query.get(k) == v for k, v in required_query.items()
                                                                  ) and set(query) <= set(required_query) | {"page"}
                            and ("page" not in query or (len(query["page"]) == 1 and query["page"][0].isdigit()
                                                           and int(query["page"][0]) >= 1))))
        elif match:
            known_query = (match.group(2) is None and not query) or (
                match.group(2) in {"/comments", "/reviews"} and query.get("per_page") == ["100"]
                and set(query) <= {"per_page", "page"}
                and ("page" not in query or (len(query["page"]) == 1 and query["page"][0].isdigit()
                                                and int(query["page"][0]) >= 1))
            )
        else:
            known_query = False
        if not known_path or not known_query:
            raise MetadataProjectionError("metadata_uri_invalid")
        if self._token is None:
            self._token = self._token_provider()
        token = self._token
        if not isinstance(token, str) or not token or any(ch.isspace() for ch in token):
            raise MetadataProjectionError("metadata_auth_unknown")
        request = urllib.request.Request(url, method="GET", headers={
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version, "User-Agent": "Engineering-Metadata-Collector",
        })
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                status = response.status
                headers = dict(response.headers.items())
                body = response.read(self.max_body_bytes + 1)
        except Exception:
            raise MetadataProjectionError("metadata_transport_unknown") from None
        if len(body) > self.max_body_bytes:
            raise MetadataProjectionError("metadata_transport_unknown")
        if parsed.path == "/user":
            safe_facts = _canonical({"method": "GET", "url": url, "status": status,
                                     "accept": "application/vnd.github+json", "api_version": self.api_version,
                                     "transport_revision": self.revision})
            response_facts = _canonical([[str(key), str(value)] for key, value in headers.items()])
            framed = bytearray()
            for part in (safe_facts, response_facts, body):
                framed.extend(len(part).to_bytes(8, "big"))
                framed.extend(part)
            self.identity_transcript = bytes(framed)
        return status, headers, body

    def verify_identity(self) -> None:
        if not self._identity_verified:
            identity_url = "https://api.github.com/user"
            identity_status, _identity_headers, identity_body = self._request(identity_url)
            try:
                actual = _strict_json(identity_body)
            except Exception:
                raise MetadataProjectionError("metadata_auth_unknown") from None
            if identity_status != 200 or not isinstance(actual, dict) or actual.get("login") != self.verified_account:
                raise MetadataProjectionError("metadata_auth_unknown")
            self._identity_verified = True
    @property
    def identity_verified(self) -> bool:
        return self._identity_verified

    def get(self, url: str):
        self.verify_identity()
        status, headers, body = self._request(url)
        return status, headers, body

    __call__ = get


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_json(body: bytes):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    def reject_constant(_value):
        raise ValueError("nonfinite_json_number")
    return json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=unique_pairs,
                      parse_constant=reject_constant)


def _text_leaves(value: object, *, exclude_keys: frozenset[str] = frozenset()) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _text_leaves(item, exclude_keys=exclude_keys)]
    if isinstance(value, dict):
        return [text for key, item in value.items() if key not in exclude_keys
                for text in _text_leaves(item, exclude_keys=frozenset() if key == "custom_properties" else exclude_keys)]
    return []


class VerifiedCollection:
    def __init__(self, snapshot: dict, raw_transcript: bytes, receipt: dict, nonce: str,
                 production_verified: bool = False) -> None:
        self.snapshot = snapshot
        self.raw_transcript = raw_transcript
        self.receipt = receipt
        self._nonce = nonce
        self.production_verified = production_verified


def _coverage_complete(coverage: object, pr_numbers: list[int], binding_pr: int) -> bool:
    if not isinstance(coverage, list) or not coverage:
        return False
    seen: set[tuple[str, int | None, int]] = set()
    for page in coverage:
        if (not isinstance(page, dict) or set(page) != {"endpoint", "pr", "page", "item_count", "terminal"}
                or page["endpoint"] not in {"repository", "issues", "pulls", "pull_detail", "releases", "issue_comments", "pr_comments", "reviews", "binding_readback"}
                or not isinstance(page["page"], int) or isinstance(page["page"], bool) or page["page"] < 1
                or not isinstance(page["item_count"], int) or isinstance(page["item_count"], bool) or page["item_count"] < 0
                or not isinstance(page["terminal"], bool)):
            return False
        endpoint, pr, number = page["endpoint"], page.get("pr"), page["page"]
        if endpoint in {"pull_detail", "pr_comments", "reviews", "binding_readback"} and pr not in pr_numbers:
            return False
        if endpoint in {"repository", "issues", "pulls", "releases", "issue_comments"} and pr is not None:
            return False
        if endpoint == "repository" and (number != 1 or page["item_count"] != 1 or not page["terminal"]):
            return False
        if endpoint == "pull_detail" and (number != 1 or page["item_count"] != 1 or not page["terminal"]):
            return False
        if endpoint == "binding_readback" and (number != 1 or page["item_count"] != 1 or not page["terminal"]):
            return False
        if endpoint == "binding_readback" and pr != binding_pr:
            return False
        key = (endpoint, pr, number)
        if key in seen:
            return False
        seen.add(key)
    endpoints = {item["endpoint"] for item in coverage}
    if not {"repository", "issues", "pulls", "releases", "issue_comments"} <= endpoints:
        return False
    if sum(item["item_count"] for item in coverage if item["endpoint"] == "pulls") != len(pr_numbers):
        return False
    if any(not any(item["endpoint"] == "pull_detail" and item.get("pr") == pr for item in coverage) for pr in pr_numbers):
        return False
    if sum(item["endpoint"] == "binding_readback" for item in coverage) != 1:
        return False
    if any(not any(item["endpoint"] == kind and item.get("pr") == pr for item in coverage)
           for pr in pr_numbers for kind in ("pr_comments", "reviews")):
        return False
    expected_endpoints = {"repository", "issues", "pulls", "releases", "issue_comments", "pull_detail", "pr_comments", "reviews", "binding_readback"}
    if endpoints != expected_endpoints and not (not pr_numbers and endpoints == expected_endpoints - {"pull_detail", "pr_comments", "reviews", "binding_readback"}):
        return False
    for endpoint in {item["endpoint"] for item in coverage}:
        selected = [item for item in coverage if item["endpoint"] == endpoint]
        by_pr = {(item.get("pr")) for item in selected}
        for pr in by_pr:
            pages = sorted(item["page"] for item in selected if item.get("pr") == pr)
            if pages != list(range(1, len(pages) + 1)):
                return False
            terminals = [item["page"] for item in selected if item.get("pr") == pr and item["terminal"]]
            if terminals != [pages[-1]]:
                return False
    return True


def _project_repository(value: object, repository: str, *, include_identity_text: bool = False, depth: int = 0,
                        component: str = "full-repository", strict_required: bool = False) -> dict:
    if depth > 3:
        raise MetadataProjectionError("metadata_schema_unknown")
    template_tails = {
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
    scalar_fields = {
        "id", "node_id", "name", "full_name", "owner", "private", "html_url", "description", "fork", "url",
        *template_tails, "git_url", "ssh_url", "clone_url", "mirror_url", "svn_url", "homepage", "license", "language",
        "forks_count", "forks", "stargazers_count", "watchers_count", "watchers", "size", "default_branch",
        "open_issues_count", "open_issues", "is_template", "topics", "has_issues", "has_projects", "has_downloads",
        "has_wiki", "has_pages", "has_discussions", "archived", "disabled", "visibility", "pushed_at", "created_at",
        "updated_at", "permissions", "allow_rebase_merge", "temp_clone_token", "allow_squash_merge", "allow_auto_merge",
        "delete_branch_on_merge", "allow_merge_commit", "allow_forking", "web_commit_signoff_required", "subscribers_count",
        "network_count", "organization", "has_pull_requests", "pull_request_creation_policy", "allow_update_branch",
        "use_squash_pr_title_as_default", "squash_merge_commit_title", "squash_merge_commit_message",
        "merge_commit_title", "merge_commit_message", "anonymous_access_enabled", "master_branch",
        "code_search_index_status", "security_and_analysis", "template_repository", "parent", "source",
        "code_of_conduct", "custom_properties", "role_name",
    }
    authored = {"description", "homepage", "default_branch", "mirror_url", "master_branch", "role_name"}
    if include_identity_text:
        authored.update({"name", "full_name"})
    required = {"id", "node_id", "name", "full_name", "private", "url", "html_url"}
    component_fields = OPENAPI_OBJECT_SCHEMAS.get(component)
    if (component_fields is None or not isinstance(value, dict) or set(value) - scalar_fields
            or set(value) - component_fields or not required <= set(value)):
        raise MetadataProjectionError("metadata_shape_unknown")
    if strict_required and not OPENAPI_REQUIRED_FIELDS.get(component, frozenset()) <= set(value):
        raise MetadataProjectionError("metadata_schema_unknown")
    if strict_required:
        _validate_required_structural_fields(component, value)
    string_fields = {"node_id", "name", "full_name", "description", "default_branch", "master_branch", "role_name",
                     "git_url", "ssh_url", "clone_url",
                     "mirror_url", "svn_url", "homepage", "language", "visibility", "pushed_at", "created_at", "updated_at",
                     "temp_clone_token", "pull_request_creation_policy", "squash_merge_commit_title", "squash_merge_commit_message",
                     "merge_commit_title", "merge_commit_message", "code_search_index_status"}
    bool_fields = {"private", "fork", "is_template", "has_issues", "has_projects", "has_downloads", "has_wiki", "has_pages",
                   "has_discussions", "has_pull_requests", "anonymous_access_enabled", "allow_update_branch",
                   "use_squash_pr_title_as_default", "archived", "disabled", "allow_rebase_merge", "allow_squash_merge", "allow_auto_merge",
                   "delete_branch_on_merge", "allow_merge_commit", "allow_forking", "web_commit_signoff_required"}
    int_fields = {"id", "forks_count", "forks", "stargazers_count", "watchers_count", "watchers", "size", "open_issues_count",
                  "open_issues", "subscribers_count", "network_count"}
    for field in string_fields:
        if field in value and value[field] is not None and not isinstance(value[field], str):
            raise MetadataProjectionError("metadata_shape_unknown")
    for field in bool_fields:
        if field in value and value[field] is not None and not isinstance(value[field], bool):
            raise MetadataProjectionError("metadata_shape_unknown")
    for field in int_fields:
        if field in value and value[field] is not None and (not isinstance(value[field], int) or isinstance(value[field], bool)):
            raise MetadataProjectionError("metadata_shape_unknown")
    if "topics" in value and (not isinstance(value["topics"], list) or any(not isinstance(topic, str) for topic in value["topics"])):
        raise MetadataProjectionError("metadata_shape_unknown")
    if value.get("full_name") != repository or not isinstance(value.get("name"), str):
        raise MetadataProjectionError("metadata_binding_unknown")
    api_base = "https://api.github.com/repos/" + repository
    exact_urls = {
        "url": api_base,
        "html_url": "https://github.com/" + repository,
        **{field: api_base + tail for field, tail in template_tails.items()},
        "clone_url": "https://github.com/" + repository + ".git",
        "ssh_url": "git" + "@github.com:" + repository + ".git",
        "git_url": "git://github.com/" + repository + ".git",
        "svn_url": "https://github.com/" + repository,
    }
    for field, expected in exact_urls.items():
        if field in value and value[field] != expected:
            raise MetadataProjectionError("metadata_uri_invalid")
    owner = value.get("owner")
    owner_text = []
    if "owner" in value:
        owner_text = _validate_embedded_simple_user(owner, "simple-user", strict_required=strict_required)
        if owner["login"].casefold() != repository.split("/", 1)[0].casefold():
            raise MetadataProjectionError("metadata_binding_unknown")
    if "organization" in value and value["organization"] is not None:
        organization = value["organization"]
        organization_text = _validate_embedded_simple_user(
            organization, "nullable-simple-user", strict_required=strict_required
        )
        if (not isinstance(owner, dict) or not isinstance(owner.get("id"), int)
                or isinstance(owner.get("id"), bool) or not isinstance(owner.get("node_id"), str)
                or not isinstance(organization.get("id"), int) or isinstance(organization.get("id"), bool)
                or not isinstance(organization.get("node_id"), str) or owner.get("type") != "Organization"
                or organization.get("type") != "Organization"
                or organization["login"].casefold() != owner["login"].casefold()
                or organization.get("id") != owner.get("id")
                or organization.get("node_id") != owner.get("node_id")):
            raise MetadataProjectionError("metadata_binding_unknown")
        owner_text.extend(organization_text)
    if "license" in value and value["license"] is not None:
        license_value = value["license"]
        if (not isinstance(license_value, dict)
                or set(license_value) - {"key", "name", "url", "spdx_id", "node_id", "html_url"}):
            raise MetadataProjectionError("metadata_shape_unknown")
        _validate_nested_schema("nullable-license-simple", license_value, strict_required=strict_required)
        for field in ("name", "spdx_id", "node_id", "url", "html_url"):
            if field in license_value and license_value[field] is not None and not isinstance(license_value[field], str):
                raise MetadataProjectionError("metadata_shape_unknown")
        for field in ("name", "spdx_id"):
            if isinstance(license_value.get(field), str):
                authored.add("license." + field)
        key = license_value.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9.-]{1,80}", key):
            raise MetadataProjectionError("metadata_shape_unknown")
        if license_value.get("url") is not None and license_value["url"] != f"https://api.github.com/licenses/{key}":
            raise MetadataProjectionError("metadata_uri_invalid")
        if license_value.get("html_url") is not None and license_value["html_url"] != f"https://github.com/licenses/{key}":
            raise MetadataProjectionError("metadata_uri_invalid")
    if "permissions" in value:
        permissions = value["permissions"]
        if not isinstance(permissions, dict) or set(permissions) - {"pull", "push", "admin", "maintain", "triage"} or any(not isinstance(flag, bool) for flag in permissions.values()):
            raise MetadataProjectionError("metadata_shape_unknown")
    projected = {key: value[key] for key in authored if isinstance(value.get(key), str)}
    if isinstance(value.get("license"), dict):
        projected["license"] = {key: value["license"][key] for key in ("name", "spdx_id")
                                 if isinstance(value["license"].get(key), str)}
    topics = value.get("topics", [])
    if not isinstance(topics, list) or any(not isinstance(item, str) for item in topics):
        raise MetadataProjectionError("metadata_shape_unknown")
    projected["topics"] = topics
    if owner_text:
        projected.setdefault("nested_text", []).extend(owner_text)
    for field in ("parent", "source", "template_repository"):
        nested_repo = value.get(field)
        if nested_repo is None:
            continue
        if not isinstance(nested_repo, dict) or not isinstance(nested_repo.get("full_name"), str):
            raise MetadataProjectionError("metadata_shape_unknown")
        child_component = "minimal-repository" if field == "template_repository" else "nullable-repository"
        projected[field] = _project_repository(nested_repo, nested_repo["full_name"],
                                               include_identity_text=True, depth=depth + 1,
                                               component=child_component,
                                               strict_required=strict_required)["repository"]
    properties = value.get("custom_properties", {})
    if not isinstance(properties, dict) or any(not isinstance(key, str) for key in properties):
        raise MetadataProjectionError("metadata_shape_unknown")
    projected_properties = {}
    for key, item in properties.items():
        if item is None or isinstance(item, str):
            projected_properties[key] = item
        elif isinstance(item, list) and all(isinstance(part, str) for part in item):
            projected_properties[key] = item
        else:
            raise MetadataProjectionError("metadata_shape_unknown")
    if projected_properties:
        projected["custom_properties"] = projected_properties
        projected.setdefault("nested_text", []).extend(projected_properties)
        projected.setdefault("nested_text", []).extend(_text_leaves(projected_properties))
    if "security_and_analysis" in value:
        analysis = value["security_and_analysis"]
        allowed_analysis = {"advanced_security", "code_security", "dependabot_security_updates", "secret_scanning",
                            "secret_scanning_push_protection", "secret_scanning_non_provider_patterns",
                            "secret_scanning_ai_detection", "secret_scanning_validity_checks", "secret_scanning_delegated_alert_dismissal",
                            "secret_scanning_delegated_bypass", "secret_scanning_delegated_bypass_options"}
        if analysis is not None and (not isinstance(analysis, dict) or set(analysis) - allowed_analysis):
            raise MetadataProjectionError("metadata_shape_unknown")
        for feature, setting in (analysis or {}).items():
            if not isinstance(setting, dict):
                raise MetadataProjectionError("metadata_shape_unknown")
            if feature == "secret_scanning_validity_checks":
                _validate_nested_schema("security-and-analysis-validity-checks", setting, strict_required=True)
            elif feature == "secret_scanning_delegated_bypass_options":
                _validate_nested_schema("security-delegated-bypass-options", setting)
                reviewers = setting.get("reviewers", [])
                for reviewer in reviewers:
                    _validate_nested_schema("security-delegated-bypass-reviewer", reviewer, strict_required=True)
            else:
                _validate_nested_schema("security-and-analysis-setting", setting)
                if set(setting) - {"status"}:
                    raise MetadataProjectionError("metadata_shape_unknown")
    if "code_of_conduct" in value and value["code_of_conduct"] is not None:
        conduct = value["code_of_conduct"]
        if (not isinstance(conduct, dict) or set(conduct) - {"url", "key", "name", "html_url"}
                or not isinstance(conduct.get("key"), str)):
            raise MetadataProjectionError("metadata_shape_unknown")
        _validate_nested_schema("code-of-conduct-simple", conduct, strict_required=strict_required)
        expected_conduct_url = f"https://api.github.com/codes_of_conduct/{quote(conduct['key'], safe='')}"
        if conduct.get("url") != expected_conduct_url:
            raise MetadataProjectionError("metadata_uri_invalid")
        conduct_html_url = conduct.get("html_url")
        if conduct_html_url is not None:
            try:
                parsed_conduct_html = urlsplit(conduct_html_url)
                port = parsed_conduct_html.port
            except (TypeError, ValueError):
                raise MetadataProjectionError("metadata_uri_invalid") from None
            default_branch = value.get("default_branch")
            expected_prefix = (f"/{repository}/blob/{quote(default_branch, safe='/')}"
                               if isinstance(default_branch, str) and default_branch else None)
            suffix = (parsed_conduct_html.path[len(expected_prefix) + 1:]
                      if expected_prefix and parsed_conduct_html.path.startswith(expected_prefix + "/") else None)
            if (parsed_conduct_html.scheme != "https" or parsed_conduct_html.hostname != "github.com"
                    or parsed_conduct_html.username or parsed_conduct_html.password or port is not None
                    or parsed_conduct_html.query or parsed_conduct_html.fragment or suffix not in {
                        "CODE_OF_CONDUCT", "CODE_OF_CONDUCT.md", ".github/CODE_OF_CONDUCT.md",
                        "docs/CODE_OF_CONDUCT.md"}):
                raise MetadataProjectionError("metadata_uri_invalid")
        for key in ("name", "key"):
            if isinstance(conduct.get(key), str):
                projected.setdefault("nested_text", []).append(conduct[key])
    return {"repository": projected}


def _project_pull(value: object, repository: str, *, schema_component: str = "pull-request",
                  strict_required: bool = False) -> dict:
    if not isinstance(value, dict):
        raise MetadataProjectionError("metadata_shape_unknown")
    if (schema_component not in OPENAPI_OBJECT_SCHEMAS or set(value) - OPENAPI_OBJECT_SCHEMAS[schema_component]
            or strict_required and not OPENAPI_REQUIRED_FIELDS.get(schema_component, frozenset()) <= set(value)):
        raise MetadataProjectionError("metadata_schema_unknown")
    if strict_required:
        _validate_required_structural_fields(schema_component, value)
    nested = dict(value)
    authored_head_base: list[str] = []
    head_sha = None
    for name in ("head", "base"):
        part = nested.pop(name, None)
        if strict_required and not isinstance(part, dict):
            raise MetadataProjectionError("metadata_shape_unknown")
        if part is not None:
            if not isinstance(part, dict) or set(part) - {"sha", "ref", "label", "user", "repo"}:
                raise MetadataProjectionError("metadata_shape_unknown")
            if strict_required and not {"label", "ref", "sha", "user", "repo"} <= set(part):
                raise MetadataProjectionError("metadata_shape_unknown")
            for field in ("sha",):
                if field in part and (not isinstance(part[field], str)
                                      or not re.fullmatch(r"[0-9a-f]{40}", part[field])):
                    raise MetadataProjectionError("metadata_shape_unknown")
            if name == "head":
                head_sha = part.get("sha")
            for field in ("ref", "label"):
                if field in part and not isinstance(part[field], str):
                    raise MetadataProjectionError("metadata_shape_unknown")
            if "user" in part:
                user = part["user"]
                if user is None:
                    if schema_component != "pull-request-simple":
                        raise MetadataProjectionError("metadata_shape_unknown")
                else:
                    authored_head_base.extend(_validate_embedded_simple_user(
                        user, "simple-user", strict_required=strict_required))
            if isinstance(part.get("label"), str) and ":" in part["label"]:
                label_owner = part["label"].split(":", 1)[0]
                expected_owner = repository.split("/", 1)[0]
                if isinstance(part.get("repo"), dict) and isinstance(part["repo"].get("full_name"), str):
                    expected_owner = part["repo"]["full_name"].split("/", 1)[0]
                if label_owner.casefold() != expected_owner.casefold():
                    raise MetadataProjectionError("metadata_binding_unknown")
            repo_value = part.get("repo")
            if strict_required and not isinstance(repo_value, dict):
                raise MetadataProjectionError("metadata_shape_unknown")
            if repo_value is not None:
                if not isinstance(repo_value, dict) or not isinstance(repo_value.get("full_name"), str):
                    raise MetadataProjectionError("metadata_binding_unknown")
                repo_name = repo_value["full_name"]
                if name == "base" and repo_name.casefold() != repository.casefold():
                    raise MetadataProjectionError("metadata_binding_unknown")
                projected_repo = _project_repository(repo_value, repo_name, include_identity_text=True,
                                                     component="repository",
                                                     strict_required=strict_required)["repository"]
                for field in ("name", "full_name", "description", "homepage", "default_branch", "mirror_url", "topics", "license", "custom_properties", "nested_text"):
                    authored_head_base.extend(_text_leaves(projected_repo.get(field)))
            authored_head_base.extend(text for text in (part.get("label"), part.get("ref")) if isinstance(text, str))
    projected = project_record("pull", nested, repository,
                               schema_endpoint="pulls" if schema_component == "pull-request-simple" else "pull_detail",
                               strict_required=strict_required, head_sha=head_sha,
                               _top_level_required_validated=strict_required)
    if authored_head_base:
        projected.setdefault("nested_text", []).extend(authored_head_base)
    return projected


def _project_label(value: object, repository: str, *, strict_required: bool = False) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, dict) or set(value) - OPENAPI_OBJECT_SCHEMAS["label"]:
        raise MetadataProjectionError("metadata_shape_unknown")
    if not isinstance(value.get("name"), str):
        raise MetadataProjectionError("metadata_shape_unknown")
    _validate_nested_schema("label", value, strict_required=strict_required)
    for key in ("id",):
        if key in value and (not isinstance(value[key], int) or isinstance(value[key], bool)):
            raise MetadataProjectionError("metadata_shape_unknown")
    for key in ("description", "color", "archived_at", "node_id"):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            raise MetadataProjectionError("metadata_shape_unknown")
    if "default" in value and not isinstance(value["default"], bool):
        raise MetadataProjectionError("metadata_shape_unknown")
    authored = [value[key] for key in ("name", "description", "color", "archived_at")
                if isinstance(value.get(key), str)]
    if value.get("archived_by") is not None:
        _validate_actor(value["archived_by"], strict_required=strict_required)
        for key in ("name", "email"):
            if isinstance(value["archived_by"].get(key), str):
                authored.append(value["archived_by"][key])
    if "url" in value:
        expected = f"https://api.github.com/repos/{repository}/labels/{quote(value['name'], safe='')}"
        if value["url"] != expected:
            raise MetadataProjectionError("metadata_uri_invalid")
    return authored


def _fetch_pages(url: str, endpoint: str, pr: int | None, fetch) -> tuple[list[object], list[dict], bytearray]:
    records: list[object] = []
    coverage: list[dict] = []
    transcript = bytearray()
    seen: set[str] = set()
    seen_records: set[tuple[str, object]] = set()
    page_number = 1
    while True:
        if page_number > 100:
            raise MetadataProjectionError("metadata_pagination_unknown")
        if url in seen:
            raise MetadataProjectionError("metadata_pagination_unknown")
        seen.add(url)
        try:
            status, headers, body = fetch(url)
        except Exception:
            raise MetadataProjectionError("metadata_transport_unknown") from None
        if status != 200 or not isinstance(headers, dict) or not isinstance(body, bytes) or len(body) > GitHubTransport.max_body_bytes:
            raise MetadataProjectionError("metadata_transport_unknown")
        header_bytes = _canonical([[str(key), str(value)] for key, value in headers.items()])
        for part in (url.encode("utf-8"), str(status).encode("ascii"), header_bytes, body):
            transcript.extend(len(part).to_bytes(8, "big"))
            transcript.extend(part)
        try:
            payload = _strict_json(body)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise MetadataProjectionError("metadata_schema_unknown") from None
        if not isinstance(payload, list):
            raise MetadataProjectionError("metadata_schema_unknown")
        link = next((value for key, value in headers.items() if str(key).casefold() == "link"), "")
        next_url = None
        last_page = None
        seen_relations = set()
        if link:
            for component in link.split(","):
                match = re.fullmatch(r'\s*<([^<>]+)>\s*;\s*rel="([a-z]+)"\s*', component)
                if not match:
                    raise MetadataProjectionError("metadata_pagination_unknown")
                candidate, relation = match.groups()
                if relation in seen_relations:
                    raise MetadataProjectionError("metadata_pagination_unknown")
                seen_relations.add(relation)
                try:
                    parsed = urlsplit(candidate)
                    current = urlsplit(url)
                    port = parsed.port
                except ValueError:
                    raise MetadataProjectionError("metadata_pagination_unknown") from None
                if (parsed.scheme != "https" or parsed.netloc != "api.github.com" or parsed.path != current.path
                        or parsed.fragment or parsed.username or parsed.password or port):
                    raise MetadataProjectionError("metadata_pagination_unknown")
                query = parse_qs(parsed.query, keep_blank_values=True)
                current_query = parse_qs(current.query, keep_blank_values=True)
                current_page = int(current_query.pop("page", ["1"])[0])
                expected_base = dict(current_query)
                if set(query) != set(expected_base) | {"page"} or any(query.get(key) != value for key, value in expected_base.items()):
                    raise MetadataProjectionError("metadata_pagination_unknown")
                if "page" not in query or len(query["page"]) != 1 or not query["page"][0].isdigit():
                    raise MetadataProjectionError("metadata_pagination_unknown")
                linked_page = int(query["page"][0])
                if relation == "next":
                    if linked_page != page_number + 1 or next_url is not None:
                        raise MetadataProjectionError("metadata_pagination_unknown")
                    next_url = candidate
                elif relation == "first" and linked_page != 1:
                    raise MetadataProjectionError("metadata_pagination_unknown")
                elif relation == "prev" and linked_page != max(1, current_page - 1):
                    raise MetadataProjectionError("metadata_pagination_unknown")
                elif relation == "prev" and current_page == 1:
                    raise MetadataProjectionError("metadata_pagination_unknown")
                elif relation == "last":
                    if linked_page < page_number:
                        raise MetadataProjectionError("metadata_pagination_unknown")
                    last_page = linked_page
                elif relation not in {"first", "prev", "last"}:
                    raise MetadataProjectionError("metadata_pagination_unknown")
        coverage.append({"endpoint": endpoint, "pr": pr, "page": page_number,
                         "item_count": len(payload), "terminal": next_url is None})
        if last_page is not None and (next_url is None and last_page > page_number
                                      or next_url is not None and int(parse_qs(urlsplit(next_url).query)["page"][0]) > last_page):
            raise MetadataProjectionError("metadata_pagination_unknown")
        for record in payload:
            if isinstance(record, dict):
                record_id = record.get("id", record.get("number"))
                if isinstance(record_id, int) and not isinstance(record_id, bool):
                    identity = (endpoint, record_id)
                    if identity in seen_records:
                        raise MetadataProjectionError("metadata_pagination_unknown")
                    seen_records.add(identity)
        records.extend(payload)
        if next_url is None:
            break
        if not payload:
            raise MetadataProjectionError("metadata_pagination_unknown")
        url, page_number = next_url, page_number + 1
    return records, coverage, transcript


def _fetch_object(url: str, fetch) -> tuple[dict, bytes]:
    try:
        status, headers, body = fetch(url)
    except Exception:
        raise MetadataProjectionError("metadata_transport_unknown") from None
    if status != 200 or not isinstance(headers, dict) or not isinstance(body, bytes) or len(body) > GitHubTransport.max_body_bytes:
        raise MetadataProjectionError("metadata_transport_unknown")
    try:
        payload = _strict_json(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise MetadataProjectionError("metadata_schema_unknown") from None
    if not isinstance(payload, dict):
        raise MetadataProjectionError("metadata_schema_unknown")
    headers_raw = _canonical([[str(key), str(value)] for key, value in headers.items()])
    transcript = bytearray()
    for part in (url.encode("utf-8"), str(status).encode("ascii"), headers_raw, body):
        transcript.extend(len(part).to_bytes(8, "big"))
        transcript.extend(part)
    return payload, bytes(transcript)


def collect_metadata(audience: str, repository: str, local_commit: str, remote_head: str,
                     binding_pr: int, fetch, *, head_repository: str | None = None,
                     head_ref: str | None = None) -> VerifiedCollection:
    """Collect through an injected transport and always issue a synthetic receipt."""
    return _collect_metadata(audience, repository, local_commit, remote_head, binding_pr, fetch,
                             head_repository=head_repository, head_ref=head_ref)


def _collect_metadata(audience: str, repository: str, local_commit: str, remote_head: str,
                      binding_pr: int, fetch, *, head_repository: str | None = None,
                      head_ref: str | None = None,
                      strict_required: bool = False) -> VerifiedCollection:
    """Collect bounded REST pages and issue only a synthetic receipt."""
    if (audience not in {"source", "distribution"} or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not re.fullmatch(r"[0-9a-f]{40}", local_commit) or not re.fullmatch(r"[0-9a-f]{40}", remote_head)
            or not isinstance(binding_pr, int) or isinstance(binding_pr, bool) or binding_pr < 1
            or not callable(fetch) or not isinstance(strict_required, bool)):
        raise MetadataProjectionError("metadata_binding_unknown")
    strict_binding = head_repository is not None or head_ref is not None
    if strict_binding and (not isinstance(head_repository, str)
                           or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", head_repository)
                           or not isinstance(head_ref, str) or not head_ref):
        raise MetadataProjectionError("metadata_binding_unknown")
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    base = "https://api.github.com/repos/" + repository
    transcript = bytearray()
    repository_data, raw = _fetch_object(base, fetch)
    transcript.extend(raw)
    repository_projection = _project_repository(repository_data, repository, include_identity_text=True,
                                                strict_required=strict_required)
    coverage: list[dict] = [{"endpoint": "repository", "pr": None, "page": 1, "item_count": 1, "terminal": True}]
    surfaces = {name: [] for name in SURFACES}
    endpoint_sets = (
        ("issues", "/issues?state=all&per_page=100", "issues", "issue"),
        ("pulls", "/pulls?state=all&per_page=100", "pulls", "pull"),
        ("releases", "/releases?per_page=100", "releases", "release"),
        ("issue_comments", "/issues/comments?per_page=100", "comments", "comment"),
    )
    pull_summaries: list[tuple[dict, dict]] = []
    for endpoint, route, surface, kind in endpoint_sets:
        rows, pages, raw = _fetch_pages(base + route, endpoint, None, fetch)
        coverage.extend(pages)
        transcript.extend(raw)
        for row in rows:
            if endpoint == "pulls":
                if not isinstance(row, dict) or not isinstance(row.get("number"), int) or row["number"] < 1:
                    raise MetadataProjectionError("metadata_schema_unknown")
                summary_projection = _project_pull(row, repository, schema_component="pull-request-simple",
                                                   strict_required=strict_required)
                pull_summaries.append((row, summary_projection))
                continue
            projected = project_record(kind, row, repository, schema_endpoint=endpoint,
                                       strict_required=strict_required)
            if isinstance(row, dict) and isinstance(row.get("number"), int):
                projected["number"] = row["number"]
            surfaces[surface].append(projected)
    # Preserve repository authored text in the unchanged snapshot schema for scanning.
    surfaces["issues"].append(repository_projection)
    binding_seen = 0
    for summary, summary_projection in pull_summaries:
        number = summary["number"]
        if number < 1 or any(item.get("number") == number for item in surfaces["pull_requests"]):
            raise MetadataProjectionError("metadata_schema_unknown")
        detail, raw = _fetch_object(base + f"/pulls/{number}", fetch)
        transcript.extend(raw)
        coverage.append({"endpoint": "pull_detail", "pr": number, "page": 1, "item_count": 1, "terminal": True})
        if (detail.get("number") != number or detail.get("id") != summary.get("id")
                or not isinstance(detail.get("id"), int) or detail["id"] < 1):
            raise MetadataProjectionError("metadata_binding_unknown")
        for row in (summary, detail):
            head = row.get("head")
            base_part = row.get("base")
            if (not isinstance(head, dict) or not isinstance(head.get("sha"), str)
                    or not isinstance(base_part, dict) or not isinstance(base_part.get("sha"), str)):
                raise MetadataProjectionError("metadata_schema_unknown")
            head_repo = head.get("repo")
            base_repo = base_part.get("repo")
            if strict_binding and (not isinstance(head_repo, dict) or not isinstance(base_repo, dict)
                                   or base_repo.get("full_name", "").casefold() != repository.casefold()
                                   or not isinstance(head_repo.get("full_name"), str)):
                raise MetadataProjectionError("metadata_binding_unknown")
            if number == binding_pr:
                if head["sha"] != remote_head:
                    raise MetadataProjectionError("metadata_binding_unknown")
                if strict_binding and (head_repo.get("full_name", "").casefold() != head_repository.casefold()
                                       or head.get("ref") != head_ref):
                    raise MetadataProjectionError("metadata_binding_unknown")
        if number == binding_pr:
            binding_seen += 1
        projected = _project_pull(detail, repository, strict_required=strict_required)
        projected.setdefault("nested_text", []).extend(_text_leaves(summary_projection))
        projected["number"] = number
        surfaces["pull_requests"].append(projected)
        for endpoint, route, surface, kind in (
            ("pr_comments", f"/pulls/{number}/comments?per_page=100", "comments", "comment"),
            ("reviews", f"/pulls/{number}/reviews?per_page=100", "reviews", "review"),
        ):
            rows, pages, raw = _fetch_pages(base + route, endpoint, number, fetch)
            coverage.extend(pages)
            transcript.extend(raw)
            for row in rows:
                projected_row = project_record(kind, row, repository, schema_endpoint=endpoint,
                                                strict_required=strict_required,
                                                parent_number=number)
                if isinstance(row, dict) and isinstance(row.get("id"), int):
                    projected_row["id"] = row["id"]
                surfaces[surface].append(projected_row)
    if binding_seen != 1:
        raise MetadataProjectionError("metadata_binding_unknown")
    binding_summary = next(row for row, _projection in pull_summaries if row["number"] == binding_pr)
    readback, raw = _fetch_object(base + f"/pulls/{binding_pr}", fetch)
    transcript.extend(raw)
    coverage.append({"endpoint": "binding_readback", "pr": binding_pr, "page": 1, "item_count": 1, "terminal": True})
    if (readback.get("id") != binding_summary.get("id") or readback.get("number") != binding_pr
            or readback.get("head", {}).get("sha") != remote_head):
        raise MetadataProjectionError("metadata_binding_unknown")
    if strict_binding and (readback.get("head", {}).get("repo", {}).get("full_name", "").casefold() != head_repository.casefold()
                           or readback.get("head", {}).get("ref") != head_ref
                           or readback.get("base", {}).get("repo", {}).get("full_name", "").casefold() != repository.casefold()):
        raise MetadataProjectionError("metadata_binding_unknown")
    snapshot = {"schema": "engineering.audience-metadata-snapshot.v1", "audience": audience,
                "source_commit": local_commit, "surfaces": surfaces}
    collection = _issue_receipt(snapshot, bytes(transcript), repository=repository, local_commit=local_commit,
                                remote_head=remote_head, binding_pr=binding_pr, coverage=coverage,
                                started_at=started_at, completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                head_repository=head_repository, head_ref=head_ref)
    if collection is None:
        raise MetadataProjectionError("metadata_coverage_unknown")
    return collection


def collect_authenticated_metadata(audience: str, repository: str, local_commit: str, remote_head: str,
                                   binding_pr: int, verified_account: str, head_repository: str,
                                   head_ref: str) -> VerifiedCollection:
    if (not re.fullmatch(r"[0-9a-f]{40}", local_commit) or local_commit != remote_head
            or not isinstance(head_repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", head_repository)
            or not isinstance(head_ref, str) or not head_ref):
        raise MetadataProjectionError("metadata_binding_unknown")
    transport = GitHubTransport(verified_account, repository, GitHubTransport.gh_token_provider(verified_account))
    transport.verify_identity()
    evidence = _collect_metadata(audience, repository, local_commit, remote_head, binding_pr, transport,
                                 head_repository=head_repository, head_ref=head_ref, strict_required=True)
    snapshot = consume_collection(evidence, audience, repository, local_commit, remote_head, binding_pr,
                                  head_repository=head_repository, head_ref=head_ref)
    if snapshot is None or not transport.identity_verified or not transport.identity_transcript:
        raise MetadataProjectionError("metadata_coverage_unknown")
    transport_identity_sha256 = _digest(transport.verified_account.encode("utf-8"))
    raw_transcript = b"".join((
        _canonical({"method": "GET", "host": "api.github.com", "accept": "application/vnd.github+json",
                    "api_version": transport.api_version, "transport_revision": transport.revision,
                    "identity_sha256": transport_identity_sha256}),
        transport.identity_transcript, evidence.raw_transcript,
    ))
    receipt = dict(evidence.receipt)
    receipt.update({"transport_revision": transport.revision,
                    "transport_identity_sha256": transport_identity_sha256,
                    "production_verified": True,
                    "raw_sha256": _digest(raw_transcript),
                    "snapshot_sha256": _digest(_canonical(snapshot))})
    nonce = hashlib.sha256(raw_transcript + _canonical(snapshot) + str(id(snapshot)).encode()).hexdigest()
    _ISSUED[nonce] = (receipt["raw_sha256"], receipt["snapshot_sha256"], audience, repository,
                      local_commit, remote_head, binding_pr, head_repository, head_ref, True,
                      _digest(_canonical(receipt)))
    return VerifiedCollection(snapshot, raw_transcript, receipt, nonce, True)


def _issue_receipt(snapshot: dict, raw_transcript: bytes, *, repository: str,
                   local_commit: str, remote_head: str, binding_pr: int,
                   coverage: list[dict], started_at: str, completed_at: str,
                   head_repository: str | None = None, head_ref: str | None = None) -> VerifiedCollection | None:
    """Issue only an in-process synthetic capability for a fully covered snapshot."""
    if (not isinstance(raw_transcript, bytes) or not raw_transcript
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not re.fullmatch(r"[0-9a-f]{40}", local_commit)
            or not re.fullmatch(r"[0-9a-f]{40}", remote_head)
            or not isinstance(binding_pr, int) or isinstance(binding_pr, bool) or binding_pr < 1
            or not isinstance(started_at, str) or not isinstance(completed_at, str)
            or not started_at or not completed_at
            or not isinstance(snapshot, dict) or set(snapshot) != {"schema", "audience", "source_commit", "surfaces"}
            or snapshot.get("schema") != "engineering.audience-metadata-snapshot.v1"
            or snapshot.get("source_commit") != local_commit
            or snapshot.get("audience") not in {"source", "distribution"}
            or not isinstance(snapshot.get("surfaces"), dict)
            or set(snapshot["surfaces"]) != set(SURFACES)
            or any(not isinstance(snapshot["surfaces"][name], list) for name in SURFACES)):
        return None
    surfaces = snapshot["surfaces"]
    pr_numbers = [item.get("number") for item in surfaces["pull_requests"] if isinstance(item, dict)]
    if len(pr_numbers) != len(surfaces["pull_requests"]) or any(not isinstance(n, int) or n < 1 for n in pr_numbers):
        return None
    if len(set(pr_numbers)) != len(pr_numbers) or not _coverage_complete(coverage, pr_numbers, binding_pr):
        return None
    grouped_coverage: dict[tuple[str, int | None], list[dict]] = {}
    for page in coverage:
        grouped_coverage.setdefault((page["endpoint"], page.get("pr")), []).append(page)
    coverage_summary = []
    for (endpoint, pr), pages in sorted(grouped_coverage.items(), key=lambda item: (item[0][0], item[0][1] or 0)):
        item_count = sum(page["item_count"] for page in pages)
        coverage_summary.append({
            "endpoint": endpoint,
            "pr": pr,
            "page_count": len(pages),
            "item_count": item_count,
            "terminal": pages[-1]["terminal"],
            "verified_empty": item_count == 0 and pages[-1]["terminal"],
        })
    nonce = hashlib.sha256(raw_transcript + _canonical(snapshot) + str(id(snapshot)).encode()).hexdigest()
    receipt = {
        "schema": "engineering.github-metadata-receipt.v1",
        "audience": snapshot["audience"],
        "repository": repository,
        "local_commit": local_commit,
        "remote_head": remote_head,
        "binding_pr": binding_pr,
        "binding_head_repository": head_repository,
        "binding_head_ref": head_ref,
        "collector_revision": "engineering.github-metadata-collector.v1",
        "transport_revision": "synthetic-test-seam",
        "transport_identity_sha256": None,
        "production_verified": False,
        "started_at": started_at,
        "completed_at": completed_at,
        "raw_sha256": _digest(raw_transcript),
        "snapshot_sha256": _digest(_canonical(snapshot)),
        "coverage": coverage,
        "coverage_summary": coverage_summary,
    }
    if binding_pr not in pr_numbers:
        return None
    _ISSUED[nonce] = (receipt["raw_sha256"], receipt["snapshot_sha256"], snapshot["audience"], repository,
                      local_commit, remote_head, binding_pr, head_repository, head_ref, False,
                      _digest(_canonical(receipt)))
    return VerifiedCollection(snapshot, raw_transcript, receipt, nonce, False)


def verify_collection(collection: object, audience: str, repository: str, local_commit: str,
                      remote_head: str, binding_pr: int, *, head_repository: str | None = None,
                      head_ref: str | None = None, require_production: bool = False) -> bool:
    if not isinstance(collection, VerifiedCollection):
        return False
    expected = _ISSUED.get(collection._nonce)
    actual = (collection.receipt.get("raw_sha256"), collection.receipt.get("snapshot_sha256"),
              collection.receipt.get("audience"), collection.receipt.get("repository"),
              collection.receipt.get("local_commit"), collection.receipt.get("remote_head"),
              collection.receipt.get("binding_pr"), collection.receipt.get("binding_head_repository"),
              collection.receipt.get("binding_head_ref"), collection.receipt.get("production_verified"),
              _digest(_canonical(collection.receipt)))
    return (expected is not None and (not require_production or collection.production_verified) and actual == expected
            and (not collection.production_verified or local_commit == remote_head)
            and expected == (_digest(collection.raw_transcript), _digest(_canonical(collection.snapshot)),
                             audience, repository, local_commit, remote_head, binding_pr, head_repository, head_ref,
                             collection.production_verified,
                             _digest(_canonical(collection.receipt))))


def consume_collection(collection: object, audience: str, repository: str, local_commit: str,
                       remote_head: str, binding_pr: int, *, head_repository: str | None = None,
                       head_ref: str | None = None, require_production: bool = False) -> dict | None:
    if (require_production and (not isinstance(collection, VerifiedCollection) or not collection.production_verified)
            or not verify_collection(collection, audience, repository, local_commit, remote_head, binding_pr,
                                     head_repository=head_repository, head_ref=head_ref,
                                     require_production=require_production)):
        return None
    _ISSUED.pop(collection._nonce, None)
    return collection.snapshot


def validate_transport_url(field: str, value: str, repository: str, pr_number: int | None = None,
                          allow_fragment: bool = False, object_id: int | None = None,
                          release_tag: str | None = None, asset_name: str | None = None,
                          object_kind: str | None = None, schema_endpoint: str | None = None,
                          parent_number: int | None = None, head_sha: str | None = None) -> bool:
    if not isinstance(value, str) or any(ord(ch) < 32 for ch in value) or "\\" in value:
        raise MetadataProjectionError("metadata_uri_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise MetadataProjectionError("metadata_uri_invalid") from None
    if (parsed.scheme != "https" or parsed.username or parsed.password or port is not None
            or parsed.hostname not in {"api.github.com", "github.com", "uploads.github.com"}
            or parsed.query and field != "upload_url"
            or parsed.fragment and not allow_fragment
            or field != "browser_download_url" and re.search(r"%(?:2f|2F|5c|5C|25)|(?:^|/)\.\.?(/|$)", parsed.path)):
        raise MetadataProjectionError("metadata_uri_invalid")
    if field == "upload_url":
        match = re.fullmatch(r"https://uploads\.github\.com/repos/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/releases/([0-9]+)/assets\{\?name,label\}", value)
        if match is None:
            raise MetadataProjectionError("metadata_uri_invalid")
        owner, repo = repository.split("/", 1)
        if match.group(1) != owner or match.group(2) != repo or object_id is not None and int(match.group(3)) != object_id:
            raise MetadataProjectionError("metadata_uri_invalid")
        return True
    if field == "statuses_url" and object_kind == "pull":
        owner, repo = repository.split("/", 1)
        if (not isinstance(head_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", head_sha)
                or value != f"https://api.github.com/repos/{owner}/{repo}/statuses/{head_sha}"):
            raise MetadataProjectionError("metadata_uri_invalid")
        return True
    if field == "url" and object_id is not None and object_kind is None:
        owner, repo = repository.split("/", 1)
        if value != f"https://api.github.com/repos/{owner}/{repo}/releases/assets/{object_id}":
            raise MetadataProjectionError("metadata_uri_invalid")
        return True
    if field == "url" and object_kind is not None:
        owner, repo = repository.split("/", 1)
        if object_kind == "reaction":
            if schema_endpoint in {"issues", "pulls"} and pr_number is not None:
                expected_path = f"/repos/{owner}/{repo}/issues/{pr_number}/reactions"
            elif schema_endpoint == "issue_comments" and object_id is not None:
                expected_path = f"/repos/{owner}/{repo}/issues/comments/{object_id}/reactions"
            elif schema_endpoint == "pr_comments" and object_id is not None:
                expected_path = f"/repos/{owner}/{repo}/pulls/comments/{object_id}/reactions"
            else:
                expected_path = None
            if (expected_path is None or parsed.scheme != "https" or parsed.hostname != "api.github.com"
                    or parsed.path != expected_path or parsed.query or parsed.fragment):
                raise MetadataProjectionError("metadata_uri_invalid")
            return True
        paths = {
            "issue": f"/repos/{owner}/{repo}/issues/{pr_number}",
            "pull": f"/repos/{owner}/{repo}/pulls/{pr_number}",
            "release": f"/repos/{owner}/{repo}/releases/{object_id}",
            "comment": (f"/repos/{owner}/{repo}/issues/comments/{object_id}" if schema_endpoint == "issue_comments"
                        else f"/repos/{owner}/{repo}/pulls/comments/{object_id}" if schema_endpoint == "pr_comments" else None),
        }
        expected_path = paths.get(object_kind)
        if expected_path is None or parsed.scheme != "https" or parsed.hostname != "api.github.com" \
                or parsed.path != expected_path or parsed.query or parsed.fragment:
            raise MetadataProjectionError("metadata_uri_invalid")
        return True
    if field == "browser_download_url" and release_tag is not None and asset_name is not None:
        owner, repo = repository.split("/", 1)
        expected = f"https://github.com/{owner}/{repo}/releases/download/{quote(release_tag, safe='')}/{quote(asset_name, safe='')}"
        if value != expected:
            raise MetadataProjectionError("metadata_uri_invalid")
        return True
    if field == "html_url" and release_tag is not None:
        owner, repo = repository.split("/", 1)
        expected = f"https://github.com/{owner}/{repo}/releases/tag/{quote(release_tag, safe='')}"
        if value != expected:
            raise MetadataProjectionError("metadata_uri_invalid")
        return True
    if field == "html_url" and object_kind in {"issue", "pull"}:
        owner, repo = repository.split("/", 1)
        expected_path = (f"/{owner}/{repo}/issues/{pr_number}" if object_kind == "issue"
                         else f"/{owner}/{repo}/pull/{pr_number}")
        if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.path != expected_path:
            raise MetadataProjectionError("metadata_uri_invalid")
        return True
    if field == "html_url" and parent_number is not None and schema_endpoint in {"pr_comments", "reviews"}:
        owner, repo = repository.split("/", 1)
        if (parsed.scheme != "https" or parsed.hostname != "github.com"
                or parsed.path != f"/{owner}/{repo}/pull/{parent_number}"):
            raise MetadataProjectionError("metadata_uri_invalid")
        return True
    if field == "pull_request_url" and parent_number is not None:
        owner, repo = repository.split("/", 1)
        if (parsed.scheme != "https" or parsed.hostname != "api.github.com"
                or parsed.path != f"/repos/{owner}/{repo}/pulls/{parent_number}"):
            raise MetadataProjectionError("metadata_uri_invalid")
        return True
    expected_host = "api.github.com" if field in {
        "url", "comments_url", "events_url", "labels_url", "issue_url", "assets_url",
        "tarball_url", "zipball_url", "commits_url", "review_comments_url", "review_comment_url", "statuses_url",
        "repository_url", "timeline_url", "pull_request_url", "review_url", "parent_issue_url",
    } else "github.com"
    if (parsed.scheme != "https" or parsed.hostname != expected_host
            or parsed.username or parsed.password or port or parsed.query
            or parsed.fragment and (not allow_fragment or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", parsed.fragment))):
        raise MetadataProjectionError("metadata_uri_invalid")
    if re.search(r"%(?![0-9a-fA-F]{2})|%2f|%5c|%25|(?:^|/)\.{1,2}(?:/|$)", parsed.path, re.I):
        raise MetadataProjectionError("metadata_uri_invalid")
    owner, repo = repository.split("/", 1)
    route = parsed.path
    api_repository_routes = {"url", "comments_url", "events_url", "labels_url", "issue_url", "assets_url",
                             "tarball_url", "zipball_url", "commits_url", "review_comments_url", "review_comment_url", "statuses_url",
                             "repository_url", "timeline_url", "pull_request_url", "review_url", "parent_issue_url"}
    web_repository_routes = {"html_url", "diff_url", "patch_url", "browser_download_url"}
    expected = f"/repos/{owner}/{repo}/" if field in api_repository_routes else f"/{owner}/{repo}/" if field in web_repository_routes else None
    if expected is None or not (route.startswith(expected) or route.rstrip("/") == expected.rstrip("/")):
        raise MetadataProjectionError("metadata_uri_invalid")
    api_base = re.escape(f"/repos/{owner}/{repo}")
    web_base = re.escape(f"/{owner}/{repo}")
    route_suffixes = {
        "url": (rf"{api_base}", rf"{api_base}/issues/[1-9][0-9]*", rf"{api_base}/pulls/[1-9][0-9]*",
                rf"{api_base}/issues/comments/[1-9][0-9]*", rf"{api_base}/pulls/comments/[1-9][0-9]*",
                rf"{api_base}/pulls/[1-9][0-9]*/reviews/[1-9][0-9]*", rf"{api_base}/releases/[1-9][0-9]*",
                rf"{api_base}/releases/assets/[1-9][0-9]*"),
        "comments_url": (rf"{api_base}/issues/[1-9][0-9]*/comments", rf"{api_base}/pulls/[1-9][0-9]*/comments"),
        "events_url": (rf"{api_base}/events", rf"{api_base}/issues/[1-9][0-9]*/events"),
        "labels_url": (rf"{api_base}/issues/[1-9][0-9]*/labels",
                       rf"{api_base}/issues/[1-9][0-9]*/labels\{{/name\}}",
                       rf"{api_base}/milestones/[1-9][0-9]*/labels"),
        "issue_url": (rf"{api_base}/issues/[1-9][0-9]*",),
        "repository_url": (api_base,),
        "timeline_url": (rf"{api_base}/issues/[1-9][0-9]*/timeline",),
        "pull_request_url": (rf"{api_base}/pulls/[1-9][0-9]*",),
        "review_url": (rf"{api_base}/pulls/[1-9][0-9]*/reviews/[1-9][0-9]*",),
        "review_comments_url": (rf"{api_base}/pulls/[1-9][0-9]*/comments",),
        "review_comment_url": (rf"{api_base}/pulls/comments/[1-9][0-9]*", rf"{api_base}/pulls/comments\{{/number\}}"),
        "statuses_url": (rf"{api_base}/statuses/[0-9a-fA-F]{{40}}",),
        "assets_url": (rf"{api_base}/releases/[1-9][0-9]*/assets",),
        "commits_url": (rf"{api_base}/commits/[0-9a-fA-F]{{7,64}}", rf"{api_base}/pulls/[1-9][0-9]*/commits"),
        "tarball_url": (rf"{api_base}/tarball(?:/[^/?#]+)?",),
        "zipball_url": (rf"{api_base}/zipball(?:/[^/?#]+)?",),
        "parent_issue_url": (rf"{api_base}/issues/[1-9][0-9]*",),
        "html_url": (web_base, rf"{web_base}/issues/[1-9][0-9]*", rf"{web_base}/pull/[1-9][0-9]*",
                      rf"{web_base}/issues/comments/[1-9][0-9]*", rf"{web_base}/pulls/comments/[1-9][0-9]*",
                      rf"{web_base}/releases/tag/[^/?#]+", rf"{web_base}/commit/[0-9a-fA-F]{{7,64}}"),
        "diff_url": (rf"{web_base}/pull/[1-9][0-9]*\.diff",),
        "patch_url": (rf"{web_base}/pull/[1-9][0-9]*\.patch",),
        "browser_download_url": (rf"{web_base}/releases/download/[^/?#]+/[^/?#]+",),
    }
    permitted_routes = route_suffixes.get(field)
    if permitted_routes is None or not any(re.fullmatch(pattern, route) for pattern in permitted_routes):
        raise MetadataProjectionError("metadata_uri_invalid")
    if (field == "labels_url" and route.endswith("/labels{/name}")
            and (schema_endpoint != "issues" or not isinstance(pr_number, int)
                 or isinstance(pr_number, bool) or pr_number < 1)):
        raise MetadataProjectionError("metadata_uri_invalid")
    if pr_number is not None:
        exact_object_routes = {
            "html_url": {f"/{owner}/{repo}/issues/{pr_number}", f"/{owner}/{repo}/pull/{pr_number}"},
            "diff_url": {f"/{owner}/{repo}/pull/{pr_number}.diff"},
            "patch_url": {f"/{owner}/{repo}/pull/{pr_number}.patch"},
            "comments_url": {f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
                              f"/repos/{owner}/{repo}/pulls/{pr_number}/comments"},
            "events_url": {f"/repos/{owner}/{repo}/issues/{pr_number}/events",
                           f"/repos/{owner}/{repo}/issues/{pr_number}/events"},
            "labels_url": {f"/repos/{owner}/{repo}/issues/{pr_number}/labels",
                           f"/repos/{owner}/{repo}/issues/{pr_number}/labels{{/name}}"},
            "issue_url": {f"/repos/{owner}/{repo}/issues/{pr_number}"},
            "pull_request_url": {f"/repos/{owner}/{repo}/pulls/{pr_number}"},
            "review_comments_url": {f"/repos/{owner}/{repo}/pulls/{pr_number}/comments"},
            "commits_url": {f"/repos/{owner}/{repo}/pulls/{pr_number}/commits"},
            "review_comment_url": {f"/repos/{owner}/{repo}/pulls/comments{{/number}}"},
        }
        permitted = exact_object_routes.get(field)
        if permitted is not None and route not in permitted:
            raise MetadataProjectionError("metadata_uri_invalid")
    return True


def validate_actor_url(field: str, value: str, login: str, actor_id: int | None = None,
                       actor_type: str | None = None) -> bool:
    if field not in {"url", "html_url", "avatar_url", "followers_url", "following_url", "gists_url",
                     "starred_url", "subscriptions_url", "organizations_url", "repos_url", "events_url",
                     "received_events_url"}:
        raise MetadataProjectionError("metadata_uri_invalid")
    if (not isinstance(value, str) or any(ord(ch) < 32 or ch.isspace() for ch in value)
            or "\\" in value):
        raise MetadataProjectionError("metadata_uri_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise MetadataProjectionError("metadata_uri_invalid") from None
    if parsed.scheme != "https" or parsed.hostname not in {"api.github.com", "github.com", "avatars.githubusercontent.com"}:
        raise MetadataProjectionError("metadata_uri_invalid")
    authority = parsed.netloc.rsplit("@", 1)[-1]
    if (parsed.username is not None or parsed.password is not None or port is not None
            or ":" in authority or parsed.fragment):
        raise MetadataProjectionError("metadata_uri_invalid")
    if re.search(r"%(?![0-9a-fA-F]{2})|%2f|%5c|%25|(?:^|/)\.{1,2}(?:/|$)", parsed.path, re.I):
        raise MetadataProjectionError("metadata_uri_invalid")
    if field == "avatar_url":
        segments = parsed.path.split("/")
        modern_avatar = (
            parsed.hostname == "avatars.githubusercontent.com"
            and len(parsed.path) <= 130
            and len(segments) == 3 and segments[0] == ""
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", segments[1]) is not None
            and re.fullmatch(r"[0-9]{1,64}", segments[2]) is not None
            and "%" not in parsed.path
            and (not parsed.query or re.fullmatch(r"v=[0-9]+", parsed.query) is not None)
        )
        legacy_avatar = parsed.hostname == "github.com" and bool(re.fullmatch(r"/images/error/[A-Za-z0-9_-]+\.gif", parsed.path))
        if not (modern_avatar or legacy_avatar):
            raise MetadataProjectionError("metadata_uri_invalid")
        if parsed.query and (not modern_avatar or not re.fullmatch(r"v=[0-9]+", parsed.query)):
            raise MetadataProjectionError("metadata_uri_invalid")
    else:
        expected_host = "api.github.com" if field != "html_url" else "github.com"
        if parsed.hostname != expected_host:
            raise MetadataProjectionError("metadata_uri_invalid")
        if (field == "html_url" and actor_type == "Bot" and not parsed.query
                and re.fullmatch(r"/apps/[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", parsed.path)):
            return True
        tails = {
            "url": "", "html_url": "", "followers_url": "/followers", "following_url": "/following{/other_user}",
            "gists_url": "/gists{/gist_id}", "starred_url": "/starred{/owner}{/repo}",
            "subscriptions_url": "/subscriptions", "organizations_url": "/orgs", "repos_url": "/repos",
            "events_url": "/events{/privacy}", "received_events_url": "/received_events",
        }
        prefix = "/us" + "ers/" if parsed.hostname == "api.github.com" else "/"
        expected = prefix + login + tails.get(field, "")
        encoded_expected = prefix + quote(login, safe="") + tails.get(field, "")
        if parsed.path not in {expected, encoded_expected} or parsed.query:
            raise MetadataProjectionError("metadata_uri_invalid")
    return True


def _validate_actor(value: object, *, strict_required: bool = False) -> None:
    _validate_embedded_simple_user(value, "simple-user", strict_required=strict_required)


def _validate_embedded_simple_user(value: object, component: str, *, strict_required: bool = False) -> list[str]:
    _validate_nested_schema(component, value, strict_required=strict_required)
    login = value.get("login")
    if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?(?:\[bot\])?", login):
        raise MetadataProjectionError("metadata_shape_unknown")
    for field in value.keys() & {"avatar_url", "url", "html_url", "followers_url", "following_url", "gists_url", "starred_url",
                                  "subscriptions_url", "organizations_url", "repos_url", "events_url", "received_events_url"}:
        validate_actor_url(field, value[field], login,
                           value.get("id") if isinstance(value.get("id"), int) else None,
                           actor_type=value.get("type") if isinstance(value.get("type"), str) else None)
    return [value[field] for field in ("name", "email") if isinstance(value.get(field), str)]


def _validate_organization(value: object, *, strict_required: bool = False) -> None:
    fields = {"login", "id", "node_id", "url", "repos_url", "events_url", "hooks_url", "issues_url", "members_url",
              "public_members_url", "avatar_url", "description", "name", "company", "blog", "location", "email",
              "twitter_username", "is_verified", "has_organization_projects", "has_repository_projects", "public_repos",
              "public_gists", "followers", "following", "html_url", "type"}
    if (not isinstance(value, dict) or set(value) - fields or not isinstance(value.get("login"), str)
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", value["login"])):
        raise MetadataProjectionError("metadata_shape_unknown")
    _validate_nested_schema("organization-simple", value, strict_required=strict_required, allow_extra=True)
    for key, item in value.items():
        if key in {"id", "public_repos", "public_gists", "followers", "following"}:
            if not isinstance(item, int) or isinstance(item, bool):
                raise MetadataProjectionError("metadata_shape_unknown")
        elif key in {"is_verified", "has_organization_projects", "has_repository_projects"}:
            if not isinstance(item, bool):
                raise MetadataProjectionError("metadata_shape_unknown")
        elif key in {"description", "name", "company", "blog", "location", "email", "twitter_username"} and item is None:
            continue
        elif not isinstance(item, str):
            raise MetadataProjectionError("metadata_shape_unknown")
    login = value["login"]
    api_paths = {"url": f"/orgs/{login}", "repos_url": f"/orgs/{login}/repos",
                 "events_url": f"/us" + f"ers/{login}/events{{/privacy}}", "hooks_url": f"/orgs/{login}/hooks",
                 "issues_url": f"/orgs/{login}/issues", "members_url": f"/orgs/{login}/members{{/member}}",
                 "public_members_url": f"/orgs/{login}/public_members{{/member}}"}
    for field, path in api_paths.items():
        if field in value:
            try:
                parsed = urlsplit(value[field])
                port = parsed.port
            except (TypeError, ValueError):
                raise MetadataProjectionError("metadata_uri_invalid") from None
            if (parsed.scheme != "https" or parsed.hostname != "api.github.com" or parsed.username or parsed.password
                    or port is not None or parsed.path != path or parsed.query or parsed.fragment):
                raise MetadataProjectionError("metadata_uri_invalid")
    if "html_url" in value and value["html_url"] != f"https://github.com/{login}":
        raise MetadataProjectionError("metadata_uri_invalid")
    if "avatar_url" in value:
        validate_actor_url("avatar_url", value["avatar_url"], login,
                           value.get("id") if isinstance(value.get("id"), int) else None)


def _actor_authored_text(value: object, *, strict_required: bool = False) -> list[str]:
    return _validate_embedded_simple_user(value, "simple-user", strict_required=strict_required)


def _integration_owner_authored_text(value: object, *, strict_required: bool = False) -> list[str]:
    if not isinstance(value, dict):
        raise MetadataProjectionError("metadata_shape_unknown")
    if "login" in value:
        return _actor_authored_text(value, strict_required=strict_required)
    _validate_nested_schema("enterprise", value, strict_required=strict_required)
    slug = value.get("slug")
    if (not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", slug)
            or value.get("html_url") != f"https://github.com/enterprises/{slug}"):
        raise MetadataProjectionError("metadata_uri_invalid")
    validate_actor_url("avatar_url", value["avatar_url"], slug, value["id"])
    return [value[field] for field in ("name", "description", "website_url")
            if isinstance(value.get(field), str)]


def _validate_link_relation(endpoint: str, relation: str, href: object, repository: str,
                            record_number: object, record_id: object, head_sha: str | None) -> None:
    owner, repo = repository.split("/", 1)
    if endpoint in {"pull_detail", "pulls"}:
        if not isinstance(record_number, int) or isinstance(record_number, bool) or record_number < 1:
            raise MetadataProjectionError("metadata_shape_unknown")
        api = f"https://api.github.com/repos/{owner}/{repo}"
        web = f"https://github.com/{owner}/{repo}"
        expected = {
            "self": f"{api}/pulls/{record_number}",
            "html": f"{web}/pull/{record_number}",
            "issue": f"{api}/issues/{record_number}",
            "comments": f"{api}/issues/{record_number}/comments",
            "review_comments": f"{api}/pulls/{record_number}/comments",
            "review_comment": f"{api}/pulls/comments{{/number}}",
            "commits": f"{api}/pulls/{record_number}/commits",
        }
        if relation == "statuses":
            if not isinstance(head_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
                raise MetadataProjectionError("metadata_shape_unknown")
            expected["statuses"] = f"{api}/statuses/{head_sha}"
    elif endpoint in {"pr_comments", "reviews"}:
        if (not isinstance(record_id, int) or isinstance(record_id, bool) or record_id < 1
                or not isinstance(record_number, int) or isinstance(record_number, bool) or record_number < 1):
            raise MetadataProjectionError("metadata_shape_unknown")
        api = f"https://api.github.com/repos/{owner}/{repo}"
        web = f"https://github.com/{owner}/{repo}"
        expected = {"pull_request": f"{api}/pulls/{record_number}"}
        if endpoint == "pr_comments":
            expected.update({"self": f"{api}/pulls/comments/{record_id}",
                             "html": f"{web}/pull/{record_number}#discussion-diff-{record_id}"})
        else:
            expected["html"] = f"{web}/pull/{record_number}#pullrequestreview-{record_id}"
    else:
        raise MetadataProjectionError("metadata_shape_unknown")
    if relation not in expected or not isinstance(href, str) or href != expected[relation]:
        raise MetadataProjectionError("metadata_uri_invalid")


def _validate_app_url(value: object, slug: object) -> None:
    if not isinstance(value, str) or not isinstance(slug, str) or any(ord(ch) < 32 for ch in value) or "\\" in value:
        raise MetadataProjectionError("metadata_uri_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise MetadataProjectionError("metadata_uri_invalid") from None
    if (parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password or port is not None
            or parsed.query or parsed.fragment or parsed.path != f"/apps/{slug}"):
        raise MetadataProjectionError("metadata_uri_invalid")


def _validate_team_url(field: str, value: object, owner: str, slug: str,
                       organization_id: int | None = None, team_id: int | None = None) -> None:
    if not isinstance(value, str) or any(ord(ch) < 32 for ch in value) or "\\" in value:
        raise MetadataProjectionError("metadata_uri_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise MetadataProjectionError("metadata_uri_invalid") from None
    patterns = {
        "url": (("api.github.com", rf"/orgs/{re.escape(owner)}/teams/{re.escape(slug)}"),
                ("api.github.com", r"/organizations/[0-9]+/team/[0-9]+")),
        "members_url": (("api.github.com", rf"/orgs/{re.escape(owner)}/teams/{re.escape(slug)}/members\{{/member\}}"),
                        ("api.github.com", r"/organizations/[0-9]+/team/[0-9]+/members\{/member\}")),
        "repositories_url": (("api.github.com", rf"/orgs/{re.escape(owner)}/teams/{re.escape(slug)}/repos"),
                             ("api.github.com", r"/organizations/[0-9]+/team/[0-9]+/repos")),
        "html_url": (("github.com", rf"/orgs/{re.escape(owner)}/teams/{re.escape(slug)}"),),
    }
    if (parsed.scheme != "https" or parsed.username or parsed.password or port is not None or parsed.query or parsed.fragment
            or field not in patterns
            or not any(parsed.hostname == host and re.fullmatch(path, parsed.path)
                       for host, path in patterns.get(field, ()))):
        raise MetadataProjectionError("metadata_uri_invalid")
    if parsed.path.startswith("/organizations/"):
        pieces = parsed.path.split("/")
        try:
            observed_org, observed_team = int(pieces[2]), int(pieces[4])
        except (ValueError, IndexError):
            raise MetadataProjectionError("metadata_uri_invalid") from None
        if organization_id != observed_org or team_id != observed_team:
            raise MetadataProjectionError("metadata_uri_invalid")


def project_record(kind: str, value: object, repository: str = "synthetic/repo", *,
                   schema_endpoint: str | None = None, strict_required: bool = False,
                   parent_number: int | None = None, head_sha: str | None = None,
                   _top_level_required_validated: bool = False) -> dict:
    """Minimal closed projection used by callers; unclassified fields never pass through."""
    structural = {"id", "node_id", "number", "state", "state_reason", "locked", "active_lock_reason", "draft", "merged", "maintainer_can_modify",
                  "mergeable", "rebaseable", "mergeable_state", "author_association", "created_at", "updated_at", "closed_at",
                  "merged_at", "published_at", "submitted_at", "comments", "review_comments", "commits", "additions", "deletions",
                  "changed_files", "download_count", "content_type", "digest", "immutable", "prerelease", "make_latest", "commit_id",
                  "original_commit_id", "merge_commit_sha", "sha", "pull_request_review_id", "in_reply_to_id", "position", "original_position",
                  "line", "original_line", "start_line", "original_start_line", "side", "start_side", "subject_type"}
    generated = {"url", "html_url", "comments_url", "events_url", "labels_url", "issue_url", "repository_url", "timeline_url",
                 "pull_request_url", "review_url", "diff_url", "patch_url", "commits_url",
                 "review_comments_url", "review_comment_url", "statuses_url", "assets_url", "upload_url", "tarball_url", "zipball_url",
                 "browser_download_url", "parent_issue_url"}
    if kind not in TOP_LEVEL_AUTHORED_FIELDS or not isinstance(value, dict):
        raise MetadataProjectionError("metadata_shape_unknown")
    catalog_name = {"issue": "issues", "pull": "pull_detail", "release": "releases",
                    "comment": "issue_comments", "review": "reviews"}[kind]
    valid_keys = ENDPOINT_SCHEMAS.get(schema_endpoint, ENDPOINT_SCHEMAS[catalog_name])
    if kind == "comment" and schema_endpoint is None:
        valid_keys = valid_keys | ENDPOINT_SCHEMAS["pr_comments"]
    component_by_endpoint = {"repository": "full-repository", "issues": "issue", "pulls": "pull-request-simple",
                             "pull_detail": "pull-request", "releases": "release", "issue_comments": "issue-comment",
                             "pr_comments": "pull-request-review-comment", "reviews": "pull-request-review"}
    required_fields = OPENAPI_REQUIRED_FIELDS.get(component_by_endpoint.get(schema_endpoint or catalog_name, ""), frozenset())
    if set(value) - valid_keys or strict_required and not _top_level_required_validated and not required_fields <= set(value):
        raise MetadataProjectionError("metadata_schema_unknown")
    if strict_required and not _top_level_required_validated:
        component = component_by_endpoint.get(schema_endpoint or catalog_name)
        if component is not None:
            _validate_required_structural_fields(component, value)
    if kind in {"issue", "pull"} and "state" in value and value["state"] not in {"open", "closed"}:
        raise MetadataProjectionError("metadata_shape_unknown")
    pull_request_issue = kind == "issue" and "pull_request" in value
    if pull_request_issue:
        marker = value["pull_request"]
        _validate_nested_schema("issue-pull-request", marker, strict_required=True)
        record_number = value.get("number")
        if not isinstance(record_number, int) or isinstance(record_number, bool) or record_number < 1:
            raise MetadataProjectionError("metadata_binding_unknown")
        merged_at = marker.get("merged_at")
        if merged_at is not None:
            if (not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", merged_at)):
                raise MetadataProjectionError("metadata_shape_unknown")
            try:
                datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
            except ValueError:
                raise MetadataProjectionError("metadata_shape_unknown") from None
        for link_field in ("url", "html_url", "diff_url", "patch_url"):
            link = marker[link_field]
            if link is not None:
                validate_transport_url(link_field, link, repository, pr_number=record_number,
                                       object_kind="pull", schema_endpoint="issues")
    result: dict[str, object] = {}
    for key, item in value.items():
        if key in TOP_LEVEL_AUTHORED_FIELDS[kind]:
            if item is not None and not isinstance(item, str):
                raise MetadataProjectionError("metadata_shape_unknown")
            if item is not None:
                result[key] = item
        elif key in structural:
            integer_fields = {"id", "number", "comments", "review_comments", "commits", "additions", "deletions", "changed_files",
                              "download_count", "size", "pull_request_review_id", "in_reply_to_id", "position", "original_position",
                              "line", "original_line", "start_line", "original_start_line"}
            boolean_fields = {"locked", "draft", "merged", "mergeable", "rebaseable", "immutable", "prerelease", "maintainer_can_modify"}
            string_fields = structural - integer_fields - boolean_fields
            valid = (item is None or (key in integer_fields and isinstance(item, int) and not isinstance(item, bool)
                    or key in boolean_fields and isinstance(item, bool)
                    or key in string_fields and isinstance(item, str)))
            if not valid:
                raise MetadataProjectionError("metadata_shape_unknown")
            if key in string_fields and isinstance(item, str):
                result.setdefault("nested_text", []).append(item)
        elif key == "nested_text":
            if not isinstance(item, list) or any(not isinstance(text, str) for text in item):
                raise MetadataProjectionError("metadata_shape_unknown")
            result.setdefault("nested_text", []).extend(item)
        elif key in generated:
            if item is None and key in {"parent_issue_url", "tarball_url", "zipball_url"}:
                continue
            if not isinstance(item, str):
                raise MetadataProjectionError("metadata_shape_unknown")
            allow_fragment = key == "html_url"
            record_number = value.get("number")
            validate_transport_url(key, item, repository,
                                   pr_number=record_number if isinstance(record_number, int) and not isinstance(record_number, bool) else None,
                                   allow_fragment=allow_fragment,
                                   object_id=value.get("id") if key in {"url", "upload_url"} else None,
                                   release_tag=value.get("tag_name") if key == "html_url" and kind == "release" else None,
                                   object_kind=("pull" if kind == "issue" and pull_request_issue and key == "html_url"
                                                else "pull" if kind == "pull" and key == "statuses_url"
                                                else kind if key in {"url", "html_url"} else None),
                                   schema_endpoint=schema_endpoint or catalog_name,
                                   parent_number=parent_number, head_sha=head_sha)
            if allow_fragment and urlsplit(item).fragment:
                record_id = value.get("id")
                allowed_fragments = {f"issuecomment-{record_id}", f"discussion_r{record_id}",
                                     f"pullrequestreview-{record_id}"}
                if urlsplit(item).fragment not in allowed_fragments:
                    raise MetadataProjectionError("metadata_uri_invalid")
        elif key in {"user", "assignee", "closed_by", "author", "uploader", "merged_by"}:
            if item is not None:
                actor_text = _actor_authored_text(item, strict_required=strict_required)
                if actor_text:
                    result.setdefault("nested_text", []).extend(actor_text)
        elif key in {"labels", "assignees", "requested_reviewers"}:
            if not isinstance(item, list):
                raise MetadataProjectionError("metadata_shape_unknown")
            # Names are authored; actor entries are handled by the actor shape above.
            if key == "labels":
                for label in item:
                    result.setdefault("nested_text", []).extend(
                        _project_label(label, repository, strict_required=strict_required))
            else:
                for actor_item in item:
                    _validate_actor(actor_item)
                    result.setdefault("nested_text", []).extend(_actor_authored_text(actor_item, strict_required=strict_required))
        elif key == "requested_teams":
            if not isinstance(item, list):
                raise MetadataProjectionError("metadata_shape_unknown")
            owner = repository.split("/", 1)[0]
            for team in item:
                if (not isinstance(team, dict) or not set(team) <= OPENAPI_OBJECT_SCHEMAS["team-simple"]
                        or not isinstance(team.get("slug"), str)):
                    raise MetadataProjectionError("metadata_shape_unknown")
                _validate_nested_schema("team-simple", team, strict_required=strict_required)
                for url_field in ("url", "html_url", "members_url", "repositories_url"):
                    if url_field in team:
                        _validate_team_url(url_field, team[url_field], owner, team["slug"],
                                           team.get("organization_id"), team.get("id"))
                for field in ("slug", "name", "description", "ldap_dn", "permission", "privacy",
                              "notification_setting"):
                    if isinstance(team.get(field), str):
                        result.setdefault("nested_text", []).append(team[field])
        elif key == "milestone":
            if item is not None:
                if not isinstance(item, dict) or set(item) - OPENAPI_OBJECT_SCHEMAS["nullable-milestone"]:
                    raise MetadataProjectionError("metadata_shape_unknown")
                _validate_nested_schema("nullable-milestone", item, strict_required=strict_required)
                if item.get("state") not in {None, "open", "closed"}:
                    raise MetadataProjectionError("metadata_shape_unknown")
                for numeric in ("id", "number", "open_issues", "closed_issues"):
                    if numeric in item and (not isinstance(item[numeric], int) or isinstance(item[numeric], bool)):
                        raise MetadataProjectionError("metadata_shape_unknown")
                for timestamp in ("created_at", "updated_at", "closed_at", "due_on"):
                    if timestamp in item and item[timestamp] is not None and not isinstance(item[timestamp], str):
                        raise MetadataProjectionError("metadata_shape_unknown")
                for text_key in ("title", "description"):
                    if isinstance(item.get(text_key), str):
                        result.setdefault("nested_text", []).append(item[text_key])
                for url_key in ("url", "html_url", "labels_url"):
                    if url_key in item:
                        milestone_number = item.get("number")
                        if not isinstance(milestone_number, int) or isinstance(milestone_number, bool):
                            raise MetadataProjectionError("metadata_shape_unknown")
                        expected = {
                            "url": f"https://api.github.com/repos/{repository}/milestones/{milestone_number}",
                            "html_url": f"https://github.com/{repository}/milestones/{milestone_number}",
                            "labels_url": f"https://api.github.com/repos/{repository}/milestones/{milestone_number}/labels",
                        }[url_key]
                        if item[url_key] != expected:
                            raise MetadataProjectionError("metadata_uri_invalid")
                creator = item.get("creator")
                if creator is not None:
                    result.setdefault("nested_text", []).extend(_actor_authored_text(creator, strict_required=strict_required))
        elif key == "reactions":
            reaction_fields = {"url", "total_count", "+1", "-1", "laugh", "hooray", "confused", "heart", "rocket", "eyes"}
            if not isinstance(item, dict) or set(item) - reaction_fields:
                raise MetadataProjectionError("metadata_shape_unknown")
            _validate_nested_schema("reaction-rollup", item, strict_required=strict_required)
            if "url" in item:
                validate_transport_url("url", item["url"], repository,
                                       pr_number=value.get("number") if isinstance(value.get("number"), int) else None,
                                       object_id=value.get("id") if isinstance(value.get("id"), int) else None,
                                       object_kind="reaction", schema_endpoint=schema_endpoint or catalog_name)
            if any(not isinstance(count, int) or isinstance(count, bool) for name, count in item.items() if name != "url"):
                raise MetadataProjectionError("metadata_shape_unknown")
        elif key == "_links":
            link_relations = {
                "pull_detail": {"self", "html", "issue", "comments", "review_comments", "review_comment", "commits", "statuses"},
                "pulls": {"self", "html", "issue", "comments", "review_comments", "review_comment", "commits", "statuses"},
                "pr_comments": {"self", "html", "pull_request"},
                "reviews": {"html", "pull_request"},
            }
            endpoint = schema_endpoint or catalog_name
            relations = link_relations.get(endpoint, set())
            required_relations = {
                "pull_detail": {"self", "html", "issue", "comments", "review_comments", "review_comment", "commits", "statuses"},
                "pulls": {"self", "html", "issue", "comments", "review_comments", "review_comment", "commits", "statuses"},
                "pr_comments": {"self", "html", "pull_request"},
                "reviews": {"html", "pull_request"},
            }.get(endpoint, set()) if strict_required else set()
            if (not isinstance(item, dict) or set(item) - relations or not required_relations <= set(item)):
                raise MetadataProjectionError("metadata_shape_unknown")
            for relation, target in item.items():
                if not isinstance(target, dict) or set(target) != {"href"}:
                    raise MetadataProjectionError("metadata_shape_unknown")
                record_number = value.get("number", parent_number)
                _validate_link_relation(endpoint, relation, target["href"], repository,
                                        record_number, value.get("id"), head_sha)
        elif key == "auto_merge":
            if item is not None:
                if not isinstance(item, dict) or set(item) - OPENAPI_OBJECT_SCHEMAS["auto-merge"]:
                    raise MetadataProjectionError("metadata_shape_unknown")
                _validate_nested_schema("auto-merge", item, strict_required=strict_required)
                for field in ("commit_title", "commit_message"):
                    if isinstance(item.get(field), str):
                        result.setdefault("nested_text", []).append(item[field])
                if item.get("enabled_by") is not None:
                    result.setdefault("nested_text", []).extend(_actor_authored_text(item["enabled_by"], strict_required=strict_required))
        elif key == "stack":
            if item is not None:
                if not isinstance(item, dict) or set(item) - OPENAPI_OBJECT_SCHEMAS["pull-request-stack"]:
                    raise MetadataProjectionError("metadata_shape_unknown")
                _validate_nested_schema("pull-request-stack", item, strict_required=strict_required)
                stack_base = item.get("base")
                if stack_base is not None:
                    if not isinstance(stack_base, dict) or set(stack_base) - {"sha", "ref"}:
                        raise MetadataProjectionError("metadata_shape_unknown")
                    _validate_nested_schema("pull-request-stack-base", stack_base,
                                            strict_required=strict_required)
                    if not isinstance(stack_base.get("sha"), str) or not re.fullmatch(r"[0-9a-f]{40}", stack_base["sha"]):
                        raise MetadataProjectionError("metadata_shape_unknown")
                    if isinstance(stack_base.get("ref"), str):
                        result.setdefault("nested_text", []).append(stack_base["ref"])
        elif key == "type":
            if item is not None:
                if not isinstance(item, dict) or set(item) - OPENAPI_OBJECT_SCHEMAS["issue-type"]:
                    raise MetadataProjectionError("metadata_shape_unknown")
                _validate_nested_schema("issue-type", item, strict_required=strict_required)
                for field in ("name", "description"):
                    if isinstance(item.get(field), str):
                        result.setdefault("nested_text", []).append(item[field])
        elif key == "issue_field_values":
            if not isinstance(item, list):
                raise MetadataProjectionError("metadata_shape_unknown")
            for field_value in item:
                if not isinstance(field_value, dict) or set(field_value) - OPENAPI_OBJECT_SCHEMAS["issue-field-value"]:
                    raise MetadataProjectionError("metadata_shape_unknown")
                _validate_nested_schema("issue-field-value", field_value, strict_required=strict_required)
                if isinstance(field_value.get("issue_field_name"), str):
                    result.setdefault("nested_text", []).append(field_value["issue_field_name"])
                raw_value = field_value.get("value")
                if isinstance(raw_value, str):
                    result.setdefault("nested_text", []).append(raw_value)
                elif raw_value is not None and (not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool)):
                    raise MetadataProjectionError("metadata_shape_unknown")
                for option_key in ("single_select_option", "multi_select_options"):
                    options = field_value.get(option_key)
                    if options is None:
                        continue
                    if (option_key == "single_select_option" and not isinstance(options, dict)
                            or option_key == "multi_select_options" and not isinstance(options, list)):
                        raise MetadataProjectionError("metadata_shape_unknown")
                    option_list = options if isinstance(options, list) else [options]
                    for option in option_list:
                        _validate_nested_schema("issue-field-option", option, strict_required=True)
                        for text_key in ("name", "color"):
                            if isinstance(option.get(text_key), str):
                                result.setdefault("nested_text", []).append(option[text_key])
        elif key in {"sub_issues_summary", "issue_dependencies_summary"}:
            component = "sub-issues-summary" if key == "sub_issues_summary" else "issue-dependencies-summary"
            if not isinstance(item, dict) or set(item) - OPENAPI_OBJECT_SCHEMAS[component]:
                raise MetadataProjectionError("metadata_shape_unknown")
            _validate_nested_schema(component, item, strict_required=strict_required)
        elif key == "pinned_comment":
            if item is not None:
                if not isinstance(item, dict) or set(item) - OPENAPI_OBJECT_SCHEMAS["nullable-issue-comment"]:
                    raise MetadataProjectionError("metadata_shape_unknown")
                result.setdefault("nested_text", []).extend(_text_leaves(
                    project_record("comment", item, repository, strict_required=strict_required)))
        elif key == "minimized":
            if item is not None and (not isinstance(item, dict) or set(item) - {"reason"}):
                raise MetadataProjectionError("metadata_shape_unknown")
            if isinstance(item, dict):
                _validate_nested_schema("nullable-issue-comment-minimized", item,
                                        strict_required=strict_required)
                if isinstance(item["reason"], str):
                    result.setdefault("nested_text", []).append(item["reason"])
        elif key == "pin":
            if item is not None and (not isinstance(item, dict) or set(item) - {"pinned_at", "pinned_by"}):
                raise MetadataProjectionError("metadata_shape_unknown")
            if isinstance(item, dict):
                _validate_nested_schema("nullable-pinned-issue-comment", item,
                                        strict_required=strict_required)
            if isinstance(item, dict) and item.get("pinned_by") is not None:
                result.setdefault("nested_text", []).extend(_actor_authored_text(item["pinned_by"], strict_required=strict_required))
        elif key == "repository":
            if item is not None:
                if not isinstance(item, dict) or not isinstance(item.get("full_name"), str):
                    raise MetadataProjectionError("metadata_shape_unknown")
                result.setdefault("nested_text", []).extend(_text_leaves(
                    _project_repository(item, item["full_name"], include_identity_text=True,
                                        component="nullable-repository", strict_required=strict_required)["repository"]))
        elif key == "performed_via_github_app":
            if item is not None:
                app_fields = OPENAPI_OBJECT_SCHEMAS["integration"]
                if not isinstance(item, dict) or set(item) - app_fields:
                    raise MetadataProjectionError("metadata_shape_unknown")
                _validate_nested_schema("nullable-integration", item,
                                        strict_required=strict_required)
                slug = item.get("slug")
                if not isinstance(slug, str):
                    raise MetadataProjectionError("metadata_shape_unknown")
                if item.get("html_url") is not None:
                    _validate_app_url(item["html_url"], slug)
                for text_field in ("slug", "name", "description", "external_url"):
                    if isinstance(item.get(text_field), str):
                        result.setdefault("nested_text", []).append(item[text_field])
                if item.get("owner") is not None:
                    result.setdefault("nested_text", []).extend(
                        _integration_owner_authored_text(item["owner"], strict_required=strict_required))
                if isinstance(item.get("events"), list):
                    if any(not isinstance(event, str) for event in item["events"]):
                        raise MetadataProjectionError("metadata_shape_unknown")
                    result.setdefault("nested_text", []).extend(item["events"])
                elif item.get("events") is not None:
                    raise MetadataProjectionError("metadata_shape_unknown")
                if isinstance(item.get("permissions"), dict):
                    for permission, value in item["permissions"].items():
                        if not isinstance(permission, str) or not isinstance(value, str):
                            raise MetadataProjectionError("metadata_shape_unknown")
                        result.setdefault("nested_text", []).extend((permission, value))
                else:
                    raise MetadataProjectionError("metadata_shape_unknown")
        elif key == "assets":
            if not isinstance(item, list):
                raise MetadataProjectionError("metadata_shape_unknown")
            for asset in item:
                if (not isinstance(asset, dict) or set(asset) - OPENAPI_OBJECT_SCHEMAS["release-asset"]
                        or not OPENAPI_REQUIRED_FIELDS["release-asset"] <= set(asset)):
                    raise MetadataProjectionError("metadata_shape_unknown")
                if (not isinstance(asset.get("id"), int) or isinstance(asset.get("id"), bool)
                        or not isinstance(asset.get("name"), str) or not isinstance(asset.get("content_type"), str)
                        or not isinstance(asset.get("size"), int) or isinstance(asset.get("size"), bool)
                        or not isinstance(asset.get("download_count"), int) or isinstance(asset.get("download_count"), bool)
                        or asset.get("state") not in {"uploaded", "open"}
                        or not isinstance(asset.get("node_id"), str)
                        or any(asset.get(field) is not None and not isinstance(asset[field], str)
                               for field in ("label", "digest", "created_at", "updated_at"))):
                    raise MetadataProjectionError("metadata_shape_unknown")
                for text_key in ("name", "label"):
                    if isinstance(asset.get(text_key), str):
                        result.setdefault("nested_text", []).append(asset[text_key])
                result.setdefault("nested_text", []).append(asset["content_type"])
                for url_key in ("browser_download_url", "url"):
                    if url_key in asset and asset[url_key] is not None:
                        validate_transport_url(url_key, asset[url_key], repository,
                                               object_id=asset.get("id") if url_key == "url" else None,
                                               release_tag=value.get("tag_name") if url_key == "browser_download_url" else None,
                                               asset_name=asset.get("name") if url_key == "browser_download_url" else None)
                uploader = asset.get("uploader")
                if uploader is not None:
                    result.setdefault("nested_text", []).extend(_actor_authored_text(uploader, strict_required=strict_required))
        elif key == "pull_request":
            if not pull_request_issue:
                if not isinstance(item, dict) or not set(item) <= {"url", "html_url", "diff_url", "patch_url"}:
                    raise MetadataProjectionError("metadata_shape_unknown")
                for url_key, url_value in item.items():
                    validate_transport_url(url_key, url_value, repository)
        else:
            raise MetadataProjectionError("metadata_shape_unknown")
    # Retain validated non-transport leaves for the unchanged value-only audit.
    # Arbitrary custom-property values remain authored, even when keyed "url".
    nested_values = {key: item for key, item in value.items()
                     if key not in TOP_LEVEL_AUTHORED_FIELDS[kind] and key not in structural and key not in generated}
    validated_nested_urls = generated | {"avatar_url", "followers_url", "following_url", "gists_url",
                                         "starred_url", "subscriptions_url", "organizations_url", "repos_url",
                                         "received_events_url", "hooks_url", "issues_url", "members_url",
                                         "public_members_url", "repositories_url", "href"}
    nested_text = _text_leaves(nested_values, exclude_keys=frozenset(validated_nested_urls))
    if nested_text:
        result.setdefault("nested_text", []).extend(nested_text)
    return result


def project_fixture(audience: str, repository: str, local_commit: str, remote_head: str,
                    coverage: list[dict]) -> tuple[None, None]:
    return None, None
