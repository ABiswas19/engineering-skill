# Engineering

## Why, what, how

Engineering is a project-local traceability system for connecting requirements
and decisions to the code and tests that implement them. Its evidence is bound
to an exact commit, so a map or passing check cannot silently stand in for a
different tree. Stale, missing, or conflicting evidence remains **Unknown** and
graph-dependent claims fail closed.

The product is the reviewable chain from intent to implementation and
verification: project-owned requirements and decisions, a reproducible code
graph, deterministic links and checks, local queries, and retained completion
evidence. Engineering does not infer approval from code, publish a project, or
make a live decision automatically.

## Capabilities at a glance

- **Traceability:** exact-commit checkpoints and deterministic status, coverage,
  trace, impact, why-code, why-test, and compare queries connect intent to code
  and verification.
- **Repository assessment and governed setup:** inspect an existing repository,
  preview project controls and the pinned toolchain, then apply only an exact
  approved plan.
- **Checkpoint lifecycle:** construct or rebuild the canonical and isolated
  feature evidence without merging feature claims into the default branch.
- **Bounded delivery evidence:** prepare and complete authorized work, compare
  predicted and actual impact, run approved checks, and retain receipts.
- **Outcome-survival guard:** material redesigns map every baseline approved
  outcome to included, equivalent replacement, explicit deferral, or explicit
  exclusion before they can become implementation-ready.
- **Approval persistence and bounded autonomy:** unchanged exact scope remains
  approved; Guided, Collaborative (default), and Steward govern only routine
  local work.
- **Ongoing assurance:** foreground maintenance, opt-in semantic matrices, and
  read-only retrospect expose drift and missing evidence without inventing it.
- **Delivery evaluation and trends:** retain bounded, owner-private technical,
  semantic, and outcome evidence without turning proxy checks into acceptance.
- **Applied learning:** capture a sanitized project-local practice after verified
  completion, validate it in a distinct project, and produce only a governed
  proposal for an upstream improvement.

## Traceability flow

1. **Assess the repository.** Engineering resolves one Git root, branch,
   commit, configured default branch, existing instructions, and native checks.
   An unmanaged project stays advisory and reports traceability as Unknown.
2. **Preview and approve project controls.** Setup first shows the exact
   digest-bound manifest, ledgers, instructions, hook preservation, and pinned
   toolchain plan. Only explicit, matching setup authority may apply it.
3. **Reach the first eligible commit.** In greenfield work, that commit becomes
   the first canonical checkpoint. Mid-flight work adopts existing controls and
   reconstructs an advisory baseline without pretending undocumented history is
   complete.
4. **Build the pinned Graphify code graph.** Graphify 0.9.5 at reviewed commit
   `d89ec68af95e0cad801b56d88df383991e659823` maps code at the exact checkpoint.
   A missing, incompatible, or wrong-commit graph blocks graph claims.
5. **Compile the deterministic overlay.** Engineering overlays project-owned
   requirements, decisions, direct or derived links, checks, and integrity
   evidence. Ambiguous graph navigation never becomes verified provenance.
6. **Query locally.** Use `engineering map`, `engineering status`,
   `engineering coverage`, `engineering trace`, `engineering impact`,
   `engineering why-code`, `engineering why-test`, and `engineering compare`
   to navigate the current checkpoint without a provider call.
7. **Prepare and complete bounded work.** Preparation selects exact context,
   impact, authority, and checks. Completion compares predicted and actual
   artifacts, verifies the prepared checks, refreshes eligible feature evidence,
   and rejects scope or contract drift.
8. **Keep retained receipts.** Local completion manifests and check digests
   preserve what was verified. They are evidence, not approval, and a later
   change can make them stale.

## Deterministic core, optional reasoning

Graph construction, traversal, map rendering, overlay compilation, reducers,
hooks, checkpoint validation, status, coverage, trace, impact, comparison, and
receipt verification are local deterministic code. Engineering invokes neither
provider-backed Graphify extraction nor an LLM backend. There is no background
LLM, no daemon or scheduler, no hidden provider calls, and no enterprise graph
upload.

Codex or Claude is optional. A host may use its normal reasoning for design,
implementation, review, or interpretation of a bounded redacted context slice,
but that reasoning does not enter the canonical code graph or upgrade an
inference into evidence. Engineering overlays the host's native capabilities;
it does not replace its tools, context, permissions, autonomy, approval
mechanisms, or concurrency.

## Onboarding and evidence boundaries

- **Greenfield:** assess first, preview controls, obtain explicit setup approval,
  then let the first eligible commit establish the canonical checkpoint.
