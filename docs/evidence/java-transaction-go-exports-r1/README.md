# Go aggregate export type repair

The completed Go guest job [110383629373](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36866634936/job/110383629373)
failed while compiling the aggregate at PR #802 head
`46d5fb0c6a68ad1a1133cf99d31a83cd3a38d6b7` and tested merge
`34de611f3bc835f93d5fc0d5786b2a972021c70f`.
The original compiler stderr is retained in `component-build.stderr.txt`.
The artifact and full job log identities are recorded in `receipt.json`.

The authored Go export now qualifies its nominal request, result and error types
through the generated imported `api` package. The forbidden HTTP variant uses
the same source anchor. The original query view version and optional key version
remain unchanged. Ten authoring and workflow tests passed on the Windows source
controller. Fresh compilation and real signed node execution of this repaired
source remain separate checks; this receipt does not claim either one passed.
