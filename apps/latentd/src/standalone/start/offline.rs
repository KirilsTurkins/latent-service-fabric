//! Native helper composition opens the real current catalogs without transport.
use super::{Catalogs, StandaloneNode};
use crate::{
    config::NodeSettings,
    standalone::{state, transport, NativeRecoveryReport, NativeRecoveryRequest},
};
use latent_core::{PlatformError, PrincipalKind, TenantId};
use std::{sync::Arc, time::Instant};

mod retirement;

impl StandaloneNode {
    pub async fn inspect_configured_http_effects(
        settings: NodeSettings,
        control_runtime: tokio::runtime::Handle,
    ) -> Result<state::ConfiguredHttpEffectInspection, PlatformError> {
        use latent_core::native_capacity::{
            NativeAdmissionClass, NativeBufferClass, NativeReservationRequest,
        };
        use latent_effects::runtime::DeferredEffectAdapter;
        let mut catalogs = Catalogs::open_with_control(&settings, &control_runtime).await?;
        let bootstrap = catalogs.state.as_ref().ok_or_else(super::mode_error)?;
        let original = Arc::new(
            bootstrap
                .native
                .reserve(
                    NativeAdmissionClass::Recovery,
                    NativeReservationRequest {
                        response_bytes: 1024 * 1024,
                        ..NativeReservationRequest::default()
                    },
                    bootstrap.deadline,
                )
                .map_err(|_| super::mode_error())?,
        );
        let response = original
            .reserve_buffer(NativeBufferClass::Response, 1024 * 1024)
            .map_err(|_| super::mode_error())?;
        let adapters = match (
            catalogs.providers.as_deref(),
            settings
                .providers
                .as_ref()
                .and_then(|providers| providers.http.as_ref()),
        ) {
            (Some(provider), Some(http)) => provider
                .typed_deferred_http_adapters(http, Arc::new(state::inspection::UnadmittedTime))?,
            (_, None) => Vec::new(),
            _ => return Err(super::mode_error()),
        };
        let rows = adapters
            .iter()
            .map(|adapter| state::inspection::ConfiguredHttpEffectProfile {
                endpoint_incarnation: adapter.endpoint().endpoint_incarnation.clone(),
                profile: adapter.profile().clone(),
            })
            .collect();
        drop(adapters);
        let report = state::ConfiguredHttpEffectInspection {
            schema_version: "latent.configured-http-effect-inspection.v1",
            adapters: rows,
            response,
        };
        let deadline = Instant::now() + settings.shutdown_grace();
        if let Some(provider) = &catalogs.providers {
            if !provider.shutdown(deadline).await?.clean {
                return Err(super::mode_error());
            }
        }
        if let Some(policy) = &catalogs.policies {
            let retired = policy.shutdown(deadline).await;
            if !retired.work_completed
                || retired.active_jobs != 0
                || retired.retained_read_owners != 0
            {
                return Err(super::mode_error());
            }
        }
        if let Some(rollout) = &catalogs.rollouts {
            rollout.shutdown(settings.shutdown_grace()).await?;
            if !rollout.worker_joined().await {
                return Err(super::mode_error());
            }
        }
        if let Some(telemetry) = catalogs.telemetry.take() {
            telemetry.runtime.shutdown().await?;
        }
        if let Some(control) = catalogs.control.take() {
            control.shutdown(settings.shutdown_grace()).await?;
        }
        if let Some(audit) = &catalogs.audit {
            audit.shutdown(settings.shutdown_grace()).await?;
        }
        Ok(report)
    }

