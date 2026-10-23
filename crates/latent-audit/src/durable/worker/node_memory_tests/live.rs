use super::*;
use crate::durable::tests::{attempt, conclusion, Directory};
use std::{
    sync::{mpsc, Barrier},
    time::Duration,
};

struct Funded {
    handle: AuditHandle,
    worker: AuditWorker,
}
impl Funded {
    fn new(path: &std::path::Path, owner: &NodeMetadataOwner) -> Self {
        let (handle, worker) = DirectoryPhase2AuditJournal::open_with_node_metadata(
            path,
            AuditLimits {
                maximum_records: 32,
                ..Default::default()
            },
            owner.clone(),
        )
        .unwrap();
        Self { handle, worker }
    }
    fn idle(&self) {
        assert!(self
            .handle
            .wait_until_idle_for_test(Instant::now() + Duration::from_secs(5))
            .unwrap());
    }
}
impl Drop for Funded {
    fn drop(&mut self) {
        self.handle.close();
        let joined = self
            .worker
            .join_until(Instant::now() + Duration::from_secs(5));
        if !std::thread::panicking() {
            assert!(
                matches!(joined, Ok(true)),
                "actual audit worker did not join"
            );
        }
    }
}
fn completed(node: &Funded) -> OwnedDurableAuditAck {
    let mut active = node
        .handle
        .reserve_control_critical(&attempt())
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    active.mutation_started().unwrap();
    let ack = active.finish(conclusion()).blocking_wait().unwrap();
    node.idle();
    ack
}

#[test]
fn funded_pending_and_returned_ack_retain_original_transient_memory_until_real_drop() {
    let directory = Directory::new();
    let owner = NodeMetadataOwner::new(8 * 1024 * 1024).unwrap();
    let base = owner.occupied_bytes();
    let node = Funded::new(&directory.0.join("audit"), &owner);
    node.idle();
    let fixed = node.handle.snapshot().node_metadata_fixed_reserved_bytes;
    assert_eq!(owner.snapshot().transient_reserved_bytes, 0);
    let reserved = node.handle.reserve_control_critical(&attempt()).unwrap();
    assert!(
        node.handle
            .snapshot()
            .node_metadata_transient_reserved_bytes
            > 0
    );
    let mut active = reserved.begin().blocking_wait().unwrap();
    assert_eq!(node.handle.snapshot().retained_records, 1);
    assert_eq!(node.handle.snapshot().reserved_records, 1);
    active.mutation_started().unwrap();
    let ack = active.finish(conclusion()).blocking_wait().unwrap();
    node.idle();
    assert_eq!(ack.sequence, 2);
    let terminal = node.handle.snapshot();
    assert_eq!(terminal.pending_attempts, 0);
    assert_eq!(terminal.reserved_records, 0);
    assert_eq!(terminal.queued_bytes, 0);
    assert!(
        terminal.node_metadata_transient_reserved_bytes > 0,
        "returned ack still owns actual Strings/custody"
    );
    assert_eq!(terminal.node_metadata_fixed_reserved_bytes, fixed);
    drop(ack);
    assert_eq!(owner.snapshot().transient_reserved_bytes, 0);
    assert_eq!(owner.occupied_bytes(), fixed);
    drop(node);
    assert_eq!(
        owner.occupied_bytes(),
        base,
        "real Store/shared/PageBudget/header teardown precedes refund"
    );
}

#[test]
fn funded_read_only_page_clones_share_backing_and_keep_node_capacity_after_close() {
    let directory = Directory::new();
    let owner = NodeMetadataOwner::new(8 * 1024 * 1024).unwrap();
    let base = owner.occupied_bytes();
    let node = Funded::new(&directory.0.join("audit"), &owner);
    drop(completed(&node));
    let query = || crate::durable::AuditQueryRequest {
        scope: attempt().scope,
        filter: Default::default(),
        cursor: None,
        limit: 2,
        maximum_bytes: 32768,
    };
    // Setup contention is the declared hot-path refusal, not capacity failure.
    // Retry only that exact before-enqueue branch with all accounting unchanged.
    let before = node.handle.snapshot();
    let mut admitted = None;
    for _ in 0..16 {
        match node
            .handle
            .query(query(), Instant::now() + Duration::from_secs(5))
        {
            Ok(ticket) => {
                admitted = Some(ticket);
                break;
            }
            Err(error) if error.message == "audit-busy" => {
                assert_eq!(node.handle.snapshot(), before);
                std::thread::sleep(Duration::from_millis(10));
            }
            Err(error) => panic!("actual query admission failed: {error:?}"),
        }
    }
    let page = admitted
        .expect("bounded setup contention did not clear")
        .blocking_wait()
        .unwrap();
    node.idle();
    assert_eq!(page.records().len(), 2);
    let occupied = owner.occupied_bytes();
    let second = page.clone();
    let lease = page.response_lease();
    assert!(std::ptr::eq(
        page.records().as_ptr(),
        second.records().as_ptr()
    ));
    assert_eq!(
        owner.occupied_bytes(),
        occupied,
        "shared view copies no graph or headers"
    );
    drop(node);
    assert!(owner.snapshot().transient_reserved_bytes > 0);
    drop(page);
    assert_eq!(second.records().len(), 2);
    drop(second);
    assert!(lease.reserved_bytes() > 0);
    assert!(owner.snapshot().transient_reserved_bytes > 0);
    std::thread::spawn(move || drop(lease)).join().unwrap();
    assert_eq!(owner.occupied_bytes(), base);
}

