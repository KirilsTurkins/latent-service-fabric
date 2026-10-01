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
browser suites remain required. All five suites run concurrently with separate
servers, browser processes and evidence directories. Source-path validation still checks
every component for symlinks, final containment, size and case; Linux's exact-case
lookup avoids repeatedly enumerating entire directories for each document/link.
Windows retains explicit casing checks. Plugin factories share the current
configuration's prepared corpus instead of independently rebuilding it. Markdown
syntax parsing uses a bounded process-local cache keyed by exact body bytes and
format; each caller receives a separate mutable tree. File reads, path checks,
front matter, link checks and changed-example checks still run on current inputs.
Neither preparation nor parsed syntax is persisted across website commands.
The site does not display last-update metadata, so eager Git history scans stay
disabled. Windows retains the existing HTML minifier because its native SWC
cache can reject host ACLs; Linux CI uses the accelerated native HTML minifier.

The full Rust job has seven required matrix lanes: checks, workspace tests,
providers, public renderer, actual Angular, publication workflows and Angular T1.
Each runtime lane runs the unchanged all-target/all-feature Cargo producer on its
own checkout and verifies its fresh inventory. Complete workspace discovery,
ordinary tests, doctests and signing compatibility remain in the tests lane.
Physical qualification owns a separate runner from renderer/provider execution.

Repository contracts use seven required variants: the complete Python suite,
bindings, runtime components, standalone workflows, six-language SDK providers,
Phase 1 measurement smoke and optimization smoke. Python owns a checkout without
concurrent native fixture writers. Native variants rebuild their fixtures and
retain the same exact cases; collectors retain their frozen override rejection.
The local `tools/validate_contracts.sh` command still runs all validation by
default, and an unknown lane fails. Both matrices disable fail-fast, so every
selected obligation is attempted and every failure reaches `CI result`.
The profile selector fetches complete Git ancestry and trees with only its
catalogue, Cargo manifests and Rust source blobs. Offline change classification,
mode checks and reverse-dependent selection keep their existing behavior. The
result aggregator checks the same complete job contract from a catalogue-only
checkout, avoiding a second download of irrelevant frozen binary fixtures.
Rust workspace checks, independent production features, Clippy, doctests,
compatibility negatives, provider integrations and physical resource probes
retain their command vectors and profile selection. The two protected result aggregators and
the existing manual scale/resource options retain their required behavior.

The first optimization's warm PR run
[36912666227](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36912666227)
completed the Rust job in 29m 58s and the website job in 7m 39s: reductions of
19.4% and 71.7% against the job baseline above. Its contracts job failed, so it
does not establish a successful total-pipeline speedup. The required matrices
address the remaining serial critical path; their complete warm duration still
needs a successful remote measurement.

After merging, measure a development cache seed and a subsequent full PR run.
Use Actions job/step timestamps and renderer receipts to compare the same
selected profile. Report total time from workflow creation to its final required
result separately from execution time. Older queued runs continue to use their
old workflow revision until their branches incorporate this development change.
