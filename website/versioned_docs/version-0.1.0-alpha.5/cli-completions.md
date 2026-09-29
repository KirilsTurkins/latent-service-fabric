# Offline shell completions

`latent completions <bash|zsh|fish|powershell>` prints shell source generated from
exactly the Clap command tree used by the installed CLI. It includes nested
commands, global and command-specific options, static enum choices, and local
file/directory hints. Regenerate the script after upgrading `latent`.

```sh
latent completions bash > latent.bash
latent --config /does/not/exist completions fish > latent.fish
```

Neither command opens the configuration path. Generation does not resolve a
profile, read package or provider data, start a Tokio runtime, contact a node or
registry, or run another program. It writes no files itself. Loading the script
installs ordinary shell-local completion rules, not a daemon or a callback into
LSF. Completion offers static grammar and ordinary local paths, not live tenants,
publications, profiles, providers, secrets, or operation IDs.

## Output and errors

Successful stdout contains only the requested script. Its bytes are deterministic
for a given binary and shell, independent of configuration and `--quiet`.
`--quiet` does **not** suppress this payload. `--output human` is accepted, but
`--output json` is rejected with exit code 2, empty stdout, and a fixed diagnostic
on stderr, including when combined with `--quiet`. Shell source is never wrapped
in a JSON outcome document.

Missing or unsupported shell names and extra arguments retain the existing CLI
argument-error behavior (exit 2, including the usual JSON error document when
JSON was requested). Help/version retain their existing successful behavior.
Write, short-write exhaustion, broken-pipe, and flush failures return exit 2;
a write failure may leave a partial script, which must not be installed. The
examples below replace an installed file only after successful generation.

## User-local installation

Use only the section for your shell. All changes below are explicit user actions;
`latent` never edits startup files or installs completion files automatically.
No administrator privileges, release packaging changes, or execution-policy
changes are needed. Review generated code before loading it.

### Bash

```bash
mkdir -p "$HOME/.local/share/latent/completions"
file="$HOME/.local/share/latent/completions/latent.bash"
latent completions bash > "$file.tmp" && mv "$file.tmp" "$file"
source "$file"
```

To load it in new interactive shells, manually add this to `~/.bashrc`:

```bash
[[ ! -r "$HOME/.local/share/latent/completions/latent.bash" ]] ||
    source "$HOME/.local/share/latent/completions/latent.bash"
```

Remove that line and the script to uninstall. `complete -r latent` removes the
registration from the current shell; opening a new shell also clears it.

### Zsh

```zsh
mkdir -p "$HOME/.local/share/zsh/site-functions"
file="$HOME/.local/share/zsh/site-functions/_latent"
latent completions zsh > "$file.tmp" && mv "$file.tmp" "$file"
fpath=("$HOME/.local/share/zsh/site-functions" $fpath)
autoload -Uz compinit
compinit
```

For new shells, manually add the `fpath` line to `~/.zshrc` **before** your existing
`compinit` invocation. Do not add duplicate `compinit` calls. After regeneration,
start a new shell or reload the completion function. Remove `_latent` and your
added `fpath` line to uninstall, then start a new shell; rebuild your existing Zsh
completion cache if it still contains the removed registration.

### Fish

```fish
set -l config_home "$HOME/.config"
if set -q XDG_CONFIG_HOME; and test -n "$XDG_CONFIG_HOME"
    set config_home "$XDG_CONFIG_HOME"
end
mkdir -p "$config_home/fish/completions"
set -l file "$config_home/fish/completions/latent.fish"
latent completions fish > "$file.tmp"; and mv "$file.tmp" "$file"
source "$file"
```

Fish loads this user completion directory automatically; no startup-file change
is required. With a custom Fish configuration directory, use the corresponding
entry in `$fish_complete_path`. Remove the generated file to uninstall, and run
`complete -c latent -e` or start a new shell to clear the loaded rules.

### PowerShell 7+

The pinned upstream PowerShell generator emits command and option names. LSF
adds static enum/path and option-scanning metadata derived from the same Clap
tree; it does not maintain another product-command list. The script uses
PowerShell 7's hashtable JSON reader. Path completion uses literal filesystem
paths, not PowerShell providers or explicit UNC paths, and does not evaluate
expressions typed into the command line.

```powershell
$directory = Join-Path $HOME '.local/share/latent/completions'
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$file = Join-Path $directory 'latent.ps1'
$source = & latent completions powershell
if ($LASTEXITCODE -ne 0) { throw 'Completion generation failed; old file retained.' }
$source | Set-Content -LiteralPath "$file.tmp" -Encoding utf8 -ErrorAction Stop
Move-Item -LiteralPath "$file.tmp" -Destination $file -Force -ErrorAction Stop
. $file
```

For future interactive sessions, manually add this line to the appropriate
PowerShell `$PROFILE` file:

```powershell
. (Join-Path $HOME '.local/share/latent/completions/latent.ps1')
```

Remove that line and the generated file to uninstall, then start a new session
to discard its registered completer. Do not weaken an execution policy to load
this script; follow the policy already in effect on your machine.

## Regeneration and focused checks

Rerun the selected generation/install commands after each CLI upgrade, checking
its exit status before replacing the file, then reload it or start a new shell.
The script corresponds to the binary that generated it, not to a remote node's
version. Shell-specific quoting and path presentation follow the shell generator
and local shell behavior.

From a checkout, the focused proof requires no node startup, Wasm fixture build,
provider integration, or benchmark:

```sh
cargo test --locked -p latent --lib
cargo test --locked -p latent --test completions
cargo fmt --all --check
cargo check --locked -p latent --all-targets
cargo clippy --locked -p latent --all-targets --all-features --no-deps -- -D warnings
```

Use the repository's `rust-toolchain.toml` and install Bash and Fish for Linux
testing. The process suite runs real scripts under `bash --noprofile --norc` and
`fish --no-config` in temporary homes with controlled command paths; neither
script may call `latent` back. Fish positional enum choices are derived from
the same Clap tree, including options before or after the subcommand.
Unit/process tests cover
all four generators, deterministic bytes, nested/global/static values,
test-only grammar extension, offline dispatch, argument errors, and writer and
flush failures. Generation tests alone are not evidence that Zsh or
PowerShell were executed: record those shell executions separately in validation
reports. No issue-specific CI workflow is required.
