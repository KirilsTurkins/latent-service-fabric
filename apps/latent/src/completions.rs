//! Ahead-of-time shell source only: no configuration, runtime, filesystem or child processes.

mod powershell;
#[cfg(test)]
mod tests;

use std::io::{self, Write};

use clap::{CommandFactory, ValueEnum};

use crate::args::{Cli, OutputFormat};

#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub enum Shell {
    Bash,
    Zsh,
    Fish,
    #[value(name = "powershell")]
    PowerShell,
}

impl Shell {
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
    shell: Shell,
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
    match write_script(shell, Cli::command(), stdout) {
        Ok(()) => 0,
        Err(_) => {
            let _ = writeln!(
                stderr,
                "latent: completion output could not be generated or written."
            );
            2
        }
    }
}

fn write_script(
    shell: Shell,
    mut command: clap::Command,
    writer: &mut dyn Write,
) -> io::Result<()> {
    let mut bytes = Vec::new();
    let name = command.get_name().to_owned();
    // Upstream's convenience API panics on writer failure. A Vec is an infallible
    // I/O sink; only our checked write_all/flush touches the caller's writer.
    clap_complete::generate(shell.generator(), &mut command, name, &mut bytes);
    if shell == Shell::PowerShell {
        bytes = powershell::augment(&command, bytes)?;
    }
    writer.write_all(&bytes)?;
    writer.flush()
}
