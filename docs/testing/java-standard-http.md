# Java ordinary URLConnection provider controls

The standard Java HTTP source profile now has a focused real-component gate.
The fixture uses ordinary `URL.openConnection()` and `HttpURLConnection`
request/response APIs, including APIs called after construction, stream close
and `disconnect`. It supplies no application transport and makes no direct SDK
HTTP request. The maintained compiler installs the shared standard backend.

The [source profile](../component-development/java-httpurlconnection.md) remains
an implementation candidate. This gate does not qualify two unchanged published
clients, an outside-checkout private JAR, HTTPS, workers/timers, all cancellation
races or the full requirements of [#688](https://github.com/KirilsTurkins/latent-service-fabric/issues/688).

## Executed boundary

The [source-bound receipt](evidence/java-standard-http-2026-10-15.json) records a
1,154,607-byte TeaVM-emitted component, actual publisher/builder signing, enforced
standalone publication/admission and the production typed streaming HTTP provider.
The frozen native tuple comes from `a49bbf172e08c13ed7bd5588e2323064652f9366`,
with Wasmtime 48.0.6 and no extra build features. It is separately identified from
the application/compiler/profile and qualification source digests. No historical
receipt or compile-only control is used as evidence of a provider operation.

The shared [standard HTTP fixture](standard-http-conformance.md) supplies controlled
loopback peers. The following 12 scenarios passed, in addition to missing runtime
and HTTP grant denials before guest execution/contact:

- UTF-8 JSON, HTTP 404 and HTTP 500 preserve actual response bodies/status.
- Truncated and oversized bodies preserve transport errors.
- Reserved Authorization and an alternate destination are denied with no peer contact.
- Early body close retires actual owners while the peer still has a gated suffix.
- The unsupported default redirect reports an error and makes no secondary contact.
- Ordinary POST sends the exact binary body and media/framing semantics.
- A peer accepts one mutation and loses its reply: the result stays `uncertain`,
  with exactly one mutation and no hidden reconnect/replay.
- A final invocation sees fresh static state and completes after the failures.

Across the 12 scenarios the peer records exactly ten started requests, no
rejected requests, one committed mutation and no contact at the secondary origin.
The two missing-grant denials and two denied HTTP operations produce no extra
contacts. Observations keep requests and actual mutations distinct.

After every scenario the maintained outbound owner checks all activation-scoped
and service-resident topology entries, cell availability, queues and quota usage.
The explicit cleanup-slot owner and every existing active broker/pool/I/O counter
must be zero. Both node and peer are joined/reaped; the node's final report requires
clean provider, compiler and cleanup shutdown. Peer socket close alone is never
treated as host retirement. The receipt includes sampled Linux process memory,
descriptors and threads. Sampled RSS is not an allocator or native/kernel bound.

The fixture permits an 8 KiB response to accommodate the existing 4,109-byte
gated partial-body vector, with 4 KiB chunks and at most two outstanding chunks.
The 64 KiB oversize vector still fails. These are fixture-local inputs; no
production limit is changed.

## Reproduction and CI ownership

The existing `tools/qualify_java_capsules.py` owner creates one additional
independent project, builds it with the already selected compiler/native tools
and executes this gate. It retains every previous standalone, SDK, signed node,
guide and inbound server stage. There is no additional workspace/native build
for this fixture. Source/helper identities enter the qualifier's original
before/after input checks.

For focused execution after preparing the existing pinned Java toolchain and
ordinary native products, use a fresh outside-checkout output directory:

```bash
python3 tools/java_standard_http_project.py "$OUT/project"
python3 tools/java_capsule.py build "$OUT/project" --output "$OUT/build" \
  --repository https://github.com/KirilsTurkins/latent-service-fabric \
  --wasi-sdk "$WASI_SDK_PATH" --gradle "$GRADLE" \
  --read-only-cache "$PINNED_GRADLE_MODULES" \
  --contracts-tool "$NATIVE/capsule_contracts" --packager "$NATIVE/package"
python3 tools/java_standard_http_node.py --artifact "$OUT/build" \
  --native "$NATIVE" --output "$OUT/node"
```

`$NATIVE` contains the exact `latent`, `latentd`, `capsule_authoring`,
`capsule_contracts` and `package` products. A supplied `native-tuple.json` is
checked against the actual binaries and retained as a build-source association;
its preparation status does not establish execution. Read-only dependency inputs
remain separate from the compiler attempt's private mutable Gradle home.

`qualification.json` is written only after this finite gate passes. Original
failed attempts retain their stages: the first fixture lacked its required
runtime-support world; subsequent harness attempts distinguished preflight grant
denial from a guest result, selected the outbound topology owner instead of
ingress-only rows, and selected a finite response ceiling that admits the existing
partial-body vector. None is relabelled as an executed successful case.
