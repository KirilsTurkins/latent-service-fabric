//! Eligibility driven by the existing bounded activation admission futures.
use super::{authorization, command_role::CommandRole, StateAuthorization};
use latent_core::{EntityKey, PlatformError, PlatformErrorCode, StateNamespaceId, TenantId};
use latent_state::entity_lanes::{
    EntityCallKind, EntityDispatch, EntityLaneError, EntityLaneFence, EntityLaneLimit,
    EntityLaneLimits, EntityLaneRequest, EntityLaneSnapshot, EntityLaneWake, EntityLanes,
    EntityPhysicalOwner, EntityRejection, EntityScope,
};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{oneshot, Notify};

pub(super) struct Wake(Notify);
impl EntityLaneWake for Wake {
    fn changed(&self) {
        self.0.notify_waiters();
    }
}

struct Queued {
    authority: Arc<StateAuthorization>,
    role: Arc<CommandRole>,
    ready: oneshot::Sender<Result<EntityPhysicalOwner<Queued>, PlatformError>>,
}

/// One finite shared table. No guest cell, per-key task, or state read view.
pub(super) struct EntityAdmission {
    lanes: EntityLanes<Queued>,
    wake: Arc<Wake>,
    dispatch_rows: usize,
    maximum_wait_age: Duration,
}

/// Physical clones are moved into the actual view/operation/commit keepers.
#[derive(Clone)]
pub(super) struct EntityOwner {
    physical: EntityPhysicalOwner<Queued>,
    fence: EntityCommitFence,
}

/// Observation only: response authority can retain this without retaining a lane.
#[derive(Clone)]
pub(super) struct EntityCommitFence {
    lanes: EntityLanes<Queued>,
    fence: EntityLaneFence,
}

impl EntityCommitFence {
    pub fn with_current<R>(&self, action: impl FnOnce() -> R) -> Result<R, PlatformError> {
        self.lanes
            .with_fence(&self.fence, action)
            .map_err(lane_error)
    }
}

impl EntityOwner {
    pub fn fence(&self) -> EntityCommitFence {
        self.fence.clone()
    }

    pub fn begin_cleanup(&self) -> Result<(), PlatformError> {
        self.physical.begin_cleanup().map_err(lane_error)
    }
}

/// Conservative additional limits. Native ingress still prepays every accepted
/// request and remains the original global capacity owner. Installed runtimes
/// can select tighter finite values with `new_with_entity_limits`.
pub fn default_entity_limits() -> EntityLaneLimits {
    EntityLaneLimits {
        global_queued: 64,
        tenant_queued: 32,
        entity_queued: 8,
        global_keys: 64,
        tenant_keys: 32,
        global_active: 32,
        tenant_active: 16,
        global_bytes: 128 * 1024 * 1024,
        tenant_bytes: 64 * 1024 * 1024,
        entity_bytes: 32 * 1024 * 1024,
        scope_bytes: 1024,
        command_identity_bytes: 128,
        maximum_wait_age: Duration::from_secs(30),
    }
}

impl EntityAdmission {
    pub fn new(limits: EntityLaneLimits) -> Result<Self, PlatformError> {
        if limits.global_queued > 4096
            || limits.global_keys > 4096
            || limits.global_active > 4096
            || limits.tenant_queued > limits.global_queued
            || limits.entity_queued > limits.tenant_queued
            || limits.tenant_keys > limits.global_keys
            || limits.tenant_active > limits.global_active
            || limits.tenant_bytes > limits.global_bytes
            || limits.entity_bytes > limits.tenant_bytes
            || limits.global_bytes > 1024 * 1024 * 1024
            || limits.scope_bytes > 1024
            || limits.command_identity_bytes > 128
            || limits.maximum_wait_age > Duration::from_secs(30)
        {
            return Err(lane_error(EntityLaneError::InvalidLimits));
        }
        let dispatch_rows = limits.global_queued;
        let maximum_wait_age = limits.maximum_wait_age;
        let wake = Arc::new(Wake(Notify::new()));
        let lanes = EntityLanes::new_with_wake(limits, Some(wake.clone())).map_err(lane_error)?;
        Ok(Self {
            lanes,
            wake,
            dispatch_rows,
            maximum_wait_age,
        })
    }

    pub fn snapshot(&self) -> Result<EntityLaneSnapshot, PlatformError> {
        self.lanes.snapshot().map_err(lane_error)
    }

