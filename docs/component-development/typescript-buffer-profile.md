# Pure `node:buffer` source profile

`lsf-node-buffer-v1` supplies a compiler-owned, module-only byte Buffer foundation
for #745. `buffer` and `node:buffer` resolve to the same module and constructor,
independently of package identity and the selected synchronous/async runtime.
It adds no global `Buffer`, Node process, I/O, capability, permission or native
storage. Every other uninstalled Node builtin retains its existing refusal.

The additive global mechanism below has source and pinned host-compiler evidence
only; it has not run in a signed Component Model guest. Earlier module-only
Buffer programmes retain their own immutable receipts. Arbitrary npm dependencies
and the full TypeScript accounting/socket criteria remain unqualified.

## Automatically selected global provision

`lsf-node-buffer-global-v1` installs the same finite constructor as `Buffer`,
`buffer.Buffer` and `node:buffer.Buffer` before application module initialization.
It is selected from unbound `Buffer` or unshadowed direct/literal
`globalThis.Buffer` references in retained compiler output, independently of
package names and dependency catalogues. Dynamic aliases and reflection-only
lookups are outside this selector; an analysis result is not arbitrary API
reachability or initialization evidence. Local bindings and erased code do not
select it. Module-only and unselected bundles retain their previous bytes.

The first bounded esbuild pass is data-only. If selected, a second normal pass
links one compiler-private side-effect initializer before transitive ESM and
CommonJS initializers. Application imports cannot load that private module.
The initializer refuses an already present global and installs a writable,
configurable, non-enumerable property. Final code uses real global reads and
writes rather than captured lexical replacement aliases. It adds no I/O,
credentials, caller state, native storage, provider, grant or engine feature.
Existing snapshot effect guards and fresh per-activation state remain required.

The selection pass may precede strict TSC. Only a selected capture without a
verified Node type provider receives the finite ambient declaration; a captured
Node provider retains its own global types. Missing/stale selected declarations
refuse, while unselected old captures require no new file. Strict typechecking
still gates componentization, packaging, signing and admission. This does not
provide guessed declarations for untyped packages or infer Node runtime support
from broad captured Node types.

Selected globals use a closed selection-v2 receipt binding the existing module
profile plus selector, initializer and declaration identities. Module-only
selection-v1 remains unchanged. The build and diagnostic readers retain and
recheck the complete source subgroup, report qualification unknown and authority
none, and preserve the original material/byte limits and omissions. The additional
Buffer/string ceilings and original activation funding below are unchanged.

Five focused controls exercise the real pinned esbuild/Acorn/TSC path, lexical
shadowing, transitive initialization and global reassignment, old/current
unselected bundle identity, selected declarations and real filesystem
receipt/context retention. These are compiler/host controls, not signed guest,
GC, physical retirement or complete cost qualification. The source-compatible
binary-client candidate still needs legitimate published typing inputs and
normal capture before any unmodified-client qualification claim.

## Storage and limits

Buffers are genuine `Uint8Array` subclasses backed by ordinary guest
`ArrayBuffer` storage. `from(ArrayBuffer, offset, length)` shares the specified
view; `from(Buffer)`, numeric arrays and numeric typed arrays copy. `slice` and
`subarray` share the original backing, including nonzero offsets. `copy` uses
the native overlap-safe typed-array copy operation. Fill snapshots an aliased
pattern before changing its destination. No finalizer or native owner is
invented for a JavaScript byte array.

The additional profile ceiling is **1 MiB per newly created Buffer/view** and
**4 Mi UTF-16 code units per input string**. Concat accepts at most 4096 inputs.
Sizes, encoded byte counts and destination ranges are checked before allocating
or encoding a copy. These limits neither replace nor increase the original
guest heap, fuel or activation budgets; overlapping copies retain their real
heap cost. `byteLength` is an observation and can report more than 1 MiB without
creating such a Buffer. Existing external ArrayBuffers can be larger, but a
new shared Buffer view still must meet the view ceiling.

`allocUnsafe`, `allocUnsafeSlow`, `SlowBuffer` and the numeric constructor use
the selected **zero-fill allocation profile**. They expose no uninitialized
native memory, pool or unsafe-storage guarantee. Fractional nonnegative
allocation sizes truncate as in the reference runtime; invalid/oversized sizes
refuse. ArrayBuffer offsets/counts retain the tested numeric coercion and bounds.
SharedArrayBuffer, arbitrary iterable/valueOf conversions and DataView inputs to
`from` are outside the first subset.

## Finite API

The named/default module exports `Buffer`, `SlowBuffer`, `constants`,
`kMaxLength` and `kStringMaxLength`. Supported static operations are `from`,
`alloc`, the zero-filled unsafe allocators, `isBuffer`, `isEncoding`,
`byteLength`, `concat` and `compare`.

Supported instance operations are shared `slice`/`subarray`, `copy`, `fill`,
`write`, `toString`, `equals`, `compare` and `toJSON`; ordinary typed-array byte
indexing and storage remain real. Fixed signed/unsigned 8/16/32-bit integer
reads/writes use the declared LE/BE order. Variable integer operations support
1 through 6 bytes; BigInt operations support signed/unsigned 64-bit LE/BE.
The `Uint` spelling aliases the corresponding `UInt` function. Offsets, widths
and value bounds refuse before changing bytes. Integer writes preserve the
tested numeric coercion, NaN and truncation behavior.