#[test]
fn funded_unjoined_worker_retains_exact_original_quarantine_after_body_completion() {
    let directory = Directory::new();
    let owner = NodeMetadataOwner::new(8 * 1024 * 1024).unwrap();
    let (handle, mut worker) = DirectoryPhase2AuditJournal::open_with_node_metadata(
        directory.0.join("audit"),
        AuditLimits {
            maximum_records: 2,
            ..Default::default()
        },
        owner.clone(),
    )
    .unwrap();
    // Retire the real journal/File owner first. Exercise the same actual worker
    // Drop mechanism with a real bounded thread held outside its result body.
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
    let entered = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let (done, received) = mpsc::sync_channel(1);
    let started = entered.clone();
    let held = release.clone();
    worker.thread = Some(std::thread::spawn(move || {
        started.wait();
        held.wait();
        done.send(()).unwrap();
    }));
    entered.wait();
    let quarantined = worker.thread_memory.as_ref().unwrap().reserved_bytes();
    assert!(quarantined > 0);
    drop(worker);
    let snapshot = handle.snapshot();
    assert_eq!(
        snapshot.node_metadata_quarantined_reserved_bytes,
        quarantined
    );
    assert!(snapshot.node_metadata_fixed_reserved_bytes >= quarantined);
    assert_eq!(snapshot.node_metadata_transient_reserved_bytes, 0);
    release.wait();
    received.recv_timeout(Duration::from_secs(5)).unwrap();
    // A body signal is not join/physical retirement. No refund is fabricated.
    assert_eq!(
        handle.snapshot().node_metadata_quarantined_reserved_bytes,
        quarantined
    );
    drop(handle);
    assert!(owner.occupied_bytes() >= quarantined + NodeMetadataOwner::bootstrap_bytes().unwrap());
}

fn activation() -> latent_core::ActivationBudget {
    use latent_core::{
        ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget,
    };
    let limits = ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 2 * 1024 * 1024,
        wall_time_limit_millis: Some(5000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &limits,
        &limits,
        &limits,
        None,
        ClockSample::new(1000, Instant::now()),
    )
    .unwrap();
    ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
}
#[test]
fn activation_audit_custody_never_moves_to_equal_foreign_budget_or_persistent_node_history() {
    let directory = Directory::new();
    let owner = NodeMetadataOwner::new(8 * 1024 * 1024).unwrap();
    let base = owner.occupied_bytes();
    let node = Funded::new(&directory.0.join("audit"), &owner);
    let original = activation();
    let foreign = activation();
    let memory = node.handle.prepare_call_memory(&original).unwrap();
    let reserved = original.host_memory_bytes();
    assert!(reserved > 0);
    assert_eq!(foreign.host_memory_bytes(), 0);
    node.idle();
    let before = node.handle.snapshot();
    let record = attempt();
    let mut admitted = None;
    for _ in 0..16 {
        match node
            .handle
            .try_reserve_critical_with_memory(&record, &memory)
        {
            Ok(pending) => {
                admitted = Some(pending);
                break;
            }
            Err(error) if error.message == "audit-busy" => {
                assert_eq!(node.handle.snapshot(), before);
                assert_eq!(original.host_memory_bytes(), reserved);
                assert_eq!(foreign.host_memory_bytes(), 0);
                std::thread::sleep(Duration::from_millis(10));
            }
            Err(error) => panic!("actual original-budget audit admission failed: {error:?}"),
        }
    }
    let pending = admitted.expect("bounded pre-admission setup contention did not clear");
    drop(memory);
    let mut active = pending.begin().blocking_wait().unwrap();
    active.mutation_started().unwrap();
    let ack = active.finish(conclusion()).blocking_wait().unwrap();
    node.idle();
    assert_eq!(original.host_memory_bytes(), reserved);
    assert_eq!(foreign.host_memory_bytes(), 0);
    assert_eq!(
        node.handle
            .snapshot()
            .node_metadata_transient_reserved_bytes,
        0,
        "activation-owned copies do not become node transient reservations"
    );
    assert_eq!(node.handle.snapshot().retained_records, 2);
    drop(node);
    assert_eq!(
        owner.occupied_bytes(),
        base,
        "persisted disk history retains no activation lease after node owner retirement"
    );
    assert_eq!(
        original.host_memory_bytes(),
        reserved,
        "returned ack remains an actual original physical owner"
    );
    drop(ack);
    assert_eq!(original.host_memory_bytes(), 0);
    assert_eq!(original.outstanding_reservations(), 0);
    assert_eq!(foreign.host_memory_bytes(), 0);
    assert_eq!(foreign.outstanding_reservations(), 0);
}

