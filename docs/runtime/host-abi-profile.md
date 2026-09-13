# Host ABI compatibility profiles

`lsf-host-abi-phase3-v2` is the current generic recognition profile in
`latent-core`. The [frozen matrix](../../wit/host-abi-phase3-v2.json) records its
exact interface identities, source hashes, function forms and installed bindings.
[ADR-0031](../../adr/0031-version-host-abi-recognition-independently-of-provider-authority.md)
and [RFC-0005](../../rfcs/0005-phase3-host-abi-profiles.md) define its ownership,
error and compatibility contract.

## Recognition and availability

| Exact interface | Inspection | Production binding |
| --- | --- | --- |
| `latent:context/context@0.1.0` | supported | built in |
| `latent:log/log@0.1.0` | supported | built in |
| `latent:clock/monotonic@0.1.0` | supported | built in |
| `latent:clock/wall@0.1.0` | supported | built in |
| `latent:random/random@0.1.0` | supported | unavailable, #219 |
| `latent:blob/blob@0.1.0` | supported | unavailable, #213/#214 |
| `latent:secrets/reader@0.1.0` | supported | unavailable, #215/#216 |
| `latent:events/publisher@0.2.0` | supported | unavailable, #217 |
| `latent:http/client@0.2.0` | supported, async import | unavailable, #211 |
| `latent:telemetry/custom@0.1.0` | supported | unavailable, #220 |
| `latent:service/invoke@0.1.0` | supported, async import | unavailable, #209 |

An inspected package has no provider authority. Wasmtime preparation rejects a
required provider that has no installed owner. The generated Phase 3 host/guest
bindings contain types and registration helpers; the production linker still
installs only context, log and clock. Activations must supply their exact prepared
imports and pass current eligibility/descriptor checks.

The complete source interface must match authoritative WIT. A compiler may prune
unused binary imports/members; every retained member still needs its exact
version and complete supported shape. A matching name, partial supplied WIT or
forged metadata cannot authorize a different host ABI. Parser, graph, comparison
and transfer limits remain independent checks. Complete host comparison shares
one finite work allowance across all required interfaces.

## Selected forms and versions

The v1 four-interface profile remains defined. Existing context/log/clock bytes
and versions are unchanged. The legacy aggregate world at 0.1.0 and its Rust
bindings remain available; the new aggregate at 0.2.0 selects v2. Binding staging
loads only the referenced package versions to preserve generated module names.

HTTP and events use explicit 0.2.0 package versions because their errors and
receipts changed. HTTP reports a complete response or a typed failure, including
uncertainty after possible dispatch. Events report broker stream/sequence and
acknowledgement, including duplicate status, or an explicit uncertain outcome.
Neither implies a transaction, consumer processing or automatic retry authority.

Only freestanding HTTP/service async imports are selected. Synchronous guest
imports may eventually use a cooperative async host bridge. Neither form makes
waiting activations free: stores, cells, handles, buffers and reservations stay
owned until completion or affirmative cleanup.

Component Model resources, futures, streams, async guest exports, flags, maps,
fixed lists and error-context remain rejected. Blob handles are opaque numeric
activation tokens; #204 owns their sealed lifecycle before a provider can be
installed. State and timer remain later-phase contracts. Streaming HTTP requires
an explicit subsequent ABI extension in #205/#212.

## Cache identity and security

The canonical SHA-256 profile identity covers the ID, ordered exact interface
names, package names, binding kind, async flag and complete WIT bytes. Lengths
are framed as little-endian u64 values with a versioned domain separator. The
profile ID and digest enter generic preparation compatibility; AOT uses the same
capability digest alongside engine/input/policy identities. Old generic prepared
or native artifacts require regeneration. Source comments conservatively affect
identity; repository LF line endings are checked.

Mutable grants and credential rotations do not authorize native code through a
cache key. Eligibility, exact descriptors and required activation bindings remain
checked at invocation. The sealed broker and provider epoch checks are separate
work in #204/#207; this profile does not claim their implementation.

The baseline is Wasmtime 47.0.4 with guest generator wit-bindgen 0.60.0. No WASI
filesystem, HTTP or WASIp3 streams are installed. Expanding that surface requires
an advisory reachability review. ABI compatibility does not establish a stronger
[execution isolation profile](../../rfcs/0001-minimum-execution-isolation-profiles.md).
External-capsule deployment enforcement belongs to #280; fixed external guest
execution hosts remain unavailable.

Normal CI parses both worlds, compiles native/Wasm generated bindings and tests
real component/linker compatibility, wrong shapes/versions, missing providers,
forged/stale descriptors, comparison limits and schema/source/generator parity.
The fixtures allocate no dormant application resources and provide no provider
performance or hostile-multitenant qualification claim.
