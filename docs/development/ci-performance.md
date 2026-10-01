# CI performance and coverage

The target is a complete required pipeline below ten minutes with warm dependency
caches. Queue delay and cold builds are recorded separately; a short timeout or
an incomplete test run does not establish that target.

The audit of successful full run
[36818485654](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36818485654)
on 1 October 2026 found these job durations, excluding queue delay:

| Job | Before optimization |
| --- | --- |
| Rust 1.97.1 | 37m 12s |
| Repository contracts | 24m 41s |
| Documentation website | 27m |
| SDK surfaces | 5m 8s |
| MSRV | 2m 23s |
| Catalog | 2m 44s |
| OCI registry | 1m 45s |

The renderer lane receipt attributes 149 seconds to SSR, 331 seconds to generic
Angular cells and 169 seconds to actual Angular runtime execution. Optimizing
the third-party host compiler addresses that work without omitting any fixture
or changing guest fuel, memory, deadlines, admission or cancellation policy.
Removing debug sections also reduces links and repeated executable hashing.

[Shared dependency caching](ci-caching.md) reduces repeated compilation and
per-PR storage churn. Cargo still checks current sources, feature selections,
targets and toolchain identity. Test inventories, test results, signed packages
and qualification receipts remain fresh outputs of the current run.

Website builds use Docusaurus 3.10.2's stable Faster implementation. Both base
paths, every maintained version, the isolated two-version fixture and all five
browser suites remain required. The fixture build overlaps production browser
journeys with at most two suites active. Source-path validation still checks
every component for symlinks, final containment, size and case; Linux's exact-case
lookup avoids repeatedly enumerating entire directories for each document/link.
Windows retains explicit casing checks. No validation result is cached.
The site does not display last-update metadata, so eager Git history scans stay
disabled. Windows retains the existing HTML minifier because its native SWC
cache can reject host ACLs; Linux CI uses the accelerated native HTML minifier.

The complete Python contract suite overlaps the independent native contract
build, and its failure propagates through the final join even if a build fails.
Rust workspace checks, independent production features, Clippy, doctests,
compatibility negatives, provider integrations and physical resource probes
retain their commands and conditions. The two protected result aggregators and
the existing manual scale/resource options retain their required behavior.

After merging, measure a development cache seed and a subsequent full PR run.
Use Actions job/step timestamps and renderer receipts to compare the same
selected profile. Report total time from workflow creation to its final required
result separately from execution time. Older queued runs continue to use their
old workflow revision until their branches incorporate this development change.
