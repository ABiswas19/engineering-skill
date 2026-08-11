# Engineering 2.2.3 delivery policy

## Scope and flow

Engineering 2.2.3 is a lightweight policy overlay on host-native task
semantics, including Codex and Claude. It adds no custom agent runtime,
scheduler, model broker, permission governor, concurrency cap, or LangGraph
dependency.

```text
user seed -> orchestrator -> reconstruct ledger/intent/dependencies/adjacencies
     -> architect/SME scope and acceptance -> native task DAG
     -> parallel lanes + implementer/designer state -> independent auditors
     -> one-writer integration -> terminal-event reconciliation
     -> exact-artifact accept/reject/block
     -> owner-private evaluation and trends
```

The orchestrator is the default entry and final independent acceptance
authority. Independent lanes run in parallel only when useful; conflicting
writes serialize under one writer per mutable resource. Material feedback
identifies affected requirements and invalidated evidence. Reviewers and
auditors remain read-only.

User input and feedback are seed evidence rather than presumed complete scope.
Before dispatch, the orchestrator reconstructs the full available decision
ledger, approved intent, dependencies, sibling and adjacent flows, and bounded
workspace state. Architecture/design and SME tasks investigate adjacent
omissions and root causes, map seed plus adjacent findings to acceptance, and
reject symptom-only or narrow handoffs. Implementers receive architect-approved
scope; final independent acceptance rejects narrow, incomplete, or proxy-only
results.

## Requirement, design, and evaluation ledger

| ID | Requirement and design | Evaluation or release evidence |
|---|---|---|
| R01 | Preserve native capabilities and permissions; policy overlay only. | Source scan and Codex/Claude smoke. |
| R02 | Orchestrator is the default entry. | Routine and consequential scenarios enter through it. |
| R03 | Orchestrator accepts/rejects the exact integrated artifact. | Stale and lane-only candidates are rejected. |
| R04 | Direct implementer-designer feedback emits observable state. | Feedback scenario and state-event record. |
| R05 | One writer owns each shared mutable resource. | Collision scenario; reviewers remain read-only. |
| R06 | Native dependency DAG uses beneficial parallelism without a policy cap. | Dependencies, peak parallelism, critical path, coordination. |
| R07 | Model selection remains caller/native-platform policy; generic delivery evidence may record requested, actual, and fallback facts without prescribing a provider, family, reasoning level, or topology. | Generic requested/actual/fallback fields. |
| R08 | Consequential lanes may carry independent auditors. | Coverage plus self-audit/post-edit rejection. |
| R09 | A material decision-review lane challenges existence, alternatives, doing nothing, and reversibility. | Triggered and justified-skip scenarios. |
| R10 | Narrowest technical/functional SME triggers on material risk/domain impact. | Domain scenario and omission regression. |
| R11 | Functional research uses current primary sources and separates facts, assumptions, citations, and Unknowns without invented organization specifics. | Citation/content checks. |
| R12 | Material feedback invalidates only affected evidence. | Unrelated evidence remains valid. |
| R13 | Owner-private signed evaluation captures delivery truth. | Schema, bounds, tamper, replay, locking, atomicity. |
| R14 | Deterministic trends cover rework, escaped defects, false blockers, and interventions. | Comparable records or explicit insufficient-sample result. |
| R15 | User recommendations stay local and reuse the applied-learning lifecycle. | Upstream source remains byte-identical. |
| R16 | Upgrade/rollback preserve overlays, queues, attestations, keys, evaluations, and graph/checkpoint state. | 2.2.1 and 2.2.2 migration fixtures. |
| R17 | Add LangGraph only for a demonstrated native-task gap and separately approved architecture/dependency change. | Dependency/source scan. |
| R18 | Distribution remains generic with Codex/Claude parity. | Sensitive scan and allowlist byte comparison. |
| R19 | README leads with user flow, routing, acceptance, evaluation, and migration truth. | Documentation contract check. |
| R20 | Every skipped trigger or unavailable metric has a reason. | Trivial and unavailable-metadata scenarios. |
| R21 | Only an active-user-home first Windows install mutates managed HKCU/current-process PATH. | Exact mocked-`winreg` matrix and PATH byte comparison. |
| R22 | Parent lane state follows native child terminal-event reconciliation, recording artifact identity, acceptance, gate, next action, latency, and unconsumed-event signal; reconciliation is bound to the validated completion digest. | Terminal reconciliation contract and trend regression. |
| R23 | Technical, domain/semantic, and real-consumer outcome acceptance remain distinct; representative-data/outcome gaps fail the acceptance gate, and supplied evidence must resolve to validated completion/check receipts. | Proxy-pass/outcome-fail, unbound-evidence rejection, and audit false-positive trend regressions. |
| R24 | User input and feedback are seed evidence; the orchestrator reconstructs full available scope before architect/SME dispatch, implementers receive architect-approved scope, and narrow handoffs/results fail independent acceptance. | Signed, commit-bound `scope_handoff` approval, expected-artifact/result regression, and native-host scope-acceptance smoke. |
| R25 | Historical/advisory traceability debt remains visible; disjoint maintenance may proceed in parallel and overlapping writers serialize, while only checkpoint identity/integrity, required current-contract evidence, or dependent graph/release acceptance blocks. | Maintenance advisory/serialization scenarios; authoritative-ledger and deterministic-overlay parity regression. |
| R26 | A material redesign, replacement, capability deletion, or simplification reconstructs baseline approved outcomes and maps each one as INCLUDED, REPLACED, DEFERRED, or EXCLUDED before implementation-ready status. REPLACED binds outcome-equivalence decision and verification identities; DEFERRED or EXCLUDED remains possible only inside the exact signed owner-approved scope handoff. | Cooperative-orchestrator-to-stateless-validator regression, complete mapping validation, explicit-exclusion approval, and completion replay. |
| R27 | Unmanaged, missing-checkpoint, stale, conflicting, or otherwise Unknown traceability permits advisory analysis only and cannot be represented as accepted design or implementation-ready evidence. | Unmanaged and canonical-checkpoint-unavailable preparation regressions with explicit Unknown boundary output. |
| R28 | Independent design/final acceptance checks original outcome survival in addition to candidate-local technical and semantic correctness. A narrowed contract does not pass by auditing itself. | Signed survival mapping is retained through preparation and completion; missing mapping and missing equivalence evidence fail closed even when candidate-local checks pass. |

