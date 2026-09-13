use super::super::{DirectoryDeploymentRepository, PublicationView};
use super::{prepare, table::StoredRollout};
use crate::rollouts::{
    capacity, codec, error, invalid, validation::token, Result, RolloutId, RolloutOperationLookup,
    RolloutPage, RolloutPageRequest, RolloutReason, RolloutState, RolloutStatus, MAX_PAGE_BYTES,
};
use latent_core::{PlatformErrorCode, TenantId};
use latent_manifest::__serde_json as json;
use std::hash::BuildHasher;
impl DirectoryDeploymentRepository {
    pub fn get_rollout(&self, tenant: &TenantId, id: &RolloutId) -> Result<Option<RolloutStatus>> {
        token(&tenant.0, 256)?;
        token(&id.0, 128)?;
        let current = self.read_publication();
        current
            .rollouts
            .row(tenant, id)
            .map(|row| status(&current, row))
            .transpose()
    }
    pub fn get_rollout_operation(
        &self,
        tenant: &TenantId,
        id: &RolloutId,
        operation: &str,
    ) -> Result<RolloutOperationLookup> {
        token(&tenant.0, 256)?;
        token(&id.0, 128)?;
        token(operation, 128)?;
        let current = self.read_publication();
        let Some(receipt) = current.rollouts.receipt(tenant, id, operation) else {
            return Ok(RolloutOperationLookup::Unknown);
        };
        if !current.confirmed {
            return Ok(RolloutOperationLookup::Uncertain);
        }
        Ok(RolloutOperationLookup::Found(receipt.clone()))
    }
    pub fn list_rollouts(&self, request: RolloutPageRequest) -> Result<RolloutPage> {
        token(&request.tenant.0, 256)?;
        if let Some(service) = &request.service {
            token(&service.0, 256)?;
        }
        if request.limit == 0
            || request.limit > 128
            || request.maximum_bytes < 4096
            || request.maximum_bytes > MAX_PAGE_BYTES
            || request.cursor.as_ref().is_some_and(|c| c.capacity() > 512)
        {
            return Err(invalid());
        }
        let current = self.read_publication();
        let filter = codec::hash(&codec::encode(
            &json::json!({"tenant":request.tenant.0,"service":request.service.as_ref().map(|s|&s.0),"state":request.state}),
            4096,
        )?);
        // A nonreused process epoch plus this owner's fresh hash seed binds a
        // cursor across in-process reopen and process restart. It grants no scope.
        let owner = format!(
            "{:x}-{:x}",
            self.rollout_cursor_epoch,
            self.pagination_fingerprint
                .hash_one(self.rollout_cursor_epoch)
        );
        let mut after = 0usize;
        if let Some(cursor) = request.cursor {
            let parts = cursor.split(':').collect::<Vec<_>>();
            if parts.len() != 5
                || parts[0] != "1"
                || parts[1] != owner
                || parts[2] != current.transaction.to_string()
                || parts[3]
                    != filter
                        .as_str()
                        .strip_prefix("sha256:")
                        .ok_or_else(invalid)?
            {
                return Err(error(
                    PlatformErrorCode::StateConflict,
                    "rollout-page-stale",
                ));
            }
            after = parts[4].parse().map_err(|_| invalid())?;
            if after > current.rollouts.data.rows.len() {
                return Err(invalid());
            }
        }
        let mut result = Vec::new();
        let mut bytes = 1024usize;
        let mut position = after;
        for (index, row) in current.rollouts.data.rows.iter().enumerate().skip(after) {
            if row.status.tenant != request.tenant
                || request
                    .service
                    .as_ref()
                    .is_some_and(|s| s != &row.status.service)
            {
                position = index + 1;
                continue;
            }
            let value = status(&current, row)?;
            if request.state.is_some_and(|state| state != value.state) {
                position = index + 1;
                continue;
            }
            let cost = codec::encode(&value, MAX_PAGE_BYTES)?
                .len()
                .saturating_mul(2)
                .saturating_add(512);
            if result.len() == request.limit || cost > request.maximum_bytes - bytes {
                if result.is_empty() {
                    return Err(capacity());
                }
                break;
            }
            result.push(value);
            bytes += cost;
            position = index + 1;
        }
        let next_cursor = (position < current.rollouts.data.rows.len()).then(|| {
            format!(
                "1:{owner}:{}:{}:{position}",
                current.transaction,
                filter
                    .as_str()
                    .strip_prefix("sha256:")
                    .expect("canonical hash")
            )
        });
        Ok(RolloutPage {
            rollouts: result,
            next_cursor,
            state_version: current.transaction,
        })
    }
}
fn status(current: &PublicationView, row: &StoredRollout) -> Result<RolloutStatus> {
    let mut value = row.status.clone();
    value.retained_operation_floor = current.rollouts.floor();
    value.objects = prepare::managed_objects(&current.routes, row);
    if prepare::active(value.state)
        && !prepare::cohort_matches(&current.routes, row).unwrap_or(false)
    {
        value.state = RolloutState::Conflicted;
        value.reason = RolloutReason::CohortChanged;
    }
    if !current.confirmed {
        value.reason = RolloutReason::OutcomeUncertain;
    }
    codec::encode(&value, MAX_PAGE_BYTES)?;
    Ok(value)
}
