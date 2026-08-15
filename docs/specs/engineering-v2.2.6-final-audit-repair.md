# Engineering v2.2.6 final-audit repair

## Scope

This repair changes only the generic Engineering controller, synthetic tests,
and generic documentation. It preserves rejected candidate objects as history
and does not publish, merge, install, activate, alter v2.2.5, or create a
hosting, collaborator, or key-management dependency.

## Requirement matrix

| Requirement | Controller rule | Regression evidence |
| --- | --- | --- |
| Bootstrap needs semantic and technical review | A host record contains exactly one independently signed `semantic` audit and exactly one independently signed `technical` audit. Arbitrary labels cannot substitute; no signer, principal, fingerprint, audit ID, or replay nonce may overlap. | Two distinct non-required labels fail before handoff or install. |
| New owner commitments cannot hide in prose or tests | Any changed artifact absent from the preparation checkpoint, including a new README, documentation, or test path, requires a refreshed exact result checkpoint. Missing result evidence fails closed; the refreshed graph then decides capability impact. | Completion rejects each new README, documentation, and test path when the result checkpoint is unavailable. |
| A new baseline cannot silently erase an active baseline | A first binding declares `predecessor: {"state":"none"}`. A successor names the active intent and digest and gives one disposition for every active outcome: `CARRIED_FORWARD`, `REPLACED`, `DEFERRED`, or `EXCLUDED`. Carry-forward names an identical successor; replacement names a distinct successor; deferred and excluded name none. | Missing, stale, partial, duplicate, or inconsistent mappings fail before supersession. A full signed carry-forward is replay-safe. |
| Native routing facts are complete without provider guessing | Every new delivery evaluation has typed `routing` fields: `reasoning`, `owner_override`, `execution_target`, and `scope`. Each is either `{"state":"unknown"}` or bounded `{"state":"recorded","value":"..."}`. Stored legacy records remain readable without upgrade. | Missing, malformed, or private routing rejects; all-Unknown input records; legacy input remains readable. |
| Legacy Graphify rebuild never inherits credentials | The legacy detached-snapshot rebuild uses the credential-filtered deterministic Graphify environment shared with the current rebuild. | Captured Graphify child environment contains no provider or connector credential variables. |

## Compatibility and recovery

Historical owner-intent records and delivery evaluations remain readable as
history. They cannot be replayed as newly issued bindings or evaluations unless
they meet the current admission contract. Host receipts remain outside candidate
Git, native approval remains separate, and unavailable exact proof blocks only
the affected new admission.

The final local pair is frozen only after focused regressions, both full suites,
repository checks, sanitization, audience classification, parity, integrity,
and clean-tree checks have passed for its exact commits and trees.
