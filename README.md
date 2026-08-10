# Engineering

## Why, what, how

Engineering prevents an attractive but unsafe shortcut: calling a change
"ready" because a graph, test, or task happened to pass. It gives each Git
project a local, evidence-bound view of requirements, decisions, code, checks,
and known gaps. It works in the foreground: assess the repository, preview any
setup, establish or reconstruct a baseline, prepare bounded work, then verify
and complete it. Missing or contradictory evidence remains **Unknown**. It
does not alter a project, publish code, or make a live decision automatically.

## Native delivery

Start with the orchestrator. It classifies the task, definition of done,
dependencies, and risk triggers, then uses the host's native task DAG. It fans
out independent work only when beneficial, assigns one writer per shared
mutable resource, and receives observable state from direct implementer-
designer feedback. Consequential lanes can carry an independent auditor.
Engineering does not replace Codex or Claude, remove their tools, context,
permissions, or autonomy, or impose an artificial concurrency limit.

User input and feedback start the investigation; they do not define the whole
scope by themselves. Before dispatch, the orchestrator reconstructs the
available decision history, approved intent, dependencies, adjacent flows, and
bounded workspace state. Architecture/design and SME work investigates root
causes and adjacent omissions and maps both the reported symptom and those
findings to acceptance. Dispatch that investigation first; only its
architect-approved scope goes to the implementer. The orchestrator rejects
symptom-only handoffs and narrow, incomplete, or proxy-only results, even when
the literal symptom appears fixed.

For a consequential feedback handoff, the native controller can carry the
bounded `scope_handoff` envelope: seed evidence, reconstructed scope,
architect-approved scope, result scope, expected result artifacts, and a
commit-bound signed approval over an exact decision-ledger artifact must be
explicit. Completion compares observed changed artifacts to that signed set.
Missing or
self-attested approval, or a narrow result, fails closed; this is a contract
on the host-native task flow, not a second orchestration runtime.

The orchestrator integrates accepted lane results and independently accepts or
rejects the exact integrated artifact. A lane result or stale artifact is not
acceptance. Material feedback identifies affected requirements and invalidated
evidence; unrelated evidence remains usable.

Model choice remains with the caller and native platform. When delivery
evaluation is used, requested, actual, and fallback model facts are recorded
without prescribing a provider, model family, reasoning level, or task
topology. Material decision review asks whether the concept should exist and
whether doing nothing is better. The narrowest technical or functional SME is
used when material risk or domain impact could change design, business rules,
ownership, KPIs, or acceptance. Current primary web research is allowed for
external facts, but facts, assumptions, citations, and Unknowns stay separate;
organization-specific details are never invented.

Owner-private delivery evaluations retain trigger decisions, requested and
actual models, fallback, dependency and parallelism data, feedback/rework,
auditor coverage, escaped defects, false blockers, and trends. A missing or
non-applicable item carries a reason. Recommendations remain local to the
user's harness and cannot silently modify the upstream Engineering Skill.
Before a parent lane reports active, complete, or awaiting approval, its
orchestrator consumes each native child terminal event and records the exact
artifact identity, acceptance state, current gate, and next action. The
owner-private evaluation ledger retains the newest 365 records within 1 MiB;
it records terminal reconciliation latency and unconsumed-event signals.
Trends use the latest comparable task/DoD cohort and return
`insufficient_sample` when fewer than two records are comparable.
Automated, build, technical, and visual checks are necessary evidence, never
product acceptance by themselves. Every delivery separately records technical,
domain/semantic, and end-to-end outcome acceptance against representative data
through the actual consumer interface/environment; missing data or outcome evidence is
`unknown` and fails the acceptance gate. The interface may be a CLI, API, file,
or other real consumer--not necessarily a UI. Proxy-pass/outcome-fail and audit
false-positive signals keep a high technical score from implying acceptance.
Accepted outcomes retain bounded outcome and representative-data evidence
digests bound to validated completion/check receipts; unbound claims are
rejected, and an audit false positive requires completed audit coverage.
Historical pre-binding evaluation records remain readable but are not upgraded
into current acceptance evidence during migration or current trend cohorts.
LangGraph is intentionally absent: add a runtime only after a demonstrated gap
in native task semantics and separate architecture approval.

