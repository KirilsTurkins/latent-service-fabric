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
    #[command(flatten)]
    pub selector: super::management::DigestArgs,
    #[command(flatten)]
    pub operation: ReleaseMutation,
}

#[derive(Args)]
pub struct PublishPackageArgs {
    #[arg(value_hint = clap::ValueHint::DirPath)]
    pub directory: PathBuf,
    /// Bounded sibling evidence index. Omission submits no detached evidence.
    #[arg(long, value_hint = clap::ValueHint::FilePath)]
    pub evidence: Option<PathBuf>,
    #[arg(long)]
    pub operation_id: String,
    #[arg(long, value_parser = clap::value_parser!(u64).range(0..=0))]
    pub expected_generation: u64,
}

#[derive(Args)]
pub struct RenewEvidenceArgs {
    #[command(flatten)]
    pub selector: super::management::DigestArgs,
    #[arg(long)]
    pub package_digest: String,
    #[arg(long, value_hint = clap::ValueHint::FilePath)]
    pub evidence: PathBuf,
    #[command(flatten)]
    pub operation: ReleaseMutation,
}
