# Native publication-scoped cross-origin asset qualification

Issue #660 implements [ADR-0049](../../adr/0049-scope-cross-origin-assets-to-publications.md)
on the existing native HTTP/static-asset owners. The
[operator guide](../operations/cross-origin-static-assets.md) is supported by the
signed-publication tests below, not by the original Node policy-peer experiment.
This is an implementation-branch/development qualification, not a released
alpha.5, cloud, production certificate or end-user authentication claim.

## Recorded native result

[Run 41058876134](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41058876134)
completed **successfully**, including native Rust tests, the signed-publication
Chromium campaign, maintained formatting and strict lint. It tested branch head
`1817de81d59cfdd1811dab3b9ce0741de8f01b5b` with development
`26966f822eaafcfad7749836e749b3ac25c5a9e8`, at clean synthetic merge
`0e6fc761b8f6751a30e4d8a6301f75495db66315`.

All **19 native Rust cases** and **19 browser cases across 11 lifecycle stages**
passed again. The browser retained 73 network-service observations and 13 separate
wire-client observations. All six node stops were clean and reaped. The
[green-run manifest](evidence/cross-origin-native-2026-10-30.1817de8.json) binds the
exact source, run, job and artifact to losslessly retained
[qualification](evidence/cross-origin-native-2026-10-30.1817de8.qualification.json.gz)
and [browser receipts](evidence/cross-origin-native-2026-10-30.1817de8.browser.json.gz).
A regression checks their hashes, lifecycle completeness, authority limitations
and cleanup. This is evidence for that exact revision, not a substitute for
final-head checks on later changes or a claim that every repository CI job passed.

### Earlier qualification and lint correction

[Run 41038217752](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41038217752)
on 30 October 2026 executed branch head
`341e3e619f99862d611b1b8d2758987a1af01eee` merged with development
`26966f822eaafcfad7749836e749b3ac25c5a9e8`. The actual clean source identity was
`fa5395e71e98860421539c832be16e1d660ea8bc`, not the branch head alone.

Native Rust execution passed **19 cases** selected by `cross_origin`: the 17
CORS configuration/admission/lifecycle/ownership cases and two existing browser
boundary/cache controls. The actual node and CLI built successfully. Chromium
156.0.8078.47 then passed **19 browser cases in all 11 lifecycle stages**, with
73 browser network-service observations and 13 separately labelled wire-client
observations. Four distinct signed publications exercised an allowed target,
a new ungranted target, an anonymous-only target and a foreign tenant.

The workflow subsequently failed its old direct Clippy command on dependency
lints. This recorded run is therefore **not an all-green workflow**. Its completed
native/browser qualification is independently successful; the maintained
workflow now selects the same workspace and strict-owner lint recipes as normal
CI. Later CI must validate the final changed commit independently.

[Evidence manifest](evidence/cross-origin-native-2026-10-30.json) records the exact
source/run/job/artifact identities, product/receipt provenance and limitations.
The original bounded receipts are retained losslessly as
[qualification JSON](evidence/cross-origin-native-2026-10-30.qualification.json.gz)
and [browser/network JSON](evidence/cross-origin-native-2026-10-30.browser.json.gz).
They are gzip archives of the original JSON, with deterministic gzip timestamps;
the manifest contains compressed and uncompressed SHA-256 digests and byte counts.
No certificate private key, credential value or request query is retained.

| Stage | Required observation |
| --- | --- |
| Default | No grant: cached/body, HEAD, conditional and preflight requests denied. |
| Allowed | Scripts execute, CSS applies and a real WOFF2 loads from native LSF; exact CORS/CORP/cache/credential behavior, unrelated origins/publications/tenants, HEAD/304/errors, unsafe/header preflights, null Origin and no-cors controls pass. |
| Removed / restored | Configuration stop/restart removes permission, then explicitly restores the same exact grant. |
| New-ungranted / new-opted-in | Route replacement does not inherit permission, even with identical asset bytes; old immutable publication authority remains independently scoped. |
| Expiring / expired / renewed | A real short-lived proof expires; current reads, conditionals and preflights fail closed, then resume only after supported evidence renewal and exact route refresh. |
| Revoked / restart-revoked | Revocation denies subsequent reads/conditionals/preflights; restart does not revive it. |

The Rust controls additionally force exhausted read capacity, disconnect while
a blocking read still owns its permit, and revocation during backpressured
preflight output. The lifecycle case covers stale-proof, clock/lease failure,
generic conflict, capacity and corruption classifications without flattening
operational failures into permission. Existing application/bearer/default-origin
controls remain selected by the normal suite.

Before/after node inventory reports no guest activation, compiled component or
execution-cell lease for the static campaign. All six node stops were clean and
reaped; shared HTTP/read buffers and owners retired. Browser and caller-listener
cleanup completed. These observations do not imply a global process-RSS bound.

## Reproduce the maintained campaign

Use the pinned [contributor toolchain](../development/toolchain.md) on Linux
x86-64. Run from a matching checkout with the node's normal native prerequisites,
an installed Chromium executable and a **new** output directory. The locked
renderer-profile toolchain supplies Playwright and a real PrimeIcons WOFF2 file.

```sh
python3 -m pip install --requirement tools/requirements.lock
python3 -m unittest tools.tests.test_cross_origin_native_schema tools.tests.test_cross_origin_native_workflow -v
node --test tools/cross-origin/contract.test.mjs tools/cross-origin/native-network.test.mjs
cargo test -p latentd --lib --locked cross_origin -- --nocapture --test-threads=1
cargo build --locked --bin latent --bin latentd
npm ci --prefix examples/renderer-profile --ignore-scripts --no-audit --no-fund
python3 tools/cross-origin/native_qualify.py \
  --cli target/debug/latent --node target/debug/latentd \
  --toolchain examples/renderer-profile --chrome "$(command -v google-chrome)" \
  --font examples/renderer-profile/node_modules/primeicons/fonts/primeicons.woff2 \
  --output target/cross-origin-native-local
python3 tools/ci_cargo.py run format
python3 tools/ci_cargo.py run clippy
```

This explicit qualification command does not replace the normal exact-case suite
catalogue or claim that listing/building tests executes them. CI owns the same
campaign in `.github/workflows/cross-origin-assets.yml`, retains source, native
products, tests and receipts, and fails on any mandatory stage or cleanup failure.
Its reviewed ownership-local contract accompanies command changes.

The only Node HTTPS peer serves the external caller document; **all assets and
CORS decisions come from native LSF**. Chromium's network-service ExtraInfo
captures actual headers and raw 304 responses, including CORS failures. Missing
wire evidence cannot become a pass. A real opaque-origin document provides the
null-Origin case. Malformed/duplicate Origin is tested by the separately labelled
wire client, not fabricated as browser JavaScript behavior.

Only the disposable Chromium context bypasses trust for its test certificate;
wire clients verify that certificate and no system trust store is changed. The
original `tools/cross-origin/browser.mjs` still records feasibility only and
cannot be used as a native qualification receipt. Deployment certificates,
proxy networking, session authorization and third-party-cookie policy remain
separate operational/security responsibilities.