## Scoped authority in 2.2.4

Engineering now distinguishes business-authority presence from whether approval
must be requested again. A controller-signed project-local record keeps exact
authority across unchanged turns, retries, callbacks, and bounded repair
epochs. It is bound to repository lineage, authority epoch, target, action
class, scope, and safeguards. Missing, revoked, consumed, expired, or changed
bindings require new business authority.

Full Access remains a native technical permission, not business approval.
Native destructive, connector, credential, and system approvals remain
mandatory even when business authority is present. Delegation can only narrow
authority, and signed exact-artifact audit history remains evidence rather than
authority. Codex and Claude continue to use one canonical skill without losing
native tools, context, permissions, autonomy, or concurrency.

## How it works

For a greenfield repository, Engineering assesses the local Git state, previews
project controls, and—after approval—scaffolds the controls. Its first eligible
commit gets a canonical local graph and deterministic overlay. For a mid-flight
repository, it assesses first, previews adoption, reconstructs an advisory
baseline, and preserves historical gaps as Unknown until they are reviewed and
accepted. In both cases the everyday flow is: **assess → preview/approve setup
→ baseline → prepare bounded work → verify/complete**.

## Deterministic and LLM-assisted work

| Phase | Mode |
| --- | --- |
| Setup preview/mutation, pinned Graphify build/update/traversal/map, overlays, reducers, hooks, status, coverage, impact, assurance, receipts, maintenance | Local deterministic; no LLM or provider call. |
| Graphify installation | Network only after explicit approval; no LLM. |
| Codex/Claude design, planning, implementation, review, bounded-context interpretation, and optional semantic-evidence authoring | LLM-assisted and task-dependent. |
| Greenfield setup | Controls can be scaffolded mechanically; intent and requirements still need human or host reasoning. |
| Mid-flight reconstruction | The host may help; exact links stay evidence-bound and incomplete history stays Unknown/advisory. |

Engineering has no daemon or background LLM loop. Map, status, hooks, and the
controller never silently call an LLM; host usage depends on the task.

## Dependencies and prerequisites

- Required: a local Git repository and an eligible commit for a canonical map.
  Without Git, Engineering stays useful in advisory mode and recommends local
  initialization; it does not create a remote or commit implicitly.
- Required for graph features: pinned Graphify 0.9.5 at reviewed commit
  `d89ec68af95e0cad801b56d88df383991e659823`, so the code graph is
  reproducible. The package does not declare a broader Python support range.
- Optional: Codex or Claude for host reasoning; deterministic CLI/map paths do
  not depend on either. Network is needed only for approved dependency install
  or separately authorized external work.
- Optional enhancements: schedulers, telemetry, identity, feedback, and
  portfolio services. They are not hidden dependencies.

## Quick start

Ask Codex or Claude to use Engineering for the current project. For routine
local inspection, run `engineering --help`, then use `engineering map`,
`engineering status <root>`, `engineering coverage <root>`,
`engineering trace <root> <id>`, `engineering impact <root> <id>`,
`engineering assurance-status <root> <capability> <cell>`,
`engineering retrospect <root>`, or `engineering maintain status` as
appropriate. `engineering autonomy <level> [root]` changes the saved level; it
is not an inspection command. On Windows, only an install into the active
operating-system user's home adds its managed command directory to user `PATH`
and the current process. A new terminal may still be required. Temporary or
custom-home installs, replay, upgrade, and rollback never mutate either `PATH`.
Version 2.2.3 prevents new test-home pollution; it does not remove arbitrary
historical entries.

Setup approval, `prepare`/`complete`, hooks, checkpoint/rebuild, and the
learning lifecycle are controller or CI operations—not routine user commands.

