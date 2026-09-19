# Phase 3 management integration (#226)

## Hosted startup investigation

The first contracts attempt at source `075db884` failed when a bounded Git status
probe timed out. Its single rerun instead reached the real node/provider workflow
and failed with `node-startup-exit` after fixture export. Neither failed run is
accepted as a green gate or silently retried. The shared process owner now exposes
only an allowlisted node stage/status code, never raw stderr, credentials or paths,
so the next exact-head run can distinguish configuration, startup and shutdown
failures. This is diagnostic coverage, not a claim that the startup failure's
root cause has been fixed. Local successful workflows remain separate evidence.

This delivery extends the existing authenticated management services. It does
not change the policy language, manufacture provider registrations, or turn a
receipt or inspection response into execution authority.

## Finite CLI operations

Use the existing protected client profile (`latent --config client.json`). The
profile tenant is an assertion; the server derives the effective tenant and
actor from the authenticated transport principal.

| Command | Supported operation |
| --- | --- |
| `policy apply/get/list/revoke/operation/explain` | Existing typed capability policy and provider-binding records |
| `trigger apply/get/list/delete/operation` | Closed buffered HTTP trigger profile; exact publication, deployment revision and generation |
| `capability list --deployment ID` | One bounded page of sampled bindings and tenant usage |
| `capability explain --deployment ID --capability CONTRACT --operation OP --resource FILE` | Descriptive current-principal inspection, not admission |

Trigger mutation requires all three explicit comparison fields:

```text
latent --config client.json trigger apply trigger.json --operation-id trigger-create-1 --expected-generation 0 --expected-state-version 0
latent --config client.json trigger operation trigger-create-1
latent --config client.json capability list --deployment renderer --include-node-usage --page-size 16
```

The trigger file uses the existing `Trigger` manifest codec, including its
explicit publication selector. Component-only selectors, future trigger
profiles, unknown resource fields and impersonation claims are rejected. List
commands fetch only the requested page. They do not retry, follow cursors, or
poll. `include-node-usage` remains subject to server-side operator authorization.

Successful trigger responses are checked against the operation ID, authenticated
scope, exact target, generations, receipt digest, and audit acknowledgement.
Ambiguous durability remains unknown. An operation lookup is a separate explicit
command; an absent operation is not evidence of rollback. All diagnostic 64-bit
counters and generations are JSON decimal strings. Capability output always
reports `executionPermission: false`; a sampled allow is not an executable grant.

Invocation keeps the Phase 1 budget grammar by default. Use
`invoke --budget-profile phase3 --budget budget.json` for the delivered child-call,
outbound-request and blob byte dimensions. State/effect dimensions remain
unsupported. This option only validates requested amounts; the node still
selects its actual accounting profile and independently intersects authority
and resource ceilings.

## Validation and qualification boundary

The focused CLI and wire management tests cover closed input grammar, response
scope/receipt associations, unknown-resource rejection, finite pagination,
lossless 64-bit values and uncertainty. They do not substitute for a real
separate client/node workflow.

The provider real-node runner is `tools/run_phase3_management_workflow.py`, using
the existing `phase2_operator_process` and `phase2_operator_scenario` ownership
helpers. Guest inputs remain the real HTTP/blob examples under
`tools/toolchain-smoke/examples/guest_http` and `guest_blob`, produced by
`tools/build_guest_capsules.py`; the existing `web_contract` example supplies
the public HTTP-trigger contract. The [provider bootstrap and shared fixture
contract](reference/standalone-providers.md) documents SDK reuse without copying
node setup or provider implementations. This initial runner deliberately reports
HTTP/blob scope, not completed web/trigger or Angular acceptance.

The [bounded provider evidence](evidence/phase3-226-provider.json) records the
actual Linux run: 31 separate CLI operations, four authorized upstream requests,
denied-path and revoked-grant checks, exact revision preservation on restart,
and joined node/provider owners with zero live activation/handle/work counters.
Two independent workflow executions passed. The receipt retains durable blob
staging inventory and the audit restart's unknown historical-loss flag rather
than claiming either was erased.

Angular remains gated to the delivered T0 runtime until the actual #234 build
has passed protected T1 configuration, enforced publisher/builder/SBOM admission,
isolated native compilation, authenticated cache reuse, exact selected
publication deployment/render, cancellation/reclamation, restart, cross-tenant
denial and independent publication/policy revocation. T2/T3 are not supported.
The immutable-assets and response-cache work in #336/#335 is a dependency, not
an implementation copied into this change. Full #226 acceptance is not yet
claimed by this milestone.
