use super::super::{
    compiler::compile_catalog_with_runtime, next_generation, now, observation::Work, persistence,
    CompiledCatalog, DirectoryDeploymentRepository,
};
use super::{
    comparison,
    table::{self, CohortMember, StoredReceipt, StoredRollout},
    PreparedRolloutMutation, WorkReservation,
};
use crate::rollouts::{
    capacity, codec, conflict, error, invalid, Result, RolloutAction, RolloutCommand,
    RolloutContext, RolloutLimits, RolloutObjectVersion, RolloutOperationOutcome,
    RolloutOperationReceipt, RolloutReason, RolloutRelease, RolloutRequest, RolloutState,
    RolloutStatus, MAX_REQUEST_BYTES,
};
use latent_core::{ArtifactBlobDigest, DeploymentId, PlatformErrorCode, ServiceId, TenantId};
use latent_manifest::{__serde_json as json, JsonManifestCodec, ManifestCodec};
use std::sync::Arc;

impl DirectoryDeploymentRepository {
    #[must_use]
    pub fn rollout_limits(&self) -> RolloutLimits {
        self.rollout_limits
    }
    pub async fn prepare_rollout(
        &self,
        request: RolloutRequest,
    ) -> Result<PreparedRolloutMutation> {
        self.prepare_rollout_inner(request, None, false).await
    }
    pub async fn prepare_canary_promotion(
        &self,
        request: RolloutRequest,
        proof: Option<latent_telemetry::phase2_canary::SealedCanaryWindow>,
    ) -> Result<PreparedRolloutMutation> {
        if !matches!(request.action(), RolloutAction::Promote) {
            return Err(invalid());
        }
        self.prepare_rollout_inner(request, proof, true).await
    }
    #[expect(
        clippy::too_many_lines,
        reason = "one bounded semantic preparation validates the full old/new pair before returning its affine commit owner"
    )]
    async fn prepare_rollout_inner(
        &self,
        request: RolloutRequest,
        proof: Option<latent_telemetry::phase2_canary::SealedCanaryWindow>,
        promotion: bool,
    ) -> Result<PreparedRolloutMutation> {
        request.validate(self.rollout_limits)?;
        let work_owner = WorkReservation::acquire(&self.rollout_work)?;
        let request = normalize(request)?;
        let digest = request_digest(&request)?;
        let previous = self.read_publication();
        let context = request.context();
        if let Some(found) = previous.rollouts.receipt(
            &context.tenant,
            request.id(),
            &context.operation.operation_id,
        ) {
            if found.request_digest != digest
                || found.actor != context.actor
                || found.action != request.action()
            {
                return Err(conflict());
            }
            if !previous.confirmed {
                return Err(error(
                    PlatformErrorCode::Unavailable,
                    "rollout-durability-uncertain",
                ));
            }
            return Ok(PreparedRolloutMutation {
                owner: Arc::clone(&self.rollout_work),
                next_routes: Arc::clone(&previous.routes),
                next_table: Arc::clone(&previous.rollouts),
                receipt: found.clone(),
                previous,
                bytes: Vec::new(),
                request_digest: digest,
                replayed: true,
                state_only: true,
                canary_proof: None,
                _work: work_owner,
            });
        }
        if request.action() == RolloutAction::Promote && !promotion {
            return Err(invalid());
        }
        let mut canary_decision = None;
        let transaction = previous.transaction.checked_add(1).ok_or_else(capacity)?;
        let revision = context
            .operation
            .expected_revision
            .checked_add(1)
            .ok_or_else(capacity)?;
        let timestamp = now()?;
        let reservation = previous.rollouts.reserve_next(&self.rollout_budget)?;
        let mut row = match &request {
            RolloutRequest::Start { context, spec } => {
                if let Some(policy) = spec.canary_policy {
                    let hub = self.canary.as_ref().ok_or_else(|| {
                        error(PlatformErrorCode::Unavailable, "rollout-canary-unavailable")
                    })?;
                    if policy.minimum_candidate_samples
                        > hub.config().maximum_samples_per_series as u64
                        || policy.minimum_candidate_samples
                            > hub.config().maximum_total_samples as u64
                    {
                        return Err(capacity());
                    }
                }
                if previous.rollouts.row(&context.tenant, &spec.id).is_some() {
                    return Err(conflict());
                }
                if previous.rollouts.data.rows.len() >= self.rollout_limits.maximum_rows {
                    return Err(capacity());
                }
                let base = previous
                    .routes
                    .deployments
                    .get(&spec.base.id)
                    .ok_or_else(|| error(PlatformErrorCode::NotFound, "rollout-base-not-found"))?;
                if base.metadata.tenant.as_ref() != Some(&context.tenant)
                    || base.service != spec.candidate.service
                    || base.metadata.namespace != spec.candidate.metadata.namespace
                {
                    return Err(error(
                        PlatformErrorCode::PermissionDenied,
                        "rollout-scope-conflict",
                    ));
                }
                if previous.routes.versions.get(&spec.base.id) != Some(&spec.base.generation) {
                    return Err(conflict());
                }
                let initial = cohort(&previous.routes, &context.tenant, &base.service)?;
                if initial.len() != 1 || initial[0].id != spec.base.id.0 {
                    return Err(error(
                        PlatformErrorCode::IncompatibleContract,
                        "rollout-initial-cohort-unsupported",
                    ));
                }
                if previous.routes.deployments.contains_key(&spec.candidate.id)
                    || base.release == spec.candidate.release
                {
                    return Err(conflict());
                }
                if previous.rollouts.data.rows.iter().any(|r| {
                    r.status.tenant == context.tenant
                        && r.status.service == base.service
                        && active(r.status.state)
                }) {
                    return Err(conflict());
                }
                let (old_package, new_package) = comparison::compare(
                    self.artifacts.as_ref(),
                    &context.tenant,
                    &base.release,
                    &spec.candidate.release,
                )
                .await?;
                let base_manifest = table::manifest(base)?;
                let candidate_manifest = table::manifest(&spec.candidate)?;
                let plan_digest = codec::hash(b"");
                StoredRollout {
                    status: RolloutStatus {
                        id: spec.id.clone(),
                        tenant: context.tenant.clone(),
                        service: base.service.clone(),
                        revision,
                        state: RolloutState::Running,
                        reason: RolloutReason::StageApplied,
                        current_step: 0,
                        candidate_weights: spec.candidate_weights.clone(),
                        base: RolloutRelease {
                            deployment_id: base.id.clone(),
                            component: base.release.clone(),
                            package: old_package,
                        },
                        candidate: RolloutRelease {
                            deployment_id: spec.candidate.id.clone(),
                            component: spec.candidate.release.clone(),
                            package: new_package,
                        },
                        objects: Vec::new(),
                        route_generation: previous.routes.generation,
                        state_version: transaction,
                        plan_digest,
                        previous_route_generation: previous.routes.generation,
                        created_at_unix_millis: timestamp,
                        updated_at_unix_millis: timestamp,
                        retained_operation_floor: previous.rollouts.floor(),
                        canary_policy: spec.canary_policy,
                    },
                    base_manifest,
                    candidate_manifest,
                    cohort: initial,
                }
            }
            RolloutRequest::Change {
                context,
                id,
                command,
            } => {
                let prior = previous
                    .rollouts
                    .row(&context.tenant, id)
                    .ok_or_else(|| error(PlatformErrorCode::NotFound, "rollout-not-found"))?;
                if prior.status.revision != context.operation.expected_revision {
                    return Err(conflict());
                }
                let mut row = prior.clone();
                match command {
                    RolloutCommand::Advance { next_step }
                    | RolloutCommand::Promote { next_step } => {
                        if matches!(command, RolloutCommand::Advance { .. })
                            && row.status.canary_policy.is_some()
                        {
                            return Err(invalid());
                        }
                        if matches!(command, RolloutCommand::Promote { .. }) {
                            let proof = proof.as_ref().ok_or_else(|| {
                                error(
                                    PlatformErrorCode::Unavailable,
                                    "rollout-canary-evidence-required",
                                )
                            })?;
                            canary_decision = Some(self.canary_decision(&previous, prior, proof)?);
                        }
                        if row.status.state != RolloutState::Running
                            || *next_step
                                != row
                                    .status
                                    .current_step
                                    .checked_add(1)
                                    .ok_or_else(capacity)?
                            || *next_step as usize >= row.status.candidate_weights.len()
                        {
                            return Err(conflict());
                        }
                        row.status.current_step = *next_step;
                    }
                    RolloutCommand::Pause => {
                        if row.status.state != RolloutState::Running {
                            return Err(conflict());
                        }
                        row.status.state = RolloutState::Paused;
                    }
                    RolloutCommand::Resume => {
                        if row.status.state != RolloutState::Paused {
                            return Err(conflict());
                        }
                        row.status.state = RolloutState::Running;
                    }
                    RolloutCommand::Abort => {
                        if !active(row.status.state) {
                            return Err(conflict());
                        }
                        row.status.state = RolloutState::Aborted;
                    }
                }
                row.status.revision = revision;
                row.status.state_version = transaction;
                row.status.updated_at_unix_millis = timestamp;
                row
            }
        };
        if matches!(request, RolloutRequest::Start { .. }) {
            row.status.plan_digest = table::plan_hash(&row)?;
        }
        let state_only = matches!(
            request.action(),
            RolloutAction::Pause | RolloutAction::Abort
        );
        let next_routes = if state_only {
            row.status.reason = RolloutReason::OperatorRequested;
            Arc::clone(&previous.routes)
        } else {
            if matches!(request, RolloutRequest::Change { .. }) {
                if !cohort_matches(&previous.routes, &row)? {
                    return Err(error(
                        PlatformErrorCode::StateConflict,
                        "rollout-cohort-conflict",
                    ));
                }
                let packages = comparison::compare(
                    self.artifacts.as_ref(),
                    &row.status.tenant,
                    &row.status.base.component,
                    &row.status.candidate.component,
                )
                .await?;
                if packages
                    != (
                        row.status.base.package.clone(),
                        row.status.candidate.package.clone(),
                    )
                {
                    return Err(error(
                        PlatformErrorCode::PermissionDenied,
                        "rollout-package-association-changed",
                    ));
                }
            }
            let generation = next_generation(previous.routes.generation)?;
            let mut desired = previous.routes.deployments.clone();
            let mut versions = previous.routes.versions.clone();
            let candidate_weight = row.status.candidate_weights[row.status.current_step as usize];
            let mut candidate = table::decode_manifest(&row.candidate_manifest)?;
            candidate.route_weight = candidate_weight;
            versions.insert(candidate.id.clone(), generation.0);
            desired.insert(candidate.id.clone(), Arc::new(candidate));
            if candidate_weight == 10000 {
                desired.remove(&row.status.base.deployment_id);
                versions.remove(&row.status.base.deployment_id);
                row.status.state = RolloutState::Completed;
                row.status.reason = RolloutReason::Completed;
            } else {
                let mut base = table::decode_manifest(&row.base_manifest)?;
                base.route_weight = 10000 - candidate_weight;
                versions.insert(base.id.clone(), generation.0);
                desired.insert(base.id.clone(), Arc::new(base));
                row.status.reason = RolloutReason::StageApplied;
            }
            let catalog = compile_catalog_with_runtime(
                desired,
                versions,
                generation,
                timestamp,
                self.artifacts.as_ref(),
                self.config,
                Some(&previous.routes),
                &mut Work::default(),
                self.runtime_profile.as_deref(),
                self.lifecycle.as_ref(),
            )
            .await?;
            Arc::new(catalog)
        };
        row.status.previous_route_generation = previous.routes.generation;
        row.status.route_generation = next_routes.generation;
        if !state_only {
            row.cohort = cohort(&next_routes, &row.status.tenant, &row.status.service)?;
        }
        row.status.objects = managed_objects(&next_routes, &row);
        let mut receipt = RolloutOperationReceipt {
            rollout_id: row.status.id.clone(),
            tenant: context.tenant.clone(),
            operation_id: context.operation.operation_id.clone(),
            request_digest: digest.clone(),
            actor: context.actor.clone(),
            action: request.action(),
            expected_revision: context.operation.expected_revision,
            revision,
            outcome: RolloutOperationOutcome::Committed,
            reason: row.status.reason,
            state_version: transaction,
            route_generation: next_routes.generation,
            state: row.status.state,
            step: row.status.current_step,
            plan_digest: row.status.plan_digest.clone(),
            completed_at_unix_millis: timestamp,
            receipt_digest: codec::hash(b""),
            canary_decision,
        };
        receipt.receipt_digest = table::receipt_hash(&receipt)?;
        receipt.canonical_bytes()?;
        let mut data = previous.rollouts.data.clone();
        data.rows
            .retain(|r| r.status.tenant != context.tenant || r.status.id != *request.id());
        data.rows.push(row);
        data.rows.sort_by(|a, b| {
            (&a.status.tenant, &a.status.id).cmp(&(&b.status.tenant, &b.status.id))
        });
        data.operation_sequence = data
            .operation_sequence
            .checked_add(1)
            .ok_or_else(capacity)?;
        if data.receipts.len() == data.receipt_slots {
            data.receipts.remove(0);
        }
        data.receipts.push(StoredReceipt {
            sequence: data.operation_sequence,
            receipt: receipt.clone(),
        });
        let next_table =
            table::RolloutTable::from_reserved(data, reservation, self.rollout_limits)?;
        next_table.validate_catalog(transaction, next_routes.generation)?;
        let control = persistence::ControlPayloadRef {
            transaction_version: transaction,
            rollouts: &next_table.data,
        };
        let bytes = persistence::encode_combined(
            &next_routes,
            &control,
            self.config.max_state_bytes,
            &mut Work::default(),
        )?;
        Ok(PreparedRolloutMutation {
            owner: Arc::clone(&self.rollout_work),
            previous,
            next_routes,
            next_table,
            bytes,
            receipt,
            request_digest: digest,
            replayed: false,
            state_only,
            canary_proof: proof,
            _work: work_owner,
        })
    }
}
fn normalize(mut request: RolloutRequest) -> Result<RolloutRequest> {
    match &mut request {
        RolloutRequest::Start { context, spec } => {
            normalize_context(context);
            spec.id.0 = spec.id.0.as_str().into();
            spec.base.id.0 = spec.base.id.0.as_str().into();
            spec.candidate.normalize_storage_fields();
            let id = spec.candidate.id.clone();
            let bytes = JsonManifestCodec::default()
                .encode_deployment(&spec.candidate)
                .map_err(|_| invalid())?;
            if bytes.len() > MAX_REQUEST_BYTES {
                return Err(capacity());
            }
            spec.candidate = JsonManifestCodec::default()
                .decode_deployment(&bytes)
                .map_err(|_| invalid())?;
            if spec.candidate.id != id {
                return Err(invalid());
            }
            spec.candidate_weights = spec.candidate_weights.clone();
        }
        RolloutRequest::Change { context, id, .. } => {
            normalize_context(context);
            id.0 = id.0.as_str().into();
        }
    }
    Ok(request)
}
impl RolloutRequest {
    /// Canonical bounded client command identity, independent of server evidence.
    pub fn request_digest(&self, limits: RolloutLimits) -> Result<ArtifactBlobDigest> {
        self.validate(limits)?;
        request_digest(&normalize(self.clone())?)
    }
}
fn normalize_context(context: &mut RolloutContext) {
    context.tenant.0 = context.tenant.0.as_str().into();
    context.actor.subject = context.actor.subject.as_str().into();
    context.operation.operation_id = context.operation.operation_id.as_str().into();
}
fn request_digest(request: &RolloutRequest) -> Result<ArtifactBlobDigest> {
    let context = request.context();
    let command = match request {
        RolloutRequest::Start { spec, .. } => {
            let mut value = json::json!({"base":spec.base.id.0,"baseGeneration":spec.base.generation,"candidate":table::manifest(&spec.candidate)?,"weights":spec.candidate_weights});
            if let Some(policy) = spec.canary_policy {
                value["canaryPolicy"] = json::to_value(policy).map_err(|_| invalid())?;
            }
            value
        }
        RolloutRequest::Change { command, .. } => {
            json::json!({"nextStep":match command{RolloutCommand::Advance{next_step}|RolloutCommand::Promote{next_step}=>Some(*next_step),_=>None}})
        }
    };
    Ok(codec::hash(&codec::encode(
        &json::json!({"version":1,"tenant":context.tenant.0,"actor":context.actor,"operation":context.operation.operation_id,"expectedRevision":context.operation.expected_revision,"id":request.id(),"action":request.action(),"command":command}),
        MAX_REQUEST_BYTES,
    )?))
}
pub(super) fn active(state: RolloutState) -> bool {
    matches!(
        state,
        RolloutState::Running | RolloutState::Paused | RolloutState::Conflicted
    )
}
pub(super) fn cohort(
    catalog: &CompiledCatalog,
    tenant: &TenantId,
    service: &ServiceId,
) -> Result<Vec<CohortMember>> {
    let mut result = Vec::new();
    for record in &catalog.records {
        let d = &record.deployment;
        if d.metadata.tenant.as_ref() == Some(tenant) && d.service == *service {
            if result.len() == 2 {
                return Err(error(
                    PlatformErrorCode::StateConflict,
                    "rollout-cohort-conflict",
                ));
            }
            result.push(CohortMember {
                id: d.id.0.clone(),
                generation: catalog.versions[&d.id],
                manifest_digest: codec::hash(
                    record
                        .attributes
                        .get("lsf.deployment")
                        .ok_or_else(invalid)?
                        .as_bytes(),
                )
                .as_str()
                .into(),
            });
        }
    }
    result.sort_by(|a, b| a.id.cmp(&b.id));
    Ok(result)
}
pub(super) fn cohort_matches(catalog: &CompiledCatalog, row: &StoredRollout) -> Result<bool> {
    Ok(cohort(catalog, &row.status.tenant, &row.status.service)? == row.cohort)
}
pub(super) fn managed_objects(
    catalog: &CompiledCatalog,
    row: &StoredRollout,
) -> Vec<RolloutObjectVersion> {
    let mut objects = Vec::new();
    for id in [
        &row.status.base.deployment_id,
        &row.status.candidate.deployment_id,
    ] {
        if let Some(generation) = catalog.versions.get(id) {
            objects.push(RolloutObjectVersion {
                deployment_id: DeploymentId(id.0.as_str().into()),
                generation: *generation,
            });
        }
    }
    objects.sort_by(|a, b| a.deployment_id.cmp(&b.deployment_id));
    objects
}
