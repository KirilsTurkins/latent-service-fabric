# Installed C library qualification

`tools/qualify_c_installed_dependencies.py` verifies a local source-candidate C
archive through the normal bundle extractor, then uses its delivered Python and
authoring commands outside the checkout. Supply a readonly candidate directory
containing the archive, `developer-bundle.json` and the source-bound frontend
`helper.pyz`, plus an already captured and reviewed independent C project/CAS.
The exact candidate commit and archive digest are mandatory.

Run as UID1000 with a fresh writable work parent, no checkout mount and networking
disabled. The supported Linux host must provide Bubblewrap and permit its user/
mount/network namespaces. The captured compiler still runs under its existing
isolation; missing containment is a refusal, never a fallback. The compiler and
dependency graph come entirely from the candidate and captured inputs.

```bash
python3 /qualification/qualify_c_installed_dependencies.py \
  --candidate /candidate --capture /capture/project --work /work/fresh-attempt \
  --expect-source REVIEWED_FULL_COMMIT \
  --expect-archive-sha256 sha256:REVIEWED_ARCHIVE_DIGEST
```

The finite helper creates all six maintained templates, verifies the original
captured library closure, compiles through the installed recipe and exercises
normal update/remove/add commands. Every changed or reordered declaration must
refuse the old approval while preserving the SDK and accepted dependency lock.
Only restoration of the exact originally reviewed configuration bytes can revive
that old capture; semantic equality alone is insufficient. Failed attempts keep
their original outputs and do not retry a mutation.

The [October 16 source-candidate receipt](evidence/c-installed-library-2026-10-16.json)
records the exact compiler output, qualifier, archive, helper and observed command
outcomes. The compiler statement retains `packageAssembled=false`; signed-node
use requires the normal separate controller packaging/provenance join. A local
candidate has no publisher authentication or released-toolkit claim.

The separate [delivered signed-watch programme](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38934579272/job/117168617232)
passed at source `6bf3d5c357fb768357522e85f61282681bddd162`, tested merge
`b4ad3f25516e9b3a43d230928695a52756f011c6`. Initial, updated and removed library
selections each produced one successful deployment and post-deploy test. All
three workspaces completed normal clean shutdown with confirmed reaping and
zero watcher exit codes. Original outside inputs were removed before
compilation. Unreviewed dependency locks, missing recipe trust and changed
signed-workspace reuse were rejected before the corresponding deployment.

Its bounded public receipt binds the qualifier, input fixture, source probe and
explicit frontend helper. The initial component was
`sha256:79ee5ee8e14d80b51710a4582e8cf4486db09617dcde9d36ecabe15d9467bd4c`;
updated and removed component identities remain in the runner's private full
build/deployment receipts. This is an explicit signed source-candidate
qualification. The full requirements of
[#684](https://github.com/KirilsTurkins/latent-service-fabric/issues/684) also
consume the separate source/static-library and standard-facility evidence.
