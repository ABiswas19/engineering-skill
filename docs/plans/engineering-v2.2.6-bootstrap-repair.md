# Engineering v2.2.6 Bootstrap Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the circular v2.2.6 default-branch signer bootstrap with an exact, non-circular delivery receipt and a host-owned post-activation trust boundary.

**Architecture:** The first installer validates a host-provided bootstrap receipt against the actual source bundle and accepted artifact without reading post-activation trust. After activation, all new owner approvals and audit attestations validate a host-owned anchor and host receipt stored outside candidate Git. A separately retained import proves the recorded owner baseline covers accepted owner outcomes and product releases before dependent admission.

**Tech Stack:** Python standard library, `ssh-keygen -Y verify`, JSON, Git identity commands for local exact-source checks, `unittest`.

**Spec:** `docs/specs/engineering-v2.2.6-owner-intent.md` and `docs/specs/engineering-v2.2.6-owner-intent-audit-repair.md`

## Global Constraints

- Keep v2.2.5 source, install receipt, and rollback untouched.
- Do not change GitHub settings/access, invite collaborators, create/publish personal keys, push, PR, merge, install, or activate.
- Do not put populated owner intent, credentials, private keys, runtime evidence, or host configuration in Git.
- Preserve exact-source install, outcome survival, intent-impact, evidence, independent-audit, rollback, privacy, and public-sanitization protections.
- Keep one writer for each paired source; mirror only allowlisted generic artifacts.

---

### Task 1: Establish bootstrap and host-boundary regressions

**Files:**
- Modify: `.agents/skills/engineering/tests/test_engineering.py`
- Test: `.agents/skills/engineering/tests/test_engineering.py::Task11OwnerIntentContractTests`

**Interfaces:**
- Produces: synthetic `host-authority` fixture, `bootstrap_authorization`, and host receipt builders.
- Consumes: existing Task10 temporary Git and key fixtures.

- [x] **Step 1: Write failing bootstrap tests**

Add tests that call the not-yet-implemented bootstrap/install path with a complete literal authorization, patch the post-activation anchor loader to raise, and assert that no such call occurs. Add negative tests for a missing v2.2.5 receipt digest, fewer than two distinct audit records, and A-token/B-bundle source facts.

- [x] **Step 2: Run focused tests to verify red**

Run: `python -m unittest .agents.skills.engineering.tests.test_engineering.Task11OwnerIntentContractTests.test_v226_bootstrap_acceptance_does_not_call_postactivation_trust`

Expected: FAIL because the bootstrap authorization API and install path do not exist.

- [x] **Step 3: Write failing host-boundary and import tests**

Add tests that create a private external host-anchor fixture, mutate a candidate-local signer file, restart/re-read the external state, vary a signed receipt's repository/epoch/contract, and require a complete post-activation import before product-release or accepted-owner-outcome admission.

- [x] **Step 4: Run focused tests to verify red**

Run: `python -m unittest .agents.skills.engineering.tests.test_engineering.Task11OwnerIntentContractTests`

Expected: FAIL only at the new host-anchor/receipt/import behaviors.

### Task 2: Implement exact bootstrap authorization

**Files:**
- Modify: `.agents/skills/engineering/scripts/engineering.py`
- Test: `.agents/skills/engineering/tests/test_engineering.py`

**Interfaces:**
- Produces: `_v226_bootstrap_authorization(source_bundle, authorization)` and `install_bundle(..., bootstrap_authorization=...)`.
- Consumes: `_bundle_files`, `_tree_digest`, existing release-token install flow.

- [x] **Step 1: Add only the bootstrap receipt validator required by failing tests**

Validate the exact schema, `sha256:` digests, 40-hex source commit, version `2.2.6`, opaque approval reference, unknown identity state, distinct two-or-more audit IDs, and shared accepted artifact digest. Compare the supplied source bundle with the recomputed bundle facts.

- [x] **Step 2: Route v2.2.6 installation through exactly one preflight**

Require either the existing release-token/artifact pair or a bootstrap authorization for a v2.2.6 source, never both. Require the caller's bootstrap facts to equal the host-owned durable bootstrap record outside candidate Git, persist them in the v5 install receipt, and revalidate source/staged bundle digests before transactional publication. Release-token enforcement governs normal delivery after the one-time bootstrap; it is not a circular prerequisite for that bootstrap.

- [x] **Step 3: Run bootstrap tests to verify green**

Run: `python -m unittest .agents.skills.engineering.tests.test_engineering.Task11OwnerIntentContractTests.test_v226_bootstrap_acceptance_does_not_call_postactivation_trust .agents.skills.engineering.tests.test_engineering.Task11OwnerIntentContractTests.test_actual_install_rejects_a_release_token_for_a_different_bundle`

Expected: PASS; the old release-token flow remains covered.

### Task 3: Replace candidate-Git trust with host-owned receipts

