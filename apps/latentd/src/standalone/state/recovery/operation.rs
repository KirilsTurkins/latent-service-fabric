//! One authenticated action uses the original current bootstrap and workers.
use super::{
    authority::{Authority, NativeProfile},
    catalog::Catalog,
    codecs::Codecs,
    execution::NativeRecoveryReport,
    request::{Action, NativeRecoveryRequest},
};
use crate::{
    config::{state::StateSettings, NodeSettings},
    standalone::{effects::ProtectedEffectClock, state::StateBootstrap},
};
use latent_artifacts::DirectoryArtifactRepository;
use latent_control_store::{DeploymentStore, DirectoryDeploymentRepository};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeReservation, NativeReservationRequest,
    },
    ActivationClock, InvocationPrincipal, PlatformError, PrincipalKind,
};
use latent_effects::dispatch_store::DispatchCatalog;
use latent_policy::{capability::PolicyStore, supply_chain::SupplyChainAuthority};
use latent_state::{
    embedded::ReadView,
    protected_store::{ProtectedCheckpoint, ProtectedCheckpointConfig, ProtectedStoreOwner},
    recovery::namespace_resume::NamespaceRecoveryView,
    store_identity::ExternalCheckpoint,
    store_io::StoreIoKind,
};
use std::{sync::Arc, time::Instant};

pub(in crate::standalone) struct RecoveryOwners<'a> {
    pub artifacts: &'a Arc<DirectoryArtifactRepository>,
    pub deployments: &'a Arc<DirectoryDeploymentRepository>,
    pub policy: &'a Arc<PolicyStore>,
    pub supply_chain: Arc<SupplyChainAuthority>,
    pub clock: Arc<dyn ActivationClock>,
    pub providers: Option<&'a crate::standalone::providers::ProviderRuntime>,
    pub http: Option<&'a crate::config::HttpInstallation>,
    pub events: Option<&'a crate::config::providers::EventInstallation>,
}

pub(in crate::standalone) async fn recover(
    settings: &NodeSettings,
    principal: &InvocationPrincipal,
    request: NativeRecoveryRequest,
    owners: RecoveryOwners<'_>,
    mut bootstrap: StateBootstrap,
) -> Result<NativeRecoveryReport, PlatformError> {
    let state = settings.state.as_ref().ok_or_else(super::denied)?;
    if !settings.credentials_from_protected_file
        || principal.kind != PrincipalKind::Administrator
        || !bootstrap.matches_local_payload(settings)
        || (request.request.inbox_binding().is_none()
            && (state.tenant_quotas.len() != 1
                || principal.tenant.as_ref()
                    != Some(&latent_core::TenantId(
                        state.tenant_quotas[0].tenant.clone(),
                    ))))
        || !state.operations.iter().any(|operation| {
            operation.publication.as_str() == request.publication
                && Some(&operation.tenant) == principal.tenant.as_ref()
        })
    {
        return Err(super::denied());
    }
    let original = Arc::new(
        bootstrap
            .native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    request_bytes: 32 * 1024,
                    work_bytes: 9 * 1024 * 1024
                        + 512 * 1024
                        + state.store.engine.cache_bytes as u64,
                    response_bytes: 14 * 1024 * 1024,
                },
                bootstrap.deadline,
            )
            .map_err(|_| super::capacity())?,
    );
    let response = original
        .reserve_buffer(NativeBufferClass::Response, 2 * 1024 * 1024)
        .map_err(|_| super::capacity())?;
    // Both result metadata and its stdout frame are prepaid while the SAME
    // original owner is live. Bootstrap close cannot mint another allowance.
    let encoded = original
        .reserve_buffer(NativeBufferClass::Response, 2 * 1024 * 1024)
        .map_err(|_| super::capacity())?;
    let store = bootstrap.open_store_offline(state).await?;
    let (outcome, pins) = if request.request.inbox_binding().is_some() {
        let result = super::inbox_enrollment::run(
            settings, state, principal, &request, &owners, &store, &bootstrap, &original,
        )
        .await;
        (result, None)
    } else {
        match prepare(
            state, principal, request, &owners, &store, &bootstrap, &original,
        )
        .await
        {
            Ok(codecs) => {
                let result = super::execution::execute(&store, Arc::clone(&codecs), state).await;
                (result, Some(codecs))
            }
            Err(error) => (Err(error), None),
        }
    };
    store.close();
    let cutoff = Instant::now() + settings.shutdown_grace();
    let retirement = store
        .drain_async(cutoff, tokio::time::sleep_until(cutoff.into()))
        .map_err(|_| super::super::unavailable())?
        .await;
    let joined = if retirement.snapshot.physically_retired() {
        super::super::store::join_retired_workers(&store, cutoff)
            .await
            .ok()
            .flatten()
    } else {
        None
    };
    drop(bootstrap);
    Ok(NativeRecoveryReport::new(
        outcome, retirement, joined, pins, response, encoded,
    ))
}