## Outcome-survival amendment

The existing project decision ledger and signed `scope_handoff` remain the only
sources of baseline and approval evidence. A material change carries one bounded
outcome-survival mapping inside that handoff; no second ledger or task state
machine is added. Every baseline requirement has one disposition, reason, and
verification identity. A replacement additionally names replacement identities
and an outcome-equivalence decision. Deferred and excluded outcomes are not
silently omitted: the exact mapping is commit-bound to the existing owner-
approved decision artifact and scope attestation.

Preparation exposes incomplete mappings and the exact Unknown or approval
boundary. An unmanaged project or unavailable canonical checkpoint may support
advisory/draft analysis but cannot create completion-ready evidence. Completion
revalidates the signed mapping and retains it with the exact artifact. Host-
native design and final auditors must still judge semantic outcome equivalence;
the deterministic controller ensures that baseline outcomes cannot disappear
from that review merely because the candidate's narrower contract is internally
consistent.

## Migration and Windows host mutation

Direct 2.2.1-to-2.2.3 and 2.2.2-to-2.2.3 upgrades retain applied practices,
queues, attestations, controller keys, delivery evaluations, and project-local
graph/checkpoint overlays. Rollback restores one validated prior bundle and
loaders while retaining those overlays. Install, replay, upgrade, and rollback
never activate a project, hook, connector, schedule, or populated data.
Historical delivery records without the new controller-bound reconciliation
field remain readable, while new evaluations fail closed until their terminal
and outcome evidence resolves to current validated receipts; legacy rows are
excluded from verified-current trend cohorts but retain a bounded count.

On Windows, only a first install whose resolved home equals the active OS user's
home registers its managed `.agents\bin` in `HKCU\Environment\Path` and current
process `PATH`. Temporary/custom homes, replay, upgrade, and rollback perform no
host PATH mutation. The bounded `host_environment_pollution` incident class is
closed by an invariant and mocked-registry regression: exactly one managed
write for active-home first install, zero registry writes for every other case,
and byte-for-byte unchanged process PATH for those other cases. A new terminal
may be needed. The release prevents new test-home pollution but never deletes
historical arbitrary PATH entries whose ownership cannot be proven.

## Release gates

- Full controller and repository checks, compilation, and sensitive/private
  content scan pass on the exact integrated candidate.
- Native Codex and Claude DAG/fan-in, feedback, fallback, collision, and
  exact-artifact acceptance smokes pass with sanitized scenarios.
- Migration/rollback preservation and the exact mocked-registry matrix pass.
- Terminal-event reconciliation, bounded evaluation retention, deterministic
  comparable-cohort trends, and insufficient-sample regressions pass.
- Historical/advisory maintenance remains visible without broad authority
  blocking; disjoint lanes and overlapping-resource serialization follow the
  existing repository lock, while graph-dependent parity gates remain strict.
- Independent technical/domain/outcome acceptance and representative-data,
  proxy-pass/outcome-fail, and audit false-positive regressions pass.
- Seed-feedback smokes reconstruct the decision ledger and adjacent flows,
  require architect-approved implementation scope, and reject narrow results;
  the signed, commit-bound `scope_handoff` controller contract must pass its
  positive and negative preparation/completion regression.
- No LangGraph, provider-permission reduction, project-specific content, or
  unapproved install/publication/activation is present.
- The orchestrator independently accepts the exact artifact and evidence;
  release and installation remain separate authorized actions.
