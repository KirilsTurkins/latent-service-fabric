use std::time::{Duration, Instant};

use latent_core::test_support::TestClock;
use latent_core::{ActivationClock, EntityKey, StateNamespaceId, TenantId};

use super::*;

mod bounds;
mod fairness;
mod lifecycle;

#[derive(Clone, Debug, PartialEq, Eq)]
struct Command {
    publication: &'static str,
    attempt: u64,
}

fn limits() -> EntityLaneLimits {
    EntityLaneLimits {
        global_queued: 64,
        tenant_queued: 32,
        entity_queued: 16,
        global_keys: 32,
        tenant_keys: 16,
        global_active: 4,
        tenant_active: 2,
        global_bytes: 1_000_000,
        tenant_bytes: 500_000,
        entity_bytes: 100_000,
        scope_bytes: 256,
        command_identity_bytes: 128,
        maximum_wait_age: Duration::from_secs(10),
    }
}

fn scope(tenant: &str, entity: &str, incarnation: u64) -> EntityScope {
    EntityScope::new(
        TenantId(tenant.into()),
        StateNamespaceId("orders".into()),
        incarnation,
        EntityKey(entity.into()),
    )
    .unwrap()
}

fn request<T>(scope: EntityScope, id: u64, payload: T, now: Instant) -> EntityLaneRequest<T> {
    EntityLaneRequest::new(
        scope,
        id.to_be_bytes().to_vec(),
        payload,
        32,
        now + Duration::from_mins(1),
        EntityCallKind::Root,
    )
}

fn enqueue(
    lanes: &EntityLanes<Command>,
    tenant: &str,
    entity: &str,
    id: u64,
    now: Instant,
) -> EntityWaiter<Command> {
    lanes
        .enqueue(
            request(
                scope(tenant, entity, 1),
                id,
                Command {
                    publication: "publication-A",
                    attempt: id,
                },
                now,
            ),
            now,
        )
        .unwrap()
}

fn start<T>(lanes: &EntityLanes<T>, now: Instant) -> EntityExecution<T> {
    match lanes
        .try_start_next(now, |_, _| true)
        .unwrap()
        .expect("ready dispatch")
    {
        EntityDispatch::Ready(execution) => execution,
        EntityDispatch::Rejected(_) => panic!("unexpected queue rejection"),
    }
}

fn assert_empty<T>(lanes: &EntityLanes<T>) {
    assert_eq!(lanes.snapshot().unwrap(), EntityLaneSnapshot::default());
    assert_eq!(lanes.inner.state.lock().unwrap().ready.capacity(), 0);
}

fn clock() -> TestClock {
    TestClock::new(1_000, Instant::now(), 1)
}
