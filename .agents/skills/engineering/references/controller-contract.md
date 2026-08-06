# Engineering controller contract

## Routing

Engineering is a thin classifier. For a request with engineering impact, select
only one applicable module:

| Request | Module |
|---|---|
| Status, trace, coverage, or explanation | Explain or query |
| Requirements, options, or implementation approach | Design or plan |
| Authorized code or configuration change | Implementation |
| Defect, failing check, or incident | Debugging |
| Code, security, architecture, or evidence assessment | Review |
| Post-work verification or reusable-learning assessment | Completion and learning |
| Stale-artifact backlog | Maintenance |

For conversation, translation, formatting, trivial inspection, and work without
engineering impact, skip Engineering. Do not build a graph or run preparation.

For an explanation request, use plain language. Cover automatic behaviour,
Guided/Collaborative/Steward autonomy, retained evidence, and approval
safeguards without exposing prompt jargon or project-specific private data.

## Graph and hook boundaries

Do not use Graphify `global` or Graphify `merge-graphs`. Do not create a
canonical umbrella graph. Each project retains its own bounded graph and
checkpoint evidence.

Preserve existing hooks. Altering live project hooks requires separate explicit
authorization. Ordinary task authorization is insufficient.

Graph construction, traversal, and map rendering are deterministic and
code-only: the pinned Graphify `update` path, its reviewed incremental adapter,
and local BFS/DFS/path/explain operations. Engineering never invokes
`graphify extract`, provider-backed labeling, or an LLM backend, and removes
provider credential variables from Graphify subprocess environments. A query
budget limits returned context, not provider/API spend. This does not constrain
the host agent's normal reasoning: when prose is needed it may read the bounded
redacted execution-context slice under task authority, without adding it to the
canonical Graphify graph.

The common-directory dispatcher identifies a project from the invoking
worktree's Git INDEX. It activates only when exactly one tracked
`engineering-traceability.json` or `engineering.json` exists. With neither
manifest it returns the deterministic `manifest_not_tracked` no-op. Once
activated it validates that manifest generation and fails closed with
`invalid_manifest`, `missing_ledger`, `invalid_ledger`, `missing_links`,
`invalid_links`, `missing_governed_artifact`, or
`invalid_governed_artifact`; it never borrows a peer worktree's identity.
Activation and local pre-commit validation do not require `origin/HEAD`.
The selected INDEX manifest remains bound through post-commit rebuild and
pre-push validation, so an untracked opposite-generation manifest cannot
redirect either operation. A configured default branch is read from that
selected manifest only for downstream behavior that needs the branch identity.
Project-control validation requires `project.default_branch` to be a non-empty
string; post-merge fails closed with `invalid_manifest` when it is missing or
invalid and uses only the value returned by that validation.

## Project and toolchain discovery

For one explicit folder with no local Git repository, Engineering returns the
read-only `not_version_controlled` advisory state. It may inspect local files
and instructions but creates no graph, store, commit, remote, or publication.
`engineering map` reports that a canonical map awaits local version control.
Setup previews one digest-bound local `git init` plus controls action; applying
that remains separate project-controls authority and preserves every file.
Folders containing nested repositories are refused as ambiguous workspaces.

Resolve one exact Git root, branch, commit, Git common directory, and configured
default branch before reading or publishing evidence. Adopt an existing
`engineering-traceability.json` and `docs/engineering-traceability/` before the
version 2 defaults, `engineering.json` and `docs/engineering/`; never duplicate
an adopted project source. Setup adopts controls only after validating the
manifest version and inputs, links, decision ledger, and every governed source.
It fails closed with the exact missing or invalid artifacts instead of treating
a configuration file alone as a completed setup.

The resolved manifest may contain the single allowlisted managed-instruction
field `managed_instructions.checks`. Its structured argv takes precedence over
the manifest's structured `checks`, which takes precedence over fallback
discovery. Every check is a non-empty argv array; free-form project
instructions and shell strings are never parsed or executed. The generic
fallback recognizes Python unittest projects and npm lockfile projects; a
project without a recognized stack keeps an empty fallback until its native
argv is explicitly configured.

Graphify is exactly version `0.9.5` from
`https://github.com/safishamsi/graphify`, commit
`d89ec68af95e0cad801b56d88df383991e659823`, with `update`, `path`, and
`explain`. Setup requires an explicit absolute Python interpreter outside
the project and rejects linked/reparse executables. Its path, executable digest,
and version are part of the plan. A missing installation may only be proposed
for that interpreter as:

```text
<python> -m pip install git+https://github.com/safishamsi/graphify.git@d89ec68af95e0cad801b56d88df383991e659823
```

Execute that exact argv with `shell=False` and a credential-reduced environment
only during explicitly authorized setup. Then verify version, source commit,
required commands, and unchanged identity through the same interpreter. Reject
an unpinned branch, different source, different interpreter, or project-local
installation target.

