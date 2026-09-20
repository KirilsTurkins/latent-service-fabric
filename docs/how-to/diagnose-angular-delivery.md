# Diagnose Angular build, delivery and hydration failures

Use this with the [build-to-browser guide](../learn/build-and-deliver-angular.mdx)
and keep the failed receipt, exact source and artifact identities. Diagnose the
stage that rejected the operation before changing source or resubmitting a
mutation. The supported profile's safety limits remain in force.

## Exercise the source and output boundaries

Use a disposable copy of the maintained application for one change at a time.
Run the [actual build adapter](../component-development/angular-build.md) with
that copy as `--input-root` and a fresh output path. Preserve the original
application and successful output for the recovery check.

| Change | Expected boundary and correction |
| --- | --- |
| Edit the shared heading or the selected `shared/version.ts` literal | Valid captured-source change. Rebuild; source, browser and renderer/package observations must describe the new bytes. |
| Add `import '../server/main.js'` to the client entry | Client/shared to server import is rejected. Move only public data types into shared code; leave server implementation private. |
| Set a shared component's `templateUrl` to `../server/private.html`, including a declared server file | The source-area resource check rejects access before Angular compilation. Use a captured shared/client resource. Shorthand/computed resource metadata does not bypass this rule. |
| Import `node:fs` or introduce ambient `process`, a worker or an interval | The closed source/module profile rejects unsupported APIs. Use an implemented, explicitly granted capability; arbitrary npm installation cannot add runtime authority. |
| Supply more than 32 KiB of aggregate recognized hydration JSON, or more than 128 KiB HTML | The supplied-output or runtime wrapper rejects the result. Reduce transferred public state/output; do not increase the limit to pass the example. A subsequent bounded render must succeed. |

The [source and hydration tests](../../tools/tests/test_build_angular_package.py)
and [Angular conformance runner](../../tools/run_angular_build_tests.py) own these
checks, including UTF-8 byte accounting, duplicate/ambiguous script attributes,
state-ID recognition and recovery. Run the focused input suite with:

```sh
python3 -m unittest tools.tests.test_build_angular_package
```

That Python suite validates capture and supplied-output boundaries. It does not
replace the complete adapter build, native preparation or real-browser workflow.

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
| `/account` leaks or shares user state | Stop qualification. Compare sealed principal, origin, filtered cookies/headers, cache policy and public transfer-state projection. Management tokens and backend credentials must never enter HTML or bundles. |
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

## Verify cleanup before another attempt

The maintained workflow owns its node, backend, compiler and browser process
groups. A completed caller or cancelled future does not prove those owners are
gone. Require the final shutdown report and process reap; preserve incomplete
cleanup as a failure. Keep explicit build/fixture/receipt directories until
their evidence has been reviewed. A corrected run gets a fresh fixture/output
and a new receipt; the previous failure remains part of the record.
