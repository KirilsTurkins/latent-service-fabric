use super::super::DirectoryDeploymentRepository;
use crate::http_routes::{
    capacity, conflict, definition::token, invalid, TriggerOperationLookup, TriggerPage,
    TriggerPageRequest, TriggerRead, TriggerReadLease, TriggerSnapshot, MAX_DEFINITION_BYTES,
    MAX_IDENTIFIER_BYTES, MAX_PAGE_BYTES, MAX_PAGE_SIZE, MAX_RECEIPT_BYTES,
};
use latent_core::{PlatformError, TenantId, TriggerId};
use std::hash::BuildHasher;

impl DirectoryDeploymentRepository {
    pub fn reserve_trigger_request(&self) -> Result<TriggerReadLease, PlatformError> {
        self.http_budget.read(MAX_DEFINITION_BYTES)
    }
    pub fn get_trigger(
        &self,
        tenant: &TenantId,
        id: &TriggerId,
    ) -> Result<TriggerRead<TriggerSnapshot>, PlatformError> {
        validate_ids(&tenant.0, &id.0)?;
        let current = self.read_publication();
        let lease = self
            .http_budget
            .read_with_scratch(MAX_DEFINITION_BYTES + 4096, 16 * 1024)?;
        Ok(TriggerRead::new(
            TriggerSnapshot {
                trigger: current
                    .http
                    .index(&tenant.0, &id.0)
                    .map(|i| current.http.versioned(i)),
                state_version: current.transaction,
                route_generation: current.routes.generation,
                confirmed: current.confirmed,
            },
            lease,
        ))
    }
    pub fn get_trigger_operation(
        &self,
        tenant: &TenantId,
        operation: &str,
    ) -> Result<TriggerRead<TriggerOperationLookup>, PlatformError> {
        validate_ids(&tenant.0, operation)?;
        let current = self.read_publication();
        let lease = self
            .http_budget
            .read_with_scratch(MAX_RECEIPT_BYTES, 16 * 1024)?;
        let result = if !current.confirmed {
            TriggerOperationLookup::Uncertain
        } else if let Some(found) = current.http.find(&tenant.0, operation) {
            TriggerOperationLookup::Found(found.clone())
        } else {
            TriggerOperationLookup::Unknown {
                retained_floor: current.http.floor(),
                high_watermark: current.http.data.sequence,
            }
        };
        Ok(TriggerRead::new(result, lease))
    }
    pub fn list_triggers(
        &self,
        request: &TriggerPageRequest,
    ) -> Result<TriggerRead<TriggerPage>, PlatformError> {
        if !token(&request.tenant.0, MAX_IDENTIFIER_BYTES)
            || request.tenant.0.capacity() > MAX_IDENTIFIER_BYTES
            || request.target_service.as_ref().is_some_and(|s| {
                s.0.capacity() > MAX_IDENTIFIER_BYTES || !token(&s.0, MAX_IDENTIFIER_BYTES)
            })
            || request.page_size == 0
            || request.page_size > MAX_PAGE_SIZE
            || request
                .page_token
                .as_ref()
                .is_some_and(|s| s.capacity() > 128)
        {
            return Err(invalid());
        }
        let current = self.read_publication();
        if !current.confirmed {
            return Err(super::unavailable());
        }
        let cursor = |index: usize| {
            let signature = self.pagination_fingerprint.hash_one((
                "http-trigger-page-v1",
                self.rollout_cursor_epoch,
                current.transaction,
                &request.tenant,
                &request.target_service,
                request.page_size,
                index,
            ));
            format!("1:{}:{index}:{signature:016x}", current.transaction)
        };
        let start = if let Some(token) = &request.page_token {
            let index: usize = token
                .split(':')
                .nth(2)
                .ok_or_else(invalid)?
                .parse()
                .map_err(|_| invalid())?;
            if index > current.http.rows.len() || *token != cursor(index) {
                return Err(conflict());
            }
            index
        } else {
            0
        };
        let lease = self
            .http_budget
            .read_with_scratch(MAX_PAGE_BYTES, 16 * 1024)?;
        let mut triggers = Vec::with_capacity(request.page_size as usize);
        let mut bytes = 1024usize;
        let mut next = None;
        for (i, row) in current.http.rows.iter().enumerate().skip(start) {
            if row.manifest.metadata.tenant.as_ref() != Some(&request.tenant)
                || request
                    .target_service
                    .as_ref()
                    .is_some_and(|s| s != &row.manifest.target.service)
            {
                continue;
            }
            let cost = 4 * current.http.data.records[i].manifest.len() + 4096;
            if triggers.len() == request.page_size as usize || cost > MAX_PAGE_BYTES - bytes {
                if triggers.is_empty() {
                    return Err(capacity());
                }
                next = Some(cursor(i));
                break;
            }
            bytes += cost;
            triggers.push(current.http.versioned(i));
        }
        Ok(TriggerRead::new(
            TriggerPage {
                triggers,
                next_page_token: next,
                state_version: current.transaction,
                route_generation: current.routes.generation,
            },
            lease,
        ))
    }
}
fn validate_ids(tenant: &str, id: &str) -> Result<(), PlatformError> {
    if !token(tenant, MAX_IDENTIFIER_BYTES) || !token(id, MAX_IDENTIFIER_BYTES) {
        return Err(invalid());
    }
    Ok(())
}
