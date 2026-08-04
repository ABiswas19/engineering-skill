# Engineering

## Why, what, how

Engineering prevents an attractive but unsafe shortcut: calling a change
"ready" because a graph, test, or task happened to pass. It gives each Git
project a local, evidence-bound view of requirements, decisions, code, checks,
and known gaps. It works in the foreground: assess the repository, preview any
setup, establish or reconstruct a baseline, prepare bounded work, then verify
and complete it. Missing or contradictory evidence remains **Unknown**. It
does not alter a project, publish code, or make a live decision automatically.

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
`status`, `coverage`, `trace`, `impact`, `assurance-status`, `autonomy`, or
`maintain status` as appropriate. On Windows, installation adds its one managed
command directory to the user PATH; open a new terminal after first install.

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

## Scale and limits

| Context | Evidence today |
| --- | --- |
| Solo developer | Intended and locally validated; worktrees on one machine share local evidence. |
| Team | Manifests/ledgers are tracked; each machine regenerates checkpoints. Tests model clones, worktrees, locking, reconciliation, and concurrency, not a real multi-user deployment. |
| Enterprise | Capability/topology reducers have cell and boundary fixtures, but this is not an enterprise platform claim. No centralized HA service, distributed operational store, SSO/RBAC authority, telemetry platform, scheduler, cross-project live aggregator, or large-enterprise field validation ships in 2.2. |

Very large monorepos, many concurrent users or machines, long-duration
operational evidence, and real corporate topology/adapters remain untested or
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
