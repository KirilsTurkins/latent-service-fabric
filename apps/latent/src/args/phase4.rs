use crate::error::Failure;
use clap::{Args, Subcommand};
use std::path::PathBuf;

#[derive(Args)]
pub struct NamespaceArgs {
    #[arg(long)]
    pub namespace: String,
    /// Positive canonical decimal incarnation, preserved through recovery.
    #[arg(long)]
    pub incarnation: String,
    /// Requested installed current read/write target; knowing its ID grants nothing.
    #[arg(long)]
    pub authorization_publication: String,
}
#[derive(Args)]
pub struct NamespaceMutationArgs {
    #[command(flatten)]
    pub target: NamespaceArgs,
    #[arg(long)]
    pub operation_id: String,
    /// Original expected generation: zero for create, positive for transitions.
    #[arg(long)]
    pub expected_generation: u64,
}
#[derive(Args)]
pub struct ConfigureNamespaceArgs {
    #[command(flatten)]
    pub mutation: NamespaceMutationArgs,
    /// Bounded typed schema/quota document; arbitrary state keys are unsupported.
    #[arg(long,value_hint=clap::ValueHint::FilePath)]
    pub configuration: PathBuf,
}
#[derive(Args)]
pub struct NamespaceOperationArgs {
    #[command(flatten)]
    pub target: NamespaceArgs,
    #[arg(long)]
    pub operation_id: String,
}
#[derive(Args)]
pub struct EntityPageArgs {
    #[command(flatten)]
    pub target: NamespaceArgs,
    #[arg(long,default_value_t=128,value_parser=clap::value_parser!(u32).range(1..=128))]
    pub limit: u32,
    /// Exact opaque canonical padded base64 from the preceding response.
    #[arg(long)]
    pub cursor: Option<String>,
    #[arg(long)]
    pub prefix: Option<String>,
}
#[derive(Subcommand)]
pub enum StateCommand {
    Inspect(NamespaceArgs),
    Create(ConfigureNamespaceArgs),
    Quiesce(NamespaceMutationArgs),
    Retire(NamespaceMutationArgs),
    Destroy(NamespaceMutationArgs),
    Recreate(ConfigureNamespaceArgs),
    /// Look up one original operation ID, including after a lost response.
    Operation(NamespaceOperationArgs),
    Entities(EntityPageArgs),
}

#[derive(Args)]
pub struct CommandArgs {
    #[command(flatten)]
    pub target: NamespaceArgs,
    #[arg(long)]
    pub operation: String,
    #[arg(long)]
    pub client_key: String,
    #[arg(long)]
    pub entity: Option<String>,
    /// Requested host-approved shared/delegated scope; never a credential.
    #[arg(long)]
    pub shared_recovery_scope: Option<String>,
}
#[derive(Args)]
pub struct LookupArgs {
    #[command(flatten)]
    pub command: CommandArgs,
    #[arg(long)]
    pub attempt_id: Option<String>,
}
#[derive(Args)]
pub struct CommitArgs {
    #[command(flatten)]
    pub command: CommandArgs,
    #[arg(long)]
    pub receipt_id: String,
}
#[derive(Args)]
pub struct EffectArgs {
    #[command(flatten)]
    pub command: CommandArgs,
    #[arg(long)]
    pub effect_id: String,
}
#[derive(Args)]
pub struct EffectHistoryArgs {
    #[command(flatten)]
    pub effect: EffectArgs,
    #[arg(long,default_value_t=128,value_parser=clap::value_parser!(u32).range(1..=128))]
    pub limit: u32,
    #[arg(long)]
    pub cursor: Option<String>,
}
#[derive(Args)]
pub struct CancelArgs {
    #[command(flatten)]
    pub lookup: LookupArgs,
    #[arg(long)]
    pub reason: String,
}
#[derive(Subcommand)]
pub enum TransactionCommand {
    Lookup(LookupArgs),
    Commit(CommitArgs),
    Effect(EffectArgs),
    EffectHistory(EffectHistoryArgs),
    /// Requests cancellation; physical retirement remains a separate fact.
    Cancel(CancelArgs),
}

