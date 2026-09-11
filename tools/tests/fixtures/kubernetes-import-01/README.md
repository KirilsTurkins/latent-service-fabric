These files preserve original small metadata bytes from the first actual
Windows kind setup, owner `lsf-112-8c22b65b1529`, source
`82207b7eaa7176741392d0f69c11a41a466c537d`. No credentials or layer bytes are included.

The original root remains locally retained at
`target/phase1-extension/issue112-source-01/target/phase1-extension/issue112-setup-01`.

| File | Original member | SHA-256 |
| --- | --- | --- |
| cri-lsf.json | commands/24-import-lsf/stdout.bin | 81116dd6371069e9dbc4fbe27f2ab169be4387117494f700961b649260768856 |
| image-transfer.json | image-transfer.json | 2a43e970fadc715ac29992523e5e93d0c8574783d4f7a180b5e814498a09e3c3 |
| index.json | images.tar: index.json | 77bb5ae886bf776cccccf82443052741efb718fc84f414ddd1f3d0fe5956bc2f |
| cri-native.json | resume-01/commands/21-import-native/stdout.bin | ecd9a79f1acc34c01c98c0f5efaf11a687bc7a6ec5cce2a68d4026afe791757b |
| cri-client.json | target/phase1-extension/issue112-client-inspect-01/command/stdout.bin (MAIN repository) | 544e919363b4ab9996615089de3666f083985b410a837ae01c8af18402d9b322 |

The retained tar is 105,556,480 bytes, SHA-256
`67ec4c98376734a9357a28989390849ac2254886ef9aae0fdd8ba95dce1105f7`.
The failed verifier expected the selected original OCI manifest in CRI
`repoDigests`. Actual containerd reports the archive's OCI index digest there.
The index contains the exact original manifests; the CRI configuration and
uncompressed layer identifiers match the selected original image. Tests require
the exact root, selected manifest, configuration, and tag association.

The read-only resume at source `0f67f4dd5305d91877d3d2ed0dc4efe0a5e04dd7`
verified LSF, then exposed that native has an empty CRI `repoDigests` list.
A separately retained read-only inspection found the same empty list for client.
Their actual containerd tag targets are the original manifests. Tests require
that separate exact target plus the archive index membership and full CRI
configuration; empty CRI digest lists are retained as unavailable evidence.
