# Engineering Applied Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the reviewed Engineering v2 baseline in its standalone repository, then add a safe Promote-and-apply learning loop and a working sanitized public export.

**Architecture:** Preserve the existing single-file controller and contribution lifecycle. Add a bounded declarative practice payload, one transactional applied-practice ledger under the existing Engineering home, and thin CLI/skill projections. Keep source improvement proposal-only and produce the public mirror from a corporate-only allowlist into an independent repository history.

**Tech Stack:** Python 3.12 standard library, `unittest`, Git, Graphify 0.9.5 at `d89ec68af95e0cad801b56d88df383991e659823`, Markdown, JSON, GitHub Actions.

## Global Constraints

- The standalone repository must contain no project-specific product names, histories, runtime state, or private evidence.
- The base Engineering skill and installed bundle must remain byte-identical during learning lifecycle operations.
- Applied practices are declarative only; arbitrary code, commands, hooks, dependencies, contracts, and network behavior are rejected.
- Promotion and application are one explicit, atomic, rollback-safe transition.
- At most 128 active practices and 256 KiB serialized applied-ledger state are allowed.
- Existing `promoted` records remain historical and inactive unless they satisfy the new practice validation.
- Codex and Claude consume one canonical Engineering home.
- The public mirror has independent history and receives only an allowlisted, fully scanned tree.
- Public publication requires an approved licence and explicit delivery authority.
- No user-home installation, project-controls application, or live-project mutation occurs in this plan.
- Each task records its dependency and completion signal before the next begins.

---

## File Structure

```text
.agents/skills/engineering/
  SKILL.md                         Human and agent operating contract
  manifest.json                    Version, schema, and Graphify pin
  agents/openai.yaml               Codex discovery metadata
  references/controller-contract.md
  scripts/engineering.py           Deterministic controller and CLI
  tests/scenarios.json             Fresh-context behavior scenarios
  tests/test_engineering.py        Controller and lifecycle tests
.github/workflows/security.yml     Generic cross-platform checks
docs/specs/engineering-applied-learning-design.md
docs/plans/engineering-applied-learning.md
release/public-export.json         Corporate-only export allowlist
tests/test_repository.py           Standalone/public-tree contracts
tools/check_sensitive.py           Generic full-tree scanner
tools/export_public.py             Allowlisted independent-tree exporter
.gitignore
AGENTS.md
CLAUDE.md
README.md
SECURITY.md
```

### Task 1: Establish the standalone reviewed v2 baseline

**Dependency:** Exact reviewed Engineering source checkpoint `c48e86084e873f97160be3492d205696b3860529` is available read-only.

**Completion signal:** The standalone source contains only the seven intended skill files, generic repository controls, no forbidden names or generated state, and the existing v2 test suite passes unchanged.

**Files:**
- Create: `.agents/skills/engineering/**`
- Create: `.gitignore`
- Create: `AGENTS.md`
- Create: `CLAUDE.md`
- Create: `README.md`
- Create: `SECURITY.md`
- Create: `tools/check_sensitive.py`
- Create: `tests/test_repository.py`

- [ ] **Step 1: Write the failing standalone-source contract**

Add tests that enumerate the expected seven source files, reject `__pycache__`,
`*.pyc`, generated graph/state files, absolute user paths, private identifiers,
and the forbidden project-name set. The test must scan file content and paths.

```python
EXPECTED_SKILL_FILES = {
    "SKILL.md",
    "manifest.json",
    "agents/openai.yaml",
    "references/controller-contract.md",
    "scripts/engineering.py",
    "tests/scenarios.json",
    "tests/test_engineering.py",
}

def test_skill_tree_is_generic_and_exact():
    actual = {path.relative_to(SKILL_ROOT).as_posix() for path in SKILL_ROOT.rglob("*") if path.is_file()}
    assert actual == EXPECTED_SKILL_FILES
```

- [ ] **Step 2: Run the contract and confirm it fails**

Run: `python -m unittest tests.test_repository -v`

Expected: FAIL because the standalone skill tree and repository controls do not exist.

- [ ] **Step 3: Import only the reviewed skill files**

Copy the seven exact files from the reviewed checkpoint into
`.agents/skills/engineering/`. Do not import repository history, generated
files, design ledgers, runtime state, or unrelated tests. Record a migration
receipt containing the source commit and SHA-256 for each imported file.

- [ ] **Step 4: Add generic repository controls**

