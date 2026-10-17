# IntelliJ IDEA 2026

Open the **repository root directory**, not just `sdk/java-client` or an
individual Cargo manifest. The committed `.idea/` project model and `.run/`
configurations make the polyglot repository visible without a generation step.
This is contributor tooling for the source checkout, not part of the packaged
SDK or a new application execution model.

## First open

1. Install the selected tools from [the toolchain guide](toolchain.md). Use a
   Linux checkout, WSL2 Linux filesystem, or a Linux remote-development backend
   for native runtime and complete validation. Configure IDEA's environment
   with the appropriate `PATH` and `JAVA_HOME`; a desktop launcher may not
   inherit your interactive shell environment.
2. Review IDEA's trust prompt. Install or enable the compatible JetBrains
   **Rust** (`com.jetbrains.rust`) and **Python** (`Pythonid`) plugins, and
   restart when requested. Use the current Rust plugin, not the deprecated
   IntelliJ Rust plugin. The unified task configurations require Python support;
   Shell Script is now optional editing support, not a launcher prerequisite.
   Other language plugins and their licensing remain task-specific.
3. Prepare `.venv` using the pinned Python and `tools/requirements.lock` from
   the toolchain guide. Under **File | Project Structure | SDKs**, add that
   existing Python environment and name its SDK **LSF Python**. Select
   `.venv\Scripts\python.exe` on Windows or `.venv/bin/python` on Linux/macOS.
   Under **Modules | lsf.tools | Dependencies**, verify **Module SDK: LSF
   Python**. All task configurations inherit this one module SDK; there is no
   need to set an interpreter on every configuration. SDK paths stay in your
   local IDE SDK table, not in Git. Do **not** change the Java project SDK to
   Python. Apply the SDK settings before running a task.
4. Let the Rust plugin synchronize the attached Cargo workspaces. Select the
   rustup toolchain and install `rust-src` for the pinned toolchain when IDEA
   offers it. The root `rust-toolchain.toml`, not a copied IDE version, owns the
   Rust version and component targets. Cargo synchronization can resolve
   dependencies and execute build scripts after the project is trusted.
5. For Java client work, add the exact Temurin JDK from the toolchain guide and
   select it as the project SDK. Match `JAVA_HOME` to the same installation.
   Run **LSF - java-client-prepare** explicitly to download verified locked
   dependencies and generate Protobuf sources. Preparation is not compilation
   or a passing SDK qualification. Java sources target Java 25.
6. Run **LSF - ide-doctor**. It checks command availability and metadata drift
   without installing anything. **LSF - toolchain-check** performs the existing
   full toolchain check in its Bash/Make environment. These checks cannot
   inspect IDE licensing, plugin enablement, indexing state or SDK selection.

