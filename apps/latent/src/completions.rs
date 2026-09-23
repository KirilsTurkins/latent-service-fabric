//! Ahead-of-time shell source only: no configuration, runtime, filesystem or child processes.

mod fish;
mod powershell;
#[cfg(test)]
mod tests;

use std::io::{self, Write};

use clap::{CommandFactory, ValueEnum};

use crate::args::{Cli, OutputFormat};

#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub enum CompletionShell {
    Bash,
    Zsh,
    Fish,
    #[value(name = "powershell")]
    PowerShell,
}

impl CompletionShell {
    fn generator(self) -> clap_complete::Shell {
        match self {
            Self::Bash => clap_complete::Shell::Bash,
            Self::Zsh => clap_complete::Shell::Zsh,
            Self::Fish => clap_complete::Shell::Fish,
            Self::PowerShell => clap_complete::Shell::PowerShell,
        }
    }
}

pub fn execute(
    shell: CompletionShell,
    format: OutputFormat,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    if format == OutputFormat::Json {
        let _ = writeln!(
            stderr,
            "latent: completions requires shell source output; omit --output json."
        );
        return 2;
    }
    if write_script(shell, Cli::command(), stdout).is_ok() {
        0
    } else {
        let _ = writeln!(
            stderr,
            "latent: completion output could not be generated or written."
        );
        2
    }
}

fn write_script(
    shell: CompletionShell,
    mut command: clap::Command,
    writer: &mut dyn Write,
) -> io::Result<()> {
    let mut bytes = Vec::new();
    let name = command.get_name().to_owned();
    // Upstream's convenience API panics on writer failure. A Vec is an infallible
    // I/O sink; only our checked write_all/flush touches the caller's writer.
    clap_complete::generate(shell.generator(), &mut command, name, &mut bytes);
    if shell == CompletionShell::PowerShell {
        bytes = powershell::augment(&command, bytes)?;
    }
    if shell == CompletionShell::Fish {
        bytes = fish::augment(&command, bytes)?;
    }
    writer.write_all(&bytes)?;
    writer.flush()
}