fn invalid() -> Failure {
    Failure::local(
        "invalid-phase4-arguments",
        "Supply one bounded target and preserve the original operation ID and precondition.",
    )
}
fn id(value: &str) -> Result<(), Failure> {
    if value.is_empty() || value.len() > 256 || value.chars().any(char::is_control) {
        Err(invalid())
    } else {
        Ok(())
    }
}
impl NamespaceArgs {
    pub fn validate(&self) -> Result<(), Failure> {
        id(&self.namespace)?;
        let incarnation = self.incarnation.parse::<u64>().map_err(|_| invalid())?;
        if incarnation == 0 || incarnation.to_string() != self.incarnation {
            return Err(invalid());
        }
        self.authorization_publication
            .parse::<latent_core::PublicationId>()
            .map_err(|_| invalid())?;
        Ok(())
    }
}
impl NamespaceMutationArgs {
    fn validate(&self, create: bool) -> Result<(), Failure> {
        self.target.validate()?;
        id(&self.operation_id)?;
        if create != (self.expected_generation == 0) || (create && self.target.incarnation != "1") {
            return Err(invalid());
        }
        Ok(())
    }
}
impl StateCommand {
    pub const fn name(&self) -> &'static str {
        match self {
            Self::Inspect(_) => "state inspect",
            Self::Create(_) => "state create",
            Self::Quiesce(_) => "state quiesce",
            Self::Retire(_) => "state retire",
            Self::Destroy(_) => "state destroy",
            Self::Recreate(_) => "state recreate",
            Self::Operation(_) => "state operation",
            Self::Entities(_) => "state entities",
        }
    }
    pub fn validate(&self) -> Result<(), Failure> {
        match self {
            Self::Inspect(v) => v.validate(),
            Self::Create(v) => v.mutation.validate(true),
            Self::Recreate(v) => v.mutation.validate(false),
            Self::Quiesce(v) | Self::Retire(v) | Self::Destroy(v) => v.validate(false),
            Self::Operation(v) => {
                v.target.validate()?;
                id(&v.operation_id)
            }
            Self::Entities(v) => {
                v.target.validate()?;
                if v.cursor.as_ref().is_some_and(|v| v.len() > 344)
                    || v.prefix.as_ref().is_some_and(|v| v.len() > 344)
                {
                    return Err(invalid());
                }
                Ok(())
            }
        }
    }
}
impl CommandArgs {
    pub fn validate(&self) -> Result<(), Failure> {
        self.target.validate()?;
        for value in [
            Some(&self.operation),
            Some(&self.client_key),
            self.entity.as_ref(),
            self.shared_recovery_scope.as_ref(),
        ]
        .into_iter()
        .flatten()
        {
            latent_core::transaction_contract::identity(value).map_err(|_| invalid())?;
        }
        Ok(())
    }
}
impl TransactionCommand {
    pub const fn name(&self) -> &'static str {
        match self {
            Self::Lookup(_) => "transaction lookup",
            Self::Commit(_) => "transaction commit",
            Self::Effect(_) => "transaction effect",
            Self::EffectHistory(_) => "transaction effect-history",
            Self::Cancel(_) => "transaction cancel",
        }
    }
    pub fn validate(&self) -> Result<(), Failure> {
        match self {
            Self::Lookup(v) => {
                v.command.validate()?;
                v.attempt_id.as_ref().map_or(Ok(()), |v| id(v))
            }
            Self::Commit(v) => {
                v.command.validate()?;
                id(&v.receipt_id)
            }
            Self::Effect(v) => {
                v.command.validate()?;
                id(&v.effect_id)
            }
            Self::EffectHistory(v) => {
                v.effect.command.validate()?;
                id(&v.effect.effect_id)?;
                if v.cursor.as_ref().is_some_and(|v| v.len() > 344) {
                    return Err(invalid());
                }
                Ok(())
            }
            Self::Cancel(v) => {
                v.lookup.command.validate()?;
                v.lookup.attempt_id.as_ref().map_or(Ok(()), |v| id(v))?;
                if v.reason.is_empty()
                    || v.reason.len() > 1024
                    || v.reason.chars().any(char::is_control)
                {
                    return Err(invalid());
                }
                Ok(())
            }
        }
    }
}
