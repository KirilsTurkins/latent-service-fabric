use base64::Engine;
use latent_activation::{ActivationOutcome, ActivationSuccess};
use latent_commit::atomic::{CommandRecord, DurableResult, Outcome};
use latent_core::{
    transaction_contract::Value, BudgetConsumption, DeclaredError, Metadata, PlatformError,
    PlatformErrorCode,
};

use super::errors::fixed;

/// The trusted application/HTTP adapter validates its complete portable response
/// before handing a result to the business writer. These values grant no commit.
pub enum CommandOutput {
    Success(Value),
    Rejection { code: String, value: Value },
}
pub trait CommandResultCodec: Send + Sync {
    fn format(&self) -> &str;
    fn validate(&self, outcome: &ActivationOutcome) -> Result<CommandOutput, PlatformError>;
    fn replay(
        &self,
        record: &CommandRecord,
        result: &DurableResult,
        consumption: BudgetConsumption,
    ) -> Result<ActivationOutcome, PlatformError>;
}

/// Ordinary typed results retain guest business data. Framework/cell metadata
/// is excluded. HTTP bindings supply their approved response validator/codec.
pub struct CanonicalCommandResult;
const MESSAGE: &str = "lsf-declared-error-message";
impl CommandResultCodec for CanonicalCommandResult {
    fn format(&self) -> &'static str {
        "lsf-wit-values-v1"
    }
    fn validate(&self, outcome: &ActivationOutcome) -> Result<CommandOutput, PlatformError> {
        let output = match outcome {
            ActivationOutcome::Succeeded(success) => CommandOutput::Success(Value {
                bytes: success.output.clone(),
                media_type: success.output_media_type.clone(),
                metadata: vec![],
            }),
            ActivationOutcome::DeclaredError { error, .. } => {
                if error.metadata.contains_key(MESSAGE) || error.message.len() > 1024 {
                    return Err(fixed(
                        PlatformErrorCode::InvalidArgument,
                        "invalid-command-result",
                    ));
                }
                let mut metadata: Vec<_> = error
                    .metadata
                    .iter()
                    .map(|(key, value)| (key.clone(), value.clone()))
                    .collect();
                metadata.push((MESSAGE.into(), error.message.clone()));
                CommandOutput::Rejection {
                    code: error.code.clone(),
                    value: Value {
                        bytes: error.payload.clone(),
                        media_type: error.media_type.clone(),
                        metadata,
                    },
                }
            }
            ActivationOutcome::Failed { error, .. } => return Err(error.clone()),
        };
        let value = match &output {
            CommandOutput::Success(value) | CommandOutput::Rejection { value, .. } => value,
        };
        value
            .validate()
            .map_err(|_| fixed(PlatformErrorCode::ResourceExhausted, "command-result-bound"))?;
        Ok(output)
    }
    fn replay(
        &self,
        record: &CommandRecord,
        result: &DurableResult,
        consumption: BudgetConsumption,
    ) -> Result<ActivationOutcome, PlatformError> {
        if record.source().result_format != self.format() {
            return Err(fixed(
                PlatformErrorCode::IncompatibleContract,
                "original-command-result-format-unavailable",
            ));
        }
        result.verify(record).map_err(super::errors::atomic)?;
        let value = result.value().ok_or_else(|| {
            fixed(
                PlatformErrorCode::Unavailable,
                "original-command-receipt-only",
            )
        })?;
        match result.outcome() {
            Outcome::Committed => Ok(ActivationOutcome::Succeeded(ActivationSuccess {
                output: value.bytes.clone(),
                output_media_type: value.media_type.clone(),
                consumption,
                committed_state_version: committed_view_text(record),
                effect_ids: record.effect_ids().iter().map(|id| id.hex()).collect(),
                metadata: Metadata::new(),
            })),
            Outcome::Rejected => {
                let mut metadata: Metadata = value.metadata.iter().cloned().collect();
                let message = metadata.remove(MESSAGE).ok_or_else(|| {
                    fixed(
                        PlatformErrorCode::CorruptArtifact,
                        "original-command-rejection-format-invalid",
                    )
                })?;
                Ok(ActivationOutcome::DeclaredError {
                    error: DeclaredError {
                        code: result
                            .code()
                            .ok_or_else(|| {
                                fixed(
                                    PlatformErrorCode::CorruptArtifact,
                                    "original-command-rejection-format-invalid",
                                )
                            })?
                            .into(),
                        message,
                        payload: value.bytes.clone(),
                        media_type: value.media_type.clone(),
                        metadata,
                    },
                    consumption,
                })
            }
            _ => Err(fixed(
                PlatformErrorCode::Unavailable,
                "original-command-not-replayable",
            )),
        }
    }
}

pub(super) fn committed_view_text(record: &CommandRecord) -> Option<String> {
    record
        .committed_view_token()
        .map(|token| base64::engine::general_purpose::STANDARD.encode(token))
}
