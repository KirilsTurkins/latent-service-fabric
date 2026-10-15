# Installed Java library input controls

The [installed-input qualifier](../../tools/qualify_java_installed_dependencies.py)
runs using the delivered isolated Python and compiler recipe, outside a checkout.
It consumes an already extracted, verified local developer-tools candidate and
an application with its reviewed dependency CAS. Candidate extraction and
publisher authentication retain their normal independent boundaries; this
control does not authenticate a publisher or publish a release.

Run in a fresh Linux container with networking disabled, user 1000, and the
candidate and installed tools mounted read-only. Mount only the qualifier file,
not a checkout. The private work directory must contain `attempt/app` with the
captured application and CAS, an empty `attempt/build-cache`, and private `home`,
`tmp` and `outside-checkout` directories. Original local JARs and private resolver
credentials are unnecessary for this build.

```bash
"$INSTALLED/sdk/bin/python" -I -B /qualification.py \
  --work /work --installed "$INSTALLED" --candidate "$CANDIDATE" \
  --expect-source "$CANDIDATE_SOURCE" \
  --expect-archive-sha256 "$CANDIDATE_ARCHIVE_SHA256" \
  --expect-component-sha256 "$PREVIOUSLY_QUALIFIED_COMPONENT_SHA256"
```

The maintained pure-library fixtures use Commons Codec 1.17.1. This control
verifies the captured graph, builds using only the shipped compiler inputs, and
requires the emitted component to match the caller's prior qualified component.
It then updates Codec to 1.17.2 and removes it through the normal installed Java
CLI. Each edit must invalidate the capture before compilation, retain all
accepted native/closure/SDK locks, and require fresh resolution and review.
Normal `add` must restore the same declarations. If removing and adding a
coordinate changed their order, status must still deny the reordered
configuration. The control then restores only the exact original configuration
bytes verified before the test, and rechecks the original captured identity.
This is an invalidation roundtrip; it does not resolve or deploy the new version.

The [15 October public/private observations](evidence/java-installed-library-inputs-2026-10-15.json)
bind the candidate, qualifier, compiler outputs and byte-identical components.
Their candidate has `publisherAuthenticated=false`. Signed component execution
and failure recovery are recorded separately in [PR #1006](https://github.com/KirilsTurkins/latent-service-fabric/pull/1006)
and authenticated private-feed ingestion in [PR #1001](https://github.com/KirilsTurkins/latent-service-fabric/pull/1001).
Authenticated frontend watch and deployment of a newly reviewed version remain
separate acceptance work for #682.
