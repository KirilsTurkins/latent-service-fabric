use latent_artifacts::{PublicationRef, ReleaseActor};
use latent_core::{PlatformError, ReleaseDigest, RouteGeneration, ServiceId, TenantId, TriggerId};
use latent_manifest::{
    __serde::{Deserialize, Serialize},
    TriggerManifest,
};

/// Supplied by authenticated control composition, never by guest request fields.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TriggerOperationContext {
    pub tenant: TenantId,
    pub actor: ReleaseActor,
    pub operation_id: String,
    pub expected_state_version: u64,
}
#[derive(Debug, Clone, PartialEq, Eq)]
#[expect(
    clippy::large_enum_variant,
    reason = "finite inline command and receipt payloads are charged by their bounded owners"
)]
pub enum TriggerOperationRequest {
    Apply {
        context: TriggerOperationContext,
        manifest: TriggerManifest,
        expected_generation: u64,
    },
    Delete {
        context: TriggerOperationContext,
        id: TriggerId,
        expected_generation: u64,
    },
}
impl TriggerOperationRequest {
    #[must_use]
    pub fn context(&self) -> &TriggerOperationContext {
        match self {
            Self::Apply { context, .. } | Self::Delete { context, .. } => context,
        }
    }
    #[must_use]
    pub fn id(&self) -> &str {
        match self {
            Self::Apply { manifest, .. } => &manifest.id.0,
            Self::Delete { id, .. } => &id.0,
        }
    }
    #[must_use]
    pub fn expected_generation(&self) -> u64 {
        match self {
            Self::Apply {
                expected_generation,
                ..
            }
            | Self::Delete {
                expected_generation,
                ..
            } => *expected_generation,
        }
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", rename_all = "kebab-case")]
pub enum TriggerOperationAction {
    Apply,
    Delete,
}

/// Exact authority identity retained by format-v2 HTTP state and receipts.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    tag = "kind",
    rename_all = "kebab-case",
    deny_unknown_fields
)]
pub enum TriggerTargetIdentity {
    Application {
        publication: PublicationRef,
        #[serde(with = "crate::rollouts::codec::text")]
        component: ReleaseDigest,
        deployment_id: String,
        deployment_generation: u64,
        revision: String,
    },
    StaticWeb {
        publication: PublicationRef,
        web_manifest_digest: String,
        assets_digest: String,
        web_generation: u64,
    },
}
impl TriggerTargetIdentity {
    #[must_use]
    pub const fn publication(&self) -> &PublicationRef {
        match self {
            Self::Application { publication, .. } | Self::StaticWeb { publication, .. } => publication,
        }
    }
    #[must_use]
    pub const fn component(&self) -> Option<&ReleaseDigest> {
        match self {
            Self::Application { component, .. } => Some(component),
            Self::StaticWeb { .. } => None,
        }
    }
    #[must_use]
    pub const fn deployment_generation(&self) -> Option<u64> {
        match self {
            Self::Application {
                deployment_generation,
                ..
            } => Some(*deployment_generation),
            Self::StaticWeb { .. } => None,
        }
    }
}

/// Immutable history, not current permission to select or execute a target.
/// Format v1 is application-only and uses the legacy flat optional fields.
/// Format v2 uses the tagged target exclusively; legacy fields are absent on new writes.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub struct TriggerOperationReceipt {
    pub format_version: u32,
    pub tenant: String,
    pub actor: ReleaseActor,
    pub operation_id: String,
    pub action: TriggerOperationAction,
    pub trigger_id: String,
    pub request_digest: String,
    pub expected_state_version: u64,
    pub expected_generation: u64,
    pub object_generation: u64,
    pub state_version: u64,
    pub route_generation: u64,
    pub manifest_digest: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target: Option<TriggerTargetIdentity>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub publication: Option<PublicationRef>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "crate::rollouts::codec::optional"
    )]
    pub component: Option<ReleaseDigest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub deployment_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub deployment_generation: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub revision: Option<String>,
    pub completed_at_unix_millis: u64,
    pub receipt_digest: String,
}
impl TriggerOperationReceipt {
    #[must_use]
    pub fn target_identity(&self) -> Option<TriggerTargetIdentity> {
        if let Some(target) = &self.target {
            return Some(target.clone());
        }
        Some(TriggerTargetIdentity::Application {
            publication: self.publication.clone()?,
            component: self.component.clone()?,
            deployment_id: self.deployment_id.clone()?,
            deployment_generation: self.deployment_generation?,
            revision: self.revision.clone()?,
        })
    }
    #[must_use]
    pub fn publication_ref(&self) -> Option<&PublicationRef> {
        self.target
            .as_ref()
            .map(TriggerTargetIdentity::publication)
            .or(self.publication.as_ref())
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VersionedTrigger {
    pub manifest: TriggerManifest,
    pub generation: u64,
    /// Present only for executable application targets.
    pub component: Option<ReleaseDigest>,
}
#[derive(Debug)]
pub struct TriggerOperationCommit {
    pub receipt: TriggerOperationReceipt,
    pub trigger: Option<VersionedTrigger>,
    pub replayed: bool,
    pub durability: Result<(), PlatformError>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
#[expect(
    clippy::large_enum_variant,
    reason = "finite inline command and receipt payloads are charged by their bounded owners"
)]
pub enum TriggerOperationLookup {
    Found(TriggerOperationReceipt),
    Unknown {
        retained_floor: u64,
        high_watermark: u64,
    },
    Uncertain,
}
#[derive(Debug)]
pub struct TriggerSnapshot {
    pub trigger: Option<VersionedTrigger>,
    pub state_version: u64,
    pub route_generation: RouteGeneration,
    pub confirmed: bool,
}
#[derive(Debug)]
pub struct TriggerPageRequest {
    pub tenant: TenantId,
    pub target_service: Option<ServiceId>,
    pub page_size: u32,
    pub page_token: Option<String>,
}
#[derive(Debug)]
pub struct TriggerPage {
    pub triggers: Vec<VersionedTrigger>,
    pub next_page_token: Option<String>,
    pub state_version: u64,
    pub route_generation: RouteGeneration,
}
