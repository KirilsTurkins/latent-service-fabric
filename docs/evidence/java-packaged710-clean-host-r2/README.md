# Original packaged authoring failure after installation

This attempt installed the authenticated approved runtime and Java tool bundle
through the supported native frontend. Adapter generation then failed before
Java compilation because the source conductor selected `wasm-tools` and
`wit-bindgen` through the clean host's ambient PATH. Neither program existed
there. The original bundle contains both pinned executables.

The corrected conductor validates the original tool inventory and passes the
two original SDK paths into adapter generation. Both existing version probes
remain mandatory. A changed executable fails inventory verification before
generation. The installed private workspace is still validated through its
original owner record. No global PATH, runtime limit or trust policy changed.

The retained [observation](observation.json), [environment](environment.json),
[process receipt](process.json), [stderr](qualification.stderr.txt) and
[stdout](qualification.stdout.txt) preserve this failed 299.43-second attempt.
The [retention receipt](receipt.json) hashes their original bytes. This evidence
does not prove guest compilation, node admission, signing, live preflight or a
successful clean-host Java campaign.

The conductor source was `a128d5172b9cafa91b394ab2786278796383e783`.
The unchanged approved producer was
`761172002e4a4d02102f8c757235b888fe4859e1`, with combined policy digest
`ce36420661807326255232c0542f334045af5a637a157ad3c99b7e77328ffcba`.
The original authenticated support and image inputs are retained with the
[earlier attempt](../java-packaged710-clean-host-r1/README.md).

The disposable Ubuntu 24.04.5 host used Python 3.13.5, glibc 2.39,
unprivileged UID 23001, two CPUs, 6 GiB memory and 512 PIDs. Its initial SDK
program check and workspace check were empty. Original publisher archives
were mounted read-only; no LSF native code was rebuilt. This campaign was
nonpublishing and its failed owned volumes remain retained.

The 35 focused Windows regression cases passed with three original platform
skips. Broader tool cases also reached the existing Windows symlink privilege
failure; that environment observation is not a Linux CI result. The new case
preserves all 26 earlier packaged probe identities and execution guards.