`engineering setup <root>` returns `engineering.setup.v1` and does not mutate
the project. Its displayed preview is compact: relative paths, digests,
existence, and hook scope only. Its `project_plan_digest` internally binds the
exact v2/adopted controls, managed `AGENTS.md` and `CLAUDE.md` blocks,
`/graphify-out/` ignore addition, preservation-aware hook installation, prior
bytes, expected bytes, modes, and selected interpreter identity. Approval is a separate `engineering
approve-setup` operation with explicit scopes, not values accepted by `setup`.
It creates a one-use HMAC attestation bound to immutable Git root lineage, the
complete current plan, exact interpreter identity, and pinned argv. When
Graphify is missing, require both `project_controls` and `graphify_install`
scopes plus both displayed digests. `setup` replans before each mutation,
consumes the exact attestation once, and rejects stale, altered, partial,
replayed, or caller-invented authority. Preparation and completion do not carry
these approvals.

Hooks may be changed only at canonical `<git-common-dir>/hooks`. External or
relative `core.hooksPath` resolving elsewhere, symlink/junction/reparse
destinations, forged markers, changed managed bytes, wrong modes, and
interpreter drift fail closed. Existing custom hooks are preserved through the
exact plan. Both `engineering-preserved/**`, which migration reads, and
`engineering-traceability-preserved/**`, which the dispatcher executes, have
distinct recursive inventories bounded to 64 artifacts and 4 MiB each. Each
binds exact hook-relative paths, file types, bytes, digests, modes, and link
targets. Links/reparse points are rejected before content reads. The exact
approved dispatcher, wrappers, manifest, and both inventories are validated
inside `_install_hooks_authorized` before mutation. Migration output is derived
solely from the approved bytes and is never reread from a mutable source. Each
hook target's approved preimage is compared inside the final replacement
primitive immediately before `os.replace`; mismatch writes nothing. A managed inventory makes later executed-hook
change, removal, or addition invalidate readiness until fresh attested setup.
Before any project-file read, setup also validates unresolved ancestors and
leaf, resolved project containment, and regular-file-or-absent type for both
manifest generations, `AGENTS.md`, `CLAUDE.md`, `.gitignore`, ledgers, links,
and setup READMEs. The setup operation lock spans final replan, inner hook
validation, hook migration, and project publication. Every changed project
document also binds exact existence, type, bytes, digest, and mode; compare-and-
swap rechecks that pre-state during staging and immediately before each
transactional replacement. Drift aborts and rolls back prior setup writes
without overwriting the concurrent document. The legacy `bootstrap`,
`reconstruct`, and `install-hooks` commands only return the setup proposal; they
never mutate.

Project file and hook publication is rollback-safe. A failed Graphify install
reports `graphify_install_failed` and leaves no project controls, baseline, or
hooks. Installer success followed by failed same-interpreter verification
reports `external_change_unverified` and also writes no project state. A
verified Graphify install is not transactionally uninstalled if later project
publication fails; restore the exact project files and hooks, retain the
verified pinned prerequisite, and report
`graphify_installed_project_setup_failed`.

## Deterministic overlay

The controller permits direct, derived, inferred, and
missing deterministic-overlay provenance; commit-bound checkpoint integrity and
atomic publication; feature/canonical separation; unrelated hook bodies; and
the `status`, `coverage`, `trace`, `impact`, `why-code`, `why-test`, and
`compare` queries. Graphify ambiguity remains base-graph navigation evidence
and is never a deterministic overlay provenance value.

## Shared local graph refresh

All linked worktrees in one clone use
`<git-common-dir>/engineering-graphs/`; independent clones keep independent
local caches. Git-tracked overlay inputs produce a stable fingerprint so a
fetched correction clears shared drift only after the receiving clone rebuilds
and validates the exact commit.

Before graph-derived work, the controller makes a read-only bootstrap
assessment. It reports unmanaged repositories as advisory/Unknown; a greenfield
repository without an eligible commit as `waiting_for_first_commit`; and a
managed repository as current only when one canonical default-branch checkpoint
has matching Graphify pin, exact commit, overlay version, input digest, graph
digest, and integrity evidence. Construction first verifies the already selected
Graphify runner. Missing or incompatible Graphify is one actionable blocker; it
never falls back to another graph generator. Installing or upgrading it remains
separate setup authority.

With setup authority, a missing or stale canonical checkpoint is rebuilt from
the exact local default-branch ref, with Graphify and overlay atomically
published and read back together. An active feature receives its own isolated
checkpoint only after that canonical baseline. Feature records are never merged
into canonical: commits already ancestral to default are historical, absent
branches archive locally, and invalid/orphaned records are quarantined as
Unknown. Nothing is automatically deleted. A first construction or broad
reconciliation reports its bounded local scope and affected controller
catalogue; it does not mutate source, branches, or remotes.

