# Pinned LLVM SjLj source backport

This directory contains source inputs for a compiler candidate. It contains no
compiler binary. Compiler artifact qualification is recorded separately below;
it does not qualify a Java component, runtime, GC, or service.
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
ignored paths before and after compilation. R7 qualified one source-built
compiler artifact; Java component assembly remains a separate qualification.

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

The next attempt built in 2,538.89 seconds and passed all nine SSA units and
thirteen original lit cases without skips. Its separate opt/WinEH/verifier
stage also passed, but the subsequent llc command lacked the explicit Wasm
EH/SjLj selectors required alongside `-exception-model=wasm`. It aborted before
instruction selection; no object, packaged compiler or Java component qualified.
That diagnostic command now selects both `-wasm-enable-eh` and
`-wasm-enable-sjlj`, matching the original mixed-EH/SjLj regression's llc RUN.
The EH selector also preserves the incoming invokes in the already transformed
cross-pass module. All source patches, mandatory oracles, guest flags and
bounds remain unchanged; this harness correction makes no size/profit claim.

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

The sixth attempt completed its build, nine units, thirteen lit cases,
opt/WinEH verifier regression, actual llc object and installation. Packaging
then exceeded the unchanged 200,000-entry budget while duplicating the SDK;
the packaged version command never started and no compiler carrier qualified.
Its actual driver readelf also revealed a missing install/package dependency:
the new driver needs both profile LLVM and clang-cpp shared libraries.

The delivery repair adds the original `install-clang-cpp` target and requires
the exact two profile DSOs plus at most six anchored aliases. Separate actual
readelf observations must bind the driver and both libraries, their SONAMEs,
directed dependencies and ordinary relative loader paths. Other dependencies
remain restricted to the existing normal seven-library host C ABI whitelist.
No preload, library-path override or unrelated SDK member change is admitted.

[R7 run 40174439697](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40174439697)
passed at source `4545bf149d8ea732e78c25509d5f90ffd16e3ad8`. Its 22 Linux
controller cases, nine SSA units, thirteen original lit cases, opt/WinEH verifier,
actual llc object, three ELF dependency checks and real packaged Clang version
all passed. The actual build took 2,341.620686 seconds. After original command
cleanup, 5,604 build entries were retired; final owned entries were 196,974 under
the unchanged 200,000 cap. Both final configuration files matched their initial
pre-build identities. No failed compiler artifact was reused.

Artifact `12593061730` is 167,405,228 bytes, SHA256
`7dffc969ad2f91ebc61126f5df0b15ba4a410733704a0abee5f60ce83ef7cb48`.
Independent cached verification authenticated 52 ZIP members, all 18 immutable
Git recipe inputs, 20 successful command records/40 raw channels, and all 10,713
typed tar members including modes and links. Decoded payload was 508,050,298
bytes including the manifest. The carrier is 159,518,361 bytes, SHA256
`07032a463018271517dd26fde68b99716937fa5e231c3430ace811f610ae0d37`.
The original SDK runtime, sysroot and lld members remain byte-identical.

Before spending on the build, strict source/SDK/header inventories project a
bounded final entry count. An independently authenticated metadata-only SDK29
census found 10,704 SDK descendants and 272 header-subtree entries including
its root. With the measured 175,211 source entries, two SDK trees and those
headers occupy 196,893 entries before the fixed roots/overlay/evidence margin.
The programme still checks its actual trees rather than trusting that census.
After all build/test/install/readelf commands complete and the original owner
reaps their process groups, only the fresh owned `build` child is retired using
Linux directory-fd operations. Original source, archives, SDK and installation
remain held. Two fixed raw configuration files (CMake cache and Ninja rules,
at most 1 MiB each) preserve the selected pools and identities. An exact path
union checks copy headroom before any products are written; final whole-root
counts still enforce the original cap. The bounded evidence allowance is 512
entries. This retires compiler scratch space, not a failed-artifact compiler
cache, and provides no Java/runtime qualification. Mandatory hosted Linux
source controls exercise real retirement before any compiler acquisition or
build; the Windows check only verifies unsupported-platform refusal.

The derived compiler has a distinct version suffix and source/patch/material
manifest. Original SDK sysroot, runtime and linker members must remain
byte-identical. The compiler's ELF dependencies must select its newly compiled
LLVM and clang-cpp libraries through the ordinary relative loader path.
The explicit compiler-only reader pins that exact successful source, run, job,
artifact, carrier, manifest and recipe together. It refuses historical failed
artifacts and arbitrary SDK roots. The existing public-fiber owning job can
select it only through `public_fiber_derived_llvm=true` at the closed consumer
feature ref; default selection remains false and the normal SDK29 gate is
unchanged. This separate programme retains TeaVM FULL, Clang O2, the unchanged
public Java/WIT, 600-second compiler command, 35-minute total, 64 KiB stack,
64 MiB memory and original parser limit. Its Java assembly outcome is pending.

The effect on the oversized public Java `pools` function remains unknown.
Original TeaVM `FULL`, Clang `-O2`, Java source, EH/SjLj/GC behavior, 64 KiB
stack, 64 MiB linear memory and 7,654,321-byte parser limit are unchanged.
