# Engineering v2.2.6 final-audit repair plan

## Boundaries

Work only in a fresh paired v2.2.6 repair worktree. Preserve rejected objects,
installed v2.2.5, rollback, host-private records, and later product lanes. Do
not publish, merge, install, activate, change hosting policy, or change access
or keys.

## TDD order

1. Add focused red regressions for required bootstrap audit categories, new
   README/documentation/test paths without a refreshed checkpoint, explicit
   predecessor disposition coverage, typed routing disclosure, and credential
   filtering in the legacy rebuild.
2. Run the exact tests and retain expected failure evidence.
3. Implement category-set validation; exact checkpoint requirement for every
   new artifact; host-signed predecessor transition validation; typed
   provider-neutral routing with read-only legacy loading; and deterministic
   Graphify environment reuse.
4. Rerun focused tests, then full Engineering and repository suites.
5. Export the generic allowlist into the paired public worktree; run public
   suites, sanitization, audience, parity, integrity, compilation, diff, and
   clean-tree gates.
6. Commit local paired candidates only after all exact-pair gates pass; then
   recompute identities from the actual worktrees for independent audit.

`metadata_audit_unknown` stays visible as delivery-only evidence and never
substitutes for artifact acceptance.
