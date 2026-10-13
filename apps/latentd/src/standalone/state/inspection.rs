//! Read-only current configuration/signed companion proposals, never grants.
use crate::config::NodeSettings;
use latent_capabilities::namespace::{CallerScope, RecoverySelection};
use latent_core::{InvocationPrincipal, PlatformError, PrincipalKind};
use latent_policy::capability::RecoveryScopeKind;
use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeTransactionHostInspection {
    pub schema_version: &'static str,
    pub configured_providers: Vec<crate::standalone::ProviderDescriptor>,
    pub configured_http_callers: Vec<NativeHttpCallerInspection>,
    pub configured_transport_callers: Vec<NativeHttpCallerInspection>,
    pub state_provider_profile: String,
    pub state_configuration_digest: String,
    pub state_configuration_epoch: u64,
    pub deferred_http: Vec<NativeDeferredEffectHostInspection>,
    #[serde(skip)]
    pub(in crate::standalone) response: latent_core::native_capacity::NativeBufferPermit,
}
impl NativeTransactionHostInspection {
    pub fn encode(
        self,
    ) -> Result<latent_core::native_capacity::NativeBuffer<Vec<u8>>, PlatformError> {
        let encoded = serde_json::to_vec(&self).map_err(|_| super::unavailable())?;
        if encoded.len() > 256 * 1024 {
            return Err(super::unavailable());
        }
        Ok(self.response.attach(encoded))
    }
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeHttpCallerInspection {
    pub subject: String,
    pub owner_kind: String,
    pub tenant: String,
    pub service: Option<String>,
    pub recovery_kind: RecoveryScopeKind,
    pub recovery_scope: String,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeDeferredEffectHostInspection {
    pub tenant: String,
    pub service: String,
    pub publication: String,
    pub namespace: String,
    pub incarnation: u64,
    pub logical_binding: String,
    pub operation: String,
    pub staging_binding: String,
    pub dispatch_binding: String,
    pub provider_profile: String,
    pub configuration_digest: String,
    pub configuration_epoch: u64,
    pub dispatch_subject: String,
    pub dispatch_recovery_kind: RecoveryScopeKind,
    pub dispatch_recovery_scope: String,
    pub result_policy: String,
}

pub(in crate::standalone) fn callers(
    settings: &NodeSettings,
) -> Result<
    (
        Vec<NativeHttpCallerInspection>,
        Vec<NativeHttpCallerInspection>,
    ),
    PlatformError,
> {
    let http = match settings.http.as_ref().map(|http| &http.authentication) {
        Some(crate::config::http::Authentication::Bearer(credentials)) => credentials
            .iter()
            .map(|credential| caller(&credential.principal))
            .collect::<Result<Vec<_>, _>>()?,
        _ => Vec::new(),
    };
    let transport = settings
        .transport
        .credentials
        .iter()
        .map(|credential| caller(&credential.principal))
        .collect::<Result<Vec<_>, _>>()?;
    Ok((http, transport))
}
fn caller(principal: &InvocationPrincipal) -> Result<NativeHttpCallerInspection, PlatformError> {
    let scope = CallerScope::derive(principal, &RecoverySelection::OriginalCaller)?;
    Ok(NativeHttpCallerInspection {
        subject: principal.subject.clone(),
        owner_kind: scope.owner_kind,
        tenant: principal
            .tenant
            .as_ref()
            .ok_or_else(super::unavailable)?
            .0
            .clone(),
        service: principal.service.as_ref().map(|service| service.0.clone()),
        recovery_kind: scope.kind,
        recovery_scope: scope.scope,
    })
}

pub(in crate::standalone) fn deferred(
    asset: &latent_artifacts::SelectedTransactionAsset,
    operation: &crate::config::state::OperationSettings,
    adapters: &[std::sync::Arc<latent_http::deferred::HttpEffectAdapter>],
) -> Result<Option<NativeDeferredEffectHostInspection>, PlatformError> {
    let Some((scope, profile)) =
        super::installations::http::recovery_profile(asset, operation, adapters)?
    else {
        return Ok(None);
    };
    let config = operation
        .deferred_http
        .as_ref()
        .ok_or_else(super::unavailable)?;
    let adapter = adapters
        .iter()
        .find(|adapter| {
            use latent_effects::runtime::DeferredEffectAdapter;
            adapter.profile() == &profile
        })
        .ok_or_else(super::unavailable)?;
    let service = latent_core::ServiceId(asset.declaration().capsule.clone());
    let principal = InvocationPrincipal {
        subject: InvocationPrincipal::local_service_subject(&operation.tenant, &service),
        kind: PrincipalKind::Service,
        tenant: Some(operation.tenant.clone()),
        service: Some(service.clone()),
        claims: std::collections::BTreeMap::default(),
    };
    let selection = if config.service_integration() {
        RecoverySelection::ServiceIntegration
    } else {
        RecoverySelection::OriginalCaller
    };
    let caller = CallerScope::derive(&principal, &selection)?;
    Ok(Some(NativeDeferredEffectHostInspection {
        tenant: scope.tenant,
        service: service.0,
        publication: scope.publication,
        namespace: scope.namespace,
        incarnation: scope.incarnation,
        logical_binding: scope.binding,
        operation: scope.operation,
        staging_binding: config.staging_binding.clone(),
        dispatch_binding: config.dispatch_binding.clone(),
        provider_profile: profile.adapter,
        configuration_digest: format!(
            "sha256:{}",
            profile
                .idempotency_profile
                .strip_prefix("qualified-http-v1:")
                .ok_or_else(super::unavailable)?
        ),
        configuration_epoch: adapter.provider_reference().configuration_epoch(),
        dispatch_subject: principal.subject,
        dispatch_recovery_kind: caller.kind,
        dispatch_recovery_scope: caller.scope,
        result_policy: operation.result_policy.clone(),
    }))
}

pub(in crate::standalone) struct UnadmittedTime;
impl latent_effects::runtime::EffectTimeSource for UnadmittedTime {
    fn observe(&self) -> latent_effects::authority::EffectTime {
        latent_effects::authority::EffectTime {
            unix_millis: 0,
            continuity_proven: false,
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConfiguredHttpEffectInspection {
    pub schema_version: &'static str,
    pub adapters: Vec<ConfiguredHttpEffectProfile>,
    #[serde(skip)]
    pub(in crate::standalone) response: latent_core::native_capacity::NativeBufferPermit,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConfiguredHttpEffectProfile {
    pub endpoint_incarnation: String,
    pub profile: latent_effects::authority::DispatchProfile,
}
impl ConfiguredHttpEffectInspection {
    pub fn encode(
        self,
    ) -> Result<latent_core::native_capacity::NativeBuffer<Vec<u8>>, PlatformError> {
        let bytes = serde_json::to_vec(&self).map_err(|_| super::unavailable())?;
        if bytes.len() > 256 * 1024 {
            return Err(super::unavailable());
        }
        Ok(self.response.attach(bytes))
    }
}
