# Cross-origin asset feasibility

This contributor experiment implements the contract in
[ADR-0049](../../adr/0049-scope-cross-origin-assets-to-publications.md) on disposable
HTTPS loopback peers and checks it using actual Chromium. It does not exercise
native LSF ingress, signed publication admission or a deployed cloud environment.

Use the pinned Node and browser tools from `examples/renderer-profile`, a local
Chromium executable, and the pinned `primeicons` package's WOFF2 font. Create a
fresh private TLS directory with the existing test-only helper (the argument
must be an absolute path):

```sh
cargo run --locked -p latent-policy --example capsule_authoring -- fixture-tls "$Tls"
node --test tools/cross-origin/contract.test.mjs
node tools/cross-origin/browser.mjs "$Toolchain" "$Chromium" "$Tls" "$Woff2" "$NewReceipt"
```

`Toolchain` is the directory containing `package.json` and installed
`playwright-core`. `NewReceipt` must not exist. The command exits nonzero on a
failed case and retains a bounded receipt with the failed case, observed request
metadata and response headers. It closes its browser and loopback listeners.
The test certificate is trusted only by the disposable browser context; no
system trust store is changed. Do not publish its private key.

The [native implementation follow-up](https://github.com/KirilsTurkins/latent-service-fabric/issues/660) must reuse the cases against actual LSF and
add publication lifecycle, configuration, cancellation and capacity coverage.
Passing this experiment is not permission to configure unsupported CORS fields
on a node or to remove the existing browser boundary.