    #[expect(
        clippy::too_many_lines,
        reason = "Signed capture and actual ordered catalog retirement keep their original owners in one visible scope"
    )]
    pub async fn inspect_transaction_hosts(
        settings: NodeSettings,
        control_runtime: tokio::runtime::Handle,
    ) -> Result<state::NativeTransactionHostInspection, PlatformError> {
        use latent_core::native_capacity::{
            NativeAdmissionClass, NativeBufferClass, NativeReservationRequest,
        };
        let configuration = settings.state.as_ref().ok_or_else(super::mode_error)?;
        let (profile, digest) = configuration
            .store
            .inspection_profile()
            .map_err(|_| super::mode_error())?;
        let (http_callers, transport_callers) = state::inspection::callers(&settings)?;
        let mut catalogs = Catalogs::open_with_control(&settings, &control_runtime).await?;
        let bootstrap = catalogs.state.as_ref().ok_or_else(super::mode_error)?;
        let original = Arc::new(
            bootstrap
                .native
                .reserve(
                    NativeAdmissionClass::Recovery,
                    NativeReservationRequest {
                        request_bytes: 32 * 1024,
                        work_bytes: 6 * 1024 * 1024,
                        response_bytes: 8 * 1024 * 1024,
                    },
                    bootstrap.deadline,
                )
                .map_err(|_| super::mode_error())?,
        );
        let response = original
            .reserve_buffer(NativeBufferClass::Response, 1024 * 1024)
            .map_err(|_| super::mode_error())?;
        let adapters = match (
            catalogs.providers.as_deref(),
            settings
                .providers
                .as_ref()
                .and_then(|providers| providers.http.as_ref()),
        ) {
            (Some(provider), Some(http)) => provider
                .typed_deferred_http_adapters(http, Arc::new(state::inspection::UnadmittedTime))?,
            (_, None) => Vec::new(),
            _ => return Err(super::mode_error()),
        };
        let repository = Arc::clone(&catalogs.artifacts);
        let operations = configuration.operations.clone();
        let native = bootstrap.native.clone();
        let worker_original = Arc::clone(&original);
        let capture = control_runtime.spawn_blocking(move || {
            let mut captured: Vec<(
                latent_core::PublicationId,
                latent_core::native_capacity::NativeBuffer<
                    latent_artifacts::SelectedTransactionAsset,
                >,
            )> = Vec::new();
            let mut effects = Vec::new();
            for operation in operations {
                if !captured
                    .iter()
                    .any(|(publication, _)| publication == &operation.publication)
                {
                    let asset = repository.capture_selected_transaction_asset_profile(
                        &operation.tenant,
                        &operation.component,
                        &operation.publication,
                        &native,
                        Arc::clone(&worker_original),
                        latent_artifacts::TransactionAssetProfile::Compact,
                    )?;
                    captured.push((operation.publication.clone(), asset));
                }
                let asset = captured
                    .iter()
                    .find(|(publication, _)| publication == &operation.publication)
                    .ok_or_else(super::mode_error)?
                    .1
                    .get();
                asset
                    .declaration()
                    .check_links(
                        &asset.metadata().manifest().metadata.name,
                        &operation.deployment,
                        &operation.binding,
                    )
                    .map_err(|_| super::mode_error())?;
                if asset.asset_digest().to_string() != operation.companion_digest
                    || !asset
                        .declaration()
                        .operations
                        .iter()
                        .any(|export| export.operation == operation.function)
                {
                    return Err(super::mode_error());
                }
                if let Some(effect) = state::inspection::deferred(asset, &operation, &adapters)? {
                    effects.push(effect);
                }
            }
            Ok::<_, PlatformError>(effects)
        });
        let effects = tokio::time::timeout_at(bootstrap.deadline.into(), capture)
            .await
            .map_err(|_| super::mode_error())?
            .map_err(|_| super::mode_error())??;
        let report = state::NativeTransactionHostInspection {
            schema_version: "latent.transaction-host-inspection.v1",
            configured_providers: catalogs
                .providers
                .as_ref()
                .map_or_else(Vec::new, |provider| provider.descriptors().to_vec()),
            configured_http_callers: http_callers,
            configured_transport_callers: transport_callers,
            state_provider_profile: profile.into(),
            state_configuration_digest: format!(
                "sha256:{:x}",
                latent_core::digest::HexDigest(digest)
            ),
            state_configuration_epoch: configuration.configuration_epoch,
            deferred_http: effects,
            response,
        };
        let deadline = Instant::now() + settings.shutdown_grace();
        if let Some(provider) = &catalogs.providers {
            if !provider.shutdown(deadline).await?.clean {
                return Err(super::mode_error());
            }
        }
        if let Some(policy) = &catalogs.policies {
            let retired = policy.shutdown(deadline).await;
            if !retired.work_completed
                || retired.active_jobs != 0
                || retired.retained_read_owners != 0
            {
                return Err(super::mode_error());
            }
        }
        if let Some(rollout) = &catalogs.rollouts {
            rollout.shutdown(settings.shutdown_grace()).await?;
            if !rollout.worker_joined().await {
                return Err(super::mode_error());
            }
        }
        if let Some(telemetry) = catalogs.telemetry.take() {
            telemetry.runtime.shutdown().await?;
        }
        if let Some(control) = catalogs.control.take() {
            control.shutdown(settings.shutdown_grace()).await?;
        }
        if let Some(audit) = &catalogs.audit {
            audit.shutdown(settings.shutdown_grace()).await?;
        }
        Ok(report)
    }

    pub async fn recover_namespace(
        settings: NodeSettings,
        credential: &str,
        tenant: &TenantId,
        request: NativeRecoveryRequest,
        control_runtime: tokio::runtime::Handle,
    ) -> Result<NativeRecoveryReport, PlatformError> {
        let principal = transport::credential_principal(&settings.transport, credential)
            .ok_or_else(super::mode_error)?;
        if !settings.credentials_from_protected_file
            || principal.kind != PrincipalKind::Administrator
            || principal.tenant.as_ref() != Some(tenant)
            || settings.state.is_none()
        {
            return Err(super::mode_error());
        }
        let mut catalogs = Catalogs::open_with_control(&settings, &control_runtime).await?;
        let bootstrap = catalogs.state.take().ok_or_else(super::mode_error)?;
        let policy = Arc::clone(
            catalogs
                .policies
                .as_ref()
                .ok_or_else(super::mode_error)?
                .handle()
                .store(),
        );
        let result = state::recover(
            &settings,
            principal,
            request,
            state::RecoveryOwners {
                artifacts: &catalogs.artifacts,
                deployments: &catalogs.deployments,
                policy: &policy,
                supply_chain: Arc::clone(
                    catalogs
                        .supply_chain
                        .as_ref()
                        .ok_or_else(super::mode_error)?,
                ),
                clock: Arc::clone(&catalogs.clock),
                providers: catalogs.providers.as_deref(),
                http: settings
                    .providers
                    .as_ref()
                    .and_then(|providers| providers.http.as_ref()),
            },
            bootstrap,
        )
        .await;
        let (mut report, failure) = match result {
            Ok(report) => (Some(report), None),
            Err(error) => (None, Some(error)),
        };
        if let Some(report) = &mut report {
            report.retire_catalog_pins();
        }
        drop(policy);
        let clean = catalogs.retire_recovery(&settings).await;
        let mut report = report.ok_or_else(|| failure.unwrap_or_else(super::mode_error))?;
        report.catalogs_retired = clean;
        Ok(report)
    }
}
