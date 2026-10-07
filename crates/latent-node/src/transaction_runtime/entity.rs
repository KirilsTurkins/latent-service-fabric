//! Eligibility driven by the existing bounded activation admission futures.
use super::{authorization, CommandTimeSource, StateAuthorization};
use latent_core::{EntityKey, PlatformError, PlatformErrorCode, StateNamespaceId, TenantId};
use latent_state::entity_lanes::{
    EntityCallKind, EntityDispatch, EntityLaneError, EntityLaneFence, EntityLaneLimit,
    EntityLaneLimits, EntityLaneRequest, EntityLaneSnapshot, EntityLaneWake, EntityLanes,
    EntityPhysicalOwner, EntityRejection, EntityScope,
};
use std::sync::{Arc, Mutex, Weak};
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
    time: Arc<dyn CommandTimeSource>,
    ready: oneshot::Sender<Result<EntityPhysicalOwner<Queued>, PlatformError>>,
}

/// One finite shared table. No guest cell, per-key task, or state read view.
pub struct EntityCommandLanes {
    store: Weak<latent_state::protected_store::ProtectedStoreOwner>,
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
/// can select tighter finite values with `EntityCommandLanes::new`.
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

impl EntityCommandLanes {
    pub fn validate_limits(limits: &EntityLaneLimits) -> Result<(), PlatformError> {
        if [
            limits.global_queued,
            limits.tenant_queued,
            limits.entity_queued,
            limits.global_keys,
            limits.tenant_keys,
            limits.global_active,
            limits.tenant_active,
            limits.scope_bytes,
            limits.command_identity_bytes,
        ]
        .contains(&0)
            || [
                limits.global_bytes,
                limits.tenant_bytes,
                limits.entity_bytes,
            ]
            .contains(&0)
            || limits.maximum_wait_age.is_zero()
        {
            return Err(lane_error(EntityLaneError::InvalidLimits));
        }
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
        Ok(())
    }

    pub fn new(
        store: &Arc<latent_state::protected_store::ProtectedStoreOwner>,
        limits: EntityLaneLimits,
    ) -> Result<Self, PlatformError> {
        Self::validate_limits(&limits)?;
        let dispatch_rows = limits.global_queued;
        let maximum_wait_age = limits.maximum_wait_age;
        let wake = Arc::new(Wake(Notify::new()));
        let lanes = EntityLanes::new_with_wake(limits, Some(wake.clone())).map_err(lane_error)?;
        Ok(Self {
            store: Arc::downgrade(store),
            lanes,
            wake,
            dispatch_rows,
            maximum_wait_age,
        })
    }

    pub(super) fn require_store(
        &self,
        store: &latent_state::protected_store::ProtectedStoreOwner,
    ) -> Result<(), PlatformError> {
        self.store
            .upgrade()
            .filter(|original| original.is_same_owner(store))
            .map(|_| ())
            .ok_or_else(authorization::denied)
    }

    pub fn snapshot(&self) -> Result<EntityLaneSnapshot, PlatformError> {
        self.lanes.snapshot().map_err(lane_error)
    }

