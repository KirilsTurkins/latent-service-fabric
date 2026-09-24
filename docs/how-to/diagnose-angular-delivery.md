# Diagnose Angular build, delivery and hydration failures

Use this with the [build-to-browser guide](../learn/build-and-deliver-angular.mdx)
to locate the stage that failed: build, publish, prepare, serve or hydrate.
Keep the error message and the command that produced it. If publication or a
rollout lost its reply, inspect its operation ID before trying it again.

During a build, correct the reported source or configuration problem and choose
a fresh output directory. During a browser failure, open the browser's Network
and Console panels and reload once: the failing request and first error usually
identify the relevant row below.

## Find the failing stage

| Observation | Next check and safe action |
| --- | --- |
| Version/profile or locked dependency mismatch | Compare the exact tool executable, package lock and renderer/backend profile with the selected checkout. Restore the approved tools; preserve the rejected observation. |
| Source/resource rejected or build child fails | Inspect the bounded adapter diagnostic and selected-input inventory. Use a fresh output path after correcting the source; an existing result is never overwritten. |
| Reproducibility requirement fails | Ordinary output is `not-checked`, and dependency closure is explicitly incomplete. Report that limitation; do not relabel it reproducible or complete. |
| Native preparation denied or unavailable | Separate package admission, tenant publication, profile identity, isolated compiler ownership and cache authentication. Preserve the preparation operation identity and inspect the authenticated audit. |
| Publication/admission denied | Verify exact package/evidence association, trusted publisher and builder, SBOM policy and tenant. A signed build observation alone grants no execution authority. |
| Asset missing, wrong media type or wrong revision | Compare the HTML's publication-qualified asset URL with that publication's immutable manifest. Private renderer/metadata files must stay inaccessible. Do not substitute an asset from another build. |
| Hydration mismatch, missing heading or navigation failure | Verify initial HTML already contains the expected page, the exact asset graph loaded, and the browser retained the captured DOM node. Preserve console/page errors; CSR replacement is a failed hydration check. |
| `/account` leaks or shares user state | Stop serving the affected route. Compare sealed principal, origin, filtered cookies/headers, cache policy and public transfer-state projection. Management tokens and backend credentials must never enter HTML or bundles. |
| Provider denied, timed out or cancelled | Inspect the original activation and grant/binding/provider epoch. The reference allows one bounded GET to its owned backend. Wait for actual owned connection retirement before judging recovery. |
| Declared application error or trap | Keep HTTP 422 separate from a platform trap, transport failure and local validation failure. Run the subsequent success path and verify fresh request state. |
| Canary not ready or mutation reply uncertain | Use the retained rollout revision and operation receipt. Read bounded canary/audit state; do not fabricate samples or replay a mutation under a new ID. |
| Restart fails after clean shutdown | Retain the startup stage/code and prior shutdown report. Check listener ownership, durable catalog/profile recovery and admission freshness. Changing the port or dropping stored state is not a successful same-node recovery test. |

Follow [provider recovery](operate-capability-providers.md),
[publication policy](../reference/package-admission.md),
[asset association](../immutable-browser-assets.md) and
[canary/rollback](../phase-2-rollback.md) for the owning contracts. Detailed server
diagnostics belong in protected operator output. Keep credentials, private
paths, payloads and unbounded provider messages out of public guide receipts.

## Try the corrected application

After correcting the cause, rebuild into a fresh directory and follow the
[delivery guide](../learn/build-and-deliver-angular.mdx) to publish and select
that package. Open the page again, use its interactive control, and check the
Console and Network panels for errors. Keep the original failed operation's
result if its outcome is still uncertain.

Stop the local node and any backend you started using the instructions from
that walkthrough. A cancelled browser request does not necessarily stop a
backend operation. Keep application source and node data until any uncertain
write has been resolved.

Contributors changing the builder should also run its
[source and output boundary checks](../development/angular-build-evidence.md#exercise-the-source-and-output-boundaries).
