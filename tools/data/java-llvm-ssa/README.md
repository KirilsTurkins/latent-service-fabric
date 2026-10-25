# Pinned LLVM SjLj source backport

This directory contains source inputs for a compiler candidate. It does not
contain or qualify a compiler binary, Java component, runtime, GC, or service.
The normal Java compiler remains the original official WASI SDK 29.

`patch.json` binds four complete LLVM 21.1.4 preimages and outputs. Its utility
changes come from upstream commits `0e025418`, `f140491d`, `23f6a8ae` and
`ca9f43fe`; the only LSF caller change selects
`RewriteAndOptimizeAllUses(DT)` in Wasm SjLj rebuilding. An unrelated upstream
`llvm::find_if` style edit is excluded. Every original source license header is
preserved; [LICENSE.txt](LICENSE.txt) is the pinned LLVM license.

`tests.json` preserves all thirteen original SjLj regression files at commit
`222fc11f2b8f25f6a0f4976272ef1bb7bf49521d`. The complete nine-case
`SSAUpdaterBulk` unit group and the original dedicated PHI regression through
SjLj, WinEH, verifier and instruction selection are mandatory. Controller tests
with synthetic XML/IR are explicitly source checks, never execution evidence.

The fixed source-branch push `java-llvm-ssa-producer.yml` programme has one
90-minute budget,
including workflow setup, and at most four simultaneous Ninja commands.
It authenticates both fixed
official archives before tar access and checks the whole source tree without
ignored paths before and after compilation. No LLVM or guest compiler build
has yet qualified this candidate.

The first build completed in 3,357.75 seconds and passed all nine SSA units,
then lit refused its missing `llvm-config` prerequisite before running the
thirteen regressions. Adding that build target corrected the harness, but the
next build reached its original 3,600-second command deadline before tests.
Its Ninja progress was not retained; no unfinished target or compiler defect
is inferred. Both failed artifacts remain separately attributed.

The selected LLVM build command now has a 4,500-second maximum within the same
5,400-second aggregate. These maxima are not additive: each command is clipped
to the remaining total budget. The shared trusted-build operational maximum
admits this duration; other callers retain their existing selected timeouts
and defaults. All tests, disk and product bounds are unchanged.
After the original owner cleans up, a bounded Ninja v7 log reader retains only
completed-prefix counts and fixed logged-target flags in command metadata,
including failures. It reads at most 4 MiB/16,384 rows/4,096 bytes per row.
Counts are not a planned-edge total, percentage, successful compiler or test
claim. Unknown, malformed, partial or over-bound logs report incomplete data;
the original command failure remains decisive. No raw build log, output path
or failed compiler binary is added to artifact retention.

All three earlier attempts used two build jobs. The third reached the reviewed
4,500-second build limit before units or lit; its complete logged prefix had
3,162 unique outputs, 782 Clang object rows, no UtilsTests object rows and no
fixed linked-target flags. These are not a percentage or planned-edge total.
All seven host-tool identities and the configure argv matched the earlier
attempts; actual CPU/RAM measurements were not retained. Runner capacity
variance is therefore an inference, not a measured cause or compiler defect.

The selected build now uses four total Ninja jobs with a four-job compile pool
and one-job link pool. A linker occupies one of the four slots; it is not an
extra fifth job. Installation remains at two jobs. These are supported LLVM
Ninja pool settings, not compiler optimization changes. After configure, a
bounded 1 MiB cache reader requires the exact generator and pool values.
The 4,500/5,400-second maxima, all tests, guest flags and product bounds remain
unchanged; another failure never starts an automatic retry.

The four-job attempt completed the LLVM build in 3,860.83 seconds and passed
all nine SSA units. Lit then refused its per-test timeout during configuration
because this Python environment lacked `psutil`; no regression case executed
and no compiler carrier qualified. The failed run and its raw observations
remain separate from later attempts. The owning workflow now installs the
single hash-locked Linux ABI3 `psutil` wheel before the producer. A same-Python
preflight checks the exact version, native extension availability and the APIs
used by pinned LLVM lit's Linux timeout path before archive acquisition.
The original 60-second per-test timeout, all thirteen lit cases and all other
bounds remain unchanged. This prerequisite correction is not a compiler or
Java component qualification.

Before acquisition, a bounded Linux reader records CPU affinity/process CPU
count, physical total/available memory and current cgroup v2 ancestor limits.
The operational preconditions are four effective CPUs, 12 GiB effective total
memory and 10 GiB available memory. Kernel text reads are limited to 64 KiB for
meminfo, 4 KiB for each other file and 32 cgroup path components; no host path
is emitted. Insufficient or unsupported facts refuse before acquisition, with
the observations retained. There is no fallback runner, system cleanup or
hard RSS quota. Neither these preconditions nor the advertised public runner
class prove memory fit, peak RSS or successful compilation.

Before any acquisition/build it measures at least 18 GiB free on the owned
filesystem and requires case-sensitive paths. It refuses insufficient space;
it never removes system SDKs, installed tools or another session's files.
The owned tree has a sampled operational 16 GiB budget, 200,000 entries,
2 GiB per file and a 2 GiB free-space reserve. This is not a hard filesystem
quota: trusted children can transiently cross the budget between bounded
ten-second scans. Only live-build samples tolerate entries or child directories
that disappear during atomic build renames; source inventories and pre/post
command checks remain strict. Root loss, permission errors and other failures
are never ignored. Source extraction is independently capped at 3 GiB with
256 MiB files; official SDK extraction at 2 GiB with 512 MiB files. All archive
members are checked before extracting source files. Published products must
remain within 2 GiB decoded, including their embedded closed manifest.
Distribution uses one fixed `derived-sdk.tar.gz` carrier that preserves exact
file modes and anchored relative symlinks; raw product directories are never
uploaded. The carrier is limited to 2 GiB minus a 64 MiB evidence reserve.
An always-run admission step checks the exact fixed receipts, XML, regression
files and command logs, including its own receipt, against that 64 MiB reserve
before allowing upload. The total selected carrier plus evidence is at most
2 GiB. Admission re-verifies the carrier's manifest, actual member hashes,
modes, links and source identity; a failed or partial compiler result never
publishes a compiler carrier. The decoded SDK bound and encoded carrier bound
are independent. Overflow, timeout, cancellation, skips, missing cases or
failed cleanup prevent publication; none triggers an automatic retry.

The derived compiler has a distinct version suffix and source/patch/material
manifest. Original SDK sysroot, runtime and linker members must remain
byte-identical. The compiler's ELF dependency must select its newly compiled
LLVM library through the ordinary relative loader path, without preload or
library-path overrides. Existing compiler consumers do not admit this new
identity; that is a separate review after a successful producer artifact.

The effect on the oversized public Java `pools` function remains unknown.
Original TeaVM `FULL`, Clang `-O2`, Java source, EH/SjLj/GC behavior, 64 KiB
stack, 64 MiB linear memory and 7,654,321-byte parser limit are unchanged.