Encodings are UTF-8 (`utf8`, `utf-8`), ASCII, Latin1 (`latin1`, `binary`),
little-endian UTF-16 (`utf16le`, `utf-16le`, `ucs2`, `ucs-2`), hex, base64 and
base64url. UTF-8 replacement, BOM preservation and whole-code-point truncation
use the real TextEncoder/TextDecoder behavior. UTF-16 reads preserve code units,
including lone surrogates, and ignore an incomplete final byte. ASCII decoding
masks the high bit; ASCII/Latin1 encoding keeps the original low byte. Hex and
base64 preserve the reference's low-byte string parsing, partial/invalid input
and padding behavior. Base64 `byteLength` deliberately retains the reference's
estimate rather than substituting the permissive decoder's output length.

Unknown encodings consumed by a codec refuse with `ERR_UNKNOWN_ENCODING`; the profile does not
silently fall back to UTF-8. Floating-point operations, swaps and Buffer search
operations (`indexOf`, `lastIndexOf`, `includes`) explicitly refuse with
`ERR_BUFFER_UNSUPPORTED`. Other unadvertised Node buffer exports/methods have no
implementation or support claim. This is not the complete Node buffer module.

## Compiler binding and evidence

The resolver has one fixed namespace/path for both aliases and loads only the
maintained source. That virtual compiler input is excluded from application
capture only at its exact identity. Selected bundle metadata records the
profile, module and backend digest; the compiler checks the actual recipe digest
and emits `typescript-buffer-selection.json`. Both module spellings use the same
maintained declaration file during typechecking. Recipe capture and isolated
compiler staging include the source, resolver, profile reader and declarations.
Application configuration cannot choose or replace this backend.
Unselected legacy SDK captures need no new declaration file. Only an actual
Buffer selection requires the captured declaration to match the maintained
recipe bytes; a selected missing/stale declaration refuses.

Eight focused controllers cover actual Node **24.19.0** reference parity and
source integration: copy and
view lifetime/overlap, codecs and invalid UTF-8, truncated write/fill/concat,
integer/endian/BigInt behavior, range/pre-encoding capacity refusal, the real
resolver alias identity, strict profile/material selection, and selected versus
unselected legacy declaration capture. An initial
non-ASCII base64 discrepancy was corrected to the observed low-byte parsing;
its affected codec control passes. These are host reference controls, not
signed runtime or complete original-budget accounting qualification.

Socket/EventEmitter/Duplex, ref/unref/managed idle, typed late-resource disposal,
DNS/TLS and transport selection remain separate work. No whole #745 criterion
or issue is completed by this foundation.

## Signed four-call global programme

`typescript-buffer-globals.yml` passed one normal strict-TypeScript build and four
fresh signed calls on one node: transitive module initialization and alias/view
identity, a timer callback using the real global, caught allocation-ceiling
refusal, and fresh initializer state after that refusal. Its sources are
repository-controlled fixtures, not unchanged published-library qualification.
[Owning run 40163842153](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40163842153/job/121080744355)
passed at source `677f05ae56498bdc63e0650d3103a1635213e2f1`: eight pinned
source controls without skips, 26 normal build commands and 177 bounded owner
commands. Each original public CLI response bound its unique requested
activation and the same deployed publication/revision tuple. The one
12,202,891-byte component was packaged, signed and admitted normally; existing
authenticated engine/splicer and native CLI products were reused without rebuilding.

All four calls returned their exact fresh-state strings. Consumed fuel was
13,984,916; 14,321,214; 14,074,207; 14,122,088 respectively, with maximum reported
peak memory 9,512,112 bytes. Each original retirement observation reported all
18 available active-provider counters, active/quarantined cells, quota
reservations and cleanup slots zero; the one configured cell remained available.
Deletion and clean reaped shutdown followed on the same owned node process.
The [immutable public receipt](../testing/typescript-buffer-globals-evidence.json)
retains all 33 artifact member identities, four raw CLI results, observed
retirement/shutdown fields, 210 unique source-bound Git materials and original
command identities. The 103-entry captured-source inventory records identities;
it does not claim that 103 raw project files were uploaded. Acquisition/signing
channels retain hashes only; private state is excluded and removed before
successful publication. Generic profile qualification remains unknown.

This distinct reference programme selects Task32, Executor2, Queue32, Wait8,
Timer8, Result8 and Native128, matching the reviewed Socket reference funding;
the earlier pure-Buffer Task16/Queue16/Native64 programme is unchanged. Effective
requests remain 1 billion fuel, 128 MiB and 120 seconds, with zero outbound
requests and other effects. The global node fuel maximum remains separately
10 billion. The owner keeps original retirement observations and an explicit
public-file collector; signing, private node/client state and acquired tools
are outside its retained artifacts. Internal factory/Store identities were
not exposed. The timer case proves callback completion, without a latency or
separately observed parked-timer claim. No whole cost, unchanged published
global-Buffer library, networking or production gate is met by this finite
programme; AC5/AC7 and the whole ticket remain open. No hosted attempt in this
programme failed; earlier local source-control setup repairs do not become
runtime failures or additional signed evidence.
