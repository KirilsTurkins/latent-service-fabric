# Java bounded standard output

The candidate `lsf.java.bounded-standard-logging.v1` port replaces the sole
console write operation in the pinned TeaVM stdout and stderr classes. It
preserves their singleton initialization, ordinary `System.out` / `System.err`
selection, `PrintStream` formatting code and application `System.setOut` /
`System.setErr` overrides. It does not select callers from a package catalogue.

The captured WIT must explicitly declare `latent:log/log@0.1.0`. Operator grants,
bindings, policy and the existing `LogBytes` accounting remain authoritative.
The production compiler adds no import or authority. Without a declaration,
nonempty output fails with `IOException`; standard `PrintStream` records the
failure for `checkError()`. Applications using the direct generated log API
retain its typed result. Other standard facilities remain in the separate
[entropy profile](java-standard-entropy.md).

| Standard path | Supported finite mapping |
| --- | --- |
| `System.out` byte writes, string/primitive print and append | Existing TeaVM formatting followed by synchronous `info` log records. |
| `System.err` writes and println | The same path with `error` records. Newlines remain message bytes. |
| Encoding | Every byte write must be complete well-formed UTF-8. Malformed or split raw UTF-8 fails explicitly. The upstream character formatter still selects its encoding and replacement behavior. |
| Size | The bridge bounds a single write at 4096 bytes. The unchanged host further limits each message to 256 UTF-8 bytes and the full encoded record to the original invocation budget. Oversized host messages fail; they are not truncated or silently split. |
| Empty writes | No host call, including an undeclared log capability. |
| Error policy | Budget exhaustion, invalid field/message, unavailable sink and a false acceptance result produce distinct `IOException` codes. `PrintStream.checkError()` exposes its standard sticky error state. No rejected output is retried. |
| Flush and lifetime | The bridge has no pending buffer or worker. Flush creates no record and does not acknowledge remote delivery. There is no log owner to drain after retirement. |

Formatting may produce more than one byte write and therefore more than one
record. Accepted earlier fragments are not rolled back if a later write fails.
The port passes no guest fields; the existing host supplies activation, trace
and span identity, field validation, sink behavior and accounting. It adds no
secret capture or guest-claimed correlation fields. It does not promise content
redaction beyond the existing host policy. `PrintStream` close and formatting
behavior otherwise remain those of the pinned TeaVM implementation; this is
not a qualification of every formatter, file stream or process console API.

Compilation captures and hashes the SDK plugin, template and recipe with the
ordinary source, graph and component provenance. Compiler model analysis loads
verified tooling, without executing application initializers or reading a log
provider at build time. Fresh activation Stores own their stream/error state.
This synchronous path requires no new timer, runtime scheduling permission or
authority ledger; concurrent/async logging qualification remains separate.

The [source evidence](../testing/evidence/java-standard-logging-source-2026-10-16.json)
contains the actual locked TeaVM model, 39 host source checks, undeclared
compilation without a log facade, real WIT/C/Java generation and 12 reference
JDK runs. These are source and reference controls. The existing Java gate now
also builds an outside-checkout signed logging component and selects 16 actual
invocations: UTF-8 stdout, stderr/newline, primitive/append formatting, exact
256-byte boundary, malformed bytes, exhausted budget, host message rejection,
sink rejection/refund, trusted correlation and fresh stream state. All original
nine SDK components, commands and job limits remain. The new component build
and signed invocations are pending; this candidate does not complete #681.

The contract is compared with the
[JDK PrintStream documentation](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/io/PrintStream.html)
and the pinned
[TeaVM console classes](https://github.com/konsoletyper/teavm/tree/0.15.0/classlib/src/main/java/org/teavm/classlib/impl/console).
