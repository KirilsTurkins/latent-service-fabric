use clap::{Args, Subcommand};
use std::path::PathBuf;

#[derive(Subcommand)]
pub enum RolloutCommand {
    Start(StartArgs),
    Get(super::management::IdArgs),
    List(ListArgs),
    Operation(OperationArgs),
    Advance(StepArgs),
    Pause(ChangeArgs),
    Resume(ChangeArgs),
    Abort(ChangeArgs),
    Evaluate(EvaluateArgs),
    Promote(StepArgs),
    Rollback(RollbackArgs),
}

#[derive(Args)]
pub struct StartArgs {
    pub id: String,
    #[arg(long)]
    pub base: String,
    #[arg(long, value_parser = clap::value_parser!(u64).range(1..))]
    pub expected_base_generation: u64,
    #[arg(long)]
    pub candidate: PathBuf,
    #[arg(long, value_delimiter = ',', num_args = 1, value_parser = clap::value_parser!(u32).range(1..=10000))]
    pub weights: Vec<u32>,
    #[arg(long)]
    pub operation_id: String,
    #[arg(long, value_parser = clap::value_parser!(u64).range(0..=0))]
    pub expected_revision: u64,
    #[arg(long)]
    pub canary_policy: Option<PathBuf>,
}
#[derive(Args)]
pub struct ChangeArgs {
    pub id: String,
    #[arg(long)]
    pub operation_id: String,
    #[arg(long, value_parser = clap::value_parser!(u64).range(1..))]
    pub expected_revision: u64,
}
#[derive(Args)]
pub struct StepArgs {
    #[command(flatten)]
    pub change: ChangeArgs,
    #[arg(long, value_parser = clap::value_parser!(u32).range(1..=63))]
    pub next_step: u32,
}
#[derive(Args)]
pub struct RollbackArgs {
    #[command(flatten)]
    pub change: ChangeArgs,
    #[arg(long, value_parser = clap::value_parser!(u64).range(1..))]
    pub target_generation: u64,
}
#[derive(Args)]
pub struct EvaluateArgs {
    pub id: String,
    #[arg(long, value_parser = clap::value_parser!(u64).range(1..))]
    pub expected_revision: u64,
}
#[derive(Args)]
pub struct OperationArgs {
    pub id: String,
    pub operation_id: String,
}
#[derive(Args)]
pub struct ListArgs {
    #[arg(long)]
    pub service: Option<String>,
    #[arg(long, value_parser = ["running", "paused", "completed", "aborted", "conflicted", "rolled-back"])]
    pub state: Option<String>,
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u32).range(..=128))]
    pub page_size: u32,
    #[arg(long)]
    pub page_token: Option<String>,
}
