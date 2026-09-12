use crate::{AdmissionEvidence, ArtifactCatalogEntry, CapsuleArtifact, PackageAdmissionUpload};
use latent_core::{
    ArtifactBlobDigest, PackageDigest, PlatformError, PrincipalKind, ReleaseDigest, TenantId,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum LifecycleScope {
    Tenant(TenantId),
    LocalUnscoped,
}
#[derive(Serialize)]
#[serde(tag = "kind", content = "tenant", rename_all = "kebab-case")]
enum ScopeRef<'a> {
    Tenant(&'a str),
    LocalUnscoped,
}
#[derive(Deserialize)]
#[serde(
    tag = "kind",
    content = "tenant",
    rename_all = "kebab-case",
    deny_unknown_fields
)]
enum ScopeValue {
    Tenant(String),
    LocalUnscoped,
}
impl Serialize for LifecycleScope {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Self::Tenant(value) => ScopeRef::Tenant(&value.0),
            Self::LocalUnscoped => ScopeRef::LocalUnscoped,
        }
        .serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for LifecycleScope {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let scope = match ScopeValue::deserialize(deserializer)? {
            ScopeValue::Tenant(value) => Self::Tenant(TenantId(value)),
            ScopeValue::LocalUnscoped => Self::LocalUnscoped,
        };
        scope
            .validate()
            .map_err(|_| serde::de::Error::custom("invalid lifecycle scope"))?;
        Ok(scope)
    }
}
impl LifecycleScope {
    #[must_use]
    pub fn tenant(&self) -> Option<&TenantId> {
        match self {
            Self::Tenant(value) => Some(value),
            Self::LocalUnscoped => None,
        }
    }
    pub fn validate(&self) -> Result<(), PlatformError> {
        if let Self::Tenant(value) = self {
            if value.0.capacity() > 512 {
                return Err(super::exhausted());
            }
            token(&value.0, 512)?;
        }
        Ok(())
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ReleaseActorKind {
    User,
    Service,
    Node,
    Trigger,
    Administrator,
    Anonymous,
    Host,
}
impl TryFrom<PrincipalKind> for ReleaseActorKind {
    type Error = PlatformError;
    fn try_from(value: PrincipalKind) -> Result<Self, Self::Error> {
        Ok(match value {
            PrincipalKind::User => Self::User,
            PrincipalKind::Service => Self::Service,
            PrincipalKind::Node => Self::Node,
            PrincipalKind::Trigger => Self::Trigger,
            PrincipalKind::Administrator => Self::Administrator,
            PrincipalKind::Anonymous => Self::Anonymous,
            _ => return Err(super::invalid()),
        })
    }
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReleaseActor {
    pub subject: String,
    pub kind: ReleaseActorKind,
}
impl ReleaseActor {
    pub fn validate(&self) -> Result<(), PlatformError> {
        if self.subject.capacity() > 512 {
            return Err(super::exhausted());
        }
        token(&self.subject, 512)
    }
}

/// Supplied only by the trusted host adapter after authenticating the caller.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReleaseMutationContext {
    pub scope: LifecycleScope,
    pub actor: ReleaseActor,
    pub operation: Option<ReleaseOperationPrecondition>,
}
impl ReleaseMutationContext {
    pub fn validate(&self) -> Result<(), PlatformError> {
        self.scope.validate()?;
        self.actor.validate()?;
        if let Some(operation) = &self.operation {
            operation.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReleaseOperationPrecondition {
    pub operation_id: String,
    pub expected_generation: u64,
}
impl ReleaseOperationPrecondition {
    pub fn validate(&self) -> Result<(), PlatformError> {
        if self.operation_id.capacity() > 128 {
            return Err(super::exhausted());
        }
        token(&self.operation_id, 128)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ReleaseLifecycleState {
    Admitted,
    Revoked,
    Retired,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ReleaseLifecycleAction {
    Publish,
    Revoke,
    Retire,
    RenewEvidence,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ReleaseOperationDisposition {
    Committed,
    Rejected,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ReleaseLifecycleReason {
    Admitted,
    EvidenceRenewed,
    OperatorRevocation,
    SecurityIncident,
    CorruptContent,
    Superseded,
    EndOfSupport,
    OperatorRetirement,
    InvalidPackage,
    IntegrityMismatch,
    IncompatibleContract,
    EvidenceRejected,
    PolicyDenied,
    ReleaseRevoked,
    ReleaseRetired,
    GenerationConflict,
    ContentConflict,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReleasePolicyIdentity {
    pub scope: String,
    pub generation: u64,
    #[serde(with = "super::codec::blob")]
    pub digest: ArtifactBlobDigest,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReleaseLifecycleRecord {
    pub scope: LifecycleScope,
    #[serde(with = "super::codec::release")]
    pub release: ReleaseDigest,
    #[serde(with = "super::codec::optional_package")]
    pub package: Option<PackageDigest>,
    pub state: ReleaseLifecycleState,
    pub generation: u64,
    pub actor: ReleaseActor,
    pub reason: ReleaseLifecycleReason,
    pub operation_id: String,
    pub policy: Option<ReleasePolicyIdentity>,
    pub observed_at_unix_millis: Option<u64>,
    #[serde(with = "super::codec::optional_blob")]
    pub evidence_revision_digest: Option<ArtifactBlobDigest>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReleaseLiveEligibility {
    Eligible,
    Denied,
    Unknown,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReleaseEligibilityReason {
    LocalEligible,
    Verified,
    Revoked,
    Retired,
    PolicyDenied,
    ProofExpired,
    RuntimeIncompatible,
    CorruptContent,
    AuthorityUnavailable,
    MutationUncertain,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReleaseLifecycleStatus {
    pub record: ReleaseLifecycleRecord,
    pub eligibility: ReleaseLiveEligibility,
    pub eligibility_reason: ReleaseEligibilityReason,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReleaseOperationReceipt {
    pub operation_id: String,
    #[serde(with = "super::codec::blob")]
    pub request_digest: ArtifactBlobDigest,
    pub scope: LifecycleScope,
    pub actor: ReleaseActor,
    pub action: ReleaseLifecycleAction,
    pub disposition: ReleaseOperationDisposition,
    pub reason: ReleaseLifecycleReason,
    #[serde(with = "super::codec::optional_release")]
    pub component_digest: Option<ReleaseDigest>,
    #[serde(with = "super::codec::optional_blob")]
    pub package_manifest_digest: Option<ArtifactBlobDigest>,
    pub expected_generation: Option<u64>,
    pub record: Option<ReleaseLifecycleRecord>,
    pub policy: Option<ReleasePolicyIdentity>,
    pub observed_at_unix_millis: Option<u64>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReleaseOperationLookup {
    Found(ReleaseOperationReceipt),
    Unknown,
    Uncertain,
}
#[derive(Debug)]
pub struct ReleaseEvidenceUpload {
    pub signatures: Vec<AdmissionEvidence>,
    pub provenance: Vec<AdmissionEvidence>,
    pub sboms: Vec<AdmissionEvidence>,
}
#[derive(Debug)]
pub enum ManagedPublicationUpload {
    Local(CapsuleArtifact),
    Package(PackageAdmissionUpload),
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManagedPublicationReceipt {
    pub release: ArtifactCatalogEntry,
    pub operation: ReleaseOperationReceipt,
}
/// Rejection-only callback input; no field grants admission or mutation authority.
#[derive(Debug, Clone, Copy)]
pub struct ReleaseOperationPreview<'a> {
    pub receipt: &'a ReleaseOperationReceipt,
    pub release: Option<&'a ArtifactCatalogEntry>,
    pub failure: Option<&'a PlatformError>,
}

/// Hard maxima, configurable downward before initial bootstrap. Counts and
/// retained file bytes are independent; there is only one metadata transaction.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LifecycleLimits {
    pub max_records: usize,
    pub max_record_bytes: usize,
    pub max_receipt_bytes: usize,
    pub max_recent_operations: usize,
    pub max_total_metadata_bytes: usize,
    pub max_intent_bytes: usize,
    pub max_evidence_revision_bytes: usize,
    pub max_total_evidence_bytes: usize,
}
impl Default for LifecycleLimits {
    fn default() -> Self {
        Self {
            max_records: 250_000,
            max_record_bytes: 4096,
            max_receipt_bytes: 8192,
            max_recent_operations: 256,
            max_total_metadata_bytes: 128 * 1024 * 1024,
            max_intent_bytes: 32 * 1024,
            max_evidence_revision_bytes: 2 * 1024 * 1024,
            max_total_evidence_bytes: 256 * 1024 * 1024,
        }
    }
}
impl LifecycleLimits {
    pub fn validate(self) -> Result<(), PlatformError> {
        let hard = Self::default();
        macro_rules! check { ($($field:ident),+)=>{$(if self.$field==0||self.$field>hard.$field{return Err(super::invalid());})+}; }
        check!(
            max_records,
            max_record_bytes,
            max_receipt_bytes,
            max_recent_operations,
            max_total_metadata_bytes,
            max_intent_bytes,
            max_evidence_revision_bytes,
            max_total_evidence_bytes
        );
        Ok(())
    }
}
pub(crate) fn token(value: &str, maximum: usize) -> Result<(), PlatformError> {
    if value.is_empty()
        || value.len() > maximum
        || value
            .chars()
            .any(|ch| ch.is_control() || ch.is_whitespace())
    {
        return Err(super::invalid());
    }
    Ok(())
}
