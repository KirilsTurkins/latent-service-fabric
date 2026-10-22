//! Production nonsuspending registry with explicit admitted-token/event ports.
//! These controls do not create a canonical thread or prove physical retirement.
pub use std::array;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Token {
    generation: u64,
    id: u64,
}
impl Token {
    fn valid(self) -> bool {
        self.generation != 0 && self.id != 0
    }
}
#[path = "../thread_registry.rs"]
mod registry;
use registry::{Error, Handle, Registry, MAX_THREADS};

fn token(id: u64) -> Token {
    Token { generation: 17, id }
}
fn admitted(registry: &mut Registry, canonical: u32) -> Handle {
    let handle = registry.reserve().unwrap();
    registry
        .admitted(
            handle,
            token(u64::from(canonical)),
            canonical as usize * 8,
            canonical,
        )
        .unwrap();
    handle
}
fn running(registry: &mut Registry, canonical: u32) -> Handle {
    let handle = admitted(registry, canonical);
    assert_eq!(
        registry.entered(canonical, canonical as usize * 8),
        Ok(handle)
    );
    registry.start(handle, canonical).unwrap();
    handle
}

#[test]
fn finite_reservations_cannot_reuse_a_stale_handle_or_rollback_accepted_work() {
    let mut registry = Registry::new(0);
    let stale = registry.reserve().unwrap();
    registry.rollback(stale).unwrap();
    let fresh = admitted(&mut registry, 1);
    assert_ne!(stale, fresh);
    assert_eq!(registry.rollback(stale), Err(Error::Stale));
    assert_eq!(registry.rollback(fresh), Err(Error::State));
    let reserved: Vec<_> = (1..MAX_THREADS)
        .map(|_| registry.reserve().unwrap())
        .collect();
    assert_eq!(registry.reserve(), Err(Error::Capacity));
    for handle in reserved {
        registry.rollback(handle).unwrap();
    }
    assert_eq!(registry.close(), Err(Error::Pending));
}

#[test]
fn admission_refuses_root_alias_and_duplicate_or_malformed_real_identities() {
    let mut registry = Registry::new(0);
    let first = admitted(&mut registry, 1);
    let next = registry.reserve().unwrap();
    for (owner, pointer, canonical) in [
        (token(2), 16, 0),
        (token(1), 16, 2),
        (token(2), 8, 2),
        (token(2), 16, 1),
        (token(2), 0, 2),
        (token(2), 17, 2),
        (
            Token {
                generation: 0,
                id: 2,
            },
            16,
            2,
        ),
        (
            Token {
                generation: 17,
                id: 0,
            },
            16,
            2,
        ),
    ] {
        assert_eq!(
            registry.admitted(next, owner, pointer, canonical),
            Err(Error::State)
        );
    }
    registry.admitted(next, token(2), 16, 2).unwrap();
    assert_eq!(registry.admitted(first, token(3), 24, 3), Err(Error::State));
    assert_eq!(registry.current_task(1), Ok(token(1)));
    assert_eq!(registry.current_task(2), Ok(token(2)));
}

#[test]
fn actual_entry_identity_and_threadinit_tls_and_reap_boundaries_are_ordered() {
    let mut registry = Registry::new(0);
    let child = admitted(&mut registry, 1);
    assert_eq!(registry.entered(1, 16), Err(Error::State));
    assert_eq!(registry.entered(99, 8), Err(Error::Stale));
    assert_eq!(registry.start(child, 1), Err(Error::State));
    assert_eq!(registry.tls_drained(child, 1), Err(Error::State));
    assert_eq!(registry.reaped(child), Err(Error::Pending));
    assert_eq!(registry.entered(1, 8), Ok(child));
    assert_eq!(registry.start(child, 2), Err(Error::State));
    registry.start(child, 1).unwrap();
    assert_eq!(registry.entered(1, 8), Err(Error::State));
    assert_eq!(registry.reaped(child), Err(Error::Pending));
    registry.tls_drained(child, 1).unwrap();
    assert_eq!(registry.current_task(1), Ok(token(1)));
    registry.claim_reap(child).unwrap();
    registry.reaped(child).unwrap();
    assert_eq!(registry.current_task(1), Err(Error::State));
}

#[test]
fn joining_requires_reap_and_exact_claim_before_packet_can_be_consumed() {
    let mut registry = Registry::new(0);
    let child = running(&mut registry, 1);
    registry.claim_join(child, 0).unwrap();
    assert_eq!(registry.complete_join(child, 0), Err(Error::Pending));
    assert_eq!(registry.claim_join(child, 0), Err(Error::JoinClaimed));
    assert_eq!(registry.detach(child), Err(Error::State));
    registry.tls_drained(child, 1).unwrap();
    assert_eq!(registry.complete_join(child, 0), Err(Error::Pending));
    registry.claim_reap(child).unwrap();
    registry.reaped(child).unwrap();
    assert_eq!(registry.complete_join(child, 2), Err(Error::Pending));
    registry.complete_join(child, 0).unwrap();
    assert_eq!(registry.complete_join(child, 0), Err(Error::Stale));
    registry.close().unwrap();
    assert_eq!(registry.reserve(), Err(Error::Closed));
}