pub(super) async fn require_installed_marker(
    store: &ProtectedStoreOwner,
    state: &StateSettings,
    original: &Arc<NativeReservation>,
) -> Result<(), PlatformError> {
    let marker = store
        .ensure_state_mode_marker(state.store_identity.clone(), Arc::clone(original))
        .map_err(|_| super::denied())?
        .await
        .map_err(|_| super::denied())?
        .map_err(|_| super::denied())?;
    if marker.created_here {
        return Err(super::denied());
    }
    Ok(())
}

#[expect(
    clippy::too_many_lines,
    reason = "Original checkpoint, signed selections, installed clock and purpose decisions remain one admission construction"
)]
async fn prepare(
    state: &StateSettings,
    principal: &InvocationPrincipal,
    request: NativeRecoveryRequest,
    owners: &RecoveryOwners<'_>,
    store: &Arc<ProtectedStoreOwner>,
    bootstrap: &StateBootstrap,
    original: &Arc<NativeReservation>,
) -> Result<Arc<Codecs>, PlatformError> {
    require_installed_marker(store, state, original).await?;
    let payloads = if matches!(
        &request.request,
        Action::InspectNamespace {}
            | Action::InspectResultMaintenance {}
            | Action::ExpireResultBody { .. }
    ) {
        bootstrap
            .local_payload_selection
            .as_deref()
            .and_then(super::super::store::LocalPayloadSelection::inventory_payloads)
    } else {
        None
    };
    let (checkpoint, floor) =
        inspect_checkpoint_with_payloads(store, state, original, payloads.as_ref()).await?;
    if floor.inbox_custody().is_some()
        && !matches!(
            &request.request,
            Action::InspectNamespace {}
                | Action::CompactNamespace { .. }
                | Action::SweepResultBodies { .. }
                | Action::InspectResultMaintenance {}
                | Action::ExpireResultBody { .. }
                | Action::Snapshot { .. }
                | Action::InspectRestore { .. }
                | Action::Restore { .. }
                | Action::InspectCloseEffects { .. }
                | Action::CloseEffects { .. }
        )
    {
        // Recovery and resume require explicit inbox reconciliation.
        return Err(super::denied());
    }
    let clock = ProtectedEffectClock::admit(
        Arc::clone(&owners.clock),
        Arc::clone(&owners.supply_chain),
        Some(&floor),
    )?;
    checkpoint.retire().await;
    // Only the requested, configured current publication supplies authority.
    // Descriptive historical sources never become competing installations.
    let input = state
        .operations
        .iter()
        .find(|operation| {
            Some(&operation.tenant) == principal.tenant.as_ref()
                && operation.publication.as_str() == request.publication
        })
        .cloned()
        .ok_or_else(super::denied)?;
    let deployment = tokio::time::timeout_at(
        bootstrap.deadline.into(),
        owners.deployments.get_versioned(
            &input.tenant,
            &latent_core::DeploymentId(input.deployment.clone()),
        ),
    )
    .await
    .map_err(|_| super::denied())??
    .ok_or_else(super::denied)?;
    let repository = Arc::clone(owners.artifacts);
    let configuration = state.clone();
    let native = bootstrap.native.clone();
    let original = Arc::clone(original);
    let metadata = original
        .reserve_buffer(NativeBufferClass::Work, 1024 * 1024)
        .map_err(|_| super::capacity())?;
    let policy = Arc::clone(owners.policy);
    let principal = principal.clone();
    let adapters = match (owners.providers, owners.http) {
        (Some(provider), Some(http)) => {
            provider.typed_deferred_http_adapters(http, clock.clone())?
        }
        (_, None) => Vec::new(),
        _ => return Err(super::denied()),
    };
    let event_adapters = match (owners.providers, owners.events) {
        (Some(provider), Some(events)) => {
            provider.typed_deferred_event_adapters(events, clock.clone())?
        }
        (_, None) => Vec::new(),
        _ => return Err(super::denied()),
    };
    let keeper = Arc::clone(&original);
    let job = store
        .with_store_retaining(
            StoreIoKind::RecoveryRead,
            8 * 1024 * 1024,
            keeper,
            move |engine| {
                let result = (|| {
                    let current = super::selection::capture_current(
                        &repository,
                        &configuration,
                        input,
                        &deployment.manifest,
                        native,
                        Arc::clone(&original),
                    )?;
                    let mut sources = vec![Arc::clone(&current)];
                    for selector in &request.decoder_sources {
                        sources.push(super::selection::capture_decoder(
                            &repository,
                            &current,
                            selector,
                        )?);
                    }
                    let mut profiles = super::selection::current_profiles(
                        &current,
                        &configuration,
                        &deployment.manifest,
                        &adapters,
                        &event_adapters,
                    )?;
                    for source in sources.iter().skip(1) {
                        profiles.extend(super::selection::profiles(
                            source,
                            &adapters,
                            &event_adapters,
                        )?);
                    }
                    let catalog =
                        Catalog::capture(&repository, &sources, profiles, &request.publication)?;
                    let (profile, digest) = configuration
                        .store
                        .inspection_profile()
                        .map_err(|_| super::denied())?;
                    let digest = format!("sha256:{:x}", latent_core::digest::HexDigest(digest));
                    let authority = Authority::retain(
                        policy,
                        catalog.primary(),
                        &principal,
                        &request.request,
                        clock,
                        original.original_deadline(),
                        &NativeProfile {
                            profile,
                            digest: &digest,
                            epoch: configuration.configuration_epoch,
                        },
                    )?;
                    let view = engine.snapshot().map_err(|_| super::denied())?;
                    let op = &catalog.primary().operation;
                    let namespace = NamespaceRecoveryView::capture(
                        &view,
                        &op.target().tenant,
                        &latent_core::StateNamespaceId(op.namespace().into()),
                    )
                    .map_err(|_| super::denied())?
                    .namespace;
                    catalog
                        .primary()
                        .schema
                        .require_namespace(&namespace)
                        .map_err(|_| super::denied())?;
                    let (runtime, review) = Codecs::identities(&catalog, &authority.actor)
                        .map_err(|_| super::denied())?;
                    let codecs = Arc::new(Codecs {
                        catalog,
                        authority,
                        action: request.request,
                        runtime,
                        review,
                        namespace,
                        identity: configuration.store_identity.clone(),
                        quotas: super::super::validation::quotas(&configuration),
                        payloads,
                        checkpoint: floor,
                        original,
                        _metadata: metadata,
                    });
                    codecs.closure(&view).map_err(|_| super::denied())?;
                    Ok(codecs)
                })();
                Ok(result)
            },
        )
        .map_err(|_| super::super::unavailable())?;
    job.await
        .map_err(|_| super::super::unavailable())?
        .map_err(|_| super::super::unavailable())?
}