| Autonomy | May do | Never does |
| --- | --- | --- |
| Guided | Detect and recommend. | Edit project controls without approval. |
| Collaborative (default) | Handle routine, authorized in-scope work; queue unrelated maintenance. | Make consequential changes. |
| Steward | Collaborative work plus one safe foreground maintenance pass. | Start a background service or expand authority. |

All levels still need explicit approval for setup, dependencies, public or
persisted contracts, publication, merge, deployment, security, credentials,
financial decisions, destructive work, and ambiguity.

Traceability debt is explicit but proportionate. Historical or advisory gaps
remain visible while unrelated work proceeds. A native orchestrator may launch
disjoint maintenance in parallel; shared-ledger mutations and overlapping
writers serialize under the existing repository lock. Preparation blocks only
when checkpoint identity/integrity, required
current-contract evidence, or a selected graph/release acceptance is at risk.
Authoritative-ledger and deterministic-overlay parity remains a blocking gate
for graph-dependent acceptance. This uses native task events and the existing
evaluation ledger, not a scheduler or another state machine.

## What ships in 2.2

2.2 ships the local capability manifest/topology, evidence reducer,
deployment-cell assessment, bounded execution context, project-owned decision
ledger indexing, and exact-commit Graphify plus deterministic overlays. It also
supports opt-in `semantic_matrices`: only a declared ownership, routing,
responsibility, classification, or state matrix touched by the change is
checked. Each row needs one owner (or explicit unavailable/unowned state), one
code identity, and positive and negative verification. Undeclared matrices,
historical gaps, and unrelated work are not blocked.

Decisions remain project-owned. Engineering indexes them but never infers
approval or implementation from code, tests, or graph edges. Local/private
evidence stays outside Git, and no live state changes automatically.

Version 2.2.2 also adds `engineering retrospect`: a read-only audit over the
finite manifest, ledger, declared overlay sources, and checkpoint. The first
call returns a digest-bound preview of sources, matrix scope, work, permissions,
outputs, and optional host-LLM cost; rerun with `--preview-digest` to audit. It
reports evidence classifications, declared matrix cells, and ledger/overlay drift. Optional host
LLM reconciliation receives only that bounded source list and remains advisory;
the controller never invokes an LLM or writes remediation.

Version 2.2.3 adds the native delivery policy and bounded owner-private
evaluation/trend records. Upgrade and rollback replace only validated skill,
loader, launcher, and receipt surfaces; they preserve applied-learning queues,
applied practices, attestations, keys, graph/checkpoint state, and other local
overlays. Neither operation activates a project, connector, hook, or schedule.

## Scale and limits

| Context | Evidence today |
| --- | --- |
| Solo developer | Intended and locally validated; worktrees on one machine share local evidence. |
| Team | Manifests/ledgers are tracked; each machine regenerates checkpoints. Tests model clones, worktrees, locking, reconciliation, and concurrency, not a real multi-user deployment. |
| Enterprise | Capability/topology reducers have cell and boundary fixtures, but this is not an enterprise platform claim. No centralized HA service, distributed operational store, SSO/RBAC authority, telemetry platform, scheduler, cross-project live aggregator, or large-enterprise field validation ships in 2.2. |

Very large monorepos, many concurrent users or machines, long-duration
operational evidence, and real enterprise topology/adapters remain untested or
partially tested. The surrounding harness services above are roadmap/deferred
work, not shipped dependencies.

## Troubleshooting and deeper detail

If a map is unavailable, check Git/commit state, the pinned Graphify runner,
and checkpoint freshness; Engineering reports the smallest recovery action.
Read [SKILL.md](.agents/skills/engineering/SKILL.md) for operating guidance,
the [controller contract](.agents/skills/engineering/references/controller-contract.md)
for exact commands and receipts, and the
[Capability Assurance design](docs/specs/engineering-capability-assurance-design.md)
for the reviewed scope and deferred services.

This repository is available under Apache-2.0. Verification does not authorize
installation or use in a live project.
