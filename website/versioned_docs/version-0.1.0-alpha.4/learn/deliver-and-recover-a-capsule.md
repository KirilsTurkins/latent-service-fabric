# Edit, deploy and recover a capsule

Change your greeting from `Hello, Ada!` to `Welcome, Ada!`, test the new answer,
and see what happens when a build fails. Then restart the node and call the
retained deployment. The development tools keep track of the published build
and credentials for you.

Complete [Creating a capsule](../component-development/creating-a-capsule.md)
through the greeting's first invocation. Keep the working terminal, project and
workspace. This guide uses its `dev` shortcut on Windows or Linux.

## 1. Choose the update path for your project

The Rust and C provider-free tutorials use `trusted-local` admission for your own
controlled code. They can use the existing workspace for build/deploy and watch.
The automatic greeting exercise below uses Rust, whose source file is
`app/src/lib.rs`. Its source and tests are explained in the shared capsule guide.

The other language tutorials use `signed-fixture`. Each fixture approves one
accepted build for 30 minutes. You can edit their source normally, but a changed
build needs a **new disposable workspace** and a fresh signed fixture. Keep the
project folder, choose a new workspace in [setup](../start/development-workspace.md),
install the same language tools there, then trust, build and prepare that project
with `--admission signed-fixture`. Skip `dev init` because your project already
exists. Start, deploy and test in that new workspace as in the capsule tutorial.
Do not reuse or replace a fixture policy to authorize a changed build.

## 2. Change the greeting and test it

In your editor, change `Hello,` to `Welcome,` in your language's greeting source
under `app`. Change the matching answers in `tests/0-expected.json` and
`tests/1-expected.json`, preserving their JSON format. Update any native unit-test
expectation beside the source too.

For the trusted-local workspace, run these commands in your original terminal.
Your node remains running in the second terminal:

```bash
dev build --workspace "$Workspace" --project "$Project"
dev deploy --workspace "$Workspace"
dev test --workspace "$Workspace" --environment node
```

Expect every required case to pass. Make the greeting call from the previous
tutorial: it now returns `Welcome, Ada!`. Building alone does not switch the
running deployment; `deploy` selects the accepted build for future requests.

## 3. Watch edits automatically

For the Rust trusted-local greeting, first stop the ordinary foreground session:

```bash
dev down --workspace "$Workspace"
```

In the second terminal, start watch with the same workspace and project. The
commands below use the default setup paths; use your own values if you changed them.

**If you use Windows (PowerShell):**

```powershell
& (Join-Path $env:USERPROFILE 'LSF-inputs-alpha4/frontend/bin/latent-dev.exe') `
    --state-root (Join-Path $env:LOCALAPPDATA 'LatentDev-tutorial') --editor-diagnostics `
    dev up --workspace test-my-greeting --project "$env:USERPROFILE/Projects/My greeting" `
    --watch --test-select greeting-0
```

**If you use Linux (Bash):**

```bash
"$HOME/LSF-inputs-alpha4/frontend/bin/latent-dev" --state-root "$HOME/.latent-dev-tutorial" \
    --editor-diagnostics dev up --workspace test-my-greeting --project "$HOME/Projects/My greeting" \
    --watch --test-select greeting-0
```

Wait for `deployed` and the focused test result. Change `Welcome,` back to `Hello,`
in the two expected files, then in `app/src/lib.rs`. Save them. Watch builds and
deploys the change and runs `greeting-0`. The next direct call returns `Hello, Ada!`.
Run the full test command from step 2 whenever you want to check the remaining cases.

## 4. See a failed build keep the last working version

Add an invalid Rust statement to `app/src/lib.rs` and save. Expect an error with
the source location and an `edit-failed` event. Call the greeting again from your
first terminal: the previous working `Hello, Ada!` deployment is still available.

Remove the invalid statement and save. The next successful build clears the old
compiler diagnostic. A failed focused test is different from a failed build:
tests run after deployment, so a failed test is reported but does not automatically
roll back the deployed program.

You can restore earlier behavior by restoring the earlier source and expected
answers, then building, deploying and testing it. Production selection of an
already published version is an operator task; see [managed rollbacks](../phase-2-rollback.md).

## 5. Inspect an interruption

After a lost response, sleep/resume or backend interruption, run:

```bash
dev status --workspace "$Workspace"
dev build-status --workspace "$Workspace"
dev logs --workspace "$Workspace"
dev recover --workspace "$Workspace"
```

Recovery asks for the result of the original operation. `no-pending-operation`
means there is nothing pending. An unknown or expired receipt remains uncertain;
do not repeat that deploy or invocation with a new identity. A newer deployment
from another actor is not overwritten. Restore an unreachable connection before
assuming either completion or shutdown.

## 6. Restart and keep your work

Stop watch with `dev down --workspace "$Workspace"`. In the second terminal,
start ordinary `up` again using [the capsule tutorial's start command](../component-development/creating-a-capsule.md#4-start-deploy-and-test).
Call the greeting without another deploy: the selected version is still there.

Finish with:

```bash
dev down --workspace "$Workspace"
dev status --workspace "$Workspace"
```

Expect `state: stopped`. Keep the workspace for later, or use the explicit
[cleanup commands](../how-to/developer-commands.md#stop-and-remove-workspaces).
For optional VS Code tasks, command options and common failures, keep the
[developer command guide](../how-to/developer-commands.md) nearby.
