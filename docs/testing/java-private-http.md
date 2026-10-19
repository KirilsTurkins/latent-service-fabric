# Captured private Java HTTP callers

`tools/qualify_java_private_http.py` adds an outside-checkout private/local-JAR
programme for [#688](https://github.com/KirilsTurkins/latent-service-fabric/issues/688).
The library uses ordinary URL/HttpURLConnection factories, request/body APIs and
close; its transitive helper loads an immutable bundled resource. Neither JAR
imports an LSF class, installs a connection factory or supplies a transport.

One explicit `javac --release 17 -proc:none` acquisition produces both original
JARs without running their initialization. Two applications select four different
local dependency identities using normal add-local, resolve and exact review.
The accepted primary-to-child edge and original JAR digests are checked. Missing
and tampered transitive objects must refuse while retaining the accepted lock.
The complete original source/class/JAR directory is then removed before either
component build.

Both builds use the maintained compiler and an explicit verified read-only
compiler cache. No missing-cache acquisition fallback is enabled. The original
SDK lock, current recipe/compiler identities and selected transitive resource
remain bound. No compatibility catalogue data is an input to the staged project
or selected recipe; unknown coordinates do not alter SDK/compiler/backend code.
This records catalogue absence, without claiming deletion of unrelated data.

Each actual component must pass all thirteen existing signed/admitted ordinary
provider cases, including HTTP errors, truncation/oversize, early close, denied
headers/targets, uncertain POST without replay, direct factory and fresh state.
Both preflight grant refusals and every physical owner/cleanup check remain.
Each peer must observe exactly eleven requests, one mutation and no alternate
contact; both node and peer must be reaped with clean shutdown. Native products
are authenticated by their existing ordinary-default tuple and keep their own
source identity. A reused tuple is not described as fresh native compilation.

The enclosing deadline is 2,400 seconds. A component build retains its existing
900-second ceiling and each node gate retains its existing 300-second ceiling.
Neither new limits nor added authority are granted. The existing Java CI job
keeps its original 55-minute limit and every prior ordered step.

Five focused Python controls exercise real local capture/verification with
synthetic class headers, original-directory removal, transitive tampering,
forged/incomplete provider evidence and pre-effect platform refusal. These
source controls do not execute JVM bytecode or qualify a component.

The [focused hosted run39339203495/job118356258933](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39339203495/job/118356258933)
passed all 26 signed cases, four grant refusals and 26 physical retirement
snapshots across both fresh components, with clean/reaped nodes and peers.
Artifact `12228269186` (`sha256:47dc81be6f276f13a5a5f30ae9a1a143816d5a94d7307768cd1c32f7c0274fa1`)
binds feature source `0c869e3912244b798131403c683a0901fa2220e5` and diagnostic
fixture source `d26b10b94c257c30058757b7d65bc0bb552d33d6`. Its fixed public JSON
records were independently checked, including both identical compiler inventories.

The focused replay authenticates four helpers compiled at `03a3f74598f2abfd0224169ae2871818f6c8419d`
and an ordinary-default, features-empty host compiled at `e97d44ddc744c9bd738d9b3b7a7d8b7234133e36`.
It does not recreate a production native tuple or claim current native compilation.
The development integration preserves all Java recipe/compiler/qualifier bytes;
the incoming workspace `Cargo.toml` differs from the captured SDK source used
by the passed components and retains that source distinction.

This programme does not qualify a second independently published HTTP client,
HTTPS certificate APIs, separate connect/read timeouts, new redirects/cookies/
proxies, concurrency or the whole #688/#741 tickets. Their remaining literal
requirements stay open.
