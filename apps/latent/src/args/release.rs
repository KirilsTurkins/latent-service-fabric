use clap::Args;
use std::path::PathBuf;

#[derive(Args, Default)]
pub struct OptionalReleaseOperation {
    #[arg(long, requires = "expected_generation")]
    pub operation_id: Option<String>,
    #[arg(long, requires = "operation_id", value_parser = clap::value_parser!(u64).range(0..=0))]
    pub expected_generation: Option<u64>,
}

#[derive(Args)]
pub struct ReleaseMutation {
    #[arg(long)]
    pub operation_id: String,
    #[arg(long, value_parser = clap::value_parser!(u64).range(1..))]
    pub expected_generation: u64,
}

#[derive(Args)]
pub struct ChangeReleaseArgs {
    pub digest: String,
    #[command(flatten)]
    pub operation: ReleaseMutation,
}

#[derive(Args)]
pub struct PublishPackageArgs {
    pub directory: PathBuf,
    /// Bounded sibling evidence index. Omission submits no detached evidence.
    #[arg(long)]
    pub evidence: Option<PathBuf>,
    #[arg(long)]
    pub operation_id: String,
    #[arg(long, value_parser = clap::value_parser!(u64).range(0..=0))]
    pub expected_generation: u64,
}

#[derive(Args)]
pub struct RenewEvidenceArgs {
    pub digest: String,
    #[arg(long)]
    pub package_digest: String,
    #[arg(long)]
    pub evidence: PathBuf,
    #[command(flatten)]
    pub operation: ReleaseMutation,
}
