# Java preparation and activation diagnostic program

Issue #709 still requires measured composed overload, guest exhaustion, provider
timeout, paging, retention expiry and concurrent inspection evidence. The
collector in `tools/qualify_java_preparation_diagnostics.py` prepares review
inputs and executes the existing Java composition owners in two separate steps.
Its source tests validate refusal and ownership controls; they do not qualify a
Java component, native node, packaged installation or any runtime scenario.

The explicit native path retains three independent identities:

| Input | Required observation |
| --- | --- |
| Six native executables | Original qualified native receipt, clean source commit/tree, original vector results, exact sizes and SHA-256 values, and ELF headers |
| Four Java components | Actual successful compiler command receipts, original source/build observations and exact component bytes; source capture remains nonhermetic |
| Collector | Exact entrypoint and composition-owner bytes, recorded separately from the native and compiler producers |

The authenticated packaged #710 entrypoint remains
`tools/qualify_packaged_java_composition.py`. Bare native executables cannot be
substituted into its authenticated installed runtime. Original producer #761
compiler tools can be retained as compiler materials; their old policy approval
does not approve a new native runtime, collector or capability policy.

## Prepare the original inputs

Use the existing `tools.java_http_composition.build.compile_pair` owner with the
explicit `diagnostics=True` selection. It performs the original generation
checks, then adapts the fresh domain using the maintained `http-status.java`
template and gives the two adapters their declared child outbound allowance
before actual compiler capture. It writes `diagnostic-adaptations.json` next to
`builds/`. No old unadapted C4 or R5 build can satisfy this selection. The domain
declares one outbound request and each adapter two, with the original runtime
maximum two; these declarations do not grant provider access.

The existing native `capsule_authoring demo-sign-separated` helper accepts the
four completed build directories, assembles their real package inputs, creates
distinct ephemeral builders, and verifies the original package/evidence through
the ordinary enforced verifier. Its separate `policy.json`, exact public-key
and builder identities, original 30-minute proof expiry, package/evidence
inventories and `release-set.json` must remain reviewable. The collector checks
that every signed component/source association matches its original compiler
receipt. Publication still performs actual native package/evidence admission;
the Python association check supplies no trust or grant.

If using the retained #761 compiler bundle, first create independent single-link
regular-file copies of all three complete original inputs: the bundle manifest,
verification receipt and archive. Verify every original byte hash before secure
extraction. The historical single-link directory with no archive is incomplete.
Retain the actual selected JDK, Gradle, WASI SDK, bindgen and wasm-tools closure
and fresh compiler command receipts. Missing materials require a new observed
build attempt; no success marker or receipt may be fabricated.

## Prepare without capability application

Run in a private, unprivileged Linux environment using Python 3.13.5. Mount the
original six native executables, compiler captures and signed releases read-only.
Use a fresh private output directory and the actual original qualified native
receipt, not a reconstructed metadata document:

```sh
python3 tools/qualify_java_preparation_diagnostics.py prepare \
  --native-directory /native/results \
  --native-receipt /native/verified-native-receipt.json \
  --builds /inputs/composition/builds \
  --releases /inputs/releases \
  --output /work/diagnostics
```

Preparation uses at most one live node and the original shared bounded provider
peer. It publishes the supplied signed fixtures using ordinary receipt-bearing
operations, reads their original catalog records and actual installed provider
identities, and reads current policy absence. It applies zero capability policies
and invokes no guest or provider business request. It positively stops and reaps
each node and the unused peer before producing `candidate.json`; missing clean
physical-retirement observations refuse a successful candidate.

The native release catalog uses content-addressed hardlinks. Before an actual
candidate is reviewed, its retired private store also needs a complete bounded
capture through the shared preparation owner: every observed inode's link count
must equal all of its paths inside that same protected root. External links,
unsafe ancestors or changes during capture refuse preparation. The strict
single-link rule for supplied compiler and signing materials remains separate.
The collector consumes the maintained descriptor-anchored storage scanner after
the node is reaped, retains the complete bounded inventory beside the candidate,
and verifies the same private-store digest before execution. These source checks
do not themselves establish an actual candidate or runtime qualification.

The default program has two sequential retained catalogs: former preparation
profile and current profile. Each requires eight initial records, derived from
actual installed provider profiles/digests/epochs and original publications:

