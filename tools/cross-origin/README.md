# Cross-origin static asset qualification

## Native signed publications

`native_qualify.py` drives the real node/CLI and `native-browser.mjs` against
signed static publications. The external Node HTTPS peer serves caller documents
only, never assets or CORS responses. Use the [native qualification guide](../../docs/testing/cross-origin-static-assets.md)
for the recorded 19-case browser/11-stage lifecycle result, exact source identity,
retained receipts and reproduction commands. The [operator guide](../../docs/operations/cross-origin-static-assets.md)
and [validated configuration fragment](../../examples/cross-origin-assets/http-ingress.json)
describe development usage; this is not released alpha.5 or production TLS qualification.

`native-network.mjs` records bounded Chromium network-service ExtraInfo, distinct
from the explicit malformed-header wire client. Its tests cover event order,
redaction, bounds and cleanup. Native Rust controls cover strict defaults, exact
selection, revocation, disconnect/read-owner retention and capacity refusal.

## Original separate-peer feasibility experiment

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

This original experiment remains independent from the native campaign above.
Passing it alone does not establish native publication admission, lifecycle,
configuration, cancellation or capacity behavior, and is not permission to remove
the existing browser boundary.
