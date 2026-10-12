//! Irreversible original installation stamps. The weak observer lives entirely
//! in latent-core, so policy/catalog acceptance never calls back into Effects.
use super::{AuthorityError, EffectAuthorityOwner, EffectRule};
use latent_core::{
    authority_rejection::{AuthorityRejectionObserver, AuthorityRejectionToken},
    PlatformErrorCode,
};
use std::{ops::Deref, sync::Arc};

pub(super) struct InstalledRule {
    pub(super) rule: EffectRule,
    pub(super) rejection: AuthorityRejectionToken,
}
impl Deref for InstalledRule {
    type Target = EffectRule;
    fn deref(&self) -> &Self::Target {
        &self.rule
    }
}

pub(super) fn compatible(previous: &InstalledRule, rule: &EffectRule) -> bool {
    previous.rejection.is_current()
        && previous.enabled == rule.enabled
        && previous.profile == rule.profile
        && previous.credential_epoch == rule.credential_epoch
        && previous.protected_credential_reference == rule.protected_credential_reference
        && previous.ceiling.intersection(rule.ceiling) == previous.ceiling
}

impl EffectAuthorityOwner {
    /// Install this same weak lower-layer adapter on the node's actual
    /// PolicyStore and LifecycleAuthorityHandle before either exposes work.
    /// No effect owner, credential, native keeper or reusable grant is retained.
    #[must_use]
    pub fn rejection_observer(&self) -> Arc<dyn AuthorityRejectionObserver> {
        self.0.rejections.observer()
    }
}

pub(super) fn error(code: PlatformErrorCode) -> AuthorityError {
    match code {
        PlatformErrorCode::ResourceExhausted => AuthorityError::Capacity,
        PlatformErrorCode::InvalidArgument => AuthorityError::Invalid,
        _ => AuthorityError::Unavailable,
    }
}
