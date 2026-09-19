# TypeScript browser application qualification

The Node SDK remains private numeric-loopback RPC. Its browser companion extends
the maintained [Angular boundary fixture](../../examples/browser-boundary/angular-build.json)
and the existing [same-origin-v1 policy](../security/browser-boundary.md), not a
second renderer or privileged RPC proxy. The source entry is
[`client/application.ts`](../../examples/browser-boundary/client/application.ts).

## Application contract and ownership

The single public operation is `POST /api/greeting`, with the fixed JSON request
`{"name":"Browser"}` and a bounded scalar response `{"greeting":"Hello Browser"}`.
The existing [web WIT fixture](../../tools/toolchain-smoke/examples/web_contract/component.rs)
implements it; the node admits an exact POST route to that real component. No
root catch-all, RPC namespace, catalog path or dynamic destination is installed.
The host derives the low-privilege `browser-fixture` principal in tenant `tests`
from its explicit `localhost:<port>` public-origin binding, not from the body.

The helper selects its current origin and fixed path, `mode: same-origin`,
`credentials: omit`, `redirect: error`, and `cache: no-store`. It never reads a
token, cookie, storage or environment variable. The browser creates the matching
Origin header; the host enforces CSRF/CORS/CSP policy. A 3,000 ms absolute local
deadline bounds fetch/reading, with a 256-byte application-owned copy and closed
JSON DTO. Browser network internals are not a claimed 256-byte process-memory
limit. HTTP errors are application failures; local abort is not an RPC Cancel
or proof that the node did not execute the request. No automatic retry occurs.
The Angular component admits one call at a time and aborts on destruction.

The server entry injects only inert render state. The browser entry supplies the
fetch implementation after hydration. The same maintained compiler/linker and
client/server separation checks build both entries; no Node transport import,
management token or server-only marker appears in the browser artifact.

## Executed checks

On Linux x86-64, Node 24.19.0, Angular 22.1.6 and Chromium 153.0.8010.47:

- Seven public-helper/hydration tests pass, including malformed/oversized replies,
  bounded cancellation without replay and escaped primitive-only hydration.
- Both actual-browser Rust tests pass, with no ignored test in the selected run.
  One checks the original asset-only node; the other installs the real public WIT
  component and observes its execution. Both re-use server DOM and navigate.
- The intended POST sends neither Authorization nor Cookie even after a test
  cookie is installed. Known RPC/admin paths, path-prefix extensions and GET on
  the POST-only route return 404. An Authorization header returns 401.
- A separate cookie-bearing POST retains the same anonymous host principal;
  cookies are not platform user authentication. Responses remain no-store and
  contain no CORS permission. Existing CSP, base-origin and MIME checks pass.
- Final node teardown checks zero active activations, quota reservations, stores
  and asset readers, then joins shared ingress/node owners. No per-app listener,
  process or renderer pool is added to production.

Executed browser code: `24c37bb3`, in integration source
`444399d3e960ac89d06ce6ba98a5f130d3e9c5a4`. The compact
[machine-readable receipt](../evidence/phase3-sdk-browser.json) records the actual
output identities, not a reusable cached test result. SHA-256 of the Node binary
was `bc17c508ffeed0ec622934f9b7fa72f8e78da65350e63c3eceb56fa688aa5e12`.

```sh
node --test tools/tests/browser_application.test.mjs tools/tests/browser_hydration.test.mjs
node tools/browser-boundary/build.mjs examples/renderer-profile "$BUILD"
cargo build --locked -p latent-toolchain-smoke --example web-contract --target wasm32-unknown-unknown --release
wasm-tools component new "$CARGO_TARGET_DIR/wasm32-unknown-unknown/release/examples/web_contract.wasm" -o "$BUILD/application.wasm"
LSF_WEB_COMPONENT="$BUILD/application.wasm" LSF_BROWSER_BUILD="$BUILD" \
  LSF_BROWSER_NODE="$(command -v node)" LSF_BROWSER_CHROME="$(command -v chromium)" \
  LSF_BROWSER_TOOLCHAIN="$PWD/examples/renderer-profile" \
  cargo test --locked -p latentd --lib actual_browser_ -- --ignored --nocapture --test-threads=1
```

Install the pinned renderer dependencies with `npm ci --ignore-scripts` first,
and select a fresh ignored `BUILD` directory. Normal CI runs both named tests
from the current successful Cargo inventory and retains both receipts; a missing
test is not accepted as an empty successful filter. The local strict Clippy run
was interrupted when Docker Desktop stopped after browser success and is not
claimed passing; exact-head CI must independently complete it.

## Qualification boundary

HTML here is produced by controlled Node SSR and published through the actual
shared immutable asset owner. The public API executes a real Wasm component,
but the HTML itself is not rendered in a generic Wasm cell. The fixture's web
asset authority is test-only; root-container Chromium disables its OS sandbox.
Neither is cryptographic publication, hostile-code containment, installed-bundle
or production Angular T1 qualification. The complete signed application,
authenticated-content, protected compiler/cache, release cutover and resource
campaign remain #226/#236/#239/#240. Cookie values are deliberately not a login
framework, and the helper does not sanitize arbitrary application HTML/scripts.
