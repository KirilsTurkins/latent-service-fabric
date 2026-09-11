use std::path::PathBuf;

use clap::{Args, Parser, Subcommand, ValueEnum};

#[derive(Parser)]
#[command(about = "Bounded artifact identity and catalog recovery probe")]
pub(super) struct Cli {
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Subcommand)]
pub(super) enum Command {
    Fixture(FixtureArgs),
    Measure(MeasureArgs),
}

#[derive(Args)]
pub(super) struct FixtureArgs {
    #[arg(long)]
    pub component: PathBuf,
    #[arg(long)]
    pub capsule: PathBuf,
    #[arg(long)]
    pub contracts: PathBuf,
    /// Must not exist; the probe never overwrites a fixture directory.
    #[arg(long)]
    pub output: PathBuf,
    #[arg(long, value_enum)]
    pub size: Size,
}

#[derive(Clone, Copy, ValueEnum)]
pub(super) enum Size {
    Small,
    #[value(name = "16m")]
    Sixteen,
    #[value(name = "64m")]
    SixtyFour,
}

impl Size {
    pub fn label(self) -> &'static str {
        match self {
            Self::Small => "small",
            Self::Sixteen => "16m",
            Self::SixtyFour => "64m",
        }
    }

    pub fn target(self) -> Option<usize> {
        match self {
            Self::Small => None,
            Self::Sixteen => Some(16 * 1024 * 1024),
            Self::SixtyFour => Some(64 * 1024 * 1024),
        }
    }
}

#[derive(Args)]
pub(super) struct MeasureArgs {
    #[arg(long, value_enum)]
    pub operation: Operation,
    #[arg(long)]
    pub fixture: PathBuf,
    /// Repeated byte-slice hashes only; repository operations require one.
    #[arg(long, default_value_t = 1, value_parser = clap::value_parser!(u32).range(1..=4096))]
    pub iterations: u32,
}

#[derive(Clone, Copy, PartialEq, Eq, ValueEnum)]
pub(super) enum Operation {
    Hash,
    ArtifactOpen,
    CatalogOpen,
}

impl Operation {
    pub fn label(self) -> &'static str {
        match self {
            Self::Hash => "hash",
            Self::ArtifactOpen => "artifact-open",
            Self::CatalogOpen => "catalog-open",
        }
    }

    pub fn boundary(self) -> &'static str {
        match self {
            Self::Hash => "content-digest-byte-slice-repeated",
            Self::ArtifactOpen => "directory-artifact-open-including-recovery",
            Self::CatalogOpen => {
                "directory-artifact-open-and-deployment-open-including-compilation"
            }
        }
    }
}
