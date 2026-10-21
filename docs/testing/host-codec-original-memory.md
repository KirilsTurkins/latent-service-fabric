# Ordinary host codec original-memory ownership

Admitted ordinary component invocations charge raw input backing capacity, decoded values,
actual Wasmtime dynamic result allocations and encoded output to the supplied
original activation budget. Raw input's existing allocation is charged at the
invocation ownership boundary. New decoded, lifted and encoded buffers reserve
before allocation; growth pays for old and replacement buffers while both exist.
The reported consumption includes the
original ledger peak after result encoding.

The pinned Wasmtime 48.0.7 extension reserves actual strings, containers, names,
flags and boxed values before allocation. Parameter copies have an independent
refundable scope. It preserves the original host-call fuel calculation for UTF-8,
UTF-16 and Latin-1 decoding. Tiny dynamic values keep the original memory and fuel
ceilings; no signature-wide maximum is reserved for each small return.

Immutable result bytes retain their original capacity and reservation through
clones and RPC handoff. Actual values are destroyed before their scope refunds.
Cancelling a call at a legal Core post-return fuel yield unwinds its native result;
the caller's shared scope remains until its last owner drops. A bounded journal
copy belongs to its existing controller admission, allowing a physically finished
child to settle after the last actual source-result owner disappears.

## Retained native execution

[The public evidence](evidence/host-codec-original-memory-native-2026-10-22.json)
binds [run 39685022895](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39685022895)
at `7b6365ee39dea9770591a931b96711965f8a1aaf`. Its **61 controls passed** with
exact discovery and successful names, no ignored controls, 31 command records and
62 verified log streams. The complete 71-member archive and all five ordinary
native products were independently checked against GitHub run/job/artifact
metadata, the exact source and all 148 recipe/auxiliary materials.

The controls include payload growth/refusal and parent accounting, original raw
spare capacity, wire compatibility and retained capacity, tiny dynamic values,
typed original-budget errors, partial lifting, fuel-preserving encodings,
cancellation followed by same-budget Store reuse, journal child settlement,
selected C public-async/synchronous-Core admission, and one real ordinary backend
invocation whose result outlives Store cleanup.

The subsequent twelve-path limits/documentation merge preserves the full native
identity (3,593 files) and every material. The immutable successful receipt keeps
its original source revision. This evidence is source-bound CI qualification;
`signedQualification` remains false. No guest source or JavaScript engine was
compiled by this native programme. The source record explicitly leaves implicit
compiler inputs unattested and declares `hermetic: false`.

## Scope retained outside this slice

Serialized controller/transport frames and legacy Phase0 framing retain their
existing ownership boundaries. This common codec prerequisite is a partial
delivery for [#736](https://github.com/KirilsTurkins/latent-service-fabric/issues/736)
and [#745](https://github.com/KirilsTurkins/latent-service-fabric/issues/745); the
whole tickets and the full TypeScript cost criterion require their remaining
implementation and qualification.