- **Mid-flight:** assess and preview adoption, retain historical gaps as Unknown,
  and accept reconstructed links only when their evidence is reviewed.
- **Linked worktrees:** worktrees in one clone share the Git-common local
  checkpoint catalogue while feature checkpoints remain isolated from the
  canonical default-branch checkpoint.
- **Independent clones:** each clone rebuilds and validates its own local cache;
  fetched source alone does not import another machine's evidence.
- **Privacy:** tracked manifests, ledgers, links, and instructions stay
  reviewable in Git. Compiled graphs, checkpoints, completion records,
  attestations, and other local/private evidence remain outside the publication
  tree. There is no enterprise graph service in version 2.
- **Fail closed:** stale, missing, or conflicting evidence is Unknown. A test
  does not erase an incident, a graph edge does not prove approval, and a
  completion receipt does not authorize publication or live use.

Setup, dependency installation, hooks, persisted public contracts,
publication, merge, deployment, release, production, security, privacy,
credentials, financial decisions, destructive work, and ambiguous intent keep
their explicit approval boundaries. Guided, Collaborative (default), and
Steward autonomy change routine local behavior only; no level schedules work or
expands authority.

## Install for a project

Use the native Codex `skill-installer` against the repository from which you
received access, pinned to the exact reviewed source revision. Repository read
access permits installation; it does not grant write, merge, maintain, or admin
rights. Use the exact 40-character merged release commit supplied with the
release evidence, never a moving branch name:

```text
--repo <owner>/<repository>
--path .agents/skills/engineering
--ref <exact-40-character-merged-release-commit>
```

The installer uses existing GitHub credentials and copies only that skill
directory to `$CODEX_HOME/skills/engineering` (normally
`~/.codex/skills/engineering`). Start a new Codex turn before using the skill. It
neither writes to the repository nor adds the Engineering command to `PATH`.
Until a command launcher has been installed through a separately authorized
release procedure, invoke the checked-in `scripts/engineering` or
`scripts/engineering.cmd` from that installed directory.

Project controls remain a separate, explicit approval flow:

1. Run `engineering setup <project-root>` to preview the exact project and
   pinned-Graphify plans. It returns the required scopes and plan digests without
   applying them.
2. Review that output, then run `engineering approve-setup <project-root>` with
   the returned `--project-plan-digest`, each required `--scope`, and the
   `--graphify-plan-digest` when `graphify_install` is required.
3. Rerun `engineering setup <project-root>`. Only an unchanged, matching
   attestation is consumed to write project controls; the first eligible commit
   then establishes the canonical checkpoint.

This native route is **Codex-only**. The current skill-installer does not create
Engineering's canonical `~/.agents` bundle, signed receipt, rollback copy,
command launchers, or the thin Claude loader. The repository contains and tests
those Codex/Claude parity functions, but exposes no supported self-service CLI
that safely installs them from an exact repository commit. Claiming a portable
Codex+Claude installation through this route is therefore unsupported. The
minimal follow-up is a governed entry point over the existing canonical
installer that verifies an exact clean source commit and emits its signed
receipt; it must be separately designed, approved, and tested before use.

## Quick start

Ask Codex or Claude to use Engineering for the current project, or inspect the
local CLI:

```text
engineering --help
engineering map <root>
engineering status <root>
engineering coverage <root>
engineering trace <root> <identifier>
engineering impact <root> <identifier>
engineering why-code <root> <identifier>
engineering why-test <root> <identifier>
engineering compare <root> <commit-a> <commit-b>
```

`map` defaults to the current directory. Setup approval, checkpoint/rebuild,
`prepare`/`complete`, hooks, and the learning lifecycle are controller or CI
protocols; use the linked contracts below rather than guessing their inputs.

On Windows the launcher prefers the Python Launcher (`py -3`) and falls back to
`python` when `py` is unavailable. It does not install an interpreter or alter
`PATH` while selecting one.

### Choose an autonomy level

Inspect the saved level with `engineering status <root>`. Change it with
`engineering autonomy <level> [root]`, where the level is:

- **Guided:** detect, explain, and recommend; ask before project edits.
- **Collaborative (default):** handle routine authorized work in the exact task
  scope and queue unrelated maintenance.
- **Steward:** Collaborative behavior plus safe queued maintenance during a
  foreground Engineering run.

