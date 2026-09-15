use super::{
    super::{observation::Work, persistence, DirectoryDeploymentRepository},
    table::{HttpTable, StoredRecord, RECEIPTS},
    PreparedTriggerOperation,
};
use crate::http_routes::{
    capacity, codec, conflict, corrupt, definition, invalid, TriggerOperationAction,
    TriggerOperationReceipt, TriggerOperationRequest, VersionedTrigger, MAX_DEFINITION_BYTES,
    MAX_IDENTIFIER_BYTES, MAX_RECEIPT_BYTES, MAX_RECORDS, MAX_TABLE_BYTES,
};
use latent_artifacts::{LifecycleScope, PublicationRef};
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::Arc;

impl DirectoryDeploymentRepository {
    #[expect(
        clippy::too_many_lines,
        reason = "one affine preparation owns normalized replay, CAS, candidate reservation and exact durable bytes"
    )]
    pub fn prepare_trigger_operation(
        &self,
        request: TriggerOperationRequest,
    ) -> Result<PreparedTriggerOperation, PlatformError> {
        validate_request(&request)?;
        let work = super::super::rollouts::WorkReservation::acquire(&self.rollout_work)?;
        let scratch = self
            .http_budget
            .reserve(crate::deployment_operations::MAX_OPERATION_SCRATCH_BYTES)?;
        let request = match request {
            TriggerOperationRequest::Apply {
                context,
                manifest,
                expected_generation,
            } => TriggerOperationRequest::Apply {
                context,
                manifest: definition::normalize(manifest)?.0,
                expected_generation,
            },
            other @ TriggerOperationRequest::Delete { .. } => other,
        };
        let definition = match &request {
            TriggerOperationRequest::Apply { manifest, .. } => Some(codec::manifest(manifest)?),
            TriggerOperationRequest::Delete { .. } => None,
        };
        let digest = codec::request_hash(&request, definition.as_deref())?;
        let previous = self.read_publication();
        let reply = self
            .http_budget
            .read(MAX_DEFINITION_BYTES + 2 * MAX_RECEIPT_BYTES + 4096)?;
        if !previous.confirmed {
            return Err(super::unavailable());
        }
        if let Some(found) = previous
            .http
            .find(&request.context().tenant.0, &request.context().operation_id)
        {
            if found.request_digest != digest
                || found.actor != request.context().actor
                || found.trigger_id != request.id()
            {
                return Err(conflict());
            }
            let receipt = found.clone();
            let apply_result = match request {
                TriggerOperationRequest::Apply { manifest, .. } => Some(VersionedTrigger {
                    manifest,
                    generation: receipt.object_generation,
                    component: receipt.component.clone(),
                }),
                TriggerOperationRequest::Delete { .. } => None,
            };
            return Ok(PreparedTriggerOperation {
                owner: Arc::clone(&self.rollout_work),
                next: Arc::clone(&previous.http),
                previous,
                receipt,
                apply_result,
                bytes: Vec::new(),
                replayed: true,
                reply,
                _scratch: scratch,
                _work: work,
            });
        }
        if previous.transaction != request.context().expected_state_version {
            return Err(conflict());
        }
        let index = previous
            .http
            .index(&request.context().tenant.0, request.id());
        if index.map_or(0, |i| previous.http.data.records[i].generation)
            != request.expected_generation()
        {
            return Err(conflict());
        }
        let generation = previous.transaction.checked_add(1).ok_or_else(capacity)?;
        let expected = request.expected_generation();
        let context = request.context().clone();
        // Reserve the entire bounded candidate before copying any current rows.
        let reservation = self.http_budget.reserve(MAX_TABLE_BYTES)?;
        let mut data = previous.http.data.clone();
        let (manifest, component, publication, action, object_generation, apply_result) =
            match request {
                TriggerOperationRequest::Apply { manifest, .. } => {
                    let (_, matcher) = definition::normalize(manifest.clone())?;
                    for (i, old) in previous.http.rows.iter().enumerate() {
                        if Some(i) != index
                            && old.matcher.authority == matcher.authority
                            && (old.manifest.metadata.tenant != manifest.metadata.tenant
                                || old.matcher == matcher)
                        {
                            return Err(super::super::error(
                                PlatformErrorCode::AlreadyExists,
                                "http-route-conflict",
                            ));
                        }
                    }
                    if index.is_none() && data.records.len() == MAX_RECORDS {
                        return Err(capacity());
                    }
                    let (publication, resolved, _) = self.http_target(&previous, &manifest)?;
                    let stored = StoredRecord {
                        manifest: definition.ok_or_else(corrupt)?,
                        generation,
                        component: resolved.release.clone(),
                    };
                    if let Some(i) = index {
                        data.records[i] = stored;
                    } else {
                        let position = previous.http.rows.partition_point(|row| {
                            (
                                row.manifest.metadata.tenant.as_ref().unwrap(),
                                &row.manifest.id,
                            ) < (manifest.metadata.tenant.as_ref().unwrap(), &manifest.id)
                        });
                        data.records.insert(position, stored);
                    }
                    let result = VersionedTrigger {
                        manifest: manifest.clone(),
                        generation,
                        component: resolved.release.clone(),
                    };
                    (
                        manifest,
                        resolved.release,
                        publication,
                        TriggerOperationAction::Apply,
                        generation,
                        Some(result),
                    )
                }
                TriggerOperationRequest::Delete { .. } => {
                    let i = index.ok_or_else(super::not_found)?;
                    let manifest = previous.http.rows[i].manifest.clone();
                    let publication = PublicationRef {
                        id: manifest.target.publication.clone().ok_or_else(corrupt)?,
                        scope: LifecycleScope::Tenant(context.tenant.clone()),
                    };
                    let removed = data.records.remove(i);
                    (
                        manifest,
                        removed.component,
                        publication,
                        TriggerOperationAction::Delete,
                        removed.generation,
                        None,
                    )
                }
            };
        let mut receipt = TriggerOperationReceipt {
            format_version: 1,
            tenant: context.tenant.0,
            actor: context.actor,
            operation_id: context.operation_id,
            action,
            trigger_id: manifest.id.0.clone(),
            request_digest: digest,
            expected_state_version: context.expected_state_version,
            expected_generation: expected,
            object_generation,
            state_version: generation,
            route_generation: previous.routes.generation.0,
            manifest_digest: codec::hash(codec::manifest(&manifest)?.as_bytes()),
            publication,
            component,
            deployment_id: manifest.target.route.ok_or_else(corrupt)?,
            deployment_generation: manifest.target.deployment_generation.ok_or_else(corrupt)?,
            revision: manifest.target.revision.ok_or_else(corrupt)?,
            completed_at_unix_millis: super::super::now()?,
            receipt_digest: codec::hash(b""),
        };
        receipt.receipt_digest = codec::receipt_hash(&receipt)?;
        receipt.canonical_bytes()?;
        data.sequence = data.sequence.checked_add(1).ok_or_else(capacity)?;
        if data.receipts.len() == RECEIPTS {
            data.receipts.remove(0);
        }
        data.receipts.push(receipt.clone());
        let next =
            HttpTable::from_reserved(data, reservation, generation, previous.routes.generation.0)?;
        let control = persistence::ControlPayloadRef {
            transaction_version: generation,
            rollouts: &previous.rollouts.data,
            deployment_operations: previous
                .operations
                .enabled
                .then_some(&previous.operations.data),
            http_routes: Some(&next.data),
        };
        let bytes = persistence::encode_combined(
            &previous.routes,
            &control,
            self.config.max_state_bytes,
            &mut Work::default(),
        )?;
        Ok(PreparedTriggerOperation {
            owner: Arc::clone(&self.rollout_work),
            previous,
            next,
            receipt,
            apply_result,
            bytes,
            replayed: false,
            reply,
            _scratch: scratch,
            _work: work,
        })
    }
}
fn validate_request(request: &TriggerOperationRequest) -> Result<(), PlatformError> {
    let c = request.context();
    for value in [&c.tenant.0, &c.actor.subject, &c.operation_id] {
        if value.capacity() > MAX_IDENTIFIER_BYTES
            || !definition::token(value, MAX_IDENTIFIER_BYTES)
        {
            return Err(invalid());
        }
    }
    c.actor.validate()?;
    match request {
        TriggerOperationRequest::Apply { manifest, .. } => {
            definition::bounded(manifest)?;
            if manifest.metadata.tenant.as_ref() != Some(&c.tenant) {
                return Err(super::super::error(
                    PlatformErrorCode::PermissionDenied,
                    "http-trigger-scope-conflict",
                ));
            }
        }
        TriggerOperationRequest::Delete { id, .. } => {
            if id.0.capacity() > MAX_IDENTIFIER_BYTES
                || !definition::token(&id.0, MAX_IDENTIFIER_BYTES)
            {
                return Err(invalid());
            }
        }
    }
    Ok(())
}
