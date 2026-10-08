# Exact-source #710 packaged qualification review (ready for independent policy approval)

Repository: KirilsTurkins/latent-service-fabric
Source: 37b48cd8e485a826cd87e23aea184d99c17e4731
Frozen source ref: refs/heads/qualify/feedback2-packaged710-37b48cd8-20261008
Version: 0.1.0-alpha.5

The two exact candidate policies are in candidate-policies.json.
Raw SHA-256: 4ab98c833153bd9d9bb349a05aaa688f0d87394b8fb5afcdf185a158d1188658
Their workflow owners are developer-tools.yml and native-runtime.yml; purpose is candidate.
No approval from an older source, policy digest or environment is reused.

Developer source-named candidate workflow_dispatch: 37755336245.
Native development-test candidate workflow_dispatch: 37755350322.
Both runs completed SUCCESS at the exact source above. All three required artifacts are present and unexpired: Linux frontend 11541328334, Java tools 11540193329, native development-test runtime 11540222831. Each archive and manifest was independently rehashed against its SHA256SUMS. Each checksum subject passed Sigstore verification against the repository trusted root, exact repository/workflow, frozen source ref and commit, with self-hosted runners denied. Original metadata and verification outputs are retained beside this review.

Proposed execution: developer-packaged-qualification.yml on development, platform=java-composition, java_diagnostics=false, developer_run=37755336245, runtime_run=37755350322, policies equal the exact file bytes above, policy_approved=true only after explicit approval of these policies and disposable qualification environments.

The workflow runs conductor contracts and an actual clean-host packaged Java composition on disposable Ubuntu 24.04 runners. It authenticates the selected immutable developer/native inputs, creates four fresh Java fixture builds and ordinary signed releases, and exercises 18 finite preflight scenarios through both delivered authenticated frontend workspaces and an explicitly selected standalone operator. Original command/node bounds, capability grants and cleanup checks remain enforced; the Java job has the maintained 120-minute runner timeout. Bounded original build, signing, provider, preflight and command observations are retained by the workflow for 7 days and will be archived outside disposable worktrees. Any known failure will be preserved without relabeling its source.

Status: exact-source candidates and independent artifact verification passed; policies explicitly approved by the user; execution not dispatched because the user then stopped work for cleanup. This does not close #710 or qualify the separate #709 diagnostics or #718 transaction/recovery programmes.
