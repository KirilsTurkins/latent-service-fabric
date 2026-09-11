<!-- LSF-WIKI-MANAGED -->
# Getting started

Use **release** for the published prerelease and **development** for ongoing changes. Do not build from `docs/wiki`: that isolated branch owns Wiki content and retains an older code snapshot.

Install the [pinned toolchain](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/development/toolchain.md). The standalone node requires Linux pressure observations and local catalog locks/directory synchronization. Windows supports selected development tooling, not the current daemon deployment.

```bash
git clone --branch release https://github.com/KirilsTurkins/latent-service-fabric.git
cd latent-service-fabric
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
cargo build -p latent -p latentd --locked
make echo-capsule
```

Follow the complete [standalone echo quickstart](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/development/standalone-quickstart.md). It creates private node/client directories, generates credentials into files, starts the node, publishes actual component bytes, applies a deployment and invokes one guest activation. Readiness, status, inventory and finite shutdown are included.

[Operator CLI](Operator-CLI) covers supported commands. Use an explicit private config; tokens have no command-line flag. The older `phase0-spike-demo` is a historical feasibility path, separate from the supported node/CLI workflow.

For ordinary checks use [validation tiers](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/VALIDATION.md). Full 100k and long-running campaigns are explicit manual work.
