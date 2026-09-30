//! Opt-in Phase 4 companion declaration. Structural checks grant no authority.

use std::collections::BTreeSet;

use latent_core::transaction_contract::identity;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TransactionOperation {
    pub operation: String,
    pub mode: TransactionOperationMode,
    pub input_format: String,
    pub result_format: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum TransactionOperationMode {
    StrictCommand,
    FreshQuery,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TransactionBinding {
    pub api_version: String,
    pub kind: String,
    pub capsule: String,
    pub deployment: String,
    pub binding: String,
    pub profile: String,
    pub host_abi_digest: String,
    pub namespace: String,
    pub state_schema: String,
    pub operations: Vec<TransactionOperation>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransactionBindingError {
    Size,
    Format,
    UnsupportedProfile,
    InvalidIdentity,
    InvalidDigest,
    InvalidOperations,
    LinkMismatch,
}

#[must_use]
pub fn phase4_host_abi_digest() -> String {
    let mut hash = Sha256::new();
    latent_core::PHASE4_HOST_ABI_V1.visit_identity_bytes(|part| hash.update(part));
    let bytes: [u8; 32] = hash.finalize().into();
    let mut digest = String::with_capacity(71);
    digest.push_str("sha256:");
    for byte in bytes {
        use std::fmt::Write;
        write!(digest, "{byte:02x}").expect("writing to a String cannot fail");
    }
    digest
}

impl TransactionBinding {
    /// Decode a finite companion document. This is deliberately separate from
    /// the supported stateless `ManifestDocument` codec and engine admission.
    pub fn decode(bytes: &[u8]) -> Result<Self, TransactionBindingError> {
        if bytes.len() > 128 * 1024 {
            return Err(TransactionBindingError::Size);
        }
        let declaration: Self =
            serde_json::from_slice(bytes).map_err(|_| TransactionBindingError::Format)?;
        declaration.validate()?;
        Ok(declaration)
    }

    pub fn validate(&self) -> Result<(), TransactionBindingError> {
        if self.api_version != "latent.dev/v1" || self.kind != "TransactionBinding" {
            return Err(TransactionBindingError::Format);
        }
        if self.profile != latent_core::transaction_contract::PROFILE
            || self.host_abi_digest != phase4_host_abi_digest()
        {
            return Err(TransactionBindingError::UnsupportedProfile);
        }
        for value in [
            &self.capsule,
            &self.deployment,
            &self.binding,
            &self.namespace,
        ] {
            identity(value).map_err(|_| TransactionBindingError::InvalidIdentity)?;
        }
        if self.state_schema.len() != 71
            || !self.state_schema.starts_with("sha256:")
            || !self.state_schema[7..]
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(TransactionBindingError::InvalidDigest);
        }
        if self.operations.is_empty() || self.operations.len() > 128 {
            return Err(TransactionBindingError::InvalidOperations);
        }
        let mut names = BTreeSet::new();
        for operation in &self.operations {
            for value in [
                &operation.operation,
                &operation.input_format,
                &operation.result_format,
            ] {
                identity(value).map_err(|_| TransactionBindingError::InvalidIdentity)?;
            }
            if !names.insert(&operation.operation) {
                return Err(TransactionBindingError::InvalidOperations);
            }
        }
        Ok(())
    }

    /// Inspect exact declared links at admission. This check is neither a
    /// namespace authorization check nor proof that a runtime is installed.
    pub fn check_links(
        &self,
        capsule: &str,
        deployment: &str,
        binding: &str,
    ) -> Result<(), TransactionBindingError> {
        self.validate()?;
        if (
            self.capsule.as_str(),
            self.deployment.as_str(),
            self.binding.as_str(),
        ) != (capsule, deployment, binding)
        {
            return Err(TransactionBindingError::LinkMismatch);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn declaration() -> TransactionBinding {
        TransactionBinding {
            api_version: "latent.dev/v1".into(),
            kind: "TransactionBinding".into(),
            capsule: "capsule".into(),
            deployment: "deployment".into(),
            binding: "binding".into(),
            profile: "lsf-transaction-v1".into(),
            host_abi_digest: phase4_host_abi_digest(),
            namespace: "app".into(),
            state_schema: format!("sha256:{}", "1".repeat(64)),
            operations: vec![TransactionOperation {
                operation: "save".into(),
                mode: TransactionOperationMode::StrictCommand,
                input_format: "raw-v1".into(),
                result_format: "result-v1".into(),
            }],
        }
    }

    #[test]
    fn companion_round_trip_is_exact_and_does_not_grant_link_authority() {
        let declaration = declaration();
        let encoded = serde_json::to_vec(&declaration).unwrap();
        assert_eq!(TransactionBinding::decode(&encoded).unwrap(), declaration);
        assert!(declaration
            .check_links("capsule", "deployment", "binding")
            .is_ok());
        assert_eq!(
            declaration.check_links("other", "deployment", "binding"),
            Err(TransactionBindingError::LinkMismatch)
        );
    }

    #[test]
    fn malformed_present_values_unknown_modes_and_stale_profile_reject() {
        let mut declaration = declaration();
        declaration.namespace.clear();
        assert_eq!(
            declaration.validate(),
            Err(TransactionBindingError::InvalidIdentity)
        );
        declaration = self::declaration();
        declaration.host_abi_digest = format!("sha256:{}", "0".repeat(64));
        assert_eq!(
            declaration.validate(),
            Err(TransactionBindingError::UnsupportedProfile)
        );
        let mut wire = serde_json::to_value(self::declaration()).unwrap();
        wire["operations"][0]["mode"] = "workflow".into();
        assert_eq!(
            TransactionBinding::decode(&serde_json::to_vec(&wire).unwrap()),
            Err(TransactionBindingError::Format)
        );
        wire["operations"][0]["mode"] = "fresh-query".into();
        wire["authority"] = true.into();
        assert_eq!(
            TransactionBinding::decode(&serde_json::to_vec(&wire).unwrap()),
            Err(TransactionBindingError::Format)
        );
    }
}