#[test]
fn real_join_dependencies_refuse_self_cycles_and_tls_exit_with_unfinished_join() {
    let mut registry = Registry::new(0);
    let a = running(&mut registry, 1);
    let b = running(&mut registry, 2);
    let c = running(&mut registry, 3);
    assert_eq!(registry.claim_join(a, 1), Err(Error::SelfJoin));
    registry.claim_join(b, 1).unwrap();
    registry.claim_join(c, 2).unwrap();
    assert_eq!(registry.claim_join(a, 3), Err(Error::Cycle));
    assert_eq!(registry.tls_drained(a, 1), Err(Error::State));
    assert_eq!(registry.tls_drained(b, 2), Err(Error::State));
    registry.tls_drained(c, 3).unwrap();
    registry.claim_reap(c).unwrap();
    registry.reaped(c).unwrap();
    registry.complete_join(c, 2).unwrap();
    registry.tls_drained(b, 2).unwrap();
    registry.claim_reap(b).unwrap();
    registry.reaped(b).unwrap();
    registry.complete_join(b, 1).unwrap();
    registry.tls_drained(a, 1).unwrap();
}

#[test]
fn detach_keeps_real_child_and_original_owner_until_tls_frames_and_canonical_reap() {
    let mut registry = Registry::new(0);
    let child = running(&mut registry, 1);
    registry.detach(child).unwrap();
    assert_eq!(registry.current_task(1), Ok(token(1)));
    assert_eq!(registry.claim_join(child, 0), Err(Error::JoinClaimed));
    assert_eq!(registry.retire_detached(child), Err(Error::Pending));
    assert_eq!(registry.close(), Err(Error::Pending));
    registry.tls_drained(child, 1).unwrap();
    assert_eq!(registry.retire_detached(child), Err(Error::Pending));
    registry.claim_reap(child).unwrap();
    registry.reaped(child).unwrap();
    assert_eq!(registry.close(), Err(Error::Pending));
    registry.retire_detached(child).unwrap();
    registry.close().unwrap();
}

#[test]
fn runnable_snapshot_owns_no_borrow_and_does_not_equal_completion_or_empty_registry() {
    let mut registry = Registry::new(0);
    let reserved = registry.reserve().unwrap();
    let admitted = admitted(&mut registry, 1);
    let child = running(&mut registry, 2);
    let snapshot = registry.candidates();
    assert_eq!(
        snapshot.iter().flatten().copied().collect::<Vec<_>>(),
        vec![(child, 2)]
    );
    // Mutation is possible only after the nonsuspending table call returned.
    registry.tls_drained(child, 2).unwrap();
    registry.claim_reap(child).unwrap();
    registry.reaped(child).unwrap();
    assert!(registry.candidates().iter().all(Option::is_none));
    assert_eq!(registry.close(), Err(Error::Pending));
    registry.rollback(reserved).unwrap();
    assert_eq!(registry.rollback(admitted), Err(Error::State));
    assert_eq!(snapshot.iter().flatten().count(), 1);
}

#[test]
fn physical_reaper_claim_remains_exclusive_until_actual_free_and_settlement_return() {
    let mut registry = Registry::new(0);
    let child = running(&mut registry, 1);
    registry.claim_join(child, 0).unwrap();
    assert_eq!(registry.claim_reap(child), Err(Error::Pending));
    registry.tls_drained(child, 1).unwrap();
    registry.claim_reap(child).unwrap();
    assert_eq!(registry.claim_reap(child), Err(Error::Pending));
    assert_eq!(registry.tls_finished(child), Ok(false));
    assert_eq!(registry.is_reaped(child), Ok(false));
    assert_eq!(registry.complete_join(child, 0), Err(Error::Pending));
    assert_eq!(registry.close_after_root_frames(), Err(Error::Pending));
    registry.reaped(child).unwrap();
    registry.complete_join(child, 0).unwrap();
    registry.close_after_root_frames().unwrap();
}

#[test]
fn final_root_close_removes_only_reaped_tombstones_after_all_user_frames() {
    let mut registry = Registry::new(0);
    let child = running(&mut registry, 1);
    assert_eq!(registry.close_after_root_frames(), Err(Error::Pending));
    registry.tls_drained(child, 1).unwrap();
    assert_eq!(registry.close_after_root_frames(), Err(Error::Pending));
    registry.claim_reap(child).unwrap();
    registry.reaped(child).unwrap();
    assert_eq!(registry.close(), Err(Error::Pending));
    registry.close_after_root_frames().unwrap();
    assert_eq!(registry.current_task(1), Err(Error::Stale));
    assert_eq!(registry.reserve(), Err(Error::Closed));
}
