# Engineering v2.2.6 audit10 semantic repair

## 1. External owner-source semantics

The authoritative bootstrap ledger is host-owned and signed outside candidate
Git. It contains a source projection supplied by the owner/root authority, not
one generated from the candidate registry. Each source requirement binds a
stable source requirement ID, `OWNER_APPROVED` lifecycle state, an exact source
excerpt and statement digest, and the candidate requirement and obligation IDs
that implement it. Verification resolves the immutable source bytes, requires
the excerpt exactly once, verifies its digest, and compares the complete signed
projection with the candidate registry. Missing, conflicting, unmapped, extra,
or candidate-generated source semantics fail closed. Engineering validates the
record but cannot mint it.

The host record uses `engineering.v2.2.6-owner-approved-ledger.v2` with exactly
four top-level fields: `schema`, `source_requirements`, `requirements`, and
`obligations`. Every source requirement has exactly:

```json
{
  "source_requirement_id": "<stable owner-source id>",
  "lifecycle_state": "OWNER_APPROVED",
  "source_excerpt": "<exact UTF-8 excerpt occurring once in the host source>",
  "statement_digest": "sha256:<digest of exact excerpt bytes>",
  "requirement_ids": ["<candidate requirement id>"],
  "obligation_ids": ["<generic obligation id>"]
}
```

Across the signed rows, every candidate requirement and obligation ID occurs
exactly once. The supported validator requires both exact candidate roots, the
host ledger, and the host owner source; it only returns the canonical ledger
after both candidate registries and the exact source bytes reconcile:

```text
python tools/v226_owner_baseline.py ledger \
  --internal-root <exact-internal-root> \
  --public-root <exact-public-root> \
  --owner-ledger <absolute-host-ledger-path> \
  --source <absolute-owner-source-path>
```

The command cannot create or replace the host ledger, source, trust anchor,
signer material, approval, installation, or activation.

## 2. Native observability truthfulness

The README describes Engineering's native observability before comparisons to
LangGraph or Langfuse. A capability matrix names the owning module, evidence
source, storage or projection, interface, privacy boundary, support state, and
known limitation for every claimed capability. The disclosure states that
Engineering is not a runtime telemetry backend and does not provide a
persistent dashboard or token/cost collection unless an external provider is
separately supplied. Static HTML is only a projection. The skill and plugin do
not acquire owner, merge, install, deployment, or product authority.

## 3. Per-outcome dependent-dispatch completeness

The post-activation import has exactly one mapping for every active owner
outcome. Each mapping binds:

- lifecycle state `DESIGN_MAPPED`;
- design document path and section;
- schema/API path and interface;
- concrete runtime behavior;
- negative-test path and selector;
- required native or served evidence class, interface, and environment; and
- exact design/contract artifact repository, commit, tree, and digest.

The signed import covers the normalized mappings and their digest. The
controller revalidates completeness at dispatch time and blocks a v0.6.1,
frontend, or other dependent lane if any outcome is missing, duplicated,
Unknown, proxy-only, stale, or bound to the wrong artifact. These mappings are
the pre-dispatch design/acceptance contract; they do not claim future runtime
evidence already exists. Populated later outcomes remain host-private and are
bound immediately after v2.2.6 activation.

## Requirement matrix

| Owner requirement | Design section | Contract | Runtime rule | Negative proof | Acceptance proof |
| --- | --- | --- | --- | --- | --- |
| Genuine external owner source | 1 | Host ledger source projection | Verify source bytes and signed mappings before registry comparison | Candidate omission/conflict/unresolved excerpt rejects | Host-issued record resolves and matches exact registry |
| Truthful native observability | 2 | README disclosure and capability matrix | Documentation gate blocks missing, late, or overstated claims | Missing matrix/negative boundary/order rejects | Repository test proves exact section and claims |
| Per-outcome dispatch completeness | 3 | Post-activation import outcome maps | Revalidate every active outcome before dependent dispatch | IDs/scopes-only, incomplete, Unknown, proxy, wrong artifact reject | Complete signed maps admit idempotently |

## Compatibility and recovery

Historical records remain readable as non-authoritative history but cannot
authorize new dependent dispatch without the current complete mapping contract.
The one-time bootstrap remains governed by installed v2.2.5, recorded owner
approval, and independent exact-artifact audits. Owner source, approvals, and
populated outcomes stay outside candidate Git. Any unavailable host source or
receipt blocks the affected admission without changing installed state.
