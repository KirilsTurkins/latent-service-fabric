//! One protected transactional trigger is enrolled under offline ownership.

use super::{
    authority::{Authority, NativeProfile},
    operation::{inspect_checkpoint, RecoveryOwners},
    request::{Action, NativeRecoveryRequest},
    selection::{capture_current, RecoverySource},
};
use crate::{
    config::{state::StateSettings, NodeSettings},
    standalone::{effects::ProtectedEffectClock, state::StateBootstrap},
};
use latent_control_store::DeploymentStore;
use latent_core::{
    native_capacity::NativeReservation, DeploymentId, InvocationPrincipal, PlatformError,
    PlatformErrorCode, StateNamespaceId,
};
use latent_effects::dispatch_store::DispatchCatalog;
use latent_manifest::TransactionOperationMode;
use latent_state::{
    embedded::{ReadView, StoreError},
    inbox_scope::{InboxScope, PreparedInboxScope},
    protected_store::{ProtectedStoreError, ProtectedStoreOwner},
    recovery::namespace_resume::NamespaceRecoveryView,
    store_io::StoreIoKind,
};
use std::sync::Arc;

struct ApprovedSource {
    scope: InboxScope,
    source: Arc<RecoverySource>,
    authority: Authority,
    purpose: &'static str,
}

impl ApprovedSource {
    fn check(&self) -> Result<(), StoreError> {
        self.authority.with_current_dependencies(
            self.purpose,
            std::slice::from_ref(self.source.publication()),
            || super::super::validation::live(&self.source.original),
        )
    }

    fn observe(&self, view: &ReadView) -> Result<(Vec<u8>, bool), StoreError> {
        self.check()?;
        let current = NamespaceRecoveryView::capture(
            view,
            &self.source.target().tenant,
            &StateNamespaceId(self.scope.namespace.clone()),
        )?;
        if current.namespace.version.incarnation != self.scope.incarnation
            || current.namespace.state_schema != self.source.asset.get().declaration().state_schema
        {
            return Err(StoreError::Conflict);
        }
        let plan = PreparedInboxScope::prepare(view, &self.scope)?;
        Ok((current.view_token()?, plan.existing()))
    }
}

#[expect(
    clippy::too_many_arguments,
    clippy::too_many_lines,
    reason = "Use the original offline store owners"
)]
pub(super) async fn run(
    settings: &NodeSettings,
    state: &StateSettings,
    principal: &InvocationPrincipal,
    request: &NativeRecoveryRequest,
    owners: &RecoveryOwners<'_>,
    store: &ProtectedStoreOwner,
    bootstrap: &StateBootstrap,
    original: &Arc<NativeReservation>,
) -> Result<serde_json::Value, PlatformError> {
    if !request.decoder_sources.is_empty() {
        return Err(super::denied());
    }
    super::operation::require_installed_marker(store, state, original).await?;
    let (checkpoint, floor) = inspect_checkpoint(store, state, original).await?;
    let clock = ProtectedEffectClock::admit(
        Arc::clone(&owners.clock),
        Arc::clone(&owners.supply_chain),
        Some(&floor),
    )?;
    let (approved, binding) = select(
        settings, state, principal, request, owners, store, bootstrap, original, clock,
    )
    .await?;
    let approved = Arc::new(approved);
    let scope_digest = approved.scope.input_binding().map_err(store_error)?;
    match &request.request {
        Action::InspectInboxSource { .. } | Action::InspectInboxBroker { .. } => {
            let observed = Arc::clone(&approved);
            let keeper = Arc::clone(original);
            let job = store
                .with_store_retaining(
                    StoreIoKind::RecoveryRead,
                    512 * 1024,
                    keeper,
                    move |engine| observed.observe(&engine.snapshot()?),
                )
                .map_err(protected_error)?;
            let (view, existing) = job
                .await
                .map_err(|_| super::super::unavailable())?
                .map_err(protected_error)?;
            checkpoint.retire().await;
            approved.check().map_err(store_error)?;
            let mut report = serde_json::json!({
                "action": "inspect-inbox-source",
                "binding": binding,
                "inputBinding": scope_digest,
                "checkpointGeneration": floor.generation(),
                "view": view,
                "enrolled": existing,
            });
            if matches!(request.request, Action::InspectInboxBroker { .. }) {
                let provider = owners.providers.ok_or_else(super::denied)?;
                let installation = settings
                    .transactional_triggers
                    .as_ref()
                    .ok_or_else(super::denied)?;
                let broker = Box::pin(provider.inspect_incoming(
                    installation,
                    &approved.scope.tenant,
                    &binding,
                    bootstrap.deadline,
                ))
                .await?;
                approved.check().map_err(store_error)?;
                report["action"] = "inspect-inbox-broker".into();
                report["brokerProgress"] =
                    serde_json::to_value(broker).map_err(|_| super::denied())?;
            }
            Ok(report)
        }
        Action::EnrollInboxSource {
            expected_scope,
            expected_view,
            expected_checkpoint_generation,
            ..
        } => {
            if expected_scope != &scope_digest
                || floor.generation() != *expected_checkpoint_generation
            {
                return Err(store_error(StoreError::Conflict));
            }
            let before = Arc::clone(&approved);
            let after = Arc::clone(&approved);
            let identity = state.store_identity.clone();
            let after_identity = identity.clone();
            let quotas = super::super::validation::quotas(state);
            let after_quotas = quotas.clone();
            let expected_view = expected_view.clone();
            let job = store
                .enroll_inbox_source(
                    checkpoint,
                    floor,
                    approved.scope.clone(),
                    Arc::clone(original),
                    crate::config::state::STARTUP_VALIDATOR_BYTES,
                    DispatchCatalog::checkpoint,
                    move |view| {
                        let (current, existing) = before.observe(view)?;
                        if existing || current != expected_view {
                            return Err(StoreError::Conflict);
                        }
                        super::super::validation::validate_inventory(
                            view,
                            &identity,
                            &quotas,
                            &before.source.original,
                        )
                    },
                    move |view, initial| {
                        super::super::validation::validate_inventory_addition(
                            view,
                            &after_identity,
                            &after_quotas,
                            &after.source.original,
                            &after.scope,
                            initial,
                        )
                    },
                    move || approved.check(),
                )
                .map_err(protected_error)?;
            let (checkpoint, enrolled) = job.await.map_err(|_| uncertain())?;
            checkpoint.retire().await;
            let enrolled = enrolled.map_err(protected_error)?;
            Ok(serde_json::json!({
                "action": "enroll-inbox-source",
                "binding": binding,
                "inputBinding": scope_digest,
                "checkpointGeneration": enrolled.generation(),
                "enrolled": true,
            }))
        }
        _ => Err(super::denied()),
    }
}

