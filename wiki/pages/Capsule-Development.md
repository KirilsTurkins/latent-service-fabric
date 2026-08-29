<!-- LSF-WIKI-MANAGED -->
# Capsule development

A capsule is a component binary plus immutable metadata that describes its
contract and artifact identity. The Phase 0 echo capsule is the repository’s
real, reproducible integration fixture.

## Phase 0 echo fixture

The fixture lives under [`examples/echo-contract`](https://github.com/KirilsTurkins/latent-service-fabric/tree/development/examples/echo-contract).
The build tooling generates WIT guest bindings, produces a `wasm32-wasip2`
Component Model binary, verifies its imports/exports, and writes a generated
local capsule manifest under `target/capsules/echo/`.

```bash
make echo-capsule
make echo-capsule-reproducibility
```

The two-build check verifies reproducible fixture output under the documented
toolchain boundary. The generated artifact is intentionally not a signed,
distributable release.

## Capsule rules

- Declare domain errors in WIT rather than hiding them in untyped payloads.
- Import only the platform capabilities the component needs.
- Do not assume a process-local listener, background thread, global mutable
  state, or long-lived store belongs to the capsule.
- Treat external dependencies as explicit contracts with policy and capability
  boundaries.
- Use stable idempotency semantics for side effects when those capabilities are
  implemented in later phases.

## Not yet a package ecosystem

OCI publishing, signatures, SBOM validation, provenance admission, AOT cache
trust, and deployment management are planned supply-chain work. The Phase 0
local trust declaration must not be described as those features.

Read [Creating a capsule](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/component-development/creating-a-capsule.md)
and the [Phase 0 spike guide](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-0-spike.md).
