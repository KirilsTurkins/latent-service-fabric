# Select a Linux development workspace

The direct Linux and SSH adapters run the same frontend, project recipes,
watch/recovery controller and real-node tests as the
[Windows walkthrough](windows-application.md). Select a backend explicitly;
the frontend never guesses a host or uses ambient SSH agent credentials.

[Download and verify the toolkit](../start/developer-setup.md#linux-download-and-verify)
first. Use the resulting frontend/runtime/tool directories and policies below. The selected host must be Ubuntu 24.04 x86-64, with
Linux 6.8 or newer and the controls required by the chosen node profile. A host
administrator provisions the reviewed helper and Python 3.13.5. Connecting does
not install an OS, grant privileges, or repair missing kernel controls.

## Direct Linux

Use the authenticated Linux frontend and helper from the download directory.
Your administrator supplies Python 3.13.5 at `/usr/local/bin/python3.13`.
This walkthrough runs as your ordinary Linux account. Keep its input and state
directories private; another workspace name under the same account is not an
isolation boundary against that account.

### 1. Select your language and create the installation inputs

Keep this Bash terminal open. Choose the same language as in the download step:
`rust`, `c`, `typescript`, `go`, `java` or `dotnet`. Use a new project and workspace
name for each tutorial. Choose an unused loopback port if 18080 is already taken.

```bash
set -euo pipefail
umask 077
export Inputs="$HOME/LSF-inputs-alpha4"
export Language=rust
Frontend="$Inputs/frontend/bin/latent-dev"
State="$HOME/.latent-dev-tutorial"
Workspace=test-my-greeting
Project="$HOME/Projects/My greeting"
mkdir -p "$HOME/Projects"
python3 - <<'PY'
import hashlib, json, os, pathlib, shutil
root = pathlib.Path(os.environ['Inputs'])
language = os.environ['Language']
assert language in ('rust', 'c', 'typescript', 'go', 'java', 'dotnet')
manifest = json.loads((root/'linux/developer-bundle.json').read_text())
helper = next(file for file in manifest['files'] if file['path'] == 'helper.pyz')
verifier = root/'gh-linux'
shutil.copyfile(shutil.which('gh'), verifier)
verifier.chmod(0o700)
identity = 'sha256:'+hashlib.sha256(verifier.read_bytes()).hexdigest()
def save(name, value):
    (root/name).write_text(json.dumps(value)+'\n')
save('direct-backend.json', dict(kind='linux', helperSha256=helper['sha256'],
     python='/usr/local/bin/python3.13', helper=str(root/'frontend/helper.pyz')))
common = dict(version=manifest['version'], trustedRoot=str(root/'trusted_root.jsonl'),
              verifier=str(verifier), verifierSha256=identity, allowCandidate=True, consent=True)
save('tutorial-runtime.json', dict(common, schemaVersion='latent.dev.install-inputs.v1',
     releaseDirectory=str(root/'native'), publisherPolicy=str(root/'native-policy.json'),
     profile='local-experimental-v1', port=18080))
save('tutorial-tools.json', dict(common, schemaVersion='latent.dev.tool-inputs.v1',
     bundleDirectory=str(root/language), publisherPolicy=str(root/'developer-policy.json'), language=language))
PY
lsf() { "$Frontend" --state-root "$State" dev "$@"; }
lsf doctor
lsf connect --workspace "$Workspace" --backend-config "$Inputs/direct-backend.json"
lsf install --workspace "$Workspace" --runtime-inputs "$Inputs/tutorial-runtime.json"
lsf install-tools --workspace "$Workspace" --tool-inputs "$Inputs/tutorial-tools.json"
```

Expect each operation to report `success`. The installer creates private node
credentials. There is no token-copying or hand-written node configuration step.
A port conflict is a failure; the controller does not stop its current owner.

### 2. Create and build a greeting

Authenticate the templates with the same selected policy and independently
installed verifier. The template index supplies the identity automatically:

```bash
Version=$(python3 -c 'import json,os; print(json.load(open(os.environ["Inputs"]+"/developer-policy.json"))["version"])')
VerifierIdentity="sha256:$(sha256sum "$Inputs/gh-linux" | cut -d' ' -f1)"
lsf acquire --bundle-directory "$Inputs/$Language" \
  --publisher-policy "$Inputs/developer-policy.json" --trusted-root "$Inputs/trusted_root.jsonl" \
  --verifier "$Inputs/gh-linux" --verifier-sha256 "$VerifierIdentity" \
  --version "$Version" --target linux-x86_64 --allow-candidate > "$Inputs/template-acquisition.json"
Bundle=$(python3 -c 'import json,os; print(json.load(open(os.environ["Inputs"]+"/template-acquisition.json"))["result"]["bundle"])')
TemplateIdentity=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["templates"]["greeting"]["identity"])' "$State/bundles/$Bundle/templates.json")
lsf init "$Project" --bundle "$Bundle" --template "$Language/greeting" --template-sha256 "$TemplateIdentity"
```

Open `app` to see your editable code and WIT contract. Review
`latent.project.json` before trusting its build recipe. `tests/scenarios.json`
lists success and declared-error cases with their input and expected files.

```bash
lsf trust --workspace "$Workspace" --project "$Project"
lsf build --workspace "$Workspace" --project "$Project"
lsf prepare-test --workspace "$Workspace" --consent-test-fixtures
```

The signed disposable fixture binds this build and expires after 30 minutes.
Use a fresh test workspace if the accepted build changes or the fixture expires.
The selected profile supplies the language's declared clock/entropy imports;
it does not supply a general JVM, CLR or Node.js operating environment.

### 3. Start, deploy and test

Open another Bash terminal and keep this foreground command running:

```bash
"$HOME/LSF-inputs-alpha4/frontend/bin/latent-dev" --state-root "$HOME/.latent-dev-tutorial" \
  dev up --workspace test-my-greeting
```

Wait for the authenticated `ready` event. In the original terminal:

```bash
lsf deploy --workspace "$Workspace"
lsf test --workspace "$Workspace" --environment node
lsf logs --workspace "$Workspace"
lsf down --workspace "$Workspace"
lsf status --workspace "$Workspace"
```

Expect `passed: true` with all greeting cases passing: `Ada` returns
`Hello, Ada!`, and an empty name returns the expected declared application error.
`down` stops the owned node and retains its data. Starting foreground `up`
again preserves the selected deployment without another deploy command.

When finished, remove this disposable workspace explicitly:

```bash
lsf purge --workspace "$Workspace" --confirm-workspace "$Workspace"
```

Your project source remains in `$Project`. To try `word-count` or `shipping`,
use a new project/workspace, select that template and its matching index entry,
then follow the same build/test steps. The [language guide](packaged-languages.md)
explains their expected results and supported execution profiles.

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
