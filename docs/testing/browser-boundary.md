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

## Acceptance boundaries at this checkpoint

At this checkpoint, exact-head PR CI and parent review were still required.
The validation run performed no workflow-scope bypass, issue closure or remote
merge. Later [Angular reference qualification](angular-reference-workflow.md)
records the complete signed application, Wasm SSR/client and protected T1
integration; it does not change this earlier Node-rendered browser receipt.
No reconnect-flood fairness, arbitrary HTML sanitization, automatic secret
classification or browser user-authentication guarantee is claimed.

## Feedback Report 2 response-policy observation, 1 October 2026

The registered `http-response-policy` selection passed against the clean native
source `4229d1a9e8ab8028793fccaba643b8e278223dda`. It executed the actual catalog-published
public component, 15 negative output vectors and successful later output. The
reachable 65-header case records the admitted activation's nonterminal
`OutputValidation / HttpResponseRejected` diagnostic through both tenant-scoped
root and tree inspection. The unchanged 16385-byte value instead crosses the
WIT codec's 4096-item bound before HTTP validation and remains a guest trap;
its producer-diagnostic propagation is a separate followup, not an HTTP reason.

Both registered `browser-boundary` cases passed with browser runner source
`9191e7b9422b635f98e158b53642a107fe773ef9` and the same native artifact. The only
change after that native build is the browser runner's absent-or-empty Referer
oracle; no native, component or controlled Angular build input changed. This
bounded observation used Rust 1.97.1, Node 24.19.0, Angular 22.2.0 and Chromium
153.0.8010.12 on Linux x86-64. It verifies actual shared ingress, cache-input
handling and no-store responses, reserved-header rejection, later successful
output, strict CSP and synthetic-token navigation/fetch behavior.

The public-application receipt's relevant fields are:

```json
{"browser":"153.0.8010.12","publicApplicationQualified":true,"applicationComponentInvoked":true,"fixedSameOriginReferrerPolicy":true,"buildTimeNoReferrerBeforeResources":true,"syntheticTokenNavigationAndFetchDoNotBecomeReferrers":true,"consumedTokenRemovedBeforeApplicationFetch":true,"noReferrerSameOriginPostQualified":true,"noReferrerPostOrigin":"same-origin","noReferrerPostStatus":200,"opaqueOrigin":{"outcome":"browser-policy-blocked","documentOrigin":"null","requestOrigin":"not-observed","requestMethod":"POST","status":null},"applicationCacheInputQualified":true,"reservedHeadersRejectedAndRecoveryQualified":true,"errors":0}
```

The opaque data document encountered a verified browser policy failure without
an exposed response. The exact journal count of 13 proves it did not start a
guest, but this observation does not establish a node 403 or whether the
request reached the network. Native literal-null Origin denial remains separate
wire evidence. The ordinary no-referrer POST preserved a same-origin Origin
and emitted no nonempty Referer. The supported application helper retains its
explicit same-origin unsafe-method policy after removing the consumed token.
Canonical signed asset navigation followed by browser history supplies the
query-bearing document source; direct query-bearing asset navigation remains
unsupported.

| Preserved artifact or log | SHA-256 |
| --- | --- |
| Actual public component | `4955a2cb884b5585c10da5e8011abee7ceafea64af399204273a20a7c8822bdf` |
| Registered response-policy pass log | `c57fa5d68995d9128577fc4054f56df887035b19f15bda35389aa91dfa481411` |
| Registered browser pass log | `29b96ea5690c28150b5ca958a744d7d3c76c2cc3460bf896fc308e16e2718b22` |

Earlier failed attempts are retained: query-bearing immutable asset navigation,
an incorrect empty-502 assertion, header-name casing, the codec/HTTP diagnostic
distinction, the browser's Origin tuple and its empty-string Referer exposure.
Product failure bytes, value bounds and CSP/CORS/private-network policy were not
changed to make those checks pass. The existing test-authority and root-browser
sandbox limitations above still apply; current-head required CI and the typed
codec producer followup remain separate gates.

The producer followup subsequently passed the maintained `http-response-policy`
selection at clean source `47d9f8b7da59205154b60eccf662391bb64697a3`, with all 15
negative vectors. The 16385-byte vector remains `GuestTrap` and now retains its
producer-owned terminal `Execution / ValueAllocationLimit` observation; profile
and numeric measurements remain absent. The 65-header vector remains completed
execution with the nonterminal HTTP rejection observation. Both are verified
through the actual authorized root/tree journal, with no debug-string inference,
HTTP relabeling or changed codec limit. The new pass log SHA-256 is
`e9ba8142a0fc58e3933d88638b151980d537b42b7641be3eb53c09b9c895c739`.

The same source-matched all-feature native target passed the exact registered
static routing/cutover case after using the real returned root GET/HEAD trigger
generations. Its Cargo pass log SHA-256 is
`7ad3e8998f18461c9fb08413112d08104d64b0d5b04dfa056996d83ae93b556d`.
A preceding generic `tools/test.py` invocation refused that runtime owner and is
retained as `not-run`; it supplies no pass evidence. The registered response
policy selection used its required maintained artifact runner. Current-head
required CI and parent review remain delivery gates.