Autonomy changes routine local behavior only. None schedules or backgrounds
work. An autonomy level does not authorize setup, dependencies, checks,
publication, merge, deployment, production, security, privacy, credentials,
destructive or external actions; it does not expand native permissions and it
does not override exact authority. Steward may process only safe queued
maintenance during a foreground Engineering run.

### Trace one requirement

Suppose the project ledger names `REQ-042` and links it to a decision, a code
symbol, and two checks:

```text
engineering trace <root> REQ-042
engineering why-code <root> src.checkout:validate_order
engineering why-test <root> tests.checkout:test_rejects_empty_order
```

`trace` shows the evidence path for the requirement. `why-code` and `why-test`
walk back from a code or test identity to the requirement or decision that
justifies it. If an expected link is absent, stale, ambiguous, or bound to a
different commit, the answer stays Unknown rather than being guessed.

## Where to see the graph

`engineering map <root>` renders the exact current checkpoint as local HTML and
opens it in the default browser. Add `--focus <identifier>` to narrow the view
to that identifier and its reachable context. Add `--no-open` to leave the file
unopened; the `engineering.map.v1` result still returns its output path.

The generated view lives outside Git under the clone's Git-common
`engineering-graphs/maps/<cache>/index.html`. It is local/private, not uploaded,
and its cache identity is bound to the current checkpoint, overlays, and render
options. For up to 5000 nodes the HTML shows a node and type table; for more
than 5000 nodes it shows a type aggregate. The page reports the checkpoint's
node count and deterministic link count. It is a bounded inspection surface,
not a graph exploration application: `trace`, `impact`, `why-code`, `why-test`,
and `compare` provide relationship paths and evidence detail. There is no hosted
UI or enterprise graph service.

## Workflow integrations

Engineering also supports governed delivery without making orchestration the
product. The host-native orchestrator can reconstruct scope, build a
dependency-aware task DAG, use beneficial parallelism, assign one writer per
shared mutable resource, and obtain independent acceptance of one exact
integrated artifact. Codex and Claude use the same portable contract and keep
their native capabilities and permissions. Automated and technical checks are
necessary evidence; domain and real-consumer outcome acceptance remain separate
and Unknown when representative evidence is missing.

Material redesign, replacement, capability deletion, and simplification also
use the existing signed scope handoff to map every baseline requirement as
`INCLUDED`, `REPLACED`, `DEFERRED`, or `EXCLUDED`, with a reason and verification
method. Replacement needs outcome-equivalence evidence. Deferral or exclusion
needs exact owner-approved scope. Unmanaged, missing-checkpoint, stale,
conflicting, or otherwise Unknown traceability supports advisory analysis only;
it cannot be reported as accepted design or implementation-ready. Independent
design and final acceptance verify that original user/business outcomes survive,
so a narrowed contract does not pass merely by auditing itself.

Version 2.2.4 distinguishes business-authority presence from whether approval
must be requested again. Exact scoped authority can persist across unchanged
turns, retries, callbacks, and bounded repair epochs. Revocation, consumption,
expiry, or a changed repository, epoch, target, action, scope, or safeguard
requires reapproval. Delegation can only narrow authority. Full Access is a
technical permission, not business authority, and native destructive and
connector approvals remain mandatory. Exact-artifact audit records are evidence
only; they never mint or expand authority.

Optional owner-private delivery evaluation records requested and actual model
facts, dependencies, coordination, rework, auditor coverage, and independent
technical, semantic, and outcome states. It retains the newest 365 records
within 1 MiB and returns `insufficient_sample` below two comparable records.
Model selection stays with the caller and native platform. No LangGraph runtime
ships; adding one requires a demonstrated native-task gap and separate
architecture and dependency approval.

## Applied learning and source improvement

Engineering uses one project-local lifecycle rather than a second learning
store. A verified completion can capture a sanitized project-local improvement
candidate with `learning-propose`. A distinct second project supplies evaluation
evidence through `learning-evaluate`. The owner then keeps, inspects, dismisses,
or promotes and applies the candidate through the existing `learning-keep`,
`learning-inspect`, `learning-dismiss`, and `learning-promote-apply` surfaces;
an applied practice can later be disabled explicitly.

Only a promotion-attested applied practice can produce a bounded proposal-only
upstream source-improvement proposal through `learning-source-proposal`. Raw
project bodies, paths, secrets, commands, diffs, commits, publication, release,
and install actions are excluded. A proposal contains no patch or authority to
change, publish, release, or install the shared skill.

## Feedback and improving Engineering

