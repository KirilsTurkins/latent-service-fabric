# Browser boundary validation observations

Date: 2026-09-19. Tested code revision:
`295895ca9d02a4c31225640b7521f3c118ff3b51`.
This is bounded local evidence for [same-origin-v1](../security/browser-boundary.md),
not a production security certification or an issue-closure decision.

## Stack and environment

- Development base: `9c271713276b124aed39921cc70b6c2745c2ca47`, including the
  reviewed response-cache and neutral network changes.
- Explicit asset dependency: PR #336 head
  `8dd265410acad8f69ec51a94a276ec0a28b5a94c`. Its independent owner/accounting/drain
  implementation is retained, not replaced or duplicated by this work.
- Rust 1.97.1, Linux x86-64, isolated 2-CPU/8-GiB validation container;
  development/test debug information and incremental compilation disabled.
  The browser work uses a separate Cargo target directory from asset integration.
- Controlled SSR build: Angular 22.1.6, Node 24.19.0. Real browser:
  Chromium 153.0.8010.47 on Debian 12. Browser HTML is Node-rendered, not
  Wasm-rendered; component-response tests execute a separate real Wasm fixture.

## Executed checks

| Check | Observed result |
| --- | --- |
| `cargo test -p latent-ingress --locked` | 22 unit and 16 integration tests passed |
| `cargo test -p latentd --lib --all-features --locked standalone::http` | 30 passed; 8 explicit prerequisite-gated ignores |
| Real `actual_http_component` ignored slice with freshly built/validated fixture | All 6 passed, including personalized cache and unsafe response rejection |
| Real `actual_browser_boundary` ignored slice | 1 passed; live ingress, no response mocking |
| `cargo clippy -p latentd --all-targets --all-features --locked --no-deps -- -D warnings` | Passed |
| `cargo fmt --all --check` and `git diff --check` | Passed |
| `node --test tools/tests/browser_hydration.test.mjs` | All 4 passed |
| HTTP schema, CI-profile and Cargo-artifact Python tests | All 35 passed |
| `python tools/validate_docs.py` | No documentation/link errors |

The ordinary HTTP slice's ignored tests were not counted as passes. Six real
component tests and the browser test were subsequently executed explicitly.
The remaining Angular-component-specific HTTP test was not executed locally;
the existing renderer CI owns that separate prerequisite and execution path.
An additional ingress-wide strict-Clippy experiment reported inherited cache
lint findings; the maintained strict `latentd` scope above passes. No unrelated
cache-lint rewrite is included.

## Compact redacted receipts

The live browser's receipt contains no tokens, cookies, tenant payloads or ports:

```json
{"browser":"153.0.8010.47","liveSharedIngress":true,"controlledNodeSsr":true,"componentRenderClaimed":false,"originalDomReused":true,"navigationHydrated":true,"escapedDataRoundTrip":true,"inlineAndRemoteScriptsBlocked":true,"baseOverrideBlocked":true,"wrongScriptMimeBlocked":true,"sameOriginPostReachedMethodPolicy":true,"errors":0}
```

Observed SHA-256 identities for the controlled outputs:

| Artifact | SHA-256 |
| --- | --- |
| Browser client | `16b79f6238c5b80b2acc0bb1ef4b8132404d5b435b179323e6c9fa4a58d1311f` |
| Home SSR HTML before immutable-client URL substitution | `16eb54cf7c11065898a1f3695c74e93fb8c18bde5ac0f5ea3e2c55d12aafee36` |
| Navigation SSR HTML before substitution | `254d40ab69a8bdcb8fcec6eae1ca811e79ae36486e82109d2a1f852544834359` |
| Real public web test component | `751f12c488d9374def6f18d5db971f425063cc0d43a6b9243f29cd9022a17628` |

The two-stage client/page publication is a controlled way to obtain an actual
immutable script URL without a self-referential content digest. It is not proof
of a production SSR/client release cutover. The asset fixture injects an explicit
test authority; root-container Chromium disables its OS sandbox. Neither choice
is presented as cryptographic admission or hostile-code containment evidence.

## Remaining acceptance boundaries

Exact-head PR CI and parent review are still required. The parent controls PR
merges and issue closure. No workflow-scope bypass, issue closure or remote merge
was performed. Full application publication, Angular Wasm SSR/client release
integration and management/T1 projection remain #226/#236 responsibilities.
No reconnect-flood fairness, arbitrary HTML sanitization, automatic secret
classification or browser user-authentication guarantee is claimed.
