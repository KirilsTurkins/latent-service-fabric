//! Bounded operation data. Neither an operation ID nor a digest is authority.
use latent_core::{PlatformError, PublicationId};
use serde::Deserialize;
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeRecoveryRequest {
    pub(super) publication: String,
    pub(super) request: Action,
}

#[derive(Deserialize)]
#[serde(
    tag = "action",
    rename_all = "kebab-case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub(super) enum Action {
    Snapshot {
        operation_id: String,
        file: File,
    },
    InspectNamespace {},
    InspectRestore {
        file: File,
        destination_root: PathBuf,
        operation_id: String,
        snapshot_digest: String,
    },
    Restore {
        file: File,
        destination_root: PathBuf,
        operation_id: String,
        snapshot_digest: String,
        window_acknowledgement: String,
    },
    StageMigration {
        operation_id: String,
        file: File,
        expected_view: Vec<u8>,
        checkpoint_digest: String,
        checkpoint_manifest_digest: String,
    },
    CompleteMigration {
        operation_id: String,
        file: File,
        expected_view: Vec<u8>,
        checkpoint_digest: String,
        checkpoint_manifest_digest: String,
    },
    Review {},
    InspectCloseEffects {
        operation_id: String,
        effect_ids: Vec<String>,
        reason: String,
    },
    CloseEffects {
        operation_id: String,
        plan: latent_effects::recovery_close::ClosePlan,
        acknowledgement: String,
    },
    Resume {
        operation_id: String,
        expected_view: Vec<u8>,
    },
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct File {
    pub root: PathBuf,
    pub name: String,
}

