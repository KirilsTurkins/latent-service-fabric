use super::{
    table::{OperationTable, StoredReceipt, TableData},
    PreparedDeploymentOperation,
};
use crate::deployment_operations::{
    capacity, codec, conflict, error, DeploymentOperationAction, DeploymentOperationReceipt,
    DeploymentOperationRequest, Result, MAX_OPERATION_SCRATCH_BYTES, MAX_RECEIPT_BYTES,
};
use crate::deployments::{
    compiler::compile_catalog_with_runtime, mutations, observation::Work, persistence,
    CompiledCatalog, DirectoryDeploymentRepository,
};
use crate::VersionedDeployment;
use latent_core::{DeploymentId, PlatformErrorCode, TenantId};
use std::sync::Arc;

impl DirectoryDeploymentRepository {
    pub async fn prepare_operation(
        &self,
        request: DeploymentOperationRequest,
    ) -> Result<PreparedDeploymentOperation> {
        if request.retained_bytes() > crate::deployment_operations::MAX_REQUEST_BYTES {
            return Err(capacity());
        }
        let work_owner = super::super::rollouts::WorkReservation::acquire(&self.rollout_work)
            .map_err(|_| capacity())?;
        let scratch = self.operation_budget.reserve(
            request
                .retained_bytes()
                .saturating_mul(4)
                .saturating_add(MAX_OPERATION_SCRATCH_BYTES + 4096),
        )?;
        let request = request.normalize()?;
        self.validate_target(&request.context().tenant, request.id())?;
        let digest = request.normalized_digest()?;
        let previous = self.read_publication();
        let reply_bytes = request
            .retained_bytes()
            .saturating_add(2 * MAX_RECEIPT_BYTES + 2048);
        let reply = self.operation_budget.read(reply_bytes)?;
        if let Some(found) = previous
            .operations
            .find(&request.context().tenant, &request.context().operation_id)
        {
            if found.request_digest != digest
                || found.actor != request.context().actor
                || found.action != request.action()
                || found.deployment_id != *request.id()
            {
                return Err(conflict());
            }
            if !previous.confirmed {
                return Err(uncertain());
            }
            let receipt = found.clone();
            let apply_result = match request {
                DeploymentOperationRequest::Apply { manifest, .. } => {
                    let encoded = super::super::rollouts::table::manifest(&manifest)?;
                    if codec::hash(encoded.as_bytes()) != receipt.manifest_digest
                        || manifest.release != receipt.component
                    {
                        return Err(conflict());
                    }
                    Some(VersionedDeployment {
                        manifest,
                        generation: receipt.object_generation,
                    })
                }
                DeploymentOperationRequest::Delete { .. } => None,
            };
            return Ok(PreparedDeploymentOperation {
                owner: Arc::clone(&self.rollout_work),
                next_routes: Arc::clone(&previous.routes),
                next_operations: Arc::clone(&previous.operations),
                previous,
                receipt,
                apply_result,
                bytes: Vec::new(),
                replayed: true,
                reply,
                _scratch: scratch,
                _work: work_owner,
            });
        }
        if !previous.confirmed {
            return Err(uncertain());
        }
        if request.context().expected_state_version != previous.transaction {
            return Err(state_conflict());
        }
        let context = request.context().clone();
        let action = request.action();
        let expected_generation = request.expected_generation();
        let id = request.id().clone();
        let manifest = match request {
            DeploymentOperationRequest::Apply { manifest, .. } => Some(manifest),
            DeploymentOperationRequest::Delete { .. } => None,
        };
        check_precondition(
            &previous.routes,
            &context.tenant,
            &id,
            expected_generation,
            manifest.as_ref(),
        )?;
        if id.0 == "default" && action == DeploymentOperationAction::Apply {
            return Err(error(
                PlatformErrorCode::AlreadyExists,
                "reserved-default-route",
            ));
        }
        let reservation = previous.operations.reserve_next(&self.operation_budget)?;
        let route_generation = super::super::next_generation(previous.routes.generation)?;
        let state_version = previous.transaction.checked_add(1).ok_or_else(capacity)?;
        let timestamp = super::super::now()?;
        let mut desired = previous.routes.deployments.clone();
        let mut versions = previous.routes.versions.clone();
        let (apply_result, manifest_digest, component, object_generation) =
            if let Some(manifest) = manifest {
                let encoded = super::super::rollouts::table::manifest(&manifest)?;
                let digest = codec::hash(encoded.as_bytes());
                let component = manifest.release.clone();
                let result = VersionedDeployment {
                    manifest: manifest.clone(),
                    generation: route_generation.0,
                };
                versions.insert(id.clone(), route_generation.0);
                desired.insert(id.clone(), Arc::new(manifest));
                (Some(result), digest, component, route_generation.0)
            } else {
                let old = previous.routes.record_by_id(&id).ok_or_else(not_found)?;
                let encoded = old
                    .attributes
                    .get("lsf.deployment")
                    .ok_or_else(crate::deployment_operations::corrupt)?;
                let digest = codec::hash(encoded.as_bytes());
                let component = old.deployment.release.clone();
                let generation = previous.routes.versions[&id];
                desired.remove(&id);
                versions.remove(&id);
                (None, digest, component, generation)
            };
        let next_routes = Arc::new(
            compile_catalog_with_runtime(
                desired,
                versions,
                route_generation,
                timestamp,
                self.artifacts.as_ref(),
                self.config,
                Some(&previous.routes),
                &mut Work::default(),
                self.runtime_profile.as_deref(),
                self.lifecycle.as_ref(),
            )
            .await?,
        );
        let mut receipt = DeploymentOperationReceipt {
            format_version: 1,
            tenant: context.tenant,
            actor: context.actor,
            operation_id: context.operation_id,
            action,
            deployment_id: id,
            request_digest: digest,
            expected_state_version: context.expected_state_version,
            expected_generation,
            object_generation,
            route_generation,
            state_version,
            manifest_digest,
            component,
            completed_at_unix_millis: timestamp,
            receipt_digest: codec::hash(b""),
        };
        receipt.receipt_digest = codec::receipt_hash(&receipt)?;
        receipt.canonical_bytes()?;
        let old = &previous.operations.data;
        let mut receipts = Vec::with_capacity(old.receipt_slots);
        let skip = usize::from(old.receipts.len() == old.receipt_slots);
        receipts.extend(old.receipts.iter().skip(skip).cloned());
        let sequence = old.operation_sequence.checked_add(1).ok_or_else(capacity)?;
        receipts.push(StoredReceipt {
            sequence,
            receipt: receipt.clone(),
        });
        let next_operations = OperationTable::from_reserved(
            TableData {
                format_version: 1,
                receipt_slots: old.receipt_slots,
                operation_sequence: sequence,
                receipts,
            },
            reservation,
            self.operation_budget.limits,
        )?;
        next_operations.validate_catalog(state_version, route_generation.0)?;
        let control = persistence::ControlPayloadRef {
            transaction_version: state_version,
            rollouts: &previous.rollouts.data,
            deployment_operations: Some(&next_operations.data),
        };
        let bytes = persistence::encode_combined(
            &next_routes,
            &control,
            self.config.max_state_bytes,
            &mut Work::default(),
        )?;
        Ok(PreparedDeploymentOperation {
            owner: Arc::clone(&self.rollout_work),
            previous,
            next_routes,
            next_operations,
            receipt,
            apply_result,
            bytes,
            replayed: false,
            reply,
            _scratch: scratch,
            _work: work_owner,
        })
    }
}
pub(super) fn check_precondition(
    catalog: &CompiledCatalog,
    tenant: &TenantId,
    id: &DeploymentId,
    expected: u64,
    apply: Option<&latent_manifest::DeploymentManifest>,
) -> Result<()> {
    let old = catalog.deployments.get(id);
    if old.is_some_and(|m| m.metadata.tenant.as_ref() != Some(tenant)) {
        return Err(if apply.is_some() {
            error(
                PlatformErrorCode::PermissionDenied,
                "deployment-scope-conflict",
            )
        } else {
            not_found()
        });
    }
    if catalog.versions.get(id).copied().unwrap_or(0) != expected {
        return Err(error(
            PlatformErrorCode::StateConflict,
            "deployment-generation-conflict",
        ));
    }
    if let Some(manifest) = apply {
        mutations::check_scope(old.map(Arc::as_ref), manifest)?;
    } else if old.is_none() {
        return Err(not_found());
    }
    Ok(())
}
pub(super) fn state_conflict() -> latent_core::PlatformError {
    error(
        PlatformErrorCode::StateConflict,
        "deployment-state-version-conflict",
    )
}
pub(super) fn uncertain() -> latent_core::PlatformError {
    error(
        PlatformErrorCode::Unavailable,
        "deployment-operation-uncertain",
    )
}
fn not_found() -> latent_core::PlatformError {
    error(PlatformErrorCode::NotFound, "deployment-not-found")
}
