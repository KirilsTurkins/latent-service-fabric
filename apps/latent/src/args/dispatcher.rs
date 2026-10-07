//! Explicit global node control, preserving the original operation identity.
use crate::error::Failure;
use clap::{Args, Subcommand, ValueEnum};

#[derive(Clone, Copy, ValueEnum)]
pub enum DispatcherScope {
    Node,
}
#[derive(Clone, Copy, ValueEnum)]
pub enum DispatcherAction {
    Pause,
    Resume,
}
#[derive(Args)]
pub struct DispatcherTarget {
    /// Global node scope requires a trusted authenticated node operator.
    #[arg(long, value_enum)]
    pub scope: DispatcherScope,
}
#[derive(Args)]
pub struct DispatcherControlArgs {
    #[command(flatten)]
    pub target: DispatcherTarget,
    #[arg(long)]
    pub operation_id: String,
    #[arg(long)]
    pub expected_owner_epoch: u64,
    #[arg(long)]
    pub expected_revision: u64,
}
#[derive(Args)]
pub struct DispatcherOperationArgs {
    #[command(flatten)]
    pub original: DispatcherControlArgs,
    /// The original action; receipt lookup never executes it again.
    #[arg(long, value_enum)]
    pub original_action: DispatcherAction,
}
#[derive(Subcommand)]
pub enum DispatcherCommand {
    Inspect(DispatcherTarget),
    /// Closes new admission; accepted provider work can still finish.
    Pause(DispatcherControlArgs),
    /// Does not clear pending control, restore review or clock discontinuity.
    Resume(DispatcherControlArgs),
    /// One authenticated receipt lookup with the original action/precondition.
    Operation(DispatcherOperationArgs),
}
impl DispatcherControlArgs {
    fn validate(&self) -> Result<(), Failure> {
        if self.operation_id.is_empty()
            || self.operation_id.len() > 256
            || self.operation_id.chars().any(char::is_control)
            || self.expected_owner_epoch == 0
            || self.expected_revision == 0
            || self.expected_revision == u64::MAX
        {
            return Err(Failure::local(
                "invalid-dispatcher-arguments",
                "Preserve the original bounded operation ID and positive owner epoch/revision.",
            ));
        }
        Ok(())
    }
}
impl DispatcherCommand {
    pub const fn name(&self) -> &'static str {
        match self {
            Self::Inspect(_) => "dispatcher inspect",
            Self::Pause(_) => "dispatcher pause",
            Self::Resume(_) => "dispatcher resume",
            Self::Operation(_) => "dispatcher operation",
        }
    }
    pub fn validate(&self) -> Result<(), Failure> {
        match self {
            Self::Inspect(_) => Ok(()),
            Self::Pause(value) | Self::Resume(value) => value.validate(),
            Self::Operation(value) => value.original.validate(),
        }
    }
}
