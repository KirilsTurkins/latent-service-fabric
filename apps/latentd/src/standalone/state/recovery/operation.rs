//! One authenticated action uses the original current bootstrap and workers.
use super::{
    authority::{Authority, NativeProfile},
    catalog::Catalog,
    codecs::Codecs,
    execution::NativeRecoveryReport,
    request::NativeRecoveryRequest,
};
use crate::{
    config::NodeSettings,
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
    protected_store::{ProtectedCheckpointConfig, ProtectedStoreOwner},
    recovery::namespace_resume::NamespaceRecoveryView,
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
        || state.tenant_quotas.len() != 1
        || principal.tenant.as_ref()
            != Some(&latent_core::TenantId(
                state.tenant_quotas[0].tenant.clone(),
            ))
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
    let prepared = prepare(
        state, principal, request, &owners, &store, &bootstrap, &original,
    )
    .await;
    let (outcome, pins) = match prepared {
        Ok(codecs) => {
            let result = super::execution::execute(&store, Arc::clone(&codecs), state).await;
            (result, Some(codecs))
        }
        Err(error) => (Err(error), None),
    };
    store.close();
    let cutoff = Instant::now() + settings.shutdown_grace();
    let retirement = store
        .drain_async(cutoff, tokio::time::sleep_until(cutoff.into()))
        .map_err(|_| super::super::unavailable())?
        .await;
    let joined = if retirement.snapshot.physically_retired() {
        store.reap_retired_threads().ok()
    } else {
        None
    };
    drop(bootstrap);
    Ok(NativeRecoveryReport::new(
        outcome, retirement, joined, pins, response, encoded,
    ))
}

async fn prepare(
    state: &crate::config::state::StateSettings,
    principal: &InvocationPrincipal,
    request: NativeRecoveryRequest,
    owners: &RecoveryOwners<'_>,
    store: &Arc<ProtectedStoreOwner>,
    bootstrap: &StateBootstrap,
    original: &Arc<NativeReservation>,
) -> Result<Arc<Codecs>, PlatformError> {
    let marker = store
        .ensure_state_mode_marker(state.store_identity.clone(), Arc::clone(original))
        .map_err(|_| super::denied())?
        .await
        .map_err(|_| super::denied())?
        .map_err(|_| super::denied())?;
    if marker.created_here {
        return Err(super::denied());
    }
    let (checkpoint, opened) = store
        .open_checkpoint(
            ProtectedCheckpointConfig {
                root: state.checkpoint_root.clone(),
            },
            state.store_identity.clone(),
            None,
            Arc::clone(original),
            DispatchCatalog::checkpoint,
        )
        .map_err(|_| super::denied())?
        .await
        .map_err(|_| super::denied())?;
    opened.map_err(|_| super::denied())?;
    let (checkpoint, inspected) = store
        .inspect_checkpoint(checkpoint, DispatchCatalog::checkpoint)
        .map_err(|_| super::denied())?
        .await
        .map_err(|_| super::denied())?;
    let inspected = inspected.map_err(|_| super::denied())?;
    let floor = inspected.checkpoint.ok_or_else(super::denied)?;
    let clock = ProtectedEffectClock::admit(
        Arc::clone(&owners.clock),
        Arc::clone(&owners.supply_chain),
        Some(&floor),
    )?;
    checkpoint.retire().await;
    let mut selections = Vec::new();
    for operation in &state.operations {
        if Some(&operation.tenant) != principal.tenant.as_ref()
            || super::profile::Profile::installed(&operation.component.0).is_err()
            || selections.iter().any(
                |(existing, _): &(
                    crate::config::state::OperationSettings,
                    latent_manifest::DeploymentManifest,
                )| existing.publication == operation.publication,
            )
        {
            continue;
        }
        if selections.len() == 4 {
            return Err(super::capacity());
        }
        let deployment = tokio::time::timeout_at(
            bootstrap.deadline.into(),
            owners.deployments.get_versioned(
                &operation.tenant,
                &latent_core::DeploymentId(operation.deployment.clone()),
            ),
        )
        .await
        .map_err(|_| super::denied())??
        .ok_or_else(super::denied)?;
        selections.push((operation.clone(), deployment.manifest));
    }
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
    let keeper = Arc::clone(&original);
    let job = store
        .with_store_retaining(
            StoreIoKind::RecoveryRead,
            8 * 1024 * 1024,
            keeper,
            move |engine| {
                let result = (|| {
                    let mut installed = Vec::new();
                    let mut profiles = Vec::new();
                    for (input, deployment) in selections {
                        let operation = super::selection::capture(
                            &repository,
                            &configuration,
                            input.clone(),
                            &deployment,
                            native.clone(),
                            Arc::clone(&original),
                        )?;
                        if let Some(profile) =
                            super::selection::profile(&operation, &input, &adapters)?
                        {
                            profiles.push(profile);
                        }
                        installed.push(operation);
                    }
                    let catalog =
                        Catalog::capture(&repository, &installed, profiles, &request.publication)?;
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