    pub async fn acquire(
        &self,
        record: &latent_commit::atomic::CommandRecord,
        authority: Arc<StateAuthorization>,
        role: Arc<CommandRole>,
        retained_bytes: u64,
        call_kind: EntityCallKind,
    ) -> Result<Option<EntityOwner>, PlatformError> {
        let key = record.key();
        let Some(entity) = &key.entity else {
            return Ok(None);
        };
        let scope = EntityScope::new(
            TenantId(key.tenant.clone()),
            StateNamespaceId(key.namespace.clone()),
            key.incarnation
                .parse()
                .map_err(|_| authorization::denied())?,
            EntityKey(entity.clone()),
        )
        .map_err(lane_error)?;
        let original = authority.authority.ownership();
        if scope.tenant() != &original.tenant
            || scope.namespace().0 != original.namespace
            || scope.incarnation() != original.incarnation
            || Some(scope.entity().0.as_str()) != original.entity.as_deref()
            || key.recovery_scope != original.caller.scope
            || record.source().publication != authority.publication()
            || record.owner_epoch() != role.epoch()
        {
            return Err(authorization::denied());
        }
        // The canonical command digest includes its scoped caller/operation key;
        // append the actual attempt and original role epoch, never caller lineage.
        let mut identity = record.id().hex().into_bytes();
        identity.extend_from_slice(&record.attempt().to_be_bytes());
        identity.extend_from_slice(&record.owner_epoch().to_be_bytes());
        let now = Instant::now();
        let deadline = authority
            .budget
            .deadline()
            .monotonic()
            .ok_or_else(authorization::denied)?
            .min(authority.authority.deadline())
            .min(
                now.checked_add(self.maximum_wait_age)
                    .ok_or_else(authorization::denied)?,
            );
        let (ready, mut receive) = oneshot::channel();
        let waiter = self
            .lanes
            .enqueue(
                EntityLaneRequest::new(
                    scope,
                    identity,
                    Queued {
                        authority,
                        role,
                        ready,
                    },
                    retained_bytes,
                    deadline,
                    call_kind,
                ),
                now,
            )
            .map_err(|refused| lane_error(refused.reason))?;
        // This deadline future belongs to the already accepted activation,
        // under its original ingress slot. No timer or task belongs to a key.
        let expired = tokio::time::sleep_until(deadline.into());
        tokio::pin!(expired);
        loop {
            // Register before dispatch. Retirement between registration and
            // dispatch cannot lose the single shared wake notification.
            let changed = self.wake.0.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            self.dispatch()?;
            tokio::select! {
                result = &mut receive => {
                    let physical = result.map_err(|_| authorization::denied())??;
                    let fence = EntityCommitFence { lanes: self.lanes.clone(), fence: physical.fence() };
                    drop(waiter);
                    return Ok(Some(EntityOwner { physical, fence }));
                }
                () = changed => {}
                () = &mut expired => return Err(lane_error(EntityLaneError::Expired)),
            }
        }
    }

    fn dispatch(&self) -> Result<(), PlatformError> {
        for _ in 0..self.dispatch_rows {
            let Some(dispatch) =
                self.lanes
                    .try_start_next(Instant::now(), |scope, queued| {
                        let original = queued.authority.authority.ownership();
                        scope.tenant() == &original.tenant
                            && scope.namespace().0 == original.namespace
                            && scope.incarnation() == original.incarnation
                            && Some(scope.entity().0.as_str()) == original.entity.as_deref()
                            && queued
                                .role
                                .with_current(|_| {
                                    queued.authority.authorize("info", 0, 0, || Ok(())).map_err(
                                        |_| latent_commit::atomic::AtomicError::PermissionDenied,
                                    )
                                })
                                .is_ok()
                    })
                    .map_err(lane_error)?
            else {
                break;
            };
            match dispatch {
                EntityDispatch::Ready(execution) => {
                    let (request, physical) = execution.into_owned_work();
                    let queued = request.into_payload();
                    // A detached original waiter accepts no view or guest; the
                    // returned physical owner drops only after send refuses it.
                    let _ = queued.ready.send(Ok(physical));
                }
                EntityDispatch::Rejected(rejected) => {
                    let failure = if rejected.reason == EntityRejection::WaitExpired {
                        lane_error(EntityLaneError::Expired)
                    } else {
                        authorization::denied()
                    };
                    let _ = rejected.request.into_payload().ready.send(Err(failure));
                }
            }
        }
        Ok(())
    }
}

fn lane_error(reason: EntityLaneError) -> PlatformError {
    let details = if let EntityLaneError::Backpressure(limit) = reason {
        let name = match limit {
            EntityLaneLimit::GlobalQueue => "global-queue",
            EntityLaneLimit::TenantQueue => "tenant-queue",
            EntityLaneLimit::EntityQueue => "entity-queue",
            EntityLaneLimit::GlobalKeys => "global-keys",
            EntityLaneLimit::TenantKeys => "tenant-keys",
            EntityLaneLimit::GlobalBytes => "global-bytes",
            EntityLaneLimit::TenantBytes => "tenant-bytes",
            EntityLaneLimit::EntityBytes => "entity-bytes",
            EntityLaneLimit::ScopeBytes => "scope-bytes",
            EntityLaneLimit::CommandIdentityBytes => "command-identity-bytes",
        };
        vec![latent_core::ErrorDetail {
            kind: "entity-lane.limit".into(),
            fields: latent_core::Metadata::from([("reason".into(), name.into())]),
        }]
    } else {
        Vec::new()
    };
    PlatformError {
        code: match reason {
            EntityLaneError::InvalidLimits
            | EntityLaneError::InvalidScope
            | EntityLaneError::InvalidCommandIdentity => PlatformErrorCode::InvalidArgument,
            EntityLaneError::Expired => PlatformErrorCode::DeadlineExceeded,
            EntityLaneError::Backpressure(_) => PlatformErrorCode::ResourceExhausted,
            EntityLaneError::NestedTransactionalCall | EntityLaneError::StaleFence => {
                PlatformErrorCode::PermissionDenied
            }
            _ => PlatformErrorCode::Unavailable,
        },
        message: "transaction-entity-eligibility-unavailable".into(),
        retryable: false,
        details,
    }
}
