# Creating a capsule

Create a small program and run it on your development node. Start with a greeting,
then try a word counter or shipping calculator. Each accepts typed input and
returns either an answer or a helpful application error.

Complete [Get the developer tools](../start/developer-setup.md) and
[Set up your workspace](../start/development-workspace.md) first. Keep its terminal
open: it defines `dev`, your selected `$Language`, `$Workspace`, `$Project` and
other tool paths. The steps below use those same variables on both operating systems.

Select **Rust**, **C**, **TypeScript**, **Go**, **Java** or **C# / .NET** above a code
example. Your selection is shared across the examples. The build, deploy and test
commands work the same way for every language; use the language you installed
during setup.

## 1. A greeting capsule

The first program accepts a name and returns a greeting. An empty name produces
a helpful error instead. This is the complete implementation in your selected language:

<!-- lsf-example: guest/tutorial-greeting capsule -->

The WIT contract describes the input and the two possible kinds of answer:

```wit
greet: func(name: string) -> result<string, string>;
```

You will find this contract under `app/wit` in your project. Generated bindings
connect it to your language's function. For now, keep the contract unchanged.

## 2. Create the project

Choose the `greeting` template. These commands read its identity from the verified
template index and create your project; you do not copy identifiers by hand.

**If you use Windows**, run this in your PowerShell working terminal:

```powershell
$Example = 'greeting'
$Templates = (dev acquire --bundle-directory (Join-Path $Inputs $Language) `
    --publisher-policy $DeveloperPolicy --trusted-root $TrustedRoot `
    --verifier $WindowsVerifier --verifier-sha256 $WindowsVerifierSha256 `
    --version $Version --target linux-x86_64 --allow-candidate | ConvertFrom-Json).result
$Bundle = $Templates.bundle
$Index = Get-Content -LiteralPath (Join-Path $State "bundles/$Bundle/templates.json") -Raw | ConvertFrom-Json
$TemplateIdentity = $Index.templates.PSObject.Properties[$Example].Value.identity
dev init "$Project" --bundle $Bundle --template "$Language/$Example" --template-sha256 $TemplateIdentity
```

**If you use Linux**, run this in your Bash working terminal:

```bash
Example=greeting
Version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$Inputs/developer-policy.json")
VerifierIdentity="sha256:$(sha256sum "$Inputs/gh-linux" | cut -d' ' -f1)"
dev acquire --bundle-directory "$Inputs/$Language" \
    --publisher-policy "$Inputs/developer-policy.json" --trusted-root "$Inputs/trusted_root.jsonl" \
    --verifier "$Inputs/gh-linux" --verifier-sha256 "$VerifierIdentity" \
    --version "$Version" --target linux-x86_64 --allow-candidate > "$Inputs/template-acquisition.json"
Bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["result"]["bundle"])' "$Inputs/template-acquisition.json")
TemplateIdentity=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["templates"][sys.argv[2]]["identity"])' "$State/bundles/$Bundle/templates.json" "$Example")
dev init "$Project" --bundle "$Bundle" --template "$Language/$Example" --template-sha256 "$TemplateIdentity"
```

Open the project in your editor:

| File or folder | What you do with it |
| --- | --- |
| `app` | Edit the source and its WIT contract |
| `latent.project.json` | Review the compiler, build recipe and source files it can use |
| `tests/scenarios.json` | Read the named test cases |
| `tests/*-input.json`, `tests/*-expected.json` | See each input and its expected answer |

## 3. Build and prepare the node

After reviewing the project, run these commands in the same terminal on either OS:

```bash
dev trust --workspace "$Workspace" --project "$Project"
dev build --workspace "$Workspace" --project "$Project"
dev prepare-test --workspace "$Workspace" --consent-test-fixtures --admission "$Admission"
```

Expect `code: success` from each command. The compiler comes from the selected
tool bundle. `prepare-test` prepares the stopped disposable node to accept this
application. Setup selected `trusted-local` for Rust/C or `signed-fixture` for the
other languages, including their required runtime permissions.

A signed fixture lasts 30 minutes and binds one build. If you edit that build or
the fixture expires, create a fresh disposable workspace before testing it. Use
the [edit guide](../learn/deliver-and-recover-a-capsule.md) for the supported watch loop.

## 4. Start, deploy and test

Open a **second terminal** and start the node. Keep this command running.
For the default paths from setup, use the following command; substitute your
workspace name if you chose another one.

**Windows (PowerShell):**

```powershell
& (Join-Path $env:USERPROFILE 'LSF-inputs-alpha4/frontend/bin/latent-dev.exe') `
    --state-root (Join-Path $env:LOCALAPPDATA 'LatentDev-tutorial') dev up --workspace test-my-greeting
```

**Linux (Bash):**

```bash
"$HOME/LSF-inputs-alpha4/frontend/bin/latent-dev" --state-root "$HOME/.latent-dev-tutorial" \
    dev up --workspace test-my-greeting
```

Wait for the `ready` event. In your **first terminal**, publish the accepted build
and run its tests with the same commands on either OS:

```bash
dev deploy --workspace "$Workspace"
dev test --workspace "$Workspace" --environment node
```

Expect `passed: true` and every required case to report `status: passed`.
`Ada` returns `Hello, Ada!`; an empty name produces the expected application error.
Some language profiles include additional runtime cases, so their case counts differ.

## 5. Send a request yourself

The greeting's first input file contains `["Ada"]`. Call it directly:

```bash
dev invoke --workspace "$Workspace" --service examples/my-greeting --contract examples:greeting/api@1.0.0 --function greet --input "$Project/tests/0-input.json"
```

The response includes `category: success`, the selected deployment and an encoded
payload. To display the typed answer, **on Windows**:

```powershell
$Reply = (dev invoke --workspace $Workspace --service examples/my-greeting `
    --contract examples:greeting/api@1.0.0 --function greet `
    --input (Join-Path $Project 'tests/0-input.json') | ConvertFrom-Json).result
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Reply.data.payload.data))
```

Or **on Linux**:

```bash
dev invoke --workspace "$Workspace" --service examples/my-greeting --contract examples:greeting/api@1.0.0 --function greet --input "$Project/tests/0-input.json" \
    | python3 -c 'import base64,json,sys; print(base64.b64decode(json.load(sys.stdin)["result"]["data"]["payload"]["data"]).decode())'
```

Expected: `[{"ok":"Hello, Ada!"}]`. These are independent example calls. If a
response is lost, use `dev recover --workspace "$Workspace"` to inspect that
original call before making another one.

## 6. Try a word counter

This program counts groups separated by spaces, tabs or newlines. An empty
document has zero words. Very long input produces a readable error.

<!-- lsf-example: guest/tutorial-word-count capsule -->

```wit
count: func(text: string) -> result<u32, string>;
```

Stop the greeting with `dev down --workspace "$Workspace"`. Create another
workspace and project using the [workspace setup](../start/development-workspace.md),
for example `test-my-words` and `My words`. Reuse your downloads and existing WSL
distro. In step 2 above set `$Example = 'word-count'` on Windows or
`Example=word-count` on Linux, then follow the same build, start, deploy and test
steps with that workspace name.

The tests send `LSF runs small programs` and expect `4`. Look in
`tests/scenarios.json` for the service, contract and function to use in a direct call.

## 7. Try a shipping calculator

This program accepts an item count and whether delivery is express. It returns
a price in cents: 500 for standard delivery or 1200 for express, plus 75 per item.

<!-- lsf-example: guest/tutorial-shipping capsule -->

```wit
quote: func(items: u32, express: bool) -> result<u32, string>;
```

Use another project and workspace, selecting `shipping` in step 2. Run the same
build, start, deploy and test commands. Two items with standard delivery produce
`650`; express delivery produces `1350`. Zero items produce
`Choose between 1 and 100 items.` as a declared application error.

The three programs need no network, files or secrets. Their compilers can still
require explicitly granted runtime clocks or entropy. To add application access
to an outside service, continue with [capabilities](../learn/use-capabilities.md).

## 8. Clean up

Stop the selected node and inspect its state:

```bash
dev down --workspace "$Workspace"
dev status --workspace "$Workspace"
```

Expect `state: stopped`. Starting `up` again retains the deployment without another
deploy command. Keep this workspace if you are continuing with [editing and recovery](../learn/deliver-and-recover-a-capsule.md).
When you no longer need its node data, remove that workspace explicitly:

```bash
dev purge --workspace "$Workspace" --confirm-workspace "$Workspace"
```

Your project source remains. Repeat cleanup for each workspace you created.
The [developer command guide](../how-to/developer-commands.md#stop-and-remove-workspaces)
also explains when to remove the shared LSF-owned WSL distro.
