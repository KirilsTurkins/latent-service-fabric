# Composition support v1

The [composition input schema](../../schemas/dev-composition-input.schema.json)
selects exact package, component, release, metadata, publication and revision
identities for `latent.composition.v1`. The
[source-backed support matrix](../../contracts/dev/composition-support-v1.json),
`latent.composition.support.v1`, records supported definitions and their maintained
owners. An unlisted combination is **untested**. These labels establish no
preparation, execution or authority, and promise no Cartesian product of features.

| Selection | Declared support and required evidence |
| --- | --- |
| Java, nested values, capsule, standalone or HTTP Java profile | Supported definition. Prepare the actual component and exact WIT under the selected engine; execute its maintained owner separately. |
| Java with engine Java support disabled | Unsupported. Select and observe the actual Java-enabled engine. |
| Java public resource values, futures or streams | Unsupported. Imported pinned own/borrow resources through freestanding operations are a separate supported SDK surface. |
| Java multiple public interfaces, version aliases, inline interfaces, empty records or resource constructors/methods | Unsupported by the current authoring owner. Actual WIT inspection also checks nested signatures and finite lifting limits. |
| Ordinary capsule importing `latent:context/context@0.1.0` | Unsupported by the configured standalone provider selection. Declaring a web export or HTTP trigger supplies no missing provider. |
| Native sealed web execution projection | Source-supported through its checked package/manifest/assets/renderer association and exact projection validator. A declaration cannot prove that association. |
| Static language, static assets, static-site publication | Supported definition. Target is publication ID plus positive web generation; package, assets and web-manifest identities replace guest execution fields. No component, release digest, guest budget, typed target, imports, exports or service edges. Current publication, asset and lifecycle checks remain required. |
| Other guest languages, unknown shapes or unlisted profiles/providers | Untested by this Java composition matrix; use their existing source-matched owners. |
| Former HTTP global lifting profile | Unsupported as a product profile. Its feature-gated disposable loopback fixture reproduces the recorded failure. |

One named nonempty interface is the current Java public shape. Async host calls
may suspend while Java waits synchronously; this does not add WIT future/stream
values. Recognition by the host ABI does not install a provider or grant a call.
Provider selections use the actual provider profile, configuration digest and
optional epoch, plus exact binding identity/digest and selected policy identities.
No registration ID, credential, principal or deployment protocol is invented.
Capsule targets pin a positive `deploymentGeneration` alongside the original
deployment ID, publication and revision. A refreshed deployment under the same
name cannot satisfy the old selection. Static targets pin their web generation.

The schema is complemented by
[the stdlib semantic helper](../../tools/dev_workflow/composition_contract.py):
full unsigned decimal bounds, 256 KiB document bounds, portable UTF-8 paths,
identity-key uniqueness and references. All eleven canonical resource-budget
fields are preserved. Child calls, outbound requests and effect counts retain
their u32 ceilings; the other counters retain u64. A null wall limit remains
invocation-dependent. Edges
carry only requested ceilings. Remaining usage, caller grants and dynamic targets
require an invocation. Rust/WIT validation of the actual selected bytes remains
authoritative.

Optional [capture budgets](../../schemas/static-site-budget.schema.json) retain
`latent.static-site.budget.v1` and the original capture scope. The helper validates
their closed schema with finite depth, node and byte limits; it does not rerun
capture, recalculate headroom, qualify signed bytes or observe node capacity.
The [response ownership helper](https://github.com/KirilsTurkins/latent-service-fabric/blob/6bea7e454e5b8f5bb9c450244804a8d27f526742/tools/browser_response_ownership.py)
accepts at most 64 declared ASCII names of 64 bytes and reports bounded conflicts.
Dynamic values and bodies still require current host validation and execution.

Package the two composition JSON contracts and the exact capture schema alongside
the helper under `tools/dev_workflow/data/`, preserving their canonical paths and
bytes. ZIP import and PyInstaller resources are supported; source checkouts use
the canonical files directly. Missing resources fail with a finite packaging reason; no schema is
fetched from the network. Record structural, authoritative preparation,
authenticated coherent live-state and separately executed qualification evidence
at their actual boundaries. Observed identities expire; normal admission and
dispatch always recheck current authority.

[The frontend build](../../tools/build_dev_frontend.py) snapshots these exact
canonical bytes for both the Linux helper ZIP and the native PyInstaller
frontend: `schemas/dev-composition-input.schema.json`,
`schemas/static-site-budget.schema.json`,
`contracts/dev/composition-support-v1.json`, and
`contracts/http/browser-response-ownership-v1.json`. They share the package
resource prefix `tools/dev_workflow/data/`. The build binds each resource digest
and size, verifies installed native copies, and rejects changed source contracts.
The helper also includes the response ownership module; a missing packaged table
fails with a finite reason.

Every native build runs the actual `dev preflight` command outside the checkout,
with no Python in `PATH` or `PYTHONPATH`. Its synthetic static selection succeeds,
while ordinary context and reserved response headers reject. All three preserve
unobserved authority and create no controller state. The build receipt records
this as `packaged-structural-preflight-only`; real publication preparation,
authenticated observation, execution and release qualification remain separate.
The [packaging regressions](../../tools/tests/test_dev_frontend_preflight_packaging.py)
also run isolated `-I` ZIP imports with an unrelated current directory, reject
missing/oversized resources, and reject a fabricated authority claim.
