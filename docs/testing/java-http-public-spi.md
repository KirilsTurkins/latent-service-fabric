# Optional Java public HTTP SPI qualification

The maintained `http-request:6.0` JAR exposes the public
`HttpRequest.ConnectionFactory` and `setConnectionFactory` APIs. This optional
guest fixture implements that API and delegates to ordinary
`URL.openConnection()`. It neither calls a typed LSF transport nor installs a
host provider. Its source is [the pinned 6.0 source](https://github.com/kevinsawicki/http-request/blob/http-request-6.0/lib/src/main/java/com/github/kevinsawicki/http/HttpRequest.java),
SHA-256 `5139810792a0f7cff2de9c4a7d2399ece3201e1d349595adaf3221af0b43a43a`.
The unchanged original JAR uses the normal resolve/review/capture and offline
build path, with the same three-JAR closure as the default-client fixture.
No maintainer registration, dependency-coordinate exception or library fork is
required. The separate [default-client campaign](java-http-phase-timing.md)
provides the evidence for ordinary clients without injection.

## Actual signed result

[Run 39499576837, job 118893355381](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39499576837/job/118893355381)
completed **SUCCESS**. The six mandatory signed calls passed:

| Case | Observed result |
| --- | --- |
| Public factory delegates to ordinary URL connection | `1:spi:200:7:1` |
| Fresh invocation retains the untouched library default | `1:spi:200:7:0` |
| Optional factory selects a denied alternate destination | `1:spi-error:permission-denied:1` |
| Optional factory attempts a reserved credential header | `1:spi-error:invalid-request:1` |
| Public reset-to-default operation | `1:spi:200:7:0` |
| Fresh default invocation after the errors | `1:spi:200:7:0` |

Two missing-authority controls refused before guest work. The real peer recorded
exactly four primary HTTP contacts, zero alternate contacts or mutations and
zero remaining connections. Every call binds the full signed revision and
retires all active physical owners. The raw final node record is clean and
reaped; cumulative audit counters are not claimed to be zero. Leaving only the
pure factory reference installed in the first activation makes the next fresh
default call a concrete static-state reset check. The factory retains no
connection or credential.

The [source-specific receipt](evidence/java-http-public-spi-signed-2026-10-20.json)
records all six raw case identities, the component, final peer/shutdown records
and source differences. Artifact `12300055737` is 136,464 bytes with SHA-256
`6b46c8ff132f79f12eafa95fc091a9bf6f5776bb49df8834d443ea0c600f9853`;
all 110 members passed CRC and SHA verification.

## Compilation and replay attribution

The component was compiled normally at source
`e1c33adb2414a8371026d479600e08d48b6df88a`: 6,410,239 bytes, SHA-256
`07012456a9e874e13f639dfff7f93fc5823cfebffb79a35585548e663d12da25`.
Its original run `39494971018` remains failed after the first actual guest
success because the result reader incorrectly required a string outbound count.
The corrected reader accepts the actual integer/u32 outbound schema and retains
strict fuel, authority, result, revision, contact and retirement checks. The old
failed artifact and receipt were not rewritten.

Replay source `afe80e8322b1899c37d9f0f8240721d1c097c64d` authenticated the complete
original artifact, restored its 55 bounded build/package members and checked
199 SDK files, 73 effective recipe files and 110 campaign materials before and
after use. Only the explicitly reviewed reader correction differed. It freshly
signed the original component and ran the six cases; it performed no guest,
native Cargo, JDK or toolchain compilation.

The native products are the authenticated historical
`f9192fb5785ca7bed8b33dbb869b3d775b72ab4b` tuple (Wasmtime 48.0.6).
The production union also contains later Wasmtime 48.0.7 pins and immutable
resource-stream changes. Their exact file deltas are recorded in the receipt;
this result does not claim current .7 execution or execution of those new
resource paths. The normal SPI qualifier still requires full f919 source
equality and therefore refuses that changed current source. Selecting and
qualifying a current tuple remains explicit future work, not an implicit
historical-receipt substitution.

## Tooling and remaining scope

The default-false `java_http_spi` workflow selector supplies a separate normal
capture/build/sign programme. Removing that selector, its two exclusions and
copied job restores the old Java authoring workflow. The owning focused Java
workflow exposes the same programme. Original default-client jobs and their
commands, guards and limits remain unchanged. SPI is never substituted for
default-client evidence.

This programme uses explicit 64 MiB operator and node component-input ceilings
(the latter derives a 68 MiB management request ceiling). These are input limits,
not execution or provider budgets; original guest, pool, cell and cache budgets
remain unchanged. The public node record projects the actual selected ceiling.

The same-node twelve-case [tenant programme](java-http-tenant-isolation.md)
remains incomplete: cold preparation outlasted the original activation/control
request deadline before any HTTP contact. This SPI programme gives no
cross-tenant credit. The mixed HTTP limit/lifecycle requirements and broader
#688/#741 remain open. It introduces neither HTTP aliases nor shared credentials.
