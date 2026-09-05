# Phase 1 local trusted release catalog

The standalone Phase 1 node stores locally trusted capsule releases through `latent_artifacts::DirectoryArtifactRepository`. Registration is a persistence operation only: the repository has no dependency on the scheduler, cell pool, Wasmtime backend, listener stack, or service process model, and publication/lookup never instantiates, prepares, schedules, or assigns a capsule to an execution cell.

## Trust boundary

Phase 1 verifies the capsule manifest with the canonical bounded JSON codec and Phase 1 semantic validator, then verifies the SHA-256 digest of the transferred component bytes. The manifest component digest, `ArtifactDescriptor.release_digest`, and computed component digest must be identical. A disagreement is `corrupt-artifact` and nothing is added to the visible catalog.

Artifacts are **locally trusted input**. This catalog does not claim signature, provenance, SBOM, registry-authentication, or trusted-AOT verification. Those are Phase 2 concerns.

## On-disk layout

The repository root contains only two managed directories:

```text
<root>/
  releases/
    <64 lowercase sha256 hex>/
      metadata.json
      manifest.json
      component.wasm
      COMPLETE
  .tmp/
```

`manifest.json` is the canonical encoding produced by `JsonManifestCodec`. `metadata.json` contains the artifact descriptor and contract descriptors. `component.wasm` is retained byte-for-byte. A release directory is visible only when `COMPLETE` exists and the directory name, metadata, canonical manifest, component length, and component SHA-256 all agree.

The release digest continues the Phase 0/Phase 1 convention that the immutable release identity is the SHA-256 digest of the component bytes. This also makes manifest/component disagreement detectable before publication.

## Publication and crash safety

Publication validates all input before opening a visible release path. Files are written to a unique directory under `.tmp`, each file is flushed with `sync_all`, `COMPLETE` is written last, the temporary directory is synced, and the complete directory is atomically renamed into `releases/`. The parent directory is then synced. Readers use only the in-memory index of complete entries, so they observe either the old catalog or the newly completed release, never files from the temporary write.

Publishing identical content under an existing digest is idempotent. Different metadata/content under an existing digest is rejected. Concurrent publishers are serialized inside one repository instance; an external publisher that wins the final rename is accepted only if the resulting completed entry is byte-for-byte equivalent.

## Restart, cleanup, and rebuild

`DirectoryArtifactRepository::open` performs startup recovery:

1. Ensure `releases/` and `.tmp/` exist.
2. Remove abandoned `.tmp` entries. Temporary files are never catalog entries and are safe to delete.
3. Scan `releases/` once in deterministic path order.
4. Ignore directories without `COMPLETE`.
5. Fully validate every completed entry before inserting it into the index.
6. Reject startup if completed data is corrupt or the configured index bound would be exceeded.

The in-memory index is therefore rebuildable solely from completed on-disk releases. No directory scan occurs on normal `resolve`, `fetch` eligibility checks, or `list` requests.

To repair a repository after an operator has identified bad completed data, stop the node, move the affected digest directory out of `releases/` for forensic retention, and restart. To discard interrupted writes only, stop the node and clear `.tmp/`; startup also performs this cleanup automatically. Never edit a completed release in place.

## Bounded index and listing

`DirectoryArtifactRepositoryConfig` makes both memory/cardinality and response bounds explicit. The default maximum index is 250,000 releases and the default maximum list page is 1,000 descriptors. Opening or publishing beyond the index bound returns `resource-exhausted` rather than growing the index without limit.

`ArtifactRepository::list(after, limit)` is part of the repository seam so management and executor callers do not downcast to the directory implementation. Entries are returned in ascending release-digest order. `ArtifactPage::next_after` is the continuation cursor. The requested limit is clamped to the configured page maximum.

A 100,000-release dormant catalog therefore consumes only bounded catalog/index memory plus on-disk metadata/artifact storage. The catalog implementation creates no per-release process, worker thread, socket/listener, runtime instance, prepared component, or execution cell; any fixed node-owned helper resources must be measured and reported separately by node-level resource probes.
