# IntelliJ IDEA 2026

Open the **repository root directory**, not just `sdk/java-client` or an
individual Cargo manifest. The committed `.idea/` project model and `.run/`
configurations make the polyglot repository visible without a generation step.
This is contributor tooling for the source checkout, not part of the packaged
SDK or a new application execution model.

## First open

1. Install the selected tools from [the toolchain guide](toolchain.md). Use a
   Linux checkout, WSL2 Linux filesystem, or a Linux remote-development backend
   for the native runtime and complete validation. Configure and launch IDEA
   with that environment's `PATH` and `JAVA_HOME`; a desktop launcher may not
   inherit your interactive shell environment. Website work can use native
   Windows; it does not require a WSL distribution or Git Bash.
2. Open the root folder and review IDEA's trust prompt. Accept the project's
   **Rust** plugin requirement (`com.jetbrains.rust`) and restart when requested.
   **Shell Script** (`com.jetbrains.sh`) is bundled and enabled in IDEA by default;
   enable it under **Settings | Plugins | Installed** if it was disabled.
   Use the current JetBrains Rust plugin, not the deprecated IntelliJ Rust
   plugin. Java/Kotlin support is part of IDEA; Python, Go, JavaScript/TypeScript,
   Protobuf and TOML support depend on the installed plugins and license.
   Install only the additional language plugins needed for your work.
3. Let the Rust plugin synchronize the attached Cargo workspaces. Select the
   rustup toolchain and install `rust-src` for the pinned toolchain when IDEA
   offers it. The root `rust-toolchain.toml`, not a copied IDE version, owns the
   Rust version and component targets. Cargo synchronization can resolve
   dependencies and execute build scripts after the project is trusted.
4. For Java client work, add the exact Temurin JDK from the toolchain guide to
   IDEA's SDK table and select it as the project SDK. Match `JAVA_HOME` to the
   same installation. Run **LSF - java-client-prepare (Windows)** or the
   **(Bash)** variant for your environment explicitly to download
   verified locked dependencies and generate Protobuf sources. Preparation is
   not compilation or a passing SDK qualification. Java sources target Java 25.
5. Prepare `.venv` with the pinned Python and `tools/requirements.lock` as in the
   toolchain guide. On Windows, `tools/intellij.cmd` chooses `LSF_IDE_PYTHON`,
   then `.venv/Scripts/python.exe`, then `py.exe -3`, then `python.exe` on `PATH`.
   An explicit Python path is one executable, not a command with flags; a broken
   explicit selection fails rather than falling back. Bash uses `intellij.sh`
   and its existing Python selection. No Python IDE plugin is required to run
   the configurations. Select `.venv` separately for Python editing/debugging.
6. Choose **LSF - ide-doctor (Windows)** in a native Windows project or
   **LSF - ide-doctor (Bash)** in a Bash environment. It checks command availability
   and project-metadata drift without installing anything. **LSF -
   toolchain-check (Bash)** performs the existing full pinned-toolchain check; install
   its prerequisites first. These checks cannot inspect your IDE license,
   plugin enablement, indexing state or SDK selection.

