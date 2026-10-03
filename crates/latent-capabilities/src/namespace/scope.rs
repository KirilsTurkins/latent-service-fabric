use latent_core::{InvocationPrincipal, PrincipalKind, TenantId};
use latent_policy::capability::RecoveryScopeKind;
use sha2::{Digest, Sha256};

use super::{denied, identity};

/// Descriptive trusted binding choice. Authorization still requires the exact
/// current policy tuple for the authenticated subject and selected publication.
/// Headers, claims and guest strings must never be treated as an approved choice.
#[derive(Debug, Clone)]
pub enum RecoverySelection {
    OriginalCaller,
    ServiceIntegration,
    Delegated { delegation: String, service: String },
    Shared { name: String },
}

/// Stable identity only, without tokens, signing keys or reusable credentials.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CallerScope {
    pub kind: RecoveryScopeKind,
    pub scope: String,
    pub owner_kind: String,
    pub owner_subject: String,
}

impl CallerScope {
    /// Data derivation is not authorization. Claims are intentionally ignored.
    pub fn derive(
        principal: &InvocationPrincipal,
        selection: &RecoverySelection,
    ) -> Result<Self, latent_core::PlatformError> {
        let tenant = principal.tenant.as_ref().ok_or_else(denied)?;
        identity(&tenant.0)?;
        identity(&principal.subject)?;
        let owner_kind = match principal.kind {
            PrincipalKind::User => "user",
            PrincipalKind::Service => "service",
            PrincipalKind::Node => "node",
            PrincipalKind::Trigger => "trigger",
            PrincipalKind::Administrator => "administrator",
            _ => return Err(denied()),
        };
        let (kind, fields) = match selection {
            RecoverySelection::OriginalCaller => (
                RecoveryScopeKind::OriginalCaller,
                vec![owner_kind, principal.subject.as_str()],
            ),
            RecoverySelection::ServiceIntegration => {
                if !matches!(
                    principal.kind,
                    PrincipalKind::Service | PrincipalKind::Trigger
                ) {
                    return Err(denied());
                }
                let service = principal.service.as_ref().ok_or_else(denied)?;
                identity(&service.0)?;
                (
                    RecoveryScopeKind::ServiceIntegration,
                    vec![owner_kind, &principal.subject, &service.0],
                )
            }
            RecoverySelection::Delegated {
                delegation,
                service,
            } => {
                identity(delegation)?;
                identity(service)?;
                (
                    RecoveryScopeKind::Delegated,
                    vec![owner_kind, &principal.subject, delegation, service],
                )
            }
            RecoverySelection::Shared { name } => {
                identity(name)?;
                (RecoveryScopeKind::Shared, vec![name.as_str()])
            }
        };
        Ok(Self {
            kind,
            scope: digest(tenant, kind, &fields),
            owner_kind: owner_kind.into(),
            owner_subject: principal.subject.clone(),
        })
    }
}

fn digest(tenant: &TenantId, kind: RecoveryScopeKind, fields: &[&str]) -> String {
    let mut hash = Sha256::new();
    hash.update(b"latent.host-recovery-scope.v1\0");
    hash.update([match kind {
        RecoveryScopeKind::OriginalCaller => 1,
        RecoveryScopeKind::ServiceIntegration => 2,
        RecoveryScopeKind::Delegated => 3,
        RecoveryScopeKind::Shared => 4,
    }]);
    for value in std::iter::once(tenant.0.as_str()).chain(fields.iter().copied()) {
        hash.update(
            u16::try_from(value.len())
                .expect("validated bounded identity")
                .to_le_bytes(),
        );
        hash.update(value.as_bytes());
    }
    format!(
        "recovery:sha256:{:x}",
        latent_core::digest::HexDigest(hash.finalize())
    )
}
