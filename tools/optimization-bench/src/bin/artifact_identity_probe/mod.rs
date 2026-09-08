mod args;
mod fixture;
mod io;
mod model;
mod operation;

#[cfg(test)]
mod tests;

use clap::Parser;

type Result<T> = std::result::Result<T, &'static str>;

pub(super) fn run() -> Result<()> {
    match args::Cli::parse().command {
        args::Command::Fixture(args) => fixture::generate(&args),
        args::Command::Measure(args) => operation::measure(&args),
    }
}