An exact commit and Graphify-pin hit performs no Graphify update. Otherwise the
controller copies the nearest compatible local ancestor into atomic staging,
computes Git's add/modify/delete/rename/copy path set, and gives those paths
unchanged to the exact pin- and signature-verified
`graphify.watch._rebuild_code(snapshot, changed_paths=[...])` adapter. Graphify,
not Engineering, owns code-suffix detection. The adapter runs in one detached
exact-commit worker with its current directory set to the snapshot and
`GRAPHIFY_OUT` set before Graphify imports to the registered staging path; the
controller stamps the incremented graph with the exact target commit before
validation.
Public `graphify update <root>` is full-corpus work used only by explicit
non-hook rebuild or maintenance. The controller rejects incompatible private
adapter signatures and a `built_at_commit` other than the requested target.

Before publication it parses and schema-validates `graph.json`, binds its
digest, target commit, and clone/worktree-stable project identity into the
checkpoint, and applies stable-ID and unexpected-shrink guards against the
selected ancestor. Graph schema validation requires unique non-empty node IDs
and requires every link endpoint to resolve to one of those IDs. Links are
unique by Graphify's source, target, relation, confidence, source file, and
source location fields; derived weights do not make duplicate relations
distinct. Exact cache
and CI repeat parse, schema, commit, identity, and digest checks, recompile the
deterministic overlay from the exact commit, and compare its nodes, edges,
integrity counts, input digest, and tracked inputs exactly. It publishes both
layers together. Feature work publishes only below
`features/<escaped-branch>/<commit>`; only freshly resolved default-branch
authority publishes below `main/<commit>`. One exact-checkpoint selector
performs cache lookup and full validation for both rebuild and canonical
reconciliation. JSON roots that are not objects are `invalid_schema` for cache,
ancestor selection, and CI. A deletion permits only the ancestor nodes whose
normalized `source_file` names that deleted path to count toward the
retained-ratio budget; it never waives unrelated graph loss.

Post-commit never performs a cold build. Hook refresh has one monotonic deadline
from entry: invoking-INDEX selection is charged first, and one worker receives
only the remainder. A non-positive or exhausted budget starts no worker.
The worker owns diff, ancestor copy, detached snapshot, adapter, validation, and
atomic publication. Expiry terminates its process tree, preserves the prior
checkpoint, and records the target stale. Semantic and document/media changes
remain stale until explicit semantic completion; copying an ancestor semantic
layer never makes them current or CI-ready.

Each worker has one parent-owned resource record below
`state/operations/<opaque-id>/`, exact registered `worktree/` and `staging/`
paths inside that operation root, and one repository lock only at
`state/lock/`. The record binds the lock's operation ID and opaque token.
Registration atomically publishes a live parent owner before the record becomes
visible. Registration and every read anchor separately to lexical and resolved
Git-common directories, then lexically recompute every normalized absolute
operation, record, worktree, staging, lock, and result path from the opaque ID
before resolving any path; every serialized path must equal that recomputed
path. The controller walks every existing component below the trusted common
directory, including `state`, `operations`, the opaque operation directory,
each resource, `lock`, and `owner.json`, and rejects any symlink, junction, or
reparse ancestor or leaf. The lexical operation and lock paths must be exact
children of their trusted roots, their resolved targets must remain within the
resolved trusted operations/state roots, and every operation-local resource
must remain below the resolved operation root. Reconciliation preserves any
in-flight operation while its exact lock owner is live and reclaims registered,
worktree-created, staging-ready, validating, published, or already-orphaned
state only after the owner is dead and both the operation and lock-owner UTC
timestamps exceed the bounded minimum orphan age. Missing, invalid, or future
timestamps remain unresolved rather than being guessed stale. Immediately
before process launch, the record saves `worker_start_pending=true` and records
tree death as false. A
successful launch atomically replaces that state with the worker PID,
`worker_start_pending=false`, false tree death, and, on POSIX, the new session's
process-group ID. A Popen failure clears pending, confirms that no worker tree
exists, and preserves the original launch failure. A pending launch is a
durable blocker because a crash may have occurred after Popen but before worker
identity persistence. Timeout uses the saved POSIX group ID even when the
leader has already exited and escalates the same group from `SIGTERM` to
`SIGKILL` within the bound. A started worker whose tree-death field is missing
or false remains blocked unless recovery can prove that its saved POSIX process
group is absent; that proof is persisted with freshly recomputed trusted paths
before cleanup can continue. A present or unverifiable POSIX group remains
blocked. On Windows, a leader already exited at the first termination poll is
also unconfirmed without Job Object or equivalent whole-tree proof. An
operation with no pending launch and no saved worker PID is a pre-launch
operation and remains recoverable. Tree death is otherwise recorded only after
group absence is confirmed; an unconfirmed tree prevents cleanup from touching
registered resources.
Cleanup has one monotonic deadline
for the complete operation,
including process start, worktree removal, and filesystem deletion, reserves
only a bounded termination grace, and delegates only the registered worktree
and staging payload to cleanup children. The parent removes the small result,
record, operation root, and exactly matching dead-owner lock only after every
cleanup child is reaped. The full trusted boundary is revalidated immediately
before each cleanup child launch and before every parent unlink or directory
removal. Before any failed cleanup result is persisted, the controller again
validates the trusted root and opaque operation ID and replaces every serialized
resource path with its freshly recomputed trusted value. A changed boundary
returns `invalid_hook_operation_boundary` without writing. A child that
survives termination grace leaves its PID and live state in the operation
record and blocks recovery until it dies. The
controller never prunes worktrees or broadly scans deletion
targets. Incomplete cleanup remains a durable orphan that blocks later workers
until exact bounded recovery succeeds; mismatched or live locks are preserved.