pub(in crate::standalone::state) async fn inspect_checkpoint(
    store: &ProtectedStoreOwner,
    state: &StateSettings,
    original: &Arc<NativeReservation>,
) -> Result<(ProtectedCheckpoint, ExternalCheckpoint), PlatformError> {
    inspect_checkpoint_with_payloads(store, state, original, None).await
}

async fn inspect_checkpoint_with_payloads(
    store: &ProtectedStoreOwner,
    state: &StateSettings,
    original: &Arc<NativeReservation>,
    payloads: Option<&super::super::store::InventoryPayloads>,
) -> Result<(ProtectedCheckpoint, ExternalCheckpoint), PlatformError> {
    use crate::config::state::STARTUP_VALIDATOR_BYTES;

    let config = ProtectedCheckpointConfig {
        root: state.checkpoint_root.clone(),
    };
    let inventory = || {
        let identity = state.store_identity.clone();
        let quotas = super::super::validation::quotas(state);
        let original = Arc::clone(original);
        let payloads = payloads.cloned();
        move |view: &ReadView| {
            super::super::validation::validate_offline_inventory(
                view,
                &identity,
                &quotas,
                &original,
                payloads.as_ref(),
            )
        }
    };
    let (checkpoint, opened) = store
        .open_checkpoint_with_inbox_inventory(
            config,
            state.store_identity.clone(),
            None,
            Arc::clone(original),
            STARTUP_VALIDATOR_BYTES,
            DispatchCatalog::checkpoint,
            inventory(),
        )
        .map_err(|_| super::denied())?
        .await
        .map_err(|_| super::denied())?;
    opened.map_err(|_| super::denied())?;
    let (checkpoint, inspected) = store
        .inspect_checkpoint_with_inbox_inventory(
            checkpoint,
            Arc::clone(original),
            STARTUP_VALIDATOR_BYTES,
            DispatchCatalog::checkpoint,
            inventory(),
        )
        .map_err(|_| super::denied())?
        .await
        .map_err(|_| super::denied())?;
    let floor = inspected
        .map_err(|_| super::denied())?
        .checkpoint
        .ok_or_else(super::denied)?;
    Ok((checkpoint, floor))
}