| Records per catalog | Purpose |
| --- | --- |
| `clockMonotonic-installed`, `clockMonotonic-allow` | Original monotonic provider binding and operator/trigger/source-service scope |
| `clockWall-installed`, `clockWall-allow` | Original wall-clock binding and the same bounded caller scope |
| `java-domain-installed`, `java-domain-allow` | Original local-service binding and exact selected domain publication |
| `java-domain-http-timeout`, `java-domain-http-timeout-allow` | Actual shared HTTP provider binding and one GET to the retained peer's exact `/allowed` endpoint |

The current catalog also requires four explicit revisions: wrong source-service
clock scope, exact clock restoration, empty local-service rules and exact service
restoration. Expected generations are retained as 1, 2, 1, 2. The default total is
16 initial applications plus four revisions. Signing policies are separate. All
policy files are the exact compact bytes used by the existing policy writer;
their raw sizes and SHA-256 values are in the candidate. No template hash, config
declaration or copied policy acts as authorization.

The original outer deadline is 900 seconds from preparation and cannot be renewed.
Execution requires the same Linux boot, original output/config/catalog,
publications, provider profiles, fixed recipient port, policy absence, source
bytes and supplied materials. Approval must arrive while enough of that original
deadline remains for the runtime program and actual 120-second retention expiry.
Expiry or drift requires retaining the failed attempt and preparing a new
separately reviewed candidate; execution never silently rebuilds or refreshes it.

## Execute only the reviewed candidate

After independent review and explicit approval of the exact raw `candidate.json`
hash, execute the unchanged candidate:

```sh
python3 tools/qualify_java_preparation_diagnostics.py execute \
  --native-directory /native/results \
  --native-receipt /native/verified-native-receipt.json \
  --builds /inputs/composition/builds \
  --releases /inputs/releases \
  --output /work/diagnostics \
  --approved-candidate-sha256 ACTUAL_APPROVED_64_LOWER_HEX
```

There is no automatic approval, mutation retry, deadline renewal or disposition
inference. The partial `prepare --without-former-child-case` selection explicitly
omits the early real-child criterion and cannot establish the complete program.

| Required runtime observation | Existing owner and refusal condition |
| --- | --- |
| Real child preparation before its first guest execution | Former-profile adapter invocation must create an actual correlated child whose terminal typed allocation proof has exact fixed/fuel/multiplier/bound/profile fields; a parent-only failure refuses |
| Current composed caller/grant denial and recovery | Original service admission and clock/service revisions, current deployment rebind operations and fresh composition; no reused stale deployment or synthesized root |
| Guest fuel exhaustion | `resource_diagnostics.fuel`, original narrowed request budget and finite Execution/GuestFuelExhausted reason, actual final consumption and physical release |
| Queue pressure | `resource_diagnostics.queue`, original two cells, disposable queue 4 to 1, actual held parent/child plus waiting root, exact Admission or Queue/QueueCapacity reason, original cancellation and zero queued consumption |
| Provider timeout | `provider_timeout.qualify`, finite Provider/ProviderDeadline observation, actual recipient-received GET, original socket-close marker, fresh success and zero provider counters; external mutation disposition stays unknown |
| Authorized paging under new admissions | `history_diagnostics`, page size 1, at most four pages, real root/child IDs, original cursor membership excludes the later HTTP root |
| Tenant and management isolation | Foreign tree cursor and roots return no retained records; invoke-only credentials are denied; observations acquire no execution owners |
| Concurrent readers and expiry | Two supported read-only CLI readers under the same original deadline, then the actual unchanged 120,000-ms terminal retention expires the original cursor into explicit unavailable history |

Each page is limited to 64 KiB, cursor to 160 ASCII bytes and identifier to 512
UTF-8 bytes. Outcome progress is permitted between pages; membership remains
pinned. The peer retains its original 32-request ceiling, one attempt per send,
and lifetime clipped to the original owner deadline. No new dispatcher, provider
pool or diagnostic runtime is created.

The final collector keeps `allAcceptanceCriteriaPassed=false` and
`packagedDistributionQualified=false`. A successful runtime scenario program is
evidence for its measured cases. Issue completion still requires review against
every #709 requirement and current CI, including safe generated-client/public
projection and immutable runtime/guest provenance. Neither an expired journal
entry nor a clean local teardown proves an external mutation's disposition.