**Files:**
- Modify: `.agents/skills/engineering/scripts/engineering.py`
- Modify: `.agents/skills/engineering/tests/test_engineering.py`

**Interfaces:**
- Produces: `_host_owned_trust_anchor()`, `_host_receipt(...)`, and `_verify_host_owned_signature(...)`.
- Consumes: caller-provided operation claims and host-owned private anchor/signers files.

- [x] **Step 1: Implement external anchor loading**

Derive the fixed host-authority directory from `ENGINEERING_USER_HOME`, reject reparse/absent/non-private paths, verify anchor schema/version/signers digest, and never create or write those files. Accept legacy v1 anchors only while reading historical records.

- [x] **Step 2: Implement receipt validation and migrate every new external admission**

Require a current anchor, exact repository lineage, authority epoch, contract, unknown-or-proven identity state, and a signature over canonical claims plus receipt. Migrate scoped authority, owner intent, owner exception, equivalence, independent audit, and traceability host attestation callers. Require current v2 anchor records for new governing work.

- [x] **Step 3: Run host-boundary tests to verify green**

Run: focused bootstrap, host-anchor, host-receipt, and post-activation-import regressions before the full suite.

Expected: PASS; candidate-local signer replacement and wrong receipt fields fail while legitimate host-owned receipts remain valid.

### Task 4: Add post-activation completeness import and downstream fence

**Files:**
- Modify: `.agents/skills/engineering/scripts/engineering.py`
- Modify: `.agents/skills/engineering/tests/test_engineering.py`
- Modify: `.agents/skills/engineering/references/controller-contract.md`

**Interfaces:**
- Produces: `intent_import`, `intent_import_status`, and a read-only dependent-dispatch admission result.
- Consumes: active imported owner intent and a host-signed completeness receipt.

- [x] **Step 1: Implement compact private import ledger**

Require the active owner-intent ID/digest/repository/epoch, exact sorted owner-outcome IDs, both coverage scopes, and an external host receipt. Sign and atomically retain it under the project controller. Duplicate exact imports replay; conflicts fail.

- [x] **Step 2: Implement non-dispatching dependent gate**

Return an admission fact only when the latest import covers `accepted_owner_outcomes` and `product_releases`; otherwise raise an explicit import-required error. Do not start a task or mutate a product/frontend project.

- [x] **Step 3: Run import tests to verify green**

Run: `python .agents/skills/engineering/tests/test_engineering.py Task11OwnerIntentContractTests.test_postactivation_import_is_required_before_v061_or_frontend_dispatch Task11OwnerIntentContractTests.test_postactivation_import_and_dependent_status_cli_dispatch_exact_inputs`

Expected: PASS, including both pre-import rejection and post-import read-only admission.

### Task 5: Document, sanitize, and verify the paired candidate

**Files:**
- Modify: `.agents/skills/engineering/SKILL.md`
- Modify: `.agents/skills/engineering/references/controller-contract.md`
- Modify: `docs/specs/engineering-v2.2.6-owner-intent.md`
- Modify: `docs/specs/engineering-v2.2.6-owner-intent-audit-repair.md`
- Modify: `docs/plans/engineering-v2.2.6-bootstrap-repair.md`
- Modify: `release/public-export.json`
- Mirror: listed shared artifacts into the paired public worktree.

**Interfaces:**
- Produces: unambiguous operator contract and allowlisted generic public projection.
- Consumes: implemented schemas and test results.

- [x] **Step 1: Update the operator contract**

State bootstrap versus post-activation authority, external host-owned configuration, Unknown identity behavior, import coverage, no GitHub/personal-key prerequisite, no self-minting, and retained native approval boundaries.

- [ ] **Step 2: Update the public allowlist and mirror exact generic files**

Add the generic plan if it contains no internal/root event or populated outcome. Keep the incident record internal-only. Copy only listed shared paths, then compare byte identity and run sensitive-data/audience checks.

- [ ] **Step 3: Run full fresh verification before freezing**

Run the repository-defined internal and public full suites, public export/sanitization parity, compilation, `git diff --check`, and clean-tree checks. Record commands, exit status, counts, exact commits, and exact tree IDs.

- [ ] **Step 4: Commit the isolated paired artifacts only after green evidence**

Create one internal and one public local commit with matching shared files. Do not push, open a PR, merge, install, or activate.

## Plan self-review

- Coverage: Tasks 1-2 enforce non-circular exact bootstrap and source/receipt integrity; Task 3 enforces external host-owned trust and receipt mismatch failure; Task 4 enforces post-activation completeness for both required scope classes; Task 5 retains documentation, parity, privacy, and full verification.
- Placeholders: none; every task identifies its concrete files, interfaces, expected failing/pass result, and verification command.
- Type consistency: bootstrap uses `source_bundle` with `source_git_commit`, `source_digest`, and `skill_version`; host receipt uses repository/epoch/contract; import uses the active intent digest and both coverage scopes.
