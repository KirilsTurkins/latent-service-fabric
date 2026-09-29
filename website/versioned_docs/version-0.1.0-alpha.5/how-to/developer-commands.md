# Developer commands

Use `latent-dev` for the application loop: create a project, build it, run tests,
deploy it, and inspect or stop its development node. Use the separate
[Operator CLI](../reference/operator-cli.md) when administering a persistent node,
managing its policies, or performing staged production rollouts.

Start with [workspace setup](../start/development-workspace.md) if you have not
installed the tools. It defines a `dev` function in PowerShell or Bash that runs
your selected frontend with its private state directory. All examples below use
that function and the `$Workspace` and `$Project` variables from setup.

For help, run `dev --help` or `dev build --help`. Without the shortcut, the syntax
is `latent-dev --state-root PATH dev COMMAND`; on Windows the binary is
`latent-dev.exe`. Global options such as `--editor-diagnostics` go before `dev`.

## The everyday loop

After [creating a capsule](../component-development/creating-a-capsule.md), keep
the node's foreground `up` command running in a second terminal. In your working
terminal, the following commands work on Windows and Linux:

```bash
dev build --workspace "$Workspace" --project "$Project"
dev deploy --workspace "$Workspace"
dev test --workspace "$Workspace" --environment node
dev logs --workspace "$Workspace"
```

`build` compiles the reviewed source; `deploy` selects the accepted build to answer
requests. A failed build leaves the previous deployment unchanged. `test` checks
the required cases in `tests/scenarios.json`; an expected application error can
be a passing case. A failed test does not automatically undo a deployment.

The signed development fixture used by some languages approves a single build
for 30 minutes. A changed build or expired fixture needs a fresh disposable
workspace and a newly prepared fixture. See [editing and recovery](../learn/deliver-and-recover-a-capsule.md)
for this path and the supported automatic watch loop.

## Create and prepare

| Command | Use it to | Main arguments |
| --- | --- | --- |
| `doctor` | Inspect host prerequisites; add a workspace to inspect its node | `--workspace NAME` is optional |
| `init` | Create a project from an authenticated language template | Destination, `--bundle`, `--template`, `--template-sha256` |
| `trust` | Approve the project's current build recipe | `--workspace`, `--project` |
| `build` | Compile the reviewed project using installed tools | `--workspace`, `--project` |
| `prepare-test` | Prepare a stopped disposable node to accept the selected build | `--workspace`, `--consent-test-fixtures`, `--admission trusted-local` or `signed-fixture`; optional `--fixtures FILE` |
| `editor` | Write optional VS Code process tasks without running them | `--workspace`, `--project`, `--frontend` |

`prepare-test` requires a workspace name starting with `test-`. Select the
admission profile from the tutorial; do not change it to bypass a rejected build.
When the recipe or selected tools change, review the change and run `trust` again.
Changing ordinary application source does not itself approve a new recipe.

Generate editor tasks after creating and trusting the project:

```bash
dev editor --workspace "$Workspace" --project "$Project" --frontend "$Frontend"
```

In VS Code, choose **Tasks: Run Task** for build, watch, logs, status, recovery or
down. Existing task files are preserved. Opening the folder starts no task.

## Run and test

| Command | Use it to | Main arguments |
| --- | --- | --- |
| `up` | Start and own the foreground node session | `--workspace`; optional `--watch --project PATH` |
| `deploy` | Publish and select the last accepted build | `--workspace` |
| `test` | Run the selected scenario suite | `--workspace`, `--environment node` or `portable`; optional repeated `--select CASE_ID` |
| `invoke` | Call one deployed function | `--workspace`, `--service`, `--contract`, `--function`, `--input` |

For a single greeting case:

```bash
dev test --workspace "$Workspace" --environment node --select greeting-0
```

Use `up --watch --project PATH --test-select greeting-0` to build and deploy edits,
then run a focused test, in a supported `test-` workspace. The [edit guide](../learn/deliver-and-recover-a-capsule.md)
shows the full foreground command for each OS. Keep that terminal open.

Portable tests additionally need `--project`, `--artifacts`, `--portable-bundle`
and `--controlled-development`. They run already compiled components and cover
a smaller set of behavior. See [portable tests](../component-development/portable-tests.md)
before selecting this environment.

## Inspect and recover

```bash
dev status --workspace "$Workspace"
dev build-status --workspace "$Workspace"
dev logs --workspace "$Workspace"
dev recover --workspace "$Workspace"
```

`status` reports the selected workspace and node state. `build-status` observes
ongoing compiler work. `logs` shows bounded node output. `recover` queries the
original pending operation after a lost response; it does not run the operation
again. `no-pending-operation` means there is nothing pending to recover.

An unknown or expired result remains uncertain. Keep the workspace and original
operation, restore connectivity, and inspect it before more work. Do not repeat
an uncertain invocation or force a conflicting deployment. An unreachable node
is not proof that it stopped.

## Stop and remove workspaces

```bash
dev down --workspace "$Workspace"
dev status --workspace "$Workspace"
```

Expect `state: stopped`. `down` retains the deployment, project and node data.
Start `up` again to use the retained deployment; no new `deploy` is needed.

To remove an owned workspace and its node data deliberately:

```bash
dev purge --workspace "$Workspace" --confirm-workspace "$Workspace"
```

The authored project folder remains. On Windows, the shared LSF WSL distro also
remains until every owned workspace has been purged. Inspect it with
`dev wsl-status`, then use `dev wsl-purge --confirm-distribution NAME` with the
exact returned distribution name if you want to remove it. Do not substitute a
different distro or shut down all WSL instances as application cleanup.

## Setup commands

These are normally used by the [workspace setup guide](../start/development-workspace.md):

| Command | What it does |
| --- | --- |
| `acquire` | Authenticates a downloaded bundle and puts it in the private cache; it does not download it |
| `provision` | Imports a verified LSF-owned WSL image with explicit `--consent-provision` |
| `wsl-workspace` | Creates a private Linux user for one workspace in that distro |
| `wsl-status` | Observes the owned distro and workspace registrations |
| `wsl-recover` | Reconciles an interrupted WSL registration change using its exact `--confirm-distribution` |
| `wsl-purge` | Removes the exact named owned distro after its workspaces are purged |
| `connect` | Selects an explicitly configured Linux or SSH backend |
| `install` | Installs the verified development node described by `--runtime-inputs` |
| `install-tools` | Installs the language compiler described by `--tool-inputs` |
| `devcontainer` | Writes opt-in container files from a verified Linux bundle; it does not build or start a container |

## Read a result

Successful commands end with a JSON result containing `code: success`. Tests also
report `passed` and individual scenario results. Foreground commands print events
such as `ready`, `deployed`, `post-deploy-tests` and `edit-failed` as work progresses.

| Exit status | Meaning |
| --- | --- |
| `0` | The command completed successfully |
| `2` | Rejected or unavailable input; inspect the reported code |
| `3` | Required tests failed |
| `5` | An operation's outcome is uncertain; recover the original operation |
| `130` | Interrupted; inspect status before assuming cleanup |

Fix compiler errors in your source. For a signature or tool mismatch, obtain the
matching verified packages. For an occupied port, choose an unused port for a
new workspace. A denied capability needs the intended scoped policy, not a less
restrictive profile.