IDEA's [Python SDK guide](https://www.jetbrains.com/help/idea/configuring-python-sdk.html)
explains the SDK table and module-level selection. The
[Python run-configuration guide](https://www.jetbrains.com/help/pycharm/run-debug-configuration-python.html)
explains interpreter, script and argument fields. The
[Rust guide](https://www.jetbrains.com/help/idea/rust-plugin.html) describes
native debugger prerequisites, including Native Debugging Support on applicable
hosts. Trust, plugin installation and SDK selection require user consent.

A missing **LSF Python** SDK is an IDE setup error, not a reason to edit all run
files. Add the interpreter once at module level. The default SDK name is shared,
not its executable path. For multiple checkouts with different environments,
choose each checkout's interpreter on its `lsf.tools` module and keep that local
module-SDK change out of commits. The Java client still inherits the Java project
SDK, and Cargo uses its independently configured Rust toolchain.

## One configuration per task

There are **53 shared configurations**: 48 Python-dispatched tasks and five
Cargo run/debug entries. For example, **LSF - website-prepare** directly invokes
`tools/intellij.py` with arguments `run website-prepare`, using the repository
root as its working directory. There are no `(Windows)` or `(Bash)` duplicates.

IDEA starts the selected Python interpreter directly, not a terminal command.
The dispatcher examines that interpreter's platform: native Windows uses the
existing Windows adapters; Linux/macOS use the existing Make/SDK owners. There
is no dependency on whether the terminal is PowerShell, cmd, Bash or Zsh, and no
bare `bash.exe` lookup before platform detection. A Windows desktop with a
Linux remote-development backend uses the backend's Linux environment. Merely
installing WSL does not select a backend or cause the dispatcher to start it.
Use a complete Linux checkout/backend for native work; synchronizing only a
Python script to a remote interpreter is not a complete build environment.

The dispatcher preserves child exit codes and passes the selected interpreter
to Python helpers. `LSF_IDE_PYTHON` is only a terminal-wrapper override; it does
not replace the SDK selected by IDEA. Run output uses the Run tool window,
not commands injected into an existing terminal. The Python Debug button debugs
the dispatcher; use the Cargo configurations for native Rust debugging.

| Group | Available work |
| --- | --- |
| Start here | Help, tracked tree, IDE diagnostics and full toolchain checks |
| Source checks | Source/schema/docs/CI validation and IDE drift checks |
| Rust | Formatting, workspace/production checks, bindings, Clippy and MSRV |
| Tests | Deterministic tests, catalogue, repository tests and IDE regressions |
| Contracts and SDKs | Contract lanes, client SDK aggregate, Java client build/test |
| Explicit preparation | Echo fixtures, Java inputs and private local-node state |
| Website | Dependency preparation, preview, checks, both builds and browser tests |
| Native debug | Three CLI help commands, core unit tests and a local node |
| Full Linux validation | Broad Make aggregate with a fresh owned output root |

Native Windows supports help, tree, source/IDE checks, formatting, catalogue
listing, Java client work and website tasks with their installed prerequisites.
Unsupported Make/runtime tasks remain visible, but fail with an environment
explanation rather than silently invoking WSL. The native daemon and full
runtime qualification still require Linux. macOS does not become a supported
native Linux runtime merely because it has a POSIX shell.

For specific registered suites/cases, use [the local test entry point](local-tests.md)
and [Make commands](make-commands.md). There is no unconfigured one-click
`cargo test --workspace` or prepared-test run. Supply the exact suite and the
same explicitly prepared inventory. Full validation needs a clean tracked
Linux checkout. [VALIDATION.md](../../VALIDATION.md) defines acceptance; a
successful IDE run establishes only the command it actually executed.

### Website and native Windows

Run **LSF - website-prepare**, then **LSF - website-start**. Preparation validates
Node against `website/package.json`, uses the authenticated archive preparer,
installs the separate package-manager package, verifies the prepared npm bundle,
and installs locked website dependencies. The website's engine checks and
lifecycle-script restrictions remain enabled. Do not substitute upstream npm,
downgrade global npm or delete lockfiles to bypass a version error.

IDEA's generic **Run npm install** action is separate from these configurations.
After preparation, select the repository's `website/toolchain/node_modules/npm`
directory as the custom package manager in **Settings | Languages & Frameworks |
JavaScript Runtime**. Select the npm installation directory, not global
`npm.cmd` or `npm-cli.js`. Prefer **LSF - website-prepare** for the repository's
complete authenticated, locked installation sequence. See the
[website guide](website.md) for the supported build and browser boundary.

The `.cmd` and `.sh` wrappers remain terminal conveniences, not shared IDE run
configurations. From PowerShell at the repository root:

```powershell
.\tools\intellij.cmd help
.\tools\intellij.cmd website-prepare
```

From an actual Bash environment:

```sh
bash tools/intellij.sh help
bash tools/intellij.sh website-prepare
```

Run commands one at a time and stop on failure. A bare `bash` in Windows can
select the WSL launcher, as the initial first-open report demonstrated. Do not
use it to launch native Windows tasks. Native help and website preparation do
not require WSL, Git Bash, GNU Make or a PowerShell execution-policy change.
The wrappers retain their interpreter-selection and failure-propagation behavior.

## Project and language views

The project contains 76 modules covering Cargo members, independent maintained
Cargo workspaces, SDKs, tools, website, examples, research and documentation.
Nested content roots define ownership; parent modules must not exclude actual
child-module roots. The Cargo tool window owns Rust target/dependency discovery.
New workspace members and SDK directories are picked up by the generator.
Templates, fixtures and vendored inputs stay browsable without being attached
as independent Cargo projects.

The Java client marks `src/transport/java`, `src/example/java` and
`build/generated/java` as production sources and `src/transportTest/java` as
tests. Its library directory uses the prepared JARs under `build/deps`. There
is no second Maven dependency graph or IDE-owned Protobuf generator. Its optional
Gradle build remains available as a separate Java-client project; do not import
it over the shared module model and commit the replacement.

Guest compiler replacements and conformance fixtures are not flattened into one
JVM module. A visible C or .NET directory does not turn IDEA into CLion or Rider.
Existing SDK tools remain the build/test authority; see
[guest authoring](../component-development/guest-sdk.md) and
[build foundation](build-foundation.md).

Caches and actual compiler output remain excluded, including Cargo targets,
`node_modules`, virtual environments, Python bytecode, Gradle/Zig caches and
website output. Source directories named `bin` or `build` are not globally
hidden; generated Java sources remain indexed. The root `.editorconfig` and
owning formatters remain authoritative. No save action rewrites generated or
byte-sensitive sources.

## Run and debug a local node

On a Linux/WSL backend, explicitly run **LSF - ide-node-prepare**, then
**LSF - local-node** with Run or Debug. Preparation exclusively creates private
`target/ide/node/` state with owner-only files, random credentials and matching
node/client configurations. It never starts a listener, replaces old state or
prints the token. The node binds only `127.0.0.1:43170`; a conflict fails rather
than selecting another service. To change ports, edit both local JSON files.

This is the [trusted-local quickstart](standalone-quickstart.md), not production
or signed-admission qualification. The credential has the `operator` role in
the `examples` tenant. Keep state for restart; stop the debug session before
another run. Use `target/ide/node/client.json` with the CLI. Never commit that
directory, copy its token to a run configuration or point shared settings at a
production node. Publication, deployment and readiness verification remain
explicit quickstart steps. For non-Linux work, see the
[portable subset](../component-development/portable-tests.md).

## Update and recover settings

Close the project before pulling the consolidated configurations, so IDEA cannot
save its old model over the updated files. Preserve local edits and inspect
`git diff -- .idea .run` first. Reopen the repository root, enable Python support
and select the **LSF Python** module SDK. The committed update removes all 24
`LSF-*-windows.run.xml` files and replaces shell entries in their original paths.
Select **LSF - help**, not an old `(Bash)` or `(Windows)` entry.

A local copy may survive in `.idea/workspace.xml` independently of shared files.
In **Run | Edit Configurations**, inspect and remove only obsolete LSF copies
once their unified counterparts work. Do not delete the whole `.idea` directory,
workspace file, shelves, personal configurations or credentials. A stale entry
that prints `bash tools/intellij.sh ...` is not a unified Python configuration.

The initial revision also required the incorrect `com.intellij.sh` plugin ID and
excluded nested source modules. Those defects were fixed before consolidation.
Shell Script (`com.jetbrains.sh`) is now optional. Verify actual source roots
are not excluded in **File | Project Structure | Modules | Sources**; keep cache
exclusions. Ordinary icons on non-JVM modules do not imply missing modules, and
marking the entire repository as Java Sources is not a repair.

Generation needs Python 3.11 or newer; qualification uses the pinned Python.
It reads tracked paths and Cargo manifests, not installed tools or output.
Stage new manifests, regenerate explicitly, and review the diff:

```sh
python3 tools/intellij.py --write
python3 tools/intellij.py --check
python3 -m unittest tools.tests.test_intellij tools.tests.test_intellij_windows -v
```

On Windows use the selected Python executable or `py -3` instead of `python3`.
Edit `tools/intellij.py`, not marked generated XML. `--write` rejects symlinked
and unowned conflicting destinations, removes only stale generator-owned files,
and preserves workspace/personal settings. `--export <new-directory>` creates a
review proposal without changing the checkout. Nothing generates or installs
merely because the project opens.

CI checks deterministic metadata and tests on Linux, Windows and macOS. It
executes direct Python dispatch, retains native Windows terminal-wrapper tests,
and performs real locked website preparation on Windows. Review artifacts
contain only generated metadata, never local settings, credentials or binaries.
Scoped CI contracts are reviewed alongside generator/test/workflow changes.

## Manual IDEA acceptance

Automated XML/dispatch tests do **not** launch IntelliJ IDEA. Before claiming
GUI qualification, record the actual IDE build, plugins and backend, then check:

- Python configuration types resolve; selecting the tools module SDK once makes
  every task use it while Java keeps its JDK. There is exactly one shared entry
  per task and no old platform-specific copies selected.
- Cargo synchronization resolves the maintained workspaces without excluded
  source roots. Prepared Java sources and locked dependencies resolve.
- Help, IDE tests, focused native debugging and the prepared website preview
  run correctly. Switching the terminal shell does not alter Python dispatch.
- Linux node breakpoints work and Stop retires the owned process. Personal
  settings, credentials and compiler output remain absent from `git status`.

A Python configuration's Debug action is not proof of native child debugging.
Keep IDE loading, command execution, process cleanup and runtime acceptance as
separate checks; report only the checks actually performed.