Canonical reconciliation resolves one configured remote and default branch,
then validates one fetch mapping whose destination is exactly
`refs/remotes/<remote>/<default-branch>`. When authorized, it uses a bounded
explicit source-to-destination refspec. Missing, narrow, ambiguous, branch,
tag, other-remote, or unrelated destinations are rejected before fetch.
Without a successful refresh in that reconciliation, a configured remote is
`unknown` and cannot publish canonical state. Source, destination, authority,
and commit are rechecked immediately before publication. It never pulls,
merges, switches, resets, prunes, or edits the invoking worktree. A repository
without a remote uses the configured local default branch and reports
`not_configured`. A valid canonical checkpoint at that same commit returns
`exact_cache` only after the same authority is rechecked immediately before the
result is accepted.

Version 2 contains no enterprise-graph endpoint, client/provider, upload,
autodetection, configuration, or automatic switch. Bounded Git refresh and
explicitly approved non-hook Graphify or project-native operations remain
separate allowed operations. Executed graph-path argv is limited to the local
Python interpreter and Git; real Graphify integration uses only public
`update` or the exact pinned private changed-path adapter.

## Legacy output reconciliation

Maintenance inventories `graphify-out` under every linked worktree. Cleanup is
allowed only after an exact shared replacement succeeds and the legacy tree is
ignored generated output whose every relative descendant matches the exact
versioned legacy inventory. Unknown, private, inventory-untracked, symlink,
junction, and reparse descendants make it ambiguous. Inventory flags are not
deletion authority: the controller immediately re-resolves the exact worktree
boundary, rebuilds inventory, repeats reparse/private checks, and revalidates
the replacement checkpoint before targeted deletion. Ambiguous output is
preserved and queued as
`legacy_graph_ambiguous`.

## Preparation contract

For a non-trivial request, preparation runs automatically before authorized
work. It must identify the exact project, branch, commit, configured authority,
and task scope; discover applicable instructions and project-native toolchain;
check relevant decisions and contracts; determine bounded impact; select
validation; and return one of `ready`, `ready_with_advisories`, or `blocked`.

Missing or contradictory authority, unverified contract evidence, or an approval
boundary that prevents the requested work returns `blocked`. Preparation may be
called directly only for diagnostics, CI, or explicit inspection.

`prepare(root, intent, scope, override=None)` and `engineering prepare` return
only `engineering.prepare.v1`: stable run and project identifiers, bounded
intent, the scope/forbidden/deterministic-only authorization envelope, autonomy,
readiness,
blockers, advisories, stable context identities and provenance, deterministic
impact, and structured required-check argv. Context selection is ordered:
explicit requirement and decision IDs, Graphify query results within the
configured token budget, then exact deterministic neighbours. New manifests
configure a 1000-token context budget; legacy manifests without that field use
the same 1000-token default. Stable IDs are
deduplicated in deterministic first-ID order while retaining the strongest
provenance (`direct`, `derived`, `inferred`, then `ambiguous`). Inferred and
ambiguous context may guide navigation but cannot satisfy readiness.

The controller selects bounded matching IDs from the pinned parsed base graph;
it does not invoke `graphify query`, an LLM, or a provider backend. It returns
`success`, `empty`, `unavailable`, or `invalid`. Unknown IDs and malformed data
are invalid; a missing or unreadable checkpoint is unavailable. Invalid or
unavailable context blocks as `missing_required_source` unless an exact
controller-signed `engineering.task-authority.v2` independently validates the unchanged safe
local task. The legacy `deterministic_only_approved` input remains parseable
for compatibility but grants no waiver. This exception never replaces
sufficient exact context or impact. Successful empty output is distinct from
failure and still requires sufficient exact evidence for readiness, regardless
of intent wording. Selected IDs join explicit IDs for exact-neighbour and impact checks. Contract approval
evaluates the full validated bidirectional
exact-context closure, including upstream contracts. Exact-context provenance
is carried across the full path; any derived edge makes that path derived, and
a later all-direct path upgrades the stable node without duplicating it. Impact
remains directed;
each row carries whether its own path contains a derived edge, and a direct path
wins when multiple paths reach the same node or stable source identity.
Preparation disables Graphify's separate
query log so bounded intent and query output are not copied outside the retained
run metadata.