IDEA's [Rust guide](https://www.jetbrains.com/help/idea/rust-plugin.html),
[Shell Script guide](https://www.jetbrains.com/help/idea/shell-scripts.html),
[required-plugin guide](https://www.jetbrains.com/help/idea/managing-plugins.html)
and [shared run-configuration guide](https://www.jetbrains.com/help/idea/run-debug-configuration.html)
explain the IDE-side steps. In the 2026 documentation, native Rust debugging on
Linux and Windows additionally requires **Native Debugging Support**; macOS
uses LLDB. Installing a plugin or choosing an SDK requires the user's consent
and cannot be completed by checking in project XML.

## Project and language views

The Project view contains a root module, Cargo workspace members, independent
non-fixture Cargo workspaces, each SDK directory, tools, website, examples,
research and documentation. Module groups separate these areas. Nested content
roots define their own module ownership; parent modules must **not** exclude
child module roots. An exclusion is not an ownership marker: it gives real source
directories the excluded-folder presentation and can affect IDE features.
The Cargo tool window, rather than the Java module model, owns Rust
target/dependency discovery. New workspace members and SDK directories are
picked up by the generator. Templates, test fixtures and vendored inputs remain
browsable through their owning modules; they are not attached as independent
Cargo projects. See JetBrains' [content-root guide](https://www.jetbrains.com/help/idea/content-roots.html)
for source and excluded-folder categories.

The Java client module marks `src/transport/java`, `src/example/java` and
`build/generated/java` as production sources, and `src/transportTest/java` as
tests. Its library directory uses the JARs produced under `build/deps` by the
existing locked preparation helper. There is no second Maven dependency graph,
unpinned Gradle download, or IDE-owned Protobuf generator. The existing optional
Gradle build remains available from a separate Java-client project; do not
import it over these generated module files and commit the resulting local
project-model replacement.

Java guest compiler/runtime replacement sources and conformance fixtures are
not flattened into one misleading JVM module. The owning guest SDK tooling
still controls compilation. Likewise, a visible C or .NET source module does
not turn IDEA into CLion or Rider. Optional language plugins provide their
supported editing features; the existing SDK command runners remain the build
and test authority. See [guest authoring](../component-development/guest-sdk.md)
and [build foundation](build-foundation.md).

Caches and compiler output are excluded from indexing: Cargo targets,
`node_modules`, virtual environments, Python bytecode, Gradle/Zig caches,
website output and SDK-specific compiler directories. Source directories named
`bin` or `build` are not globally hidden. Java generated sources stay indexed.
The existing root `.editorconfig` and owning formatters remain authoritative.
No save action rewrites generated sources or byte-sensitive fixtures.

## Shared run configurations

Configurations are permanent and run from the repository root even when another
file or module is selected. Choose the suffix matching the actual terminal:
**(Windows)** for PowerShell or Command Prompt, **(Bash)** for Bash on Linux,
macOS or an explicitly configured Linux backend. They have separate `LSF /
Windows` and `LSF / Bash` groups. A bare `bash` in native Windows can select the
Windows WSL launcher instead of Git Bash; the Windows configurations never call
it. There is no need to change your default WSL distribution or terminal shell.

Windows configurations invoke `cmd.exe /d /c tools\intellij.cmd <task>` in
script-text mode. The batch launcher selects Python without Bash or Make.
The Bash variants retain the existing Make/SDK commands. Neither stores a local
interpreter installation path. A personal override should use a new name without
the `LSF-` file prefix. The table lists the complete Bash workflow; native Windows
has help, tree, IDE/source checks, metadata-only test listing, Rust formatting,
Java client commands and website tasks. Broad workspace/runtime/contracts tasks
remain in the declared Linux/Bash environment and fail with an explanation when
requested through the native Windows dispatcher; they never start WSL for you.

| Group | Available work |
| --- | --- |
| Start here | Make help, tracked tree, IDE diagnostics and full toolchain checks |
| Source checks | Source/schema/docs/CI validation and read-only IDE drift check |
| Rust | Format, formatting check, workspace and production checks, bindings, Clippy and MSRV |
| Tests | Deterministic tests, suite catalogue, Python repository tests and IDE regressions |
| Contracts and SDKs | Every existing contract lane, external-client SDK aggregate, Java client build/test |
| Explicit preparation | Echo fixture and reproducibility, Java client inputs and private local-node state |
| Website | Dependency preparation, development server, source/unit checks, both production mounts and browser validation |
| Native debug | `latent`, `latentd` and `latent-control` help, `latent-core` unit tests and a local node |
| Full Linux validation | The existing broad Make aggregate with a fresh owned output root for each invocation |

The website development server uses the repository's prepared npm, not an
ambient package manager. Run **website-prepare** before **website-start**, choosing
the appropriate platform suffix. Only the explicit **website-prepare** and
**website-browser-install** tasks install website inputs.

### Native Windows website setup and WSL launcher errors

If PowerShell reports `WSL ... execvpe(/bin/bash) failed`, the failure occurred
before `intellij.sh` started. Updating a Linux distribution is not a prerequisite
for website work. Close IDEA before pulling the corrected branch, reopen the
root, and choose **LSF - help (Windows)** and
**LSF - website-prepare (Windows)** instead of the **(Bash)** variants. No IDE
settings deletion, global PATH rewrite or PowerShell execution-policy change is
needed. From PowerShell at the repository root the equivalent commands are:

```powershell
.\tools\intellij.cmd help
.\tools\intellij.cmd website-prepare
```

Run the second command only after the first succeeds. Python 3.11 or newer and
the pinned Node installation must already be available. The Windows launcher
also works when the checkout or selected Python is in a directory with spaces.
It preserves the child's exit code and stops preparation on the first failure.
Native Windows IDE diagnostics do not treat Bash/Make as required tools.

Website preparation checks Node against `website/package.json`, runs the existing
authenticated archive preparer, installs the separate `website/toolchain` package
with bootstrap npm, verifies the installed npm bundle, then uses that bundle for
locked website installation. Lifecycle scripts remain disabled. The native
adapter runs npm's `npm-cli.js` through Node rather than executing a `.cmd` file
through Python's shell handling. For an unusual npm installation, set
`LSF_IDE_BOOTSTRAP_NPM_CLI` to the existing bootstrap `npm-cli.js` path; an invalid
explicit path is an error. This does not change global npm or the repository pins.

After preparation, use **LSF - website-start (Windows)** for the preview.
IDEA's generic **Run npm install** action is separate: under **Settings |
Languages & Frameworks | JavaScript Runtime**, select the custom package manager
at `website\toolchain\node_modules\npm`, not global `npm.cmd`. Repository
preparation should still use **website-prepare**, which uses `npm ci` and creates
the authenticated archives first. Do not disable `engine-strict`, delete the
lockfile or substitute upstream npm just because its version string matches.
See [website development](website.md) for the prepared-distribution boundary and
JetBrains' [package-manager settings](https://www.jetbrains.com/help/idea/installing-and-removing-external-software-using-node-package-manager.html).

For a specific registered suite or case, use [the local test entry point](local-tests.md)
and [Make commands](make-commands.md) in the IDE terminal. There is intentionally
no one-click `cargo test --workspace` or unconfigured prepared-test run. Exact
suite selection and the same explicitly prepared inventory must be supplied.
Full validation requires a clean tracked Linux checkout; generated IDE files
are source, not an exemption from that rule. [VALIDATION.md](../../VALIDATION.md)
defines acceptance; a successful IDE run is only the command it actually ran.

### Run and debug a local node

On Linux/WSL, explicitly run **LSF - ide-node-prepare (Bash)**, then **LSF - local-node**
with Run or Debug. Preparation creates a new private `target/ide/node/` with
owner-only files, a random token and matching node/client configurations. It
never starts a process, opens a listener, overwrites prior state or prints the
token. The node binds only `127.0.0.1:43170`; a port conflict must fail rather
than silently selecting a different service. Change both local JSON files to
use another free loopback port when necessary.

This is the [trusted-local quickstart](standalone-quickstart.md) configuration,
not production deployment or signed-admission qualification. The credential
has the `operator` role in the `examples` tenant. Keep the private directory
for restart and stop the debug session before another run. Use the matching
`target/ide/node/client.json` with the CLI and the quickstart's commands. Never
commit that directory, copy its token into a shared run configuration, or point
a shared configuration at a production node. Package generation, publication,
deployment and readiness verification remain explicit quickstart steps.

Windows and macOS can browse the project and use supported host tools, but they
are not native Linux runtime qualification. Git Bash is not WSL and does not
make a Windows Cargo toolchain build the Linux daemon. Use a Linux IDE backend
for runtime work, and the documented [portable subset](../component-development/portable-tests.md)
for supported non-Linux checks.

## Maintaining and recovering project settings

Generation needs Python 3.11 or newer for `tomllib`; repository qualification
uses the pinned Python. It reads Git's tracked file list and Cargo manifests,
not installed tools or ignored build output. Stage new manifests before
regenerating, then review the resulting diff:

```sh
python3 tools/intellij.py --write
python3 tools/intellij.py --check
python3 -m unittest tools.tests.test_intellij tools.tests.test_intellij_windows -v
```

Edit `tools/intellij.py`, not its marked generated XML. `--write` refuses
symlinked destinations and unowned conflicting files, removes only stale files
carrying its ownership marker, and preserves workspace settings and personal
run configurations. `--export <new-directory>` writes a review proposal without
modifying the checkout. No automatic startup task runs generation or builds.

Existing IDEA users should close the project before adopting the shared model.
Back up conflicting personal `.idea/modules.xml`, `misc.xml` or similarly named
files outside the checkout, then review the tracked replacements and reopen
the root. Do not delete the whole `.idea` directory or overwrite unrelated
settings. Git ignores workspace state, shelves, local caches and non-LSF run
configurations. Keep machine-specific JDK/toolchain changes local when reviewing
the tracked `misc.xml` diff.

### Repair the initial plugin warning and brown module folders

The initial PR #1049 configuration mistakenly required `com.intellij.sh` (an
implementation package, not the plugin ID) and explicitly excluded child module
roots from their parents. These are repository configuration defects, not a
reason to downgrade IDEA or install an obsolete plugin archive.

Close the project before pulling the corrected branch so the open IDE cannot
save its old model over the updated files. Preserve any local edits and review
`git diff -- .idea` before updating. The fix updates the generator,
`.idea/externalDependencies.xml` and the root, SDK, Rust-standard-runtime and
tools module files together. Reopen the repository root after updating and let
Cargo synchronization finish. Normal adoption needs no regeneration; use
`python3 tools/intellij.py --check` in the terminal to check for stale XML.

Under **Settings | Plugins | Installed**, enable the bundled **Shell Script**
plugin if needed. The project's required ID is `com.jetbrains.sh`; there should
be no requirement for `com.intellij.sh` under **Appearance & Behavior | Required
Plugins**. JetBrains' [Shell Script plugin descriptor](https://github.com/JetBrains/intellij-community/blob/master/plugins/sh/plugin/resources/META-INF/plugin.xml)
is the source of that identity, distinct from its `com.intellij.sh` Java classes.

Under **File | Project Structure | Modules | Sources**, verify that actual
source module roots are not excluded. Cache/output folders should remain
excluded. Do not mark the entire repository as Java Sources or disable all
exclusions just to change folder colors. Documentation and non-JVM modules can
have ordinary folder icons; their icon is not proof of a missing module. The
module list and Cargo tool window are the relevant structure checks. If old
exclusions persist, inspect local `.iml` changes, preserve personal settings,
and regenerate only the generator-owned files with IDEA closed. Do not delete
workspace settings, shelves, credentials or the entire `.idea` directory.

CI checks deterministic metadata and regression tests on Linux, Windows and
macOS. The Windows matrix entry additionally executes the real batch launcher
and its exact generated command through PowerShell, with Bash/Make absent from
the test PATH, checks paths with spaces and child failure propagation, and runs
actual locked website preparation using the website's pinned Node runtime.
These command-line checks still do not launch the IntelliJ GUI. The review
artifact contains only generator output, never the local
`.idea` directory, credentials, environment variables or compiled artifacts.
Generation drift is a failure; CI does not automatically approve or commit
replacement settings. The owning CI contract fragments are reviewed alongside
changes to the generator, launcher, tests or workflow.

## Manual IDEA acceptance

The automated tests validate file structure, module ownership, regeneration,
command selection and safety behavior; they do **not** launch IntelliJ IDEA.
Before claiming GUI qualification for an IDEA 2026 build, open a fresh clone
with its supported plugins and verify the following in that actual IDE:

- Shell Script is recognized as the bundled plugin without an unavailable-plugin
  install prompt; shared Shell Script configurations have a recognized type.
- Cargo synchronization resolves the root and independent maintained workspaces;
  the Project and Cargo views show the expected packages without duplicate roots.
  Real source module roots are not marked as excluded in Project Structure.
- After Java preparation and JDK selection, generated Java classes and locked
  dependencies resolve, and the owning Java test configuration executes.
- In a native Windows checkout with PowerShell, **help (Windows)** and
  **website-prepare (Windows)** work without a WSL/Bash process or global npm
  engine error. **website-start (Windows)** opens the intended loopback preview.
- Run configurations appear before manually creating any; Make help, IDE tests,
  a focused Rust debug session and the prepared website server work from the root.
- On Linux, the explicit local-node preparation/run/debug sequence starts the
  intended loopback node, breakpoints resolve, and Stop retires that process.
- Personal workspace changes, tokens, caches and build output do not appear as
  new files in `git status`; no task started merely by opening the project.

Record the IDE build, enabled plugins, host/backend and actual results. A passing
XML or Python test alone must not be reported as that GUI acceptance.