Create minimal human-readable instructions and ignore rules for Python caches,
local test state, generated graph checkpoints, controller state, and export
staging. The sensitive-data scanner must inspect every tracked file and reject
personal paths, emails, private IDs, secret-shaped values, and forbidden names.

- [ ] **Step 5: Run the standalone and inherited v2 gates**

Run:

```powershell
python -m unittest tests.test_repository -v
python -m unittest discover -s .agents/skills/engineering/tests
python -m compileall -q .agents/skills/engineering tools tests
python tools/check_sensitive.py
git diff --check
```

Expected: all pass, with only capability/platform skips already documented by the reviewed v2 baseline.

- [ ] **Step 6: Commit the baseline locally**

Stage only the paths listed in this task and commit:

```text
feat: establish standalone Engineering v2 baseline
```

Do not push.

### Task 2: Add bounded declarative candidate payloads and user projection

**Dependency:** Task 1 baseline passes unchanged.

**Completion signal:** A verified completion can retain and project at most one sanitized candidate; ordinary completion remains silent.

**Files:**
- Modify: `.agents/skills/engineering/scripts/engineering.py`
- Modify: `.agents/skills/engineering/tests/test_engineering.py`
- Modify: `.agents/skills/engineering/references/controller-contract.md`

- [ ] **Step 1: Write failing candidate-schema tests**

Test a payload with this exact shape:

```python
practice = {
    "schema": "engineering.practice.v1",
    "title": "Verify generated output before replacing a canonical checkpoint",
    "instruction": "Publish generated output only after identity and integrity checks pass.",
    "applies_to": ["completion", "maintenance"],
    "verification": "A failed rebuild retains the prior valid checkpoint.",
    "sanitized": True,
}
```

Assert rejection of extra keys, overlong strings, unknown modules, embedded
paths/URLs/credentials, executable text, private names, and multiple candidate
payloads. Assert normalized duplicates retain one identifier.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m unittest .agents.skills.engineering.tests.test_engineering.EngineeringSkillTests.test_learning_practice_contract -v`

Expected: FAIL because the contribution schema has no practice payload.

- [ ] **Step 3: Implement the minimal validated payload**

Add `ALLOWED_PRACTICE_MODULES`, exact size limits, `_validate_practice()`, and a
normalized digest. Change:

```python
def propose_learning(root: Path, completion_id: str, kind: str, practice: dict) -> dict:
    ...
