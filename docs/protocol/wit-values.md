# Phase 1 WIT value payloads

The generic Wasmtime backend uses
`application/vnd.latent.wit-values.v1+json` for invocation input and output. The
component's validated WIT types determine the interpretation of each value.
The payload is UTF-8 JSON containing one positional array: parameters in function
declaration order on input, and results in declaration order on output. A function
with no parameters or results uses `[]`. Names identifying the contract and method
belong to the invocation envelope, not this array.

This version supports synchronous component functions exposed through component
interfaces. It does not give clients WASI, resource handles, streams, futures, or
an alternate transport. HTTP and SDK byte payloads must use the same framing when
targeting the generic backend.

## Value mapping

| WIT type | JSON representation |
| --- | --- |
| `bool` | Boolean. |
| `u8`, `u16`, `u32`, `s8`, `s16`, `s32` | Integer token within the exact type's range; `1.0`, `1e0`, and strings are rejected. |
| `u64`, `s64` | Canonical decimal string, such as `"18446744073709551615"` or `"-9223372036854775808"`. No plus sign, leading zeroes, negative zero, fraction, exponent, or whitespace. |
| `f32`, `f64` | String containing a finite JSON decimal, or exactly `"nan"`, `"inf"`, or `"-inf"`. |
| `char` | String containing exactly one Unicode scalar value. |
| `string` | Unicode string, without normalization. |
| `list<T>` | Array of `T`; `list<u8>` uses integer elements, without a base64 shortcut. |
| `tuple<...>` | Array of exactly the declared arity, in declaration order. |
| `record` | Object with exactly the declared field names. Output follows declaration order. |
| `variant` | `{"case":"name"}` for a case without payload, or `{"case":"name","value":...}` for a case with payload. |
| `enum` | Exact declared name string. |
| `flags` | Array of distinct declared name strings. Input order is unrestricted; output follows declaration order. |
| `option<T>` | `{"none":null}` or `{"some":...}`. |
| `result<T,E>` | `{"ok":...}` or `{"err":...}`. A branch without a payload uses `null`. |

Unknown, missing, or duplicate object keys are rejected, including duplicate keys
that differ only in JSON escape spelling. Variant unit cases reject a `value`
field, including `"value":null`. A result or option object contains exactly one
tag. Tuple arity, field names, case names, numeric ranges, and nested shapes must
match the actual component type. Resources (`own` and `borrow`), maps, futures,
streams, and error contexts are rejected during preparation.

Floating-point decimal strings are parsed directly into the declared precision,
so an `f32` input does not first pass through `f64`. Finite decimal overflow is
rejected; an infinity requires its explicit special token. Finite inputs follow
the target precision's normal rounding, including underflow. Output uses the
shortest decimal representation that round trips to that precision, preserves
negative zero as `"-0"`, and emits no redundant exponent or fraction syntax.
Every NaN is written as `"nan"`; NaN payload bits and sign are not preserved.
Finite numeric bit patterns round trip exactly. Input accepts alternate finite
decimal spellings such as `"1.25e+2"`; output normalizes them, here to `"125"`.

For example, a function with parameters `(name: string, count: u64,
enabled: option<bool>)` accepts:

```json
["example","18446744073709551615",{"some":false}]
```

Nested option tags preserve the distinction between no outer value and an outer
value containing no inner value: `[{"none":null}]` and
`[{"some":{"none":null}}]` are different values.

## Results and declared errors

Both outcomes retain the complete result array. For a function returning one
`result<string, variant { unavailable, rejected(string) }>`, success can be:

```json
[{"ok":"accepted"}]
```

An error can be:

```json
[{"err":{"case":"rejected","value":"invalid order"}}]
```

Only an `err` branch that is the function's **sole top-level result** becomes an
activation `DeclaredError`. Its code is always `declared-error`, its message is
always `component returned a declared error`, its media type is the value media
type above, and its payload is the entire encoded result array. Application case
names remain payload data. Nested `result` values, including errors inside a
record or list, remain ordinary returned data. If a component function has
multiple results, all results remain ordinary returned data.

## Bounds and allocation accounting

`ValueCodecLimits` defaults are:

| Limit | Default |
| --- | --- |
| Raw input bytes / emitted output bytes | 1 MiB each |
| JSON container depth / schema nesting depth | 32; configuration permits at most 64 |
| JSON nodes | 16,384 |
| Decoded UTF-8 bytes in any string or object key | 256 KiB |
| Elements or fields in any collection, including the positional array | 4,096 |
| Examined type nodes and declared name slots per signature sequence | 4,096 |
| UTF-8 bytes in a declared field, case, enum, or flag name | 256 |
| Conservatively accounted lifted allocation per component transfer | 16 MiB |
| Conservatively accounted decoded input values | 16 MiB |

The raw input is bounded before parsing. A lexical pass checks decoded string
lengths, container depth, and nodes before recursive parsing or escaped-string
scratch allocation. Nodes include containers, primitive values, and object keys.
The bounded parser rejects duplicates and checks collection length before
reading excess values. It constructs a bounded input JSON tree and consumes that
tree while building typed Wasmtime values. The separate decoded-value allowance
accounts for those retained values, including inline storage, names, strings,
vectors, and boxes. Output is written directly into a capped byte buffer;
serialization does not first construct an unbounded JSON result tree. Output
escaping counts against the emitted byte limit.

Wasmtime's hostcall fuel bounds dynamic transfer work, but it does not directly
charge every inline record field, tuple element, flag name, or variant box.
Before adoption, the backend validates each parameter/result signature, including
known host imports, using the same configured hostcall fuel that execution will
use. The signature plan adds a conservative fixed inline allowance to the fuel
allowance multiplied by the largest inline list-element amplification. Nested
lists are inspected too. Arithmetic is checked, and an excessive plan fails
preparation. The backend also accounts for aggregate type traversal across the
component surface.

The lifted allowance applies to each transfer; the decoded input allowance is
separate because input values can remain alive while a guest result or host call
is lifted. Input bytes, the bounded parser tree, retained input values, lifted
values, and output bytes are distinct allocations. These are conservative
application-owned allocation limits, not a byte-exact process RSS claim or a
replacement for guest linear-memory and execution limits. Raising one limit does
not silently raise another.

Malformed input uses `InvalidArgument` / `invalid-invocation-values`; a different
media type uses `InvalidArgument` / `unsupported-invocation-media-type`. Exceeded
input or signature limits use `ResourceExhausted` / `invocation-value-limit`.
Input failures are rejected before creating a store. Unsupported component types
use `IncompatibleContract` / `unsupported-component-value-type` during
preparation.

An output limit can fail after the guest has consumed resources. The backend
returns a bounded guest trap with code `result-limit-exceeded`, preserving the
measured consumption. An otherwise invalid runtime-supplied output value uses
trap code `invalid-component-result`. Both traps have an empty backtrace and
`result-codec-error` metadata identifying the underlying platform error code.
Cleanup still completes before the backend returns its reusable-cell proof.

The codec unit fixture at
`crates/latent-wasmtime/src/values/types.wat` exports only types. Its checked-in
binary is regenerated with `wasm-tools parse types.wat -o types.wasm`; unit tests
load it with pinned Wasmtime and do not run executable guest code.
