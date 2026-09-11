# Benchmark evidence retention

The current checkout keeps optimization reports, aggregates, paired tables,
source identities, archive manifests, checksums and recorded validation receipts.
Historical optimization archive payloads, including the original Docker comparison,
have been removed to reduce checkout size. The Kubernetes comparison package is
retained; replay requires restoring its exact Docker dependency. Phase 0 archives,
Phase 1 evidence, measurement schemas and small regression fixtures are unchanged.

The [retention ledger](../../benchmarks/optimization/retention.json) lists the
24 compacted packages and diagnostic bundles, their removed payload sizes and Git
blob identities, and their original archive manifests. In total, 60 payload files
accounting for 2,438,191,603 bytes were removed from the current tree. Docker's four
parts account for 169,803,211 bytes; its reports, tables and original manifests
remain. The Kubernetes report includes the exact dependency restoration command.

Repository validation caps `benchmarks/` at 600 MiB. New optimization gzip payloads
and archive parts are ignored by default; keep raw runs and package staging under
`target/` or an explicit external artifact directory. Commit concise reports,
paired results, configuration and provenance. Retain a complete raw package only
when it serves a current reference or required regression check within the budget.
After a ticket is delivered, retire its temporary worktrees, unpacked duplicate
evidence and obsolete compiler caches. Keep the branch commits and selected results.

This is a storage change. Reported measurements and failed attempts have not been
reclassified. A recorded Linux or Windows replay PASS describes the validation
performed at publication; it is not a new replay of this compact checkout.
Manifests and checksum sidecars describe the historical package and cannot
replace its missing raw files. Archive replay of a compact report directory
therefore requires restoring the original payloads first.

All complete packages that preceded compaction are available in repository
commit [`a432c51f9ed0a4eaf55473d80122bbb8e5a419cf`](https://github.com/KirilsTurkins/latent-service-fabric/tree/a432c51f9ed0a4eaf55473d80122bbb8e5a419cf/benchmarks/optimization).
That is the storage revision, not a substitute for each report's measured
control, candidate or harness revisions. Original manifests bind the exact
package members and compressed stream. Links to removed archive payloads in
historical reports point to this fixed revision.

## Restore one package for replay

Select the exact package directory named in its report. Restore it to a fresh
directory outside the source checkout; there is no need to restore every
benchmark. The following Bash example restores the catalog-memory package:

```sh
set -euo pipefail
storage_commit=a432c51f9ed0a4eaf55473d80122bbb8e5a419cf
package=benchmarks/optimization/catalog-memory/2026-09-10-container-linux-96716c8/catalog
restored_root=../benchmark-raw

# Only fetch the commit when absent; defer unrelated historical blobs.
git cat-file -e "$storage_commit^{commit}" 2>/dev/null || \
  git fetch --filter=blob:none --depth=1 origin "$storage_commit"

# Fails if the chosen destination already exists.
mkdir -- "$restored_root"
git archive --format=tar "$storage_commit" "$package" | tar -xf - -C "$restored_root"
python3 tools/validate_phase1_archive.py "$restored_root/$package"
```

Run the command from the repository root with the documented Python dependencies.
Use sufficient temporary disk space for bounded extraction. For reports with
multiple packages, restore each named subdirectory into the same fresh
`restored_root` before running their separate validators. The report's replay
commands use this variable to locate restored packages. A diagnostic package
that originally failed qualification remains a failed diagnostic after restore;
follow its report's exact historical verifier instructions.

The existing validators continue to require the complete raw graph, original
hashes, source and process associations, outcome populations and cleanup proofs.
Missing payloads are not accepted as successful validation. Reproduction from
source is a separate new measurement: use the report's exact measured revisions
and recipe, retain the new run's identity, and do not label its results as the
historical observations.

Removing payloads from the current tree does not erase their Git history or
shrink an existing clone's object database. No history rewrite is part of this
retention change.