The blocking conditions are `ambiguous_project`,
`missing_current_checkpoint`, `conflicting_authority`,
`unapproved_contract_change`, and `missing_required_source`. The advisory
conditions are `remote_freshness_unknown`,
`historical_gap_before_baseline_acceptance`, and `unrelated_maintenance`.
Dirty paths outside the authorization envelope are conflicting authority;
dirty paths already inside the envelope do not independently block. An affected
public contract, including a directly selected contract origin, remains blocked
until an approved stable decision ID is recorded in the authoritative project
ledger and supplied as `contract_approval_id`. A caller boolean, including the
legacy `contract_change_approved`, never clears this gate.

Preparation writes one atomic `preparation.json` below
`<git-common-dir>/engineering-graphs/runs/<run-id>/`. Linked worktrees reuse this
Git-common run directory; independent clones do not. Retained preparation data
never includes source bodies, an unbounded prompt, credentials, raw Graphify
output, arbitrary query IDs, or connector payloads. Credential-shaped intent is
redacted before use or retention; credential-shaped scope and forbidden entries
are rejected.

Final handoff defaults to one-sentence **Outcome**, then **Now** and **Next**;
include **Blocked** only for a genuine blocker. Preparation, readiness, impact,
completion evidence, and technical caveats are optional **Details**, used only
when a decision, troubleshooting, or audit needs them. Routine commentary does
not repeat controller headings. Preparation still identifies project,
authorized scope, instructions, and project-native toolchain; readiness is
`ready`, `ready with advisories`, or `blocked`; impact names known affected
contracts, artifacts, callers, and tests; completion reports checks and
retained evidence. Do not invent a stack or present an unverified assumption as
fact.

## Capability assurance and execution context

Capability Assurance is a project-local, untracked controller overlay. Its
manifest records only stable capability identities, deployment cells,
obligations, and bounded adapter contracts; observations remain bound to an
exact capability, release, interface, cell, validity interval, and applicable
role. The reducer reports independent lifecycle, deployment, availability,
verification, acceptance, confidence, freshness, and derived live status.
Absent adapters or evidence produce `unknown`; a severe incident or other
contradiction remains visible and blocks a fully-live result.

The controller may emit a harness recommendation only where a declared
obligation, an observed missing or contradictory evidence item, and a
project-neutral remediation class are all present. Catalogued detector packs
cover only their named classes. Otherwise the answer is `unknown`.

`engineering.execution-context.v1` is derived only from a preparation result.
It binds the run, root digest, commit, scope, exact direct/derived context,
bounded redacted assertions, explicit forbidden IDs, and a canonical digest.
Validation rejects malformed, stale, scope-expanded, digest-mismatched, or
provenance-expanded bundles before dispatch. A runner that cannot keep other
graph-derived sources away from the worker receives an `advisory` result, not
an enforced-isolation claim.

## Routine local-check authority

`approve-checks` remains the compatibility and higher-risk path. An explicitly
authorized host may issue a controller-signed `engineering.task-authority.v2`
with one task identity, the exact discovered command digest, and a complete
false classification for network, connector, publication, deployment,
live-environment, and destructive effects. The controller independently
requires project-declared argv, no credentials, no inline interpreter code,
and no shell execution. It revalidates the same authority and argv digest at
completion. Missing or malformed authority, any changed command, unknown or
positive effect, inline code, shell, or credential data fails closed. The
preparation record retains only the bounded authority and command identities;
ordinary user prose is never an approval substitute. Version 1 unsigned
envelopes are rejected rather than silently upgraded.

The signed envelope is short-lived bearer evidence for one repository commit;
the host must keep it within the authorized task. Cross-session identity and
role verification remain an external host/identity-service responsibility, not
an authority claim made by Engineering.

## Read-only retrospective

`engineering retrospect <root>` first returns a digest-bound preview naming the
finite sources, semantic-matrix axes and scope, deterministic work, permissions,
outputs, and optional bounded host-LLM cost. Repeating it with
`--preview-digest <digest>` inventories only the project evidence declared by
the manifest, authoritative ledger, overlay nodes, and optional semantic
matrices. It reports current, missing, stale, contradictory, orphaned, deferred,
excluded, and Unknown evidence with a remediation proposal. It makes no graph
build, controller write, LLM/provider call, or project change. An
optional `--llm-reconcile` result is only a bounded source-list packet for the
host; any host inference remains advisory until the project owner records it.
Undocumented intent remains Unknown, and only declared required cells in the
requested scope can block a later impacted change.

