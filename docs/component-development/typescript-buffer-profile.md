# Pure `node:buffer` source profile

`lsf-node-buffer-v1` supplies a compiler-owned, module-only byte Buffer foundation
for #745. `buffer` and `node:buffer` resolve to the same module and constructor,
independently of package identity and the selected synchronous/async runtime.
It adds no global `Buffer`, Node process, I/O, capability, permission or native
storage. Every other uninstalled Node builtin retains its existing refusal.

This is source and Node reference evidence. No guest compiler, engine rebuild
or signed Component Model programme has run for this profile. Arbitrary npm
dependencies and the full TypeScript accounting/socket criteria are unqualified.

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
