# Executed Windows editor tasks

The installed VS Code 1.139.0 ran the generated process tasks against an actual
WSL node on Windows x86-64. The [compact observation](editor-task-integration-observation.json)
records the frontend bytes, modified source hashes, approved runtime identity,
task exits, compiler location, revisions and owned cleanup. This is local source
integration evidence; the rebuilt frontend is not a publisher-authenticated
candidate, and the host is not a clean machine. It does not complete #568's
newcomer walkthrough or #569's final package qualification.

The extension test host used the editor's public task, document and diagnostic
APIs. It executed the generated tasks without a second lifecycle controller or
replacing their commands. The application was outside the LSF checkout, in a
Windows path containing spaces and `ü`. Only the frontend changed; runtime,
helper and compiler packages remained the independently approved
`0cb5cf08f1d7eb53650c116c93dcdd4c4a4d6bc3` artifacts. The Rust watch fixture used
the explicit provider-free `trusted-local` development admission profile.

| Observation | Result |
| --- | --- |
| Build, doctor and status tasks | Successful process exits |
| Watch starts and deploys A | An actual invocation returns `[101]` |
| Save invalid Rust | VS Code reports `app/src/lib.rs`, line 22, column 6 |
| Invoke after compiler failure | A remains selected and returns `[101]` |
| Save valid B | B returns `[201]`; the old diagnostic disappears |
| Logs task | Successful process exit |
| Terminate the watch task | Task ends; status truthfully reports the node still ready |
| Explicit down task | Confirms that the owned node stopped |
| Up after down | B returns `[201]` with its retained deployment identity |
| Final down | Owned node stops; only the owned WSL distro is then stopped |
| Open in a separate untrusted editor profile | Workspace stays untrusted; no tasks or owned VM start |

The original generated watch task used a finite-task problem matcher. VS Code
retained the current file's diagnostics until that task exited, so the compile
error was not available while watch continued. Watch now uses a background
matcher. With `--editor-diagnostics`, each build emits a bounded start/end pair
on stderr, including failures and trust rejection. A successful empty batch
clears previous errors. The structured command output and mutation recovery
contracts are unchanged.

The passing editor workflow took 97.929 seconds. Its initial failed observations
are retained as hashes and explanations: two reproduced the delayed diagnostic,
and one observer inspected an old retained deployment before the new watch build
settled. The latter received a certain local rejection and did not replay the
invocation. The corrected observer waits for that watch's confirmed deployment.

VS Code task termination on this Windows host did not prove Linux cleanup.
Use **LSF: down** to stop the workspace and **LSF: status** to confirm its state.
After transport loss, a pending mutation still requires original-operation
recovery. No test changed global WSL settings or stopped another distro.

This observation is editor API integration, not an interactive visual or
newcomer review. The untrusted-folder run used a separate editor data directory
with Workspace Trust enabled. It remained untrusted throughout; the owned WSL
distro was stopped before opening and remained stopped afterward.