    pub(super) async fn acquire(
        &self,
        record: &latent_commit::atomic::CommandRecord,
        authority: Arc<StateAuthorization>,
        time: Arc<dyn CommandTimeSource>,
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
                        time,
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
            let Some(dispatch) = self
                .lanes
                .try_start_next(Instant::now(), |scope, queued| {
                    let original = queued.authority.authority.ownership();
                    scope.tenant() == &original.tenant
                        && scope.namespace().0 == original.namespace
                        && scope.incarnation() == original.incarnation
                        && Some(scope.entity().0.as_str()) == original.entity.as_deref()
                        && queued
                            .time
                            .with_acceptance(&mut |_| {
                                queued
                                    .authority
                                    .authorize("acquire-command", 0, 0, || Ok(()))
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

/// The same original protected operation retains this keeper before Pending.
/// Only an actual opaque owner from the claimed lane can fill it, once, before
/// any guest view opens. Unexpected operation loss keeps that owner quarantined.
#[derive(Default)]
pub(super) struct EntityOperationPin(Mutex<(bool, Option<EntityOwner>)>);
impl EntityOperationPin {
    pub fn attach(&self, owner: Option<EntityOwner>) -> Result<(), PlatformError> {
        let mut slot = self.0.lock().map_err(|_| authorization::denied())?;
        if slot.0 {
            return Err(authorization::denied());
        }
        slot.0 = true;
        slot.1 = owner;
        Ok(())
    }
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests {
    use super::*;
    struct UnavailableClock;
    impl CommandTimeSource for UnavailableClock {
        fn sample(&self) -> latent_commit::atomic::CommandTime {
            latent_commit::atomic::CommandTime {
                unix_millis: 0,
                continuity_proven: false,
            }
        }
    }

    #[test]
    fn original_operation_keeper_can_be_filled_only_once_including_no_entity_selection() {
        let pin = EntityOperationPin::default();
        pin.attach(None).unwrap();
        assert!(matches!(
            pin.attach(None),
            Err(PlatformError {
                code: PlatformErrorCode::PermissionDenied,
                ..
            })
        ));
    }

    #[tokio::test]
    async fn shared_table_is_bound_to_actual_protected_store_and_cannot_substitute_equal_limits() {
        use latent_state::protected_store::{ProtectedStoreConfig, ProtectedStoreOwner};
        use std::os::unix::fs::PermissionsExt;
        let mut owners = Vec::new();
        let mut roots = Vec::new();
        for _ in 0..2 {
            let base = std::env::var_os("LATENT_STATE_TEST_ROOT")
                .map(std::path::PathBuf::from)
                .unwrap_or_else(std::env::temp_dir);
            let root = tempfile::tempdir_in(base).unwrap();
            std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
            let mut config = ProtectedStoreConfig::bounded_linux(root.path().to_owned());
            config.create_if_missing = true;
            let owner = Arc::new(ProtectedStoreOwner::start(config).unwrap().await.unwrap());
            let capacity =
                latent_core::native_capacity::NativeCapacityOwner::new(Default::default()).unwrap();
            owner.bind_native_capacity(&capacity).unwrap();
            owners.push((owner, capacity));
            roots.push(root);
        }
        let table =
            Arc::new(EntityCommandLanes::new(&owners[0].0, default_entity_limits()).unwrap());
        assert!(table.require_store(&owners[0].0).is_ok());
        assert!(matches!(
            table.require_store(&owners[1].0),
            Err(PlatformError {
                code: PlatformErrorCode::PermissionDenied,
                ..
            })
        ));
        assert_eq!(table.snapshot().unwrap(), EntityLaneSnapshot::default());
        let waiters =
            crate::command_waiters::CommandWaiterRegistry::new(Default::default()).unwrap();
        let first = super::super::command_completion::CommandCoordinator::new_with_entity_lanes(
            Arc::clone(&owners[0].0),
            waiters.clone(),
            None,
            Arc::new(UnavailableClock),
            Arc::clone(&table),
        )
        .unwrap();
        let second = super::super::command_completion::CommandCoordinator::new_with_entity_lanes(
            Arc::clone(&owners[0].0),
            waiters.clone(),
            None,
            Arc::new(UnavailableClock),
            Arc::clone(&table),
        )
        .unwrap();
        assert!(first.uses_entity_lanes(&table));
        assert!(second.uses_entity_lanes(&table));
        assert!(
            super::super::command_completion::CommandCoordinator::new_with_entity_lanes(
                Arc::clone(&owners[1].0),
                waiters,
                None,
                Arc::new(UnavailableClock),
                Arc::clone(&table),
            )
            .is_err()
        );
        drop((first, second));
        for (owner, _) in &owners {
            owner.close();
            let deadline = Instant::now() + Duration::from_secs(5);
            let report = owner
                .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
                .unwrap()
                .await;
            assert!(report.clean && report.snapshot.physically_retired());
            owner.reap_retired_threads().unwrap();
        }
        drop(owners);
        drop(roots);
    }
}
