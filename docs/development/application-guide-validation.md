# Packaged application guide validation

The user-facing entry is [Application development](../start/application-development.md).
Its Windows walkthrough and Linux/SSH and portable companions implement #568's
application path; #345/#237 retain learning-site and operator-runbook ownership.
The six language pages and their source examples remain owned by #544–#549.

The maintained documentation validator checks displayed frontend commands,
required switches, explicit choices, the six template language selections and
the native Rust toolchain pin against the actual implementation. Its regressions
reject renamed commands, unknown options, omitted required arguments and invalid
environment choices across PowerShell and Bash continuations. This is a static
drift check. It does not establish execution or authentication of the snippets.

The existing website discovery job follows Start to the application choices and
each platform guide on both supported site base paths. It checks reload, headings,
desktop/mobile accessibility, browser errors and 390-pixel reflow. Source excerpt,
link, type and build checks remain in the existing documentation jobs. Automated
browser journeys are separate from an interactive newcomer review.

On September 25, the documented native business-logic command executed against
the maintained Rust greeting on Windows x86-64 with Rust 1.97.1. The one test
`greets_trimmed_names_and_explains_invalid_input` passed. `cargo +1.97.1 test
--locked --manifest-path <author>/app/Cargo.toml` built application code only;
it did not build LSF or invoke a component. This used the existing host toolchain,
so it is supplemental evidence, not a clean-host qualification claim.

| Identity | Observation |
| --- | --- |
| Authenticated template source | `0cb5cf08f1d7eb53650c116c93dcdd4c4a4d6bc3` |
| Template manifest | `sha256:b25f4b76141c7360ef4c2765d7d1d10d876964f1c9c573c2c116721289f54c38` |
| Tested `app/src/lib.rs` | `sha256:c1649b27484ef80cc2f51eca819af450bbb23672b1624f2439c8eff4cb62e2c9` |
| Combined stdout/stderr | `sha256:547968a9e358a162b0402a257574f903d8ed8a1ceaf24fbcefcfca0d071e1b93` |
| Exit | `0`; one passed, zero failed |

The actual generated VS Code tasks, diagnostic failure and source fix are recorded
separately in [editor integration](editor-task-integration.md). The completed
[final qualification handoff](windows-qualification-handoff.md) supplies the
exact-candidate clean-machine walkthrough, independently approved identities and
combined platform review for #568/#569. The static checks, existing-host native
test and source frontend remain separately labeled evidence.
