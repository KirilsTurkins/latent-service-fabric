use super::{
    capacity, codec, invalid, DeploymentOperationAction, DeploymentOperationContext,
    DeploymentOperationRequest, Result, MAX_REQUEST_BYTES,
};
use latent_core::{ArtifactBlobDigest, DeploymentId};
use latent_manifest::{
    __serde_json as json, JsonManifestCodec, ManifestCodec, ManifestValidator,
    Phase1ManifestValidator,
};
pub(crate) fn token(value: &str, maximum: usize) -> Result<()> {
    if value.is_empty()
        || value.len() > maximum
        || value.chars().any(|c| c.is_control() || c.is_whitespace())
    {
        Err(invalid())
    } else {
        Ok(())
    }
}
impl DeploymentOperationRequest {
    #[must_use]
    pub fn context(&self) -> &DeploymentOperationContext {
        match self {
            Self::Apply { context, .. } | Self::Delete { context, .. } => context,
        }
    }
    #[must_use]
    pub fn id(&self) -> &DeploymentId {
        match self {
            Self::Apply { manifest, .. } => &manifest.id,
            Self::Delete { id, .. } => id,
        }
    }
    #[must_use]
    pub fn action(&self) -> DeploymentOperationAction {
        match self {
            Self::Apply { .. } => DeploymentOperationAction::Apply,
            Self::Delete { .. } => DeploymentOperationAction::Delete,
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
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        let c = self.context();
        std::mem::size_of::<Self>()
            .saturating_add(c.tenant.0.capacity())
            .saturating_add(c.actor.subject.capacity())
            .saturating_add(c.operation_id.capacity())
            .saturating_add(match self {
                Self::Apply { manifest, .. } => {
                    crate::rollouts::validation::deployment_bytes(manifest)
                }
                Self::Delete { id, .. } => id.0.capacity(),
            })
    }
    pub fn validate(&self) -> Result<()> {
        if self.retained_bytes() > MAX_REQUEST_BYTES {
            return Err(capacity());
        }
        let c = self.context();
        token(&c.tenant.0, 1024)?;
        token(&c.operation_id, 128)?;
        token(&self.id().0, 1024)?;
        c.actor.validate()?;
        match self {
            Self::Apply { manifest, .. } => {
                if manifest.metadata.tenant.as_ref() != Some(&c.tenant) {
                    return Err(super::error(
                        latent_core::PlatformErrorCode::PermissionDenied,
                        "deployment-scope-conflict",
                    ));
                }
                Phase1ManifestValidator
                    .validate_deployment(manifest)
                    .map_err(|_| invalid())?;
            }
            Self::Delete {
                expected_generation: 0,
                ..
            } => return Err(invalid()),
            Self::Delete { .. } => {}
        }
        Ok(())
    }
    pub fn request_digest(&self) -> Result<ArtifactBlobDigest> {
        self.validate()?;
        self.clone().normalize()?.normalized_digest()
    }
    pub(crate) fn normalize(mut self) -> Result<Self> {
        self.validate()?;
        match &mut self {
            Self::Apply {
                context, manifest, ..
            } => {
                normalize_context(context);
                manifest.normalize_storage_fields();
                let bytes = JsonManifestCodec::default()
                    .encode_deployment(manifest)
                    .map_err(|_| invalid())?;
                if bytes.len() > MAX_REQUEST_BYTES {
                    return Err(capacity());
                }
                *manifest = JsonManifestCodec::default()
                    .decode_deployment(&bytes)
                    .map_err(|_| invalid())?;
            }
            Self::Delete { context, id, .. } => {
                normalize_context(context);
                id.0 = id.0.as_str().into();
            }
        }
        Ok(self)
    }
    pub(crate) fn normalized_digest(&self) -> Result<ArtifactBlobDigest> {
        let manifest = match self {
            Self::Apply { manifest, .. } => Some(json::to_value(manifest).map_err(|_| invalid())?),
            Self::Delete { .. } => None,
        };
        let c = self.context();
        Ok(codec::hash(&codec::encode(
            &json::json!({"formatVersion":1,"tenant":c.tenant.0,"actor":c.actor,"operationId":c.operation_id,"expectedStateVersion":c.expected_state_version,"expectedGeneration":self.expected_generation(),"action":self.action(),"deploymentId":self.id().0,"manifest":manifest}),
            MAX_REQUEST_BYTES,
        )?))
    }
}
fn normalize_context(c: &mut DeploymentOperationContext) {
    c.tenant.0 = c.tenant.0.as_str().into();
    c.actor.subject = c.actor.subject.as_str().into();
    c.operation_id = c.operation_id.as_str().into();
}
