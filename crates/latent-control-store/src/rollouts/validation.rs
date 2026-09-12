use super::{
    capacity, invalid,
    model::{
        RolloutAction, RolloutCommand, RolloutContext, RolloutId, RolloutLimits, RolloutRequest,
    },
    Result, MAX_REQUEST_BYTES,
};
use latent_manifest::{DeploymentManifest, ManifestValidator, Phase1ManifestValidator};
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
fn strings(values: &[String], capacity: usize) -> usize {
    let mut bytes = capacity.saturating_mul(std::mem::size_of::<String>());
    if bytes > MAX_REQUEST_BYTES {
        return MAX_REQUEST_BYTES + 1;
    }
    for value in values {
        bytes = bytes.saturating_add(value.capacity());
        if bytes > MAX_REQUEST_BYTES {
            return MAX_REQUEST_BYTES + 1;
        }
    }
    bytes
}
fn metadata(values: &latent_core::Metadata) -> usize {
    // Cardinality bounds traversal even for empty strings in every map entry.
    let mut bytes = values.len().saturating_mul(128);
    if bytes > MAX_REQUEST_BYTES {
        return MAX_REQUEST_BYTES + 1;
    }
    for (key, value) in values {
        bytes = bytes
            .saturating_add(key.capacity())
            .saturating_add(value.capacity());
        if bytes > MAX_REQUEST_BYTES {
            return MAX_REQUEST_BYTES + 1;
        }
    }
    bytes
}
pub(crate) fn deployment_bytes(value: &DeploymentManifest) -> usize {
    let mut n = std::mem::size_of::<DeploymentManifest>();
    for s in [
        &value.api_version,
        &value.id.0,
        &value.metadata.name,
        &value.service.0,
        &value.release.0,
        &value.placement.trust_class,
    ] {
        n = n.saturating_add(s.capacity());
    }
    n = n
        .saturating_add(value.metadata.tenant.as_ref().map_or(0, |v| v.0.capacity()))
        .saturating_add(
            value
                .metadata
                .namespace
                .as_ref()
                .map_or(0, String::capacity),
        )
        .saturating_add(metadata(&value.metadata.labels))
        .saturating_add(metadata(&value.metadata.annotations))
        .saturating_add(
            value
                .grants
                .capacity()
                .saturating_mul(std::mem::size_of::<latent_manifest::CapabilityGrantSpec>()),
        );
    if n > MAX_REQUEST_BYTES {
        return MAX_REQUEST_BYTES + 1;
    }
    for g in &value.grants {
        n = n
            .saturating_add(g.capability.0.capacity())
            .saturating_add(g.policy.0.capacity())
            .saturating_add(strings(&g.operations, g.operations.capacity()))
            .saturating_add(metadata(&g.constraints));
        if n > MAX_REQUEST_BYTES {
            return MAX_REQUEST_BYTES + 1;
        }
    }
    for v in [
        &value.placement.architectures,
        &value.placement.regions,
        &value.placement.zones,
        &value.placement.required_features,
    ] {
        n = n.saturating_add(strings(v, v.capacity()));
        if n > MAX_REQUEST_BYTES {
            return MAX_REQUEST_BYTES + 1;
        }
    }
    n
}
impl RolloutRequest {
    #[must_use]
    pub fn context(&self) -> &RolloutContext {
        match self {
            Self::Start { context, .. } | Self::Change { context, .. } => context,
        }
    }
    #[must_use]
    pub fn id(&self) -> &RolloutId {
        match self {
            Self::Start { spec, .. } => &spec.id,
            Self::Change { id, .. } => id,
        }
    }
    #[must_use]
    pub fn action(&self) -> RolloutAction {
        match self {
            Self::Start { .. } => RolloutAction::Start,
            Self::Change { command, .. } => match command {
                RolloutCommand::Advance { .. } => RolloutAction::Advance,
                RolloutCommand::Promote { .. } => RolloutAction::Promote,
                RolloutCommand::Rollback { .. } => RolloutAction::Rollback,
                RolloutCommand::Pause => RolloutAction::Pause,
                RolloutCommand::Resume => RolloutAction::Resume,
                RolloutCommand::Abort => RolloutAction::Abort,
            },
        }
    }
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        let c = self.context();
        let n = std::mem::size_of::<Self>()
            .saturating_add(c.tenant.0.capacity())
            .saturating_add(c.actor.subject.capacity())
            .saturating_add(c.operation.operation_id.capacity())
            .saturating_add(self.id().0.capacity());
        if n > MAX_REQUEST_BYTES {
            return MAX_REQUEST_BYTES + 1;
        }
        match self {
            Self::Start { spec, .. } => n
                .saturating_add(spec.base.id.0.capacity())
                .saturating_add(deployment_bytes(&spec.candidate))
                .saturating_add(spec.candidate_weights.capacity().saturating_mul(2)),
            Self::Change { .. } => n,
        }
    }
    pub fn validate(&self, limits: RolloutLimits) -> Result<()> {
        limits.validate()?;
        if self.retained_bytes() > MAX_REQUEST_BYTES {
            return Err(capacity());
        }
        let c = self.context();
        token(&c.tenant.0, 256)?;
        token(&self.id().0, 128)?;
        token(&c.operation.operation_id, 128)?;
        c.actor.validate()?;
        match self {
            Self::Start { spec, .. } => {
                if c.operation.expected_revision != 0 || spec.base.generation == 0 {
                    return Err(invalid());
                }
                token(&spec.base.id.0, 128)?;
                token(&spec.candidate.id.0, 128)?;
                token(&spec.candidate.service.0, 256)?;
                if spec.candidate.metadata.tenant.as_ref() != Some(&c.tenant)
                    || spec.candidate.id == spec.base.id
                {
                    return Err(invalid());
                }
                weights(&spec.candidate_weights, limits.maximum_stages)?;
                if let Some(policy) = spec.canary_policy {
                    policy.validate()?;
                    if spec.candidate_weights.len() < 2 {
                        return Err(invalid());
                    }
                }
                if spec.candidate.route_weight != spec.candidate_weights[0] {
                    return Err(invalid());
                }
                Phase1ManifestValidator
                    .validate_deployment(&spec.candidate)
                    .map_err(|_| invalid())?;
            }
            Self::Change { command, .. } => {
                if c.operation.expected_revision == 0 {
                    return Err(invalid());
                }
                if matches!(command, RolloutCommand::Rollback { target_generation } if target_generation.0 == 0)
                {
                    return Err(invalid());
                }
            }
        }
        Ok(())
    }
}
pub(crate) fn weights(values: &[u16], maximum: usize) -> Result<()> {
    if values.is_empty()
        || values.len() > maximum
        || values.last() != Some(&10000)
        || values.iter().any(|v| *v == 0 || *v > 10000)
        || values.windows(2).any(|v| v[0] >= v[1])
    {
        Err(invalid())
    } else {
        Ok(())
    }
}
