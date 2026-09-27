# Contracts and bindings

The current node validates component metadata and dispatches supported exported
contracts/functions through the [generic Wasmtime backend](../runtime/wasmtime.md).
Verified package association and bounded release/runtime comparison accompany
execution. The host ABI, sealed capability broker and
[host/local binding compiler](../runtime/capability-bindings.md) preserve exact
contracts. [Isolated local calls](../runtime/local-service-invocation.md) execute
through a separate child activation. Remote calls, inline composition and
automatic contract migration are not implemented.

## Contract authority

WIT is authoritative for capsule-visible types, functions, resources, futures, streams, imports, and exports. Language SDK surfaces are generated or handwritten projections and must not change semantics.

## Version identity

A release has separate identities for:

- implementation semantic version,
- release content digest,
- exported contract versions,
- imported contract requirements,
- minimum fabric version.

Implementation version and contract version are not interchangeable.

## Binding graph

A binding connects one consumer import to one provider export or host capability:

```text
consumer revision + imported contract + caller policy
    → binding
    → host capability | local provider | remote provider | derived composition
```

## Physical modes

- `host`: import is supplied by the capability broker.
- `inline`: planned composition in the same activation; compilation is rejected today.
- `isolated-local`: selects an exact local target and dispatches a separately admitted child activation.
- `remote`: planned calls to another node; compilation is rejected today.
- `auto`: compiler selects one unambiguous installed provider within explicit allowed modes.

## Inline eligibility

Inline composition requires compatible trust, state, transaction, budget, and observability semantics. A deployment may forbid inline mode even when technically possible.

## Error semantics

Domain errors remain declared by WIT. Fabric errors use the platform-error envelope. Generated clients must expose both layers and must not make isolated or remote calls appear infallible.

## Compatibility direction

Compatibility checks consider removed functions, changed parameter/result types, changed variant cases, resource semantics, async behavior, and transitive package dependencies. Breaking contracts require a new major contract version and explicit migration or parallel routing.

Current preparation checks agreement between the supplied manifest/contract
metadata and actual component imports, exports and supported value signatures.
[Bounded release comparison](../reference/release-compatibility.md)
uses the exact pinned WIT definitions of checked packages, plus actual-node
runtime requirements. Descriptor-only analysis cannot establish named record or
variant structure. Unsupported and unknown results deny compatibility approval;
general WIT migration remains future work. Exact host/local binding compilation
uses these checked definitions and rejects unsupported or ambiguous inputs. WIT
versions remain distinct from workspace and SDK package release versions.