For ordinary bugs, usability feedback, documentation gaps, or feature ideas,
**open an Issue in the repository from which you installed the skill**. Include
the Engineering version, operating system, Codex or Claude host when relevant,
command or workflow, expected versus actual behavior, whether the result was
Unknown or BLOCKED, and a minimal synthetic reproduction.

Use sanitized or synthetic examples only. Never include credentials, private
repository bodies, generated graphs or checkpoints, business data, tenant
identifiers, personal paths, or production evidence. For a suspected
vulnerability, follow that repository's SECURITY policy
([SECURITY.md](SECURITY.md)); never report a suspected vulnerability in an Issue.

Project-local improvement capture through `learning-propose` remains private and
governed, and nothing is uploaded automatically. A user may manually submit a
sanitized Issue when maintainer consideration is wanted. Every repository input
enters the same capture -> evaluate/propose -> owner decision -> apply/verify
lifecycle. Feedback is a proposal only: nothing uploads, merges, installs,
promotes, or applies automatically, and Issue access does not confer upstream
write or decision authority.

## Dependencies and prerequisites

- A local Git repository and an eligible commit are required for a canonical
  map. A non-Git folder stays read-only and advisory; Engineering never creates
  a remote or commit implicitly.
- Graph features require Graphify 0.9.5 from
  `https://github.com/safishamsi/graphify` at commit
  `d89ec68af95e0cad801b56d88df383991e659823`. Installing or upgrading it is a
  separate approved action. The package does not claim a broader Python support
  range.
- Codex and Claude are optional for host reasoning. Deterministic CLI and map
  paths depend on neither. Network is needed only for an approved dependency
  install or separately authorized external work.
- Schedulers, telemetry, identity, feedback, portfolio services, and enterprise
  graph sharing are optional or deferred integrations, not hidden dependencies.

On Windows, only a new install into the active operating-system user's home may
add the managed command directory to user and current-process `PATH`; a new
terminal may still be needed. Custom/test-home install, replay, upgrade, and
rollback do not mutate `PATH`. Version 2.2.3 prevents new arbitrary test-home
pollution but does not delete historical entries whose ownership is unknown.

## What ships in 2.2

Version 2.2 ships exact-commit Graphify checkpoints, deterministic overlays,
project-owned decision-ledger indexing, bounded execution context, local
capability/topology and evidence reducers, deployment-cell assessment,
completion receipts, and proportionate traceability debt.

Opt-in `semantic_matrices` cover only an already-declared finite ownership,
routing, responsibility, classification, or state matrix touched by a change.
Each required row has one owner or an explicit unavailable/unowned state, one
code identity, and positive and negative verification. Undeclared matrices,
historical gaps, and unrelated work are not silently promoted into blockers.

`engineering retrospect` is a read-only, digest-bound inventory of the finite
declared sources and evidence classifications. Optional host reconciliation is
advisory; the controller invokes no LLM and writes no remediation. Foreground
maintenance processes only mechanically verified work and starts no daemon,
timer, poller, or background schedule.

Installation and rollback replace only validated skill, loader, launcher, and
receipt surfaces. They preserve owner-private evaluations and practices plus
project-local graphs, checkpoints, keys, and attestations; they do not activate
a project, connector, hook, schedule, or data record.

## Scale and limits

| Context | Evidence today |
| --- | --- |
| Solo developer | Intended and locally validated; linked worktrees on one machine share local evidence. |
| Team | Manifests and ledgers are tracked; each machine regenerates checkpoints. Tests model clones, worktrees, locking, reconciliation, and concurrency, not a real multi-user deployment. |
| Enterprise | Reducers have bounded fixtures, but version 2 is not an enterprise platform claim. It ships no centralized HA graph service, distributed operational store, SSO/RBAC authority, telemetry platform, scheduler, cross-project live aggregator, or large-enterprise field validation. |

Very large monorepos, many concurrent users or machines, long-duration evidence,
and real enterprise topology/adapters remain untested or partially tested.
Roadmap services are not shipped dependencies.

## Troubleshooting and deeper detail

If a map is unavailable, check Git and eligible-commit state, the exact pinned
Graphify runner, and checkpoint freshness. Engineering reports the smallest
recovery action while leaving unsupported claims Unknown.

Read [SKILL.md](.agents/skills/engineering/SKILL.md) for canonical operating
guidance and the [controller contract](.agents/skills/engineering/references/controller-contract.md)
for exact protocols, schemas, authority rules, storage, and receipts. The
[Capability Assurance design](docs/specs/engineering-capability-assurance-design.md)
records its reviewed scope and deferred services.

This repository is available under Apache-2.0. Verification does not authorize
installation or use in a live project.
