//! Deliberate native recovery after ordinary node owners have retired.
use super::{Catalogs, NodeSettings, StandaloneNode};
use crate::standalone::state::{
    recover_namespace, NativeRecoveryReport, NativeRecoveryRequest, RecoveryOwners,
};
use latent_core::{PlatformError, PlatformErrorCode, PrincipalKind, TenantId};

impl StandaloneNode {
    /// Run one bounded installed recovery action with the actual authenticated
    /// transport caller and current purpose-specific policy. Signed metadata
    /// and request identities alone grant no recovery or business authority.
    /// The normal node must have shut down; exclusive physical opening refuses
    /// a live owner. Original action disposition survives cleanup failure.
    pub async fn recover_transaction_namespace(
        settings: &NodeSettings,
        credential: &str,
        tenant: &TenantId,
        request: NativeRecoveryRequest,
        runtime: &tokio::runtime::Handle,
    ) -> Result<NativeRecoveryReport, PlatformError> {
        let principal =
            crate::standalone::transport::credential_principal(&settings.transport, credential)
                .ok_or_else(denied)?;
        if !settings.credentials_from_protected_file
            || principal.kind != PrincipalKind::Administrator
            || principal.tenant.as_ref() != Some(tenant)
        {
            return Err(denied());
        }
        let catalogs = Catalogs::open_with_control(settings, runtime).await?;
        let result = catalogs.recover(settings, principal, request).await;
        let shutdown = catalogs.close_inspection(settings).await;
        result.map(|mut observation| {
            observation.catalogs_retired(shutdown.is_ok());
            observation
        })
    }
}

fn denied() -> PlatformError {
    super::error(
        PlatformErrorCode::PermissionDenied,
        "native-namespace-recovery-unavailable",
    )
}

impl Catalogs {
    async fn recover(
        &self,
        settings: &NodeSettings,
        principal: &latent_core::InvocationPrincipal,
        request: NativeRecoveryRequest,
    ) -> Result<NativeRecoveryReport, PlatformError> {
        recover_namespace(
            settings,
            principal,
            request,
            RecoveryOwners {
                artifacts: &self.artifacts,
                providers: self.providers.as_deref(),
                policy: self
                    .policies
                    .as_ref()
                    .ok_or_else(super::mode_error)?
                    .handle()
                    .store(),
                clock: self.clock.clone(),
            },
        )
        .await
    }
}