## Completion contract

### Declared finite semantic matrices

`semantic_matrices` is opt-in and belongs in the project manifest only where an
approved project contract already declares a finite ownership, routing,
responsibility, classification, or state-distribution inventory. A touched row
has exactly one `owner`, or an explicit `state` of `unavailable` or `unowned`,
and references one `code_symbol` plus positive and negative verification nodes.
Engineering blocks only the impacted change when that atomic identity is missing
or conflicting. It does not infer inventories, add domain types, or block
undeclared, historical, or unrelated work.

Completion runs automatically after the authorized work. It compares predicted
and actual artifacts, runs or verifies selected checks, reconciles direct links,
refreshes the feature checkpoint, clears verified stale items, queues unrelated
maintenance, and confirms the work remained within authorization.

`complete(root, run_id, receipts)` and `engineering complete` consume the exact
retained `engineering.prepare.v1` run. Completion uses the same single
Git-common repository lock and operation registry as graph refresh. It executes
only the prepared argv arrays with `shell=False`; caller-supplied check receipts
are prohibited. It retains exit code, duration, and output digest, never command
output. Changed-artifact and replay identity include Git index objects, modes,
submodule state, unstaged content, and each untracked artifact's content, lstat
file type, and executable mode. Both ends of detected renames or copies are
included. For an unstaged exact copy, the bounded untracked blob is compared to
tracked HEAD and index object identities and every exact tracked source endpoint
is included in authorization and contract checks. Initial changed paths are
accepted only when bracketed by two equal exact working-state identities. The
controller validates INDEX and WORKTREE overlays for new public contracts and
rechecks the complete working-state identity after checks and immediately before
atomic publication.
An exact replay strictly rederives and compares every preparation- or
current-state-owned field, accepts only the exact manifest schema, and validates
successful prepared-command evidence. A changed or tampered replay, changed
tree, scope expansion, or unpredicted public-contract change fails closed.

The retained change manifest contains bounded identifiers for task intent,
authority and autonomy, selected context, changed artifacts, predicted and
actual impact, traceability changes, checks, unresolved risk or maintenance,
checkpoint, and commit or pull-request identity when present. It is evidence,
not approval. Completion may be called directly only for diagnostics, CI, or
explicit inspection.

The atomic Git-common manifest uses `engineering.complete.v1`. It retains no
source or context bodies, raw check output, absolute project root, connector
payload, or project-independent learning schema.

The completion part reports checks, evidence, and remaining approval or
maintenance decisions after authorized work. When blocked, it reports the
smallest missing authority or evidence and the completion checks required after
authorization; it does not continue.

## Autonomy and maintenance contract

| Level | Automatic work |
|---|---|
| `guided` | Detect, explain, and recommend; ask before editing project artifacts. |
| `collaborative` | Repair routine, directly affected drift inside the authorized task; queue unrelated drift. |
| `steward` | Collaborative behaviour plus safe queued maintenance during an Engineering run. |

`engineering maintain status <root>` shows grouped queued work, age, and impact.
`engineering maintain <root>` processes safe queued work once. `engineering
maintain <root> --area <stable-area>` limits that processing to one area.
Neither command changes autonomy or
expands authority.

The saved level lives in the adopted project manifest. A preparation override
is retained only in that run and never rewrites the saved level. The controller
accepts only `guided`, `collaborative`, or `steward`; first setup recommends and
records `collaborative`, then suppresses the repeated explanation.

Each saved-level command also appends one bounded record to the adopted project
configuration's dedicated `autonomy_history`: previous/new level, UTC
timestamp, generic origin, and generic reason only. Exact replay deduplicates
the record. Legacy autonomy entries migrate out of generic `history`;
all unrelated history remains ordered and untruncated.

Maintenance state uses the existing Git-common
`engineering-graphs/state/maintenance.json`, the same repository operation
lock, and atomic replacement. Stable kind/area/artifact/target identity
deduplicates items; impact can escalate but not silently downgrade. A
checkpoint target contains only an opaque repository-and-branch lineage, its
40-hex origin commit, and an opaque origin-run identity. It never stores an
absolute path or branch name. Status reports compact area groups, age,
safe/blocked counts, and raises each aging item once. A one-off pass processes
only allowlisted, mechanically verified repairs. Failed, blocking, ambiguous,
and consequential items remain queued. An unchanged failed repair is not
automatically retried: it remains visible until inputs change or an explicit
rerun or resolution. Collaborative
reports the one-off command when backlog exists. Steward invokes that same safe
foreground pass during preparation. No level starts a daemon, service, timer,
or background schedule.

