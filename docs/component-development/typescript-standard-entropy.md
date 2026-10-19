# TypeScript standard entropy boundary

The maintained compiler supplies ordinary `Math.random()` beneath unchanged application and captured dependency code. The exact declared `latent:random/random@0.1.0` graph selects `lsf-math-random-approved-v1`; no app callback, custom random wrapper, seed, ambient OS import or additional runtime is installed. An operator must separately bind and grant the existing approved random source. Otherwise `lsf-math-random-unsupported-v1` throws `unsupported:Math.random-without-approved-entropy` rather than returning the engine's deterministic fallback.

Each admitted call invokes `u64-value` exactly once and maps the high 53 bits to `[0, 1)` by dividing by `2^53`. The source must return an unsigned 64-bit BigInt. Existing host errors propagate unchanged; there is no retry, partial draw cache or error-derived value. `Math.random` is not a cryptographic API, and this profile supplies neither `crypto.getRandomValues` nor `randomUUID`. Each existing `u64-value` operation charges its original input/output bytes and random-provider/activation budgets. A policy that permits only eight aggregate input bytes authorizes only one draw.

The backend and guard run in the application realm after engine bootstrap. Compiler-host `Math`, stock Wizer/engine initialization, native engine-input envelopes, Fetch/Console profile selection and ABI grants remain independent. Before any nondeferred application initializer runs, the guard rejects a captured or direct snapshot-time call before requesting host entropy. Existing Console-selected activation initialization remains deferred to the first supported export; it may consume admitted entropy at that point. Entropy alone does not generalize this deferral or promise that every top-level random-using package can initialize. A snapshot-time unsupported error is a concrete compatibility boundary, not a frozen random value or successful initializer.

The captured SDK recipe contains `entropy.mjs` and `entropy_profile.py`. `typescript-entropy-selection.json` records the exact profile, required interface digest, backend and snapshot-guard digests, unchanged-engine boundary and unknown qualification. That selection is both a build-observation material and an immutable package asset, so profile/backend changes invalidate normal build/package identities. It records no entropy payload and grants no authority.

Focused controls execute the real adapter in Node, check exact high-bit conversion/fresh calls/error identity, refuse altered WIT width/error/async/version shapes and forbid caller-owned backend selection. An emitted-banner control exercises the maintained bundler through a deliberately small esbuild stand-in; it proves application scoping and snapshot refusal, not esbuild, Wizer, an emitted component or signed execution. Existing actual parser/esbuild Console controls retain their original pinned-tool requirements. Actual signed ordinary `Math.random`, missing-grant, budget and fresh-Store cases remain required before qualifying this profile or completing issue 681/685. No six-language facility or runtime lifecycle closure is claimed.


The additive owning campaign preserves the original75-minute TypeScript job,
all normal SDK/library/generator/Console commands and their budgets. It reuses
that job's authenticated current native five products and three unchanged
companions, compiling only a selected greeting and an unselected word-count.
The normal27 calls remain, followed by one before-guest RANDOM denial and six
strict outcomes: undeclared Unsupported, one draw,33 sequential draws,256 range
and high53-bit checks, original65536-byte provider exhaustion, and fresh state.
All34 outcomes require physical process retirement and clean node shutdown;
additional idle/provider snapshots follow every entropy case. No random
payload is exported. A local transitive source module exercises the standard
API; this is not published-npm-library acceptance or a crypto API.

The two shared scalar-owner production changes and native15 controls are the
same reviewed nonallocating-u64 fix as GoPR1132. Variable-length byte results
retain their old lifetime and limits. The actual Go native15 case passed at
`1cde96d92c`; the TypeScript owning job also selects all15 rather than assuming
source equality establishes its component campaign. Local source/Node/codec
controls and pending signed qualification are separate evidence.