#[expect(
    clippy::too_many_arguments,
    clippy::too_many_lines,
    reason = "Use the original offline policy and artifact owners"
)]
async fn select(
    settings: &NodeSettings,
    state: &StateSettings,
    principal: &InvocationPrincipal,
    request: &NativeRecoveryRequest,
    owners: &RecoveryOwners<'_>,
    store: &ProtectedStoreOwner,
    bootstrap: &StateBootstrap,
    original: &Arc<NativeReservation>,
    clock: Arc<ProtectedEffectClock>,
) -> Result<(ApprovedSource, String), PlatformError> {
    let installation = settings
        .transactional_triggers
        .as_ref()
        .ok_or_else(super::denied)?;
    let binding_id = request.request.inbox_binding().ok_or_else(super::denied)?;
    let tenant = principal.tenant.as_ref().ok_or_else(super::denied)?;
    let binding = installation
        .configuration
        .bindings
        .iter()
        .find(|binding| binding.id == binding_id && binding.tenant == tenant.0)
        .ok_or_else(super::denied)?;
    let scope = binding
        .inbox_scope(&installation.installation.id)
        .map_err(|_| super::denied())?;
    let input = state
        .operations
        .iter()
        .find(|operation| {
            operation.publication.as_str() == request.publication
                && operation.tenant == *tenant
                && operation.contract == binding.contract
                && operation.function == binding.function
                && operation.route == binding.route
                && operation.incarnation == scope.incarnation
                && operation.entity == scope.entity
        })
        .cloned()
        .ok_or_else(super::denied)?;
    let deployment = tokio::time::timeout_at(
        bootstrap.deadline.into(),
        owners
            .deployments
            .get_versioned(&input.tenant, &DeploymentId(input.deployment.clone())),
    )
    .await
    .map_err(|_| super::denied())??
    .ok_or_else(super::denied)?;
    let repository = Arc::clone(owners.artifacts);
    let configuration = state.clone();
    let native = bootstrap.native.clone();
    let signed_owner = Arc::clone(original);
    let keeper = Arc::clone(original);
    let selection = store
        .with_store_retaining(
            StoreIoKind::RecoveryRead,
            8 * 1024 * 1024,
            keeper,
            move |_| {
                Ok(capture_current(
                    &repository,
                    &configuration,
                    input,
                    &deployment.manifest,
                    native,
                    signed_owner,
                ))
            },
        )
        .map_err(protected_error)?;
    let source = selection
        .await
        .map_err(|_| super::super::unavailable())?
        .map_err(protected_error)??;
    if source.target().service.0 != binding.service
        || source.namespace() != scope.namespace
        || !source
            .asset
            .get()
            .declaration()
            .operations
            .iter()
            .any(|operation| {
                operation.operation == binding.function
                    && operation.mode == TransactionOperationMode::StrictCommand
            })
    {
        return Err(super::denied());
    }
    let (profile, digest) = state
        .store
        .inspection_profile()
        .map_err(|_| super::denied())?;
    let digest = format!("sha256:{:x}", latent_core::digest::HexDigest(digest));
    let authority = Authority::retain_source(
        Arc::clone(owners.policy),
        &source,
        principal,
        &request.request,
        clock,
        original.original_deadline(),
        &NativeProfile {
            profile,
            digest: &digest,
            epoch: state.configuration_epoch,
        },
    )?;
    Ok((
        ApprovedSource {
            scope,
            source,
            authority,
            purpose: request.request.purposes()[0],
        },
        binding.id.clone(),
    ))
}

fn protected_error(error: ProtectedStoreError) -> PlatformError {
    match error {
        ProtectedStoreError::CommitUncertain => uncertain(),
        ProtectedStoreError::Store(error) => store_error(error),
        _ => super::super::unavailable(),
    }
}

fn store_error(error: StoreError) -> PlatformError {
    match error {
        StoreError::CommitUncertain => uncertain(),
        StoreError::Conflict => crate::standalone::error(
            PlatformErrorCode::StateConflict,
            "inbox-source-enrollment-precondition",
        ),
        StoreError::Capacity => super::capacity(),
        _ => super::denied(),
    }
}

fn uncertain() -> PlatformError {
    crate::standalone::error(
        PlatformErrorCode::Unavailable,
        "inbox-source-enrollment-recovery-required",
    )
}
