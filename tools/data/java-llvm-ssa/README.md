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
including workflow setup, and two build jobs. It authenticates both fixed
official archives before tar access and checks the whole source tree without
ignored paths before and after compilation. No LLVM or guest compiler build
has yet qualified this candidate.

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