Completion, graph workers, and legacy-output reconciliation normalize all
observations first, then mutate this queue once under their existing repository
operation lock. Completion retains only opaque maintenance IDs. Existing state
is schema- and timestamp-validated; missing required members, non-project
paths, URI/query/control or credential-shaped artifacts, reversed timestamps,
and materially future timestamps block processing.

Retained completion replay validates prospective opaque IDs but performs no
queue mutation. A new completion validates scope, contracts, checks, and stable
working state before snapshotting maintenance, applying its one batch, and
publishing the manifest. Manifest failure restores the exact prior bytes or
absence. Successful exact checkpoint publication removes only checkpoint-stale
items with the same opaque lineage whose origin commit Git proves is an
ancestor of or equal to the published commit, using argv-only `merge-base
--is-ancestor`. Missing, ambiguous, unrelated, or unverifiable targets remain
pending. The controller retains bounded completion history; failed or unrelated
items are neither retried nor rank-downgraded.

## Invariant safeguards

No autonomy level authorizes publication, merge, deployment, release,
production change, destructive or irreversible action, security/privacy/
compliance/credential/financial decisions, public or persisted contract changes,
material architectural or dependency changes, action under ambiguous intent or
conflicting authority, or shared-skill promotion.

Use only generic, synthetic content in the shared skill. Keep project-specific
requirements, evidence, identities, and context in the project; never copy them
into shared skill material or unrelated prompts. Preserve existing instructions,
hooks, toolchain, and valid evidence unless the authorized task explicitly
requires a compatible change.

## Storage map

- Tracked inputs are the adopted manifest, decision ledger, links, and project
  instructions. They remain reviewable in Git.
- The compiled overlay, checkpoints, completion manifests, maintenance state,
  project contribution records, keys, and attestations are controller-private
  under the repository Git-common `engineering-graphs` directory.
- The current user's owner-private Engineering directory holds the bounded
  contribution queue and index, promotion attestations and keys, the signed
  install receipt, one previous receipt, and the Claude loader metadata. It
  holds no raw project bodies or populated graph copy.

Canonical user-private paths resolve beneath `ENGINEERING_USER_HOME` when set,
otherwise beneath the operating-system home. HMAC attestations provide local
tamper evidence within that owner-private boundary; they are not public-key
signatures, nonrepudiation, or proof of an interactive identity. Hostile/shared
multi-user and UNC controller storage are unsupported and fail closed without
handle-anchored path and identity enforcement.

In the path notation below, `<engineering-home>` is that resolved home. The
canonical bundle, prior bundle and loaders are
`<engineering-home>/.agents/skills/engineering/`,
`<engineering-home>/.agents/skills/.engineering.previous/`,
`<engineering-home>/.agents/skills/engineering-traceability/`, and
`<engineering-home>/.claude/skills/engineering/`. The installed command launchers
are `<engineering-home>/.agents/bin/engineering` and `engineering.cmd`; on Windows
installation adds only that managed directory to the user `PATH` (a new terminal
picks it up). The machine controller is
`<engineering-home>/.agents/engineering/controller/`; its key, attestations and
index are `attestation.key`, `attestations.json`, and
`contribution-index.json`. The queue and operation locks are
`<engineering-home>/.agents/engineering/contribution-queue.json`,
`contribution.lock`, and `install.lock`. Its install receipts are
`install-receipt.json` and `previous-install-receipt.json`. Per-project keys and
attestations live under `<git-common-dir>/engineering-graphs/controller/`.

## Check capability approval

`approve_checks(root, allow_inline_code=False)` discovers but does not execute
the project checks, returns their exact argv, and records a durable local
attestation bound to immutable project lineage plus the digest of each normalized
argv. Ordinary source changes do not invalidate it. A lineage or argv change
does. Interpreter inline-code modes fail closed unless the caller separately
uses `--allow-inline-code`; that approval covers only the exact displayed
commands and grants no broader action, connector, credential, or external-effect
authority. Check execution uses a credential-reduced environment and no shell.
The signed claims include the `inline_code` boolean, so an attestation created
with `allow_inline_code=False` cannot authorize inline argv. Approval covers the
exact invocation, not future source behaviour, and is not a sandbox: an unchanged
argv may run changed source with its remaining operating-system permissions.
The execution environment retains only `APPDATA`, `COMSPEC`, `HOME`, `LANG`,
`LC_ALL`, `LOCALAPPDATA`, `PATH`, `PATHEXT`, `SYSTEMROOT`, `TEMP`, `TMP`,
`USERPROFILE`, `VIRTUAL_ENV`, and `WINDIR`; all other inherited variables are
removed. External effects require their own authorization.
For compatibility, an HMAC-valid legacy check attestation missing only
`allow_inline_code` matches an otherwise exact non-inline claim as effective
false. It never matches an inline claim and the controller does not silently
rewrite it.