#[test]
fn funded_observation_capacity_refusal_preserves_original_state_and_lossy_drop_counter() {
    let directory = Directory::new();
    let owner = NodeMetadataOwner::new(8 * 1024 * 1024).unwrap();
    let base = owner.occupied_bytes();
    let node = Funded::new(&directory.0.join("audit"), &owner);
    node.idle();
    let record = attempt();
    let event = crate::durable::AuditObservation {
        scope: record.scope,
        actor: record.actor,
        kind: crate::Phase2AuditEventKind::CacheMiss,
        outcome: crate::AuditOutcome::Succeeded,
        identities: Default::default(),
        reason: crate::durable::AuditReason::CacheMiss,
        cache_kind: Some(crate::durable::AuditCacheKind::Raw),
        occurred_at_unix_millis: 1,
    };
    codec::observation(&event).unwrap();
    let occupied = owner
        .reserve(owner.maximum_bytes() - owner.occupied_bytes())
        .unwrap();
    let mut expected = node.handle.snapshot();
    assert_eq!(
        node.handle.try_capture(&event).err().unwrap().code,
        latent_core::PlatformErrorCode::ResourceExhausted
    );
    expected.dropped_observations += 1;
    assert_eq!(node.handle.snapshot(), expected);
    assert_eq!(expected.retained_records, 0);
    assert_eq!(expected.reserved_records, 0);
    assert_eq!(expected.queued_operations, 0);
    assert_eq!(expected.queued_bytes, 0);
    assert_eq!(expected.next_sequence, 1);
    assert_eq!(owner.occupied_bytes(), owner.maximum_bytes());
    drop(occupied);
    node.idle();
    drop(node);
    assert_eq!(owner.occupied_bytes(), base);
}

#[test]
fn funded_pending_read_only_views_share_actual_graph_through_teardown_and_last_clone() {
    let directory = Directory::new();
    let owner = NodeMetadataOwner::new(8 * 1024 * 1024).unwrap();
    let baseline = owner.occupied_bytes();
    let node = Funded::new(&directory.0.join("audit"), &owner);
    let active = node
        .handle
        .reserve_control_critical(&attempt())
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    node.idle();
    let before = owner.snapshot();
    let views = node.handle.pending_attempts().unwrap();
    assert_eq!(views.len(), 1);
    assert_eq!(views.first().unwrap().sequence(), 1);
    let pointer = std::ptr::from_ref(views.first().unwrap().attempt());
    let clone = views.clone();
    assert_eq!(
        std::ptr::from_ref(clone.first().unwrap().attempt()),
        pointer
    );
    assert_eq!(owner.snapshot(), before, "no copied graph or auxiliary Vec");
    drop(active.finish(conclusion()).blocking_wait().unwrap());
    node.idle();
    assert_eq!(node.handle.snapshot().pending_attempts, 0);
    assert!(node.handle.pending_attempts().unwrap().is_empty());
    assert!(owner.snapshot().transient_reserved_bytes > 0);
    drop(node);
    assert_eq!(
        views.first().unwrap().attempt().operation_id,
        attempt().operation_id
    );
    assert!(owner.occupied_bytes() > baseline);
    drop(views);
    assert!(
        owner.occupied_bytes() > baseline,
        "last shared view still owns graph/header"
    );
    std::thread::spawn(move || drop(clone)).join().unwrap();
    assert_eq!(owner.occupied_bytes(), baseline);
}
