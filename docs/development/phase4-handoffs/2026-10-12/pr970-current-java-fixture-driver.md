# Explicit current Java signing fixture

The current collector called `fixture-sign-current-java-inputs`, but no retained
implementation was found. The ordinary package examples do not provide that
command. `fixture-tls` is an existing tracked command on the
`latent-policy` example `capsule_authoring`.

The new explicit command uses the existing tracked signing keys, SBOM builder,
policy construction and actual package verifier. It requires the exact clean
Java capture source `9bae83952d9513c965a88d375b2a533916a98473` and all five positive
inputs from the separately retained six-component capture. The forbidden
immediate HTTP input remains a separate required refusal in the collector.
Pinned reports, components, source archives, compiler closure, source and recipe
inventories, companions, current profile markers and original invocation bounds
are checked before key generation or output creation. It accepts the explicit
Phase 4 manifest profile without changing ordinary demo signing behavior.

The source-captured material identities come from
[the existing bounded packet](pr970-current-post-evidence.json). The result
declares `synthetic-native-package-trust`, a finite ephemeral test policy,
`compilerExecutedBySigner: false`, and no signed-node or packaged-distribution
qualification. Private signing keys stay in memory. The release-set success
marker is written only after real package verification and all outputs complete.
The existing TLS command creates an owned fresh localhost identity. The current
v2 collector creates no obsolete clock file: its native owner admits the actual
protected clock and checkpoint. Historical paths remain separate.

Initial default Cargo example tests passed all eight cases, including the six
original signing/TLS controls and two new current-source/material refusals.
The new cases are explicitly registered without changing ignore guards. Actual
five-package signing, admission/refusal and the combined node campaign remain
required validation after a fresh source-matched metadata helper is available.
This implementation milestone is not runtime qualification or ticket closure.

Build the selected driver with pinned Rust 1.97.1:

```sh
cargo +1.97.1 build --locked --offline -p latent-policy --example capsule_authoring
```

Capture the exact `compiler-artifact` executable, source head/tree, manifest and
feature graph before invoking it. The explicit signing command is:

```sh
capsule_authoring fixture-sign-current-java-inputs /new/private/output \
  9bae83952d9513c965a88d375b2a533916a98473 \
  /prepared/aggregate /prepared/put-once-legacy-v1 \
  /prepared/put-once-compatible-v2 /prepared/put-once-writer-v2 \
  /prepared/put-once-diagnostics
```

Its real TLS command is `capsule_authoring fixture-tls /new/private/tls`.
The current collector's AOT compiler is a separate explicit
`latent-wasmtime` binary `latent-aot-compiler`; it is not a signer mode.