impl NativeRecoveryRequest {
    pub fn decode(bytes: &[u8]) -> Result<Self, PlatformError> {
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(super::super::denied());
        }
        let request: Self = serde_json::from_slice(bytes).map_err(|_| super::super::denied())?;
        request
            .publication
            .parse::<PublicationId>()
            .map_err(|_| super::super::denied())?;
        request.request.validate()?;
        Ok(request)
    }
}
impl Action {
    pub const fn purposes(&self) -> &'static [&'static str] {
        match self {
            Self::Snapshot { .. } => &["namespace-snapshot"],
            Self::InspectNamespace {} => &["namespace-inspect"],
            Self::InspectRestore { .. } => &["namespace-inspect-restore"],
            Self::Restore { .. } => &["namespace-inspect-restore", "namespace-restore"],
            Self::StageMigration { .. } | Self::CompleteMigration { .. } => {
                &["namespace-schema-migrate"]
            }
            Self::Review {} | Self::InspectCloseEffects { .. } | Self::CloseEffects { .. } => {
                &["namespace-review-recovery"]
            }
            Self::Resume { .. } => &["namespace-resume"],
        }
    }
    pub const fn reviewed_open(&self) -> bool {
        !matches!(
            self,
            Self::Snapshot { .. } | Self::InspectRestore { .. } | Self::Restore { .. }
        )
    }
    fn validate(&self) -> Result<(), PlatformError> {
        let identity = |value: &str| {
            latent_core::transaction_contract::identity(value).map_err(|_| super::super::denied())
        };
        match self {
            Self::InspectNamespace {} | Self::Review {} => Ok(()),
            Self::InspectCloseEffects {
                operation_id,
                effect_ids,
                reason,
            } => inspect_close(operation_id, effect_ids, reason),
            Self::CloseEffects {
                operation_id,
                plan,
                acknowledgement,
            } => {
                identity(operation_id)?;
                plan.encode().map_err(|_| super::super::denied())?;
                super::assets::digest_bytes(acknowledgement)?;
                if plan.operation_id != *operation_id {
                    return Err(super::super::denied());
                }
                Ok(())
            }
            Self::Snapshot {
                operation_id,
                file: input,
            } => {
                identity(operation_id)?;
                file(input)
            }
            Self::Resume {
                operation_id,
                expected_view,
            } => {
                identity(operation_id)?;
                view(expected_view)
            }
            Self::StageMigration {
                operation_id,
                file: input,
                expected_view,
                checkpoint_digest,
                checkpoint_manifest_digest,
            }
            | Self::CompleteMigration {
                operation_id,
                file: input,
                expected_view,
                checkpoint_digest,
                checkpoint_manifest_digest,
            } => {
                identity(operation_id)?;
                file(input)?;
                view(expected_view)?;
                super::assets::digest_bytes(checkpoint_digest)?;
                super::assets::digest_bytes(checkpoint_manifest_digest)?;
                Ok(())
            }
            Self::InspectRestore {
                file: input,
                destination_root,
                operation_id,
                snapshot_digest,
            }
            | Self::Restore {
                file: input,
                destination_root,
                operation_id,
                snapshot_digest,
                ..
            } => {
                file(input)?;
                identity(operation_id)?;
                super::assets::digest_bytes(snapshot_digest)?;
                if !destination_root.is_absolute() || destination_root.as_os_str().len() > 4096 {
                    return Err(super::super::denied());
                }
                if let Self::Restore {
                    window_acknowledgement,
                    ..
                } = self
                {
                    super::assets::digest_bytes(window_acknowledgement)?;
                }
                Ok(())
            }
        }
    }
}
fn file(input: &File) -> Result<(), PlatformError> {
    if !input.root.is_absolute()
        || input.root.as_os_str().len() > 4096
        || input.name.is_empty()
        || input.name.len() > 255
        || input.name == "."
        || input.name == ".."
        || !input
            .name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
    {
        return Err(super::super::denied());
    }
    Ok(())
}
fn inspect_close(operation: &str, effects: &[String], reason: &str) -> Result<(), PlatformError> {
    latent_core::transaction_contract::identity(operation).map_err(|_| super::super::denied())?;
    if effects.is_empty()
        || effects.len() > latent_effects::recovery_close::EFFECTS
        || operation.chars().any(char::is_control)
        || reason.is_empty()
        || reason.len() > 128
        || reason.chars().any(char::is_control)
    {
        return Err(super::super::denied());
    }
    for (index, effect) in effects.iter().enumerate() {
        super::assets::digest_bytes(&format!("sha256:{effect}"))?;
        if effects[..index].contains(effect) {
            return Err(super::super::denied());
        }
    }
    Ok(())
}
fn view(bytes: &[u8]) -> Result<(), PlatformError> {
    if bytes.len() == 67 && bytes.starts_with(b"NV\x02") {
        Ok(())
    } else {
        Err(super::super::denied())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_request_refuses_approval_fields_arbitrary_actions_and_malformed_original_view() {
        let publication =
            "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111";
        let valid =
            serde_json::json!({"publication":publication,"request":{"action":"inspect-namespace"}});
        assert!(NativeRecoveryRequest::decode(&serde_json::to_vec(&valid).unwrap()).is_ok());
        for request in [
            serde_json::json!({"action":"execute-guest"}),
            serde_json::json!({"action":"inspect-namespace","approved":true}),
            serde_json::json!({"action":"review","approved":true}),
            serde_json::json!({"action":"resume","operationId":"restore","expectedView":[78,86,2]}),
        ] {
            assert!(NativeRecoveryRequest::decode(
                &serde_json::to_vec(
                    &serde_json::json!({"publication":publication,"request":request})
                )
                .unwrap()
            )
            .is_err());
        }
    }

    #[test]
    fn native_effect_close_inspection_has_finite_original_ids_and_no_request_authority() {
        let publication = format!("publication:sha256:{}", "1".repeat(64));
        let valid = serde_json::json!({"action":"inspect-close-effects","operationId":"close-1",
            "effectIds":["a".repeat(64)],"reason":"explicitly abandon restored uncertain work"});
        let decode = |request| {
            NativeRecoveryRequest::decode(
                &serde_json::to_vec(
                    &serde_json::json!({"publication":publication,"request":request}),
                )
                .unwrap(),
            )
        };
        let accepted = decode(valid.clone()).unwrap();
        assert_eq!(accepted.request.purposes(), &["namespace-review-recovery"]);
        assert!(accepted.request.reviewed_open());
        for (key, value) in [
            ("approved", serde_json::json!(true)),
            ("effectIds", serde_json::json!([])),
            ("effectIds", serde_json::json!(vec!["a".repeat(64); 2])),
            ("effectIds", serde_json::json!(vec!["a".repeat(64); 17])),
            ("effectIds", serde_json::json!(["A".repeat(64)])),
            ("reason", serde_json::json!("request\nchanged")),
            ("operationId", serde_json::json!("close\n1")),
        ] {
            let mut rejected = valid.clone();
            rejected[key] = value;
            assert!(decode(rejected).is_err());
        }
    }
}