## Contribution quarantine and installation

`propose_learning(root, completion_id, kind, practice)` accepts only a clean terminal
`engineering.complete.v1` manifest with successful retained checks and a
current exact checkpoint plus its matching controller-issued completion
attestation. A fully shaped caller-written manifest is not authority. A new
candidate also carries one exact `engineering.practice.v1` payload: bounded
generic title, instruction, applicable modules, deterministic verification and
an explicit sanitization declaration. Unknown keys, executable text, paths,
URLs, credentials and unsupported modules fail closed. Normalized practice
digests suppress duplicate proposals. Legacy candidates without a practice
remain readable history but cannot become applied guidance. The project-local
record and bounded machine queue otherwise retain only opaque project/source
digests, a completion reference, state, evidence receipts, and review metadata.
Raw bodies, repository paths, secrets, and project instructions are excluded.

The user projection exposes only candidate ID, title, kind, applicable modules,
state, and `keep`, `inspect`, and `dismiss` actions. It never exposes project or
source digests, local paths, evidence bodies, or controller internals.

Project identity is the digest of the unique immutable Git root commit. Clones,
forks retaining that root, and linked worktrees are one lineage; remote edits do
not change it. A repository with a different root is distinct. Ambiguous
multiple-root history fails closed. The Git common-dir controller directory
retains signed completion attestations. Promotion attestations are retained
separately from the editable queue under the caller-owned Engineering
controller directory. The private contribution locator is signed over the
candidate, lineage, exact common graph directory and exact local record; it
cannot redirect across projects. Keys, registries and locators reject unresolved
reparse parents and publish atomically. POSIX mode is verified as owner-only;
Windows applies a protected owner ACL and verifies explicit SIDs, inheritance,
and absence of broad allow entries through PowerShell/.NET, failing closed.

The legacy lifecycle is `proposed`, `evaluating`,
`approved_for_promotion`, `promoted`, or `rejected`. A validated practice uses
`promoted_applied`: promotion and owner-local application are one explicit
transaction, never two confirmations. `evaluate_learning(...)` derives the registered project
identity from a terminal verified completion and records a controller-created
evaluation; `record_learning_approval(...)` records the explicit decision.
Promotion accepts only retained evaluation identifiers and the durable approval
transition, never caller-supplied project digests, results, histories, or state.
The passing evaluation must come from a distinct second project; promotion
never establishes an enterprise default. Discovery also requires the signed
promotion attestation to match the candidate digest, lifecycle and review IDs,
and every source-project identity. Missing, altered, or replayed queue material
fails closed. Each transition atomically advances the controller queue and the
project-local lifecycle record so the two cannot contradict.
`promote_and_apply(...)` also publishes the signed
`engineering.applied-practices.v1` ledger in that same transaction. It permits
at most 128 active practices and 256 KiB of serialized state. Tamper, overflow,
partial publication, missing practice data, or an unmatched evaluation leaves
the prior state intact. `disable_applied_practice(...)` changes only the signed
ledger entry after explicit approval; immutable candidate and evidence history
remains `promoted_applied`.

`applicable_practices(module, manifest_version=...)` reads only active,
integrity-valid entries for the requested module and returns candidate ID,
title, instruction, verification, and a bounded applicability reason. Major
version mismatch fails closed. Preparation snapshots the relevant preparation
and completion guidance so later replay does not depend on a changed ledger;
completion carries only its prepared snapshot. Invalid ledger state produces an
explicit blocked practice status and injects no guidance. Controller-only CLI
surfaces cover propose, evaluate, keep, inspect, dismiss, Promote and apply,
status, and disable. Mutating commands require the exact candidate-bound
confirmation phrase.

`source_improvement_proposal(candidate_id)` accepts only a
promotion-attested `promoted_applied` practice and returns its candidate and
practice digests, bounded evidence digests, affected contract modules, required
verification, and `proposal_only` authority. It returns no source path, patch,
diff, command, commit, publication, release, or installation action.

`install_bundle(source, home)` takes an explicit home for testability. It
validates the tracked Git source closure and rejects symlinks, junctions,
reparse points, unpinned Graphify metadata, and non-Git sources. Under one
foreground install lock it stages beside the canonical target, replaces the
canonical bundle, generic loaders, and command launchers, and writes `engineering.install.v1` with
the skill version, source commit, source digest, Graphify commit, UTC timestamp,
and equal Codex/Claude canonical-skill hashes. A failure restores the exact
prior surfaces. Publication of every bundle, loader, receipt, and rollback
surface uses one shared transaction. One fully digest-validated prior canonical
bundle and receipt are retained;
`rollback_install(home)` swaps only those known-good versions and regenerates
the thin Claude and v1 compatibility loaders. No shell command is constructed
from source or home values.