```

Retain the terminal completion attestation gate and include the normalized
practice in both project-local and controller queue records.

- [ ] **Step 4: Add a bounded user projection**

Return a projection containing candidate ID, generic title, kind, modules,
state, and the actions `keep`, `inspect`, and `dismiss`. Do not return project
paths, raw evidence bodies, repository identity, or controller details.

- [ ] **Step 5: Run focused and lifecycle tests**

Run the candidate, contribution, sanitization, replay, and terminal-completion test classes. Expected: PASS.

- [ ] **Step 6: Commit**

```text
feat: add bounded Engineering learning candidates
```

### Task 3: Make promotion and local application one transaction

**Dependency:** Task 2 produces validated candidate payloads.

**Completion signal:** Explicit promotion creates `promoted_applied` and one integrity-protected applied-ledger entry atomically; every failure retains prior state.

**Files:**
- Modify: `.agents/skills/engineering/scripts/engineering.py`
- Modify: `.agents/skills/engineering/tests/test_engineering.py`
- Modify: `.agents/skills/engineering/references/controller-contract.md`

- [ ] **Step 1: Write failing applied-ledger tests**

Cover distinct-project evaluation, combined approval, atomic queue/local/index/
attestation/ledger publication, replay, rollback, tamper, 128-active limit,
256-KiB limit, same-lineage rejection, and legacy `promoted` inactivity.

- [ ] **Step 2: Run the new tests and confirm failure**

Expected: FAIL because `applied-practices.json` and `promoted_applied` do not exist.

- [ ] **Step 3: Implement the existing-home ledger**

Add:

```python
def _applied_practices_path() -> Path: ...
def _load_applied_practices() -> dict: ...
def promote_and_apply(candidate_id: str, evaluation_ids: list[str], approved: bool) -> dict: ...
def disable_applied_practice(candidate_id: str, approved: bool) -> dict: ...
```

Use the existing Engineering home resolver, controller key, directory lock, and
transactional JSON publication. No new lock, key store, database, or service is
introduced.

- [ ] **Step 4: Preserve and migrate existing lifecycle records**

Accept existing `promoted` records as valid history. Provide an explicit
migration attempt that applies only records with valid terminal attestations,
distinct-project evidence, an allowed practice, and fresh combined approval.

- [ ] **Step 5: Run lifecycle, concurrency, ACL, and rollback tests**

Expected: all focused tests pass; Windows owner-private inheritance tests remain green.

- [ ] **Step 6: Commit**

```text
feat: apply promoted Engineering practices atomically
```

### Task 4: Consume applied practices and expose the lifecycle safely

**Dependency:** Task 3 produces a valid applied ledger.

**Completion signal:** Later relevant preparation/completion results include only applicable practice summaries; both agent surfaces expose the same lifecycle and no skill source bytes change.

**Files:**
- Modify: `.agents/skills/engineering/scripts/engineering.py`
- Modify: `.agents/skills/engineering/SKILL.md`
- Modify: `.agents/skills/engineering/agents/openai.yaml`
- Modify: `.agents/skills/engineering/tests/scenarios.json`
- Modify: `.agents/skills/engineering/tests/test_engineering.py`
- Modify: `.agents/skills/engineering/references/controller-contract.md`

- [ ] **Step 1: Write failing relevance and immutability tests**

Hash the base skill before and after propose, evaluate, promote/apply, consume,
disable, and rollback. Assert identical bytes. Test module relevance,
incompatible-version disablement, malformed-ledger failure, and shared Codex/
Claude Engineering-home resolution.

- [ ] **Step 2: Add bounded practice selection**

Implement:

```python
def applicable_practices(module: str, *, manifest_version: str) -> list[dict]: ...
```

Return only candidate ID, title, instruction, verification, and reason. Cap the
result to the active ledger bounds and never include evidence internals.

- [ ] **Step 3: Extend preparation/completion projections**

Add optional `applied_practices` arrays without changing existing required
fields. An unavailable or invalid ledger reports an explicit blocked practice
status and injects nothing.

- [ ] **Step 4: Add lifecycle CLI surfaces**

Add controller-only commands for propose, evaluate, Promote and apply, status,
inspect, dismiss, disable, and source-improvement proposal. Combined approval
must require the exact candidate identifier in the confirmation phrase.

- [ ] **Step 5: Update the human-readable skill contract**

Explain when a learning is surfaced, that Promote means apply, how to inspect
or disable it, and that base-source improvement remains proposal-only.

- [ ] **Step 6: Run fresh-context, CLI, parity, and full skill tests**

Expected: all pass and base-source immutability is proven.

- [ ] **Step 7: Commit**

```text
feat: consume applied Engineering practices
```

### Task 5: Add proposal-only base-skill improvement and safe public export

**Dependency:** Task 4 completes the local lifecycle.

**Completion signal:** A promoted practice produces only a bounded source proposal, while an independent public-tree export is generic, working, scanned, and history-isolated.

**Files:**
- Modify: `.agents/skills/engineering/scripts/engineering.py`
- Modify: `.agents/skills/engineering/tests/test_engineering.py`
- Create: `release/public-export.json`
- Create: `tools/export_public.py`
- Modify: `tools/check_sensitive.py`
- Modify: `tests/test_repository.py`
- Create: `.github/workflows/security.yml`

- [ ] **Step 1: Write failing source-proposal and export tests**

Assert a source-improvement result contains candidate/evidence digests,
affected contract, and required tests but no diff, source write, commit, or
publication action. Assert export copies only allowlisted paths into an
independent Git worktree and preserves its `.git` directory.

- [ ] **Step 2: Make secret-shaped fixtures scanner-safe**

Construct deliberately secret-shaped test inputs from harmless fragments at
runtime so GitHub secret scanning sees no credential-shaped tracked literal
while the controller tests still exercise rejection.

- [ ] **Step 3: Implement the corporate-only exporter**

The exporter validates source/destination boundaries, rejects reparse links and
unlisted files, preserves destination Git metadata, removes stale previously
exported files only within its recorded allowlisted set, and produces an exact
tree digest. The manifest itself is excluded from the public tree.

- [ ] **Step 4: Add generic CI and full-tree security checks**

CI runs the repository tests, full skill suite, compileall, sensitive-data scan,
and diff/whitespace checks on Windows and Linux where supported.

- [ ] **Step 5: Exercise a disposable independent public clone**

Verify no shared common Git directory or history, no forbidden names/private
state, and working tests. Public publication remains blocked if `LICENSE` is
absent or not bound to approved release evidence.

- [ ] **Step 6: Commit**

```text
feat: add safe Engineering public distribution
```

### Task 6: Reconcile, independently review, and stop at delivery authority

**Dependency:** Tasks 1–5 are clean and committed locally.

**Completion signal:** Every design requirement maps to source and an exact passing test; the complete diff has an independent read-only Opus PASS; both destination trees are ready but no unapproved publication or installation occurs.

**Files:**
- Modify: `docs/plans/engineering-applied-learning.md` only for checked evidence
- Review: complete repository tree and generated public candidate tree

- [ ] **Step 1: Reconcile requirement traceability**

Map every design verification item to exact tests and retained output. Preserve
partitioned evidence honestly when one aggregate run exceeds the execution
window.

- [ ] **Step 2: Run all gates**

```powershell
python -m unittest discover -s tests
python -m unittest discover -s .agents/skills/engineering/tests
python -m compileall -q .agents/skills/engineering tools tests
python tools/check_sensitive.py
git diff --check
```

Run the same applicable gates in the generated public candidate tree.

- [ ] **Step 3: Run independent exact-diff review**

Use Opus as the read-only checker. Bind the review to the first standalone
baseline commit and include the complete implementation diff, approved design,
plan, tests, security evidence, public-export evidence, and completion receipt.
Address any material finding test-first and rerun affected/full gates.

- [ ] **Step 4: Verify destination readiness**

Confirm exact authenticated identities, internal/public visibility, empty or
history-compatible destinations, approved licence, CI availability, and push
rights. Fail closed on any mismatch.

- [ ] **Step 5: Stop before publication and installation**

Report the clean reviewed commit chain, public-tree digest, tests, review
receipt, and remaining delivery authority. Do not push, create a PR, merge,
install the user-home bundle, or apply project controls in this plan.

## Requirement Traceability

| Requirement | Task | Verification |
|---|---|---|
| Standalone generic source | 1 | Exact-tree and forbidden-reference tests |
| Candidate at terminal evidence only | 2 | Completion/proposal tests |
| Silence and duplicate suppression | 2 | Projection/digest tests |
| Promote means apply | 3 | Atomic lifecycle test |
| Existing records remain safe | 3 | Legacy migration test |
| Bounded applied ledger | 3 | 128-entry and 256-KiB failure tests |
| Future relevant invocation only | 4 | Applicability tests |
| Codex/Claude parity | 4 | Shared-home fixture |
| Base skill never self-modifies | 4 | Byte-identity regression |
| Source improvement is proposal-only | 5 | No-diff/no-write test |
| Canonical/public paired delivery | 5, 6 | Export and destination checks |
| No private or generated state | 1, 5 | Full-tree scanner and allowlist test |
| No automatic publication/install | 4, 6 | Negative authority and delivery-boundary tests |

## Local Execution Evidence

- Task 1 baseline: `4a8c160`; exact seven-file source hashes match the reviewed migration receipt. Repository contract, compile, sensitive-data and diff checks passed. The inherited aggregate controller suite exceeded its Windows execution bound without an assertion result; final verification therefore uses unchanged per-test partitions.
- Task 2 candidates: `b6776ff`; schema, unsafe-content rejection, bounded projection, terminal evidence and duplicate replay tests passed.
- Task 3 application: `30d5b20`; distinct-project evidence, one combined Promote-and-apply approval, atomic rollback, tamper, active-count, size-limit, disablement and legacy-promotion regressions passed.
- Task 4 consumption: `b60cbb5`; relevance, version gate, completion snapshot, skill byte identity, exact CLI confirmation, human contract and Codex/Claude canonical-install parity passed.
- Task 5 distribution: `de67d05`; proposal-only source improvement, allowlisted independent-history export, public repository contract, skill-shape, compile and sensitive-data checks passed. Apache-2.0 was subsequently selected and added to the canonical allowlist; its exact digest belongs in the external completion receipt so the exported tree does not describe its own hash.
- Task 6 hardening: `0612397`; state-specific actions, owner-private applied-ledger validation and fail-closed practice consumption are covered by the bounded changed-surface regression.
- GitHub delivery, installation, project controls and live-project mutation remain excluded pending final review and explicit authority.
