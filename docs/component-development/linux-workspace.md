# Select a Linux development workspace

The direct Linux and SSH adapters run the same frontend, project recipes,
watch/recovery controller and real-node tests as the
[Windows walkthrough](windows-application.md). Select a backend explicitly;
the frontend never guesses a host or uses ambient SSH agent credentials.

Obtain the independently approved frontend/runtime/tool distributions and their
verification inputs first. The selected host must be Ubuntu 24.04 x86-64, with
Linux 6.8 or newer and the controls required by the chosen node profile. A host
administrator provisions the reviewed helper and Python 3.13.5. Connecting does
not install an OS, grant privileges, or repair missing kernel controls.

## Direct Linux

Run the authenticated Linux frontend as the intended unprivileged workspace
owner. Select the exact installed helper and interpreter with a backend JSON
file. Replace the helper digest with the independently verified bundle's digest:

```json
{
  "kind": "linux",
  "helperSha256": "sha256:REPLACE_WITH_SELECTED_HELPER_DIGEST",
  "python": "/usr/local/bin/python3.13",
  "helper": "/opt/latent-dev/helper.pyz"
}
```

For example, save it as `/home/developer/lsf-inputs/direct-backend.json` and use:

```bash
Frontend=/opt/latent-dev/bin/latent-dev
State="$HOME/.latent-dev-tutorial"
Workspace=test-my-greeting
Project="$HOME/Projects/My greeting"
"$Frontend" --state-root "$State" dev doctor
"$Frontend" --state-root "$State" dev connect --workspace "$Workspace" \
  --backend-config "$HOME/lsf-inputs/direct-backend.json"
"$Frontend" --state-root "$State" dev install --workspace "$Workspace" \
  --runtime-inputs "$HOME/lsf-inputs/runtime.json"
"$Frontend" --state-root "$State" dev install-tools --workspace "$Workspace" \
  --tool-inputs "$HOME/lsf-inputs/rust-tools.json"
```

The installation selections have the same fields as Windows step 2, with
absolute Linux paths to the selected offline distributions, approved policies,
trusted roots and pinned Linux verifier. Choose an unused loopback port and
`local-experimental-v1` for this controlled tutorial. The installer creates
private node credentials; do not create a token or configuration by hand.

Authenticate the compiler/template bundle with `dev acquire --target linux-x86_64`
and the explicit publisher/verifier inputs, then select `rust/greeting` and its
identity from that authenticated bundle's `templates.json`. Use those returned
values as `$TemplateBundle` and `$TemplateSha256`:

```bash
"$Frontend" --state-root "$State" dev init "$Project" --bundle "$TemplateBundle" \
  --template rust/greeting --template-sha256 "$TemplateSha256"
"$Frontend" --state-root "$State" dev trust --workspace "$Workspace" --project "$Project"
"$Frontend" --state-root "$State" dev build --workspace "$Workspace" --project "$Project"
"$Frontend" --state-root "$State" dev prepare-test --workspace "$Workspace" \
  --consent-test-fixtures --admission trusted-local
"$Frontend" --state-root "$State" dev up --workspace "$Workspace"
```

Review the recipe before the trust command. Keep foreground up running and use
another terminal with the same frontend/state/workspace values for `dev deploy`,
`dev test --environment node`, `dev invoke`, `dev logs` and `dev down`. Follow
Windows steps 4–6 for the same expected greeting, declared error, source edit,
compiler failure and retained restart; Bash uses `\` for line continuation.

On a Linux authoring host with the pinned Rust 1.97.1 native toolchain and linker,
run the greeting's business-logic unit test before the component build:
`cargo +1.97.1 test --locked --manifest-path "$Project/app/Cargo.toml"`.
The packaged compiler selection and the native host toolchain are separate.
Record an unavailable native test as not run; building a component does not
implicitly run it.

The controller's private state belongs in a protected local home directory.
Shared application source is synchronized as data; it does not become node
state. Two mutually untrusted applications need separate Linux accounts, as the
managed WSL adapter provides. Different workspace names under one Unix account
are not a security boundary against that account itself.

## An explicit SSH host

The administrator supplies a dedicated unprivileged account, its private SSH
identity file, and an independently verified known-hosts file. The remote helper
must be installed at `/opt/latent-dev/helper.pyz`, with Python 3.13.5 at
`/usr/local/bin/python3.13`. Keep the private identity outside the application
source. An unknown or changed host key fails before the helper runs.

On Windows, this reviewed backend selection uses the Windows OpenSSH client:

```json
{
  "kind": "ssh",
  "helperSha256": "sha256:REPLACE_WITH_SELECTED_HELPER_DIGEST",
  "host": "dev.example.test",
  "port": 22,
  "user": "lsfdev",
  "identityFile": "C:\\LSF Private\\id_ed25519",
  "knownHosts": "C:\\LSF Private\\known_hosts",
  "ssh": "C:\\Windows\\System32\\OpenSSH\\ssh.exe"
}
```

Replace the example host, account and paths with the supplied ones. Save it
outside the project and connect explicitly:

```powershell
& $Frontend --state-root $State dev connect --workspace test-remote-greeting `
    --backend-config 'C:\LSF Private\ssh-backend.json'
```

Then use the same install, install-tools, init, trust and application commands
with that workspace name. The input documents refer to files on the **client**;
the controller transfers only the selected bytes before verifying/installing on
the remote host. Node management binds the remote loopback interface. Client
loopback is a different network namespace; no public management bind or tunnel
is assumed.

On a Linux client, select `/usr/bin/ssh` and absolute Linux identity/known-hosts
paths in the same JSON schema. SSH uses strict host-key checking, the one
selected identity, no agent forwarding, no proxy command and finite connection
deadlines. A lost SSH connection leaves remote cleanup unconfirmed: restore the
connection, inspect status and recover the original pending operation. Do not
repeat an uncertain invocation.

`dev down` retains the remote workspace. `dev purge --confirm-workspace NAME`
removes only that owned workspace after confirmed cleanup; it does not remove
the remote account, SSH server, host, or another workspace. The
[optional devcontainer](devcontainer.md) is another client for this same adapter.
