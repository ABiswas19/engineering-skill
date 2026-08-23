# Engineering v2.2.6 post-audit repair plan

## Purpose and scope

This is the active repair plan for the non-circular bootstrap and completion
evidence findings. It preserves all earlier rejected candidate objects as
history and changes only the generic Engineering controller, synthetic tests,
and public-safe documentation. It does not publish, merge, install, activate,
or alter a previously installed v2.2.5 bundle.

## Requirement-to-test matrix

| Requirement | Controller change | Red regression and green evidence |
| --- | --- | --- |
| Freeze reports the real writer worktree, commit, and tree | Freeze receipt derives its facts from the actual clean paired worktrees. | A release receipt test rejects a path/head/tree mismatch; final receipt records both exact candidates. |
| Candidate Git cannot select active trust | Treat the default-branch signer transport as superseded history and resolve active signer material only from the private host boundary. | Documentation and candidate-signer substitution tests reject a current Git-based claim. |
| Completion sees a newly introduced capability path | Evaluate owner-intent impact at both the preparation checkpoint and the refreshed exact result checkpoint; fail closed when the required result evidence is unavailable. | A new capability-bearing path absent from the base graph cannot complete under an underselected declaration. |
| Concurrent approvals and exceptions remain additive | Preserve distinct scope records and exact replay identity without replacing an unrelated active record. | Two active scoped approvals and two distinct exceptions survive exact replay and resolve independently. |
| Bootstrap resolves evidence rather than parsing claims | Resolve a root-owned private record containing the exact installed-v2.2.5 receipt, recorded approval, and distinct signed audit evidence. | Forged, stale, wrong repository/epoch/contract, changed artifact, missing v2.2.5, duplicate audit, or non-independent signer evidence fails closed. |
| Bootstrap stays non-circular | Pre-audit status reports capability evidence only; after audit, root alone writes the host record and the installer consumes an equality-bound reference. | Pre-audit installation rejects; a valid post-audit record succeeds without invoking post-activation trust admission. |
| Exact source and paired artifact binding survive | Bind each candidate role to repository, base, commit, tree, bundle digest, artifact digest, pair digest, and ancestry. | A-token/B-bundle, changed public candidate, and ancestry mismatch regressions reject before copying. |
| Public delivery stays generic and parity-safe | Export only declared generic files and run sanitizer, parity, repository, and skill suites on the new heads. | Export manifest, byte parity, audience, and sensitive-content gates pass on the final pair. |

## TDD execution order

1. Add a failing completion regression where a clean result adds an exact
   graph-linked capability path that the preparation checkpoint did not know.
   Implement base-plus-refreshed checkpoint assessment, then rerun the focused
   test.
2. Add a simultaneous-approval/exception replay regression. Verify that exact
   replay returns the same record and does not replace separate active records.
3. Add failing bootstrap tests for a pre-audit record, invalid or stale signed
   evidence, wrong candidate pair, missing installed-v2.2.5 receipt, duplicate
   or non-independent audits, and a changed host record after an exact replay.
   Implement read-only host-record resolution and equality-bound caller
   reference validation. Keep the post-activation trust loader unused.
4. Add a failing documentation regression for the obsolete Git signer
   transport. Mark it as superseded history and document the host-private
   boundary, unknown identity handling, and root-owned post-audit step.
5. Run focused regressions, then the full owner-intent contract suite, full
   Engineering suite, repository suite, export, public suite, audience and
   sanitization checks. Re-run any affected full suite after the final docs or
   manifest changes.
6. Commit each clean paired candidate locally. Compute a freeze receipt from
   the actual active worktree paths, commits, trees, and source digests. Leave
   it for independent audit; do not publish or activate it.

## External boundary and recovery

The pre-audit handoff is read-only: it exposes the exact source bundle and the
actual installed-v2.2.5 receipt so the independent auditors can evaluate a
specific pair. After those audits accept, the native/root authority creates the
private host record with its own supported authority mechanism. The controller
has no operation to create, replace, or approve that record. If it is absent,
unavailable, or mismatched, installation remains blocked and the v2.2.5
receipt and rollback remain unchanged. This plan creates no Git-hosting policy,
collaborator, key, credential, or runtime prerequisite.
