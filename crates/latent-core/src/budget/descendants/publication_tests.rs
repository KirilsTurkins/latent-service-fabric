use super::tests::{accept, request, reserve, root};
use super::*;
use std::sync::mpsc;
use std::time::{Duration, Instant};

fn chain(depth: usize, malformed: bool) -> (ActivationBudget, Vec<ChildBudgetOwner>, ClockSample) {
    let (root, _, sample) = root(DelegationLimits {
        maximum_depth: 16,
        maximum_live_children: 1,
        maximum_live_descendants: 32,
    });
    let mut children: Vec<ChildBudgetOwner> = Vec::new();
    for current in 1..=depth {
        if malformed && current == 17 {
            // The public API cannot make this chain: violate its depth metadata
            // only in this private test to exercise the defensive traversal cap.
            let previous = children.last_mut().unwrap();
            let inner = Arc::get_mut(&mut previous.budget.inner).unwrap();
            inner.lineage.get_mut().unwrap().depth = 15;
        }
        let parent = children.last().map_or(&root, ChildBudgetOwner::accounting);
        let current = u32::try_from(current).expect("bounded test depth");
        let request = request(
            1000 - u64::from(current),
            1000 - u64::from(current),
            32 - current,
        );
        let mut pending = reserve(parent, &request, sample).unwrap();
        if malformed && current == 17 {
            // Normal acceptance already rejects this overlong ancestry. Keep
            // its private pending ledger only to exercise the traversal cap.
            children.push(ChildBudgetOwner {
                budget: pending.budget.take().unwrap(),
            });
        } else {
            children.push(accept(pending, sample));
        }
    }
    (root, children, sample)
}

#[test]
fn ancestry_commit_checks_the_bounded_retained_chain_and_fails_closed() {
    for depth in [0, 1, 2, 16] {
        let (root, children, _) = chain(depth, false);
        let leaf = children.last().map_or(&root, ChildBudgetOwner::accounting);
        let guard = leaf.runtime_publication_guard();
        let mut observed = [0u8; 17];
        let mut count = 0;
        let committed = guard.original.commit_ancestry_while_open(|level| {
            observed[count] = level;
            count += 1;
        });
        drop(guard);
        assert!(committed);
        assert_eq!(count, depth + 1);
        for (index, level) in observed[..count].iter().enumerate() {
            assert_eq!(usize::from(*level), depth - index);
        }
        assert!(!leaf.descendant_ledger_is_closed());
        drop(children);
        assert_eq!(root.descendant_snapshot().unwrap().live_descendants, 0);
    }

    let (root, children, _) = chain(17, true);
    let leaf = children.last().unwrap().accounting();
    let guard = leaf.runtime_publication_guard();
    let mut count = 0;
    let committed = guard.original.commit_ancestry_while_open(|_| count += 1);
    drop(guard);
    assert!(!committed);
    assert_eq!(count, 2);
    drop(children);
    assert_eq!(root.descendant_snapshot().unwrap().live_descendants, 0);

    for invalid_depth in [0, 17] {
        let (root, mut children, _) = chain(2, false);
        let leaf = children.last_mut().unwrap();
        Arc::get_mut(&mut leaf.budget.inner)
            .unwrap()
            .lineage
            .get_mut()
            .unwrap()
            .depth = invalid_depth;
        let guard = leaf.accounting().runtime_publication_guard();
        let mut count = 0;
        let committed = guard.original.commit_ancestry_while_open(|_| count += 1);
        drop(guard);
        assert!(!committed);
        assert_eq!(count, usize::from(invalid_depth == 0));
        drop(children);
        assert_eq!(root.descendant_snapshot().unwrap().live_descendants, 0);
    }

    let sample = ClockSample::new(1000, Instant::now());
    let requested = request(1000, 1000, 0);
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &requested,
        &requested,
        &requested,
        None,
        sample,
    )
    .unwrap();
    let unlinked = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    let guard = unlinked.runtime_publication_guard();
    let mut count = 0;
    let committed = guard.original.commit_ancestry_while_open(|_| count += 1);
    drop(guard);
    assert!(!committed);
    assert_eq!(count, 0);
}

#[test]
fn ancestor_close_between_flag_rmws_refuses_unchecked_ancestor() {
    for finalize in [false, true] {
        for target_root in [false, true] {
            let (root, children, _) = chain(2, false);
            let leaf = children[1].accounting().clone();
            let target = if target_root {
                root.clone()
            } else {
                children[0].accounting().clone()
            };
            let reserved = root.descendant_snapshot().unwrap().reserved_memory_bytes;
            let (held_tx, held_rx) = mpsc::sync_channel(0);
            let (resume_tx, resume_rx) = mpsc::sync_channel(0);
            let worker = std::thread::spawn(move || {
                let guard = leaf.runtime_publication_guard();
                guard.original.commit_ancestry_while_open(|depth| {
                    if depth == 2 {
                        held_tx.send(()).unwrap();
                        resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    }
                })
            });
            held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            let (done_tx, done_rx) = mpsc::sync_channel(0);
            let closer = std::thread::spawn(move || {
                if finalize {
                    let _ = target.finalize_at(None, Instant::now());
                } else {
                    target.cancel_descendants().unwrap();
                }
                done_tx.send(()).unwrap();
            });
            let terminal_received = done_rx.recv_timeout(Duration::from_secs(3));
            let completed = terminal_received.is_ok();
            resume_tx.send(()).unwrap();
            let committed = worker.join().unwrap();
            if !completed {
                done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            }
            closer.join().unwrap();
            assert!(completed);
            assert!(!committed, "finalize={finalize} target_root={target_root}");
            assert_eq!(
                root.descendant_snapshot().unwrap().reserved_memory_bytes,
                reserved
            );
            drop(children);
            assert_eq!(root.descendant_snapshot().unwrap().live_descendants, 0);
            assert_eq!(root.descendant_snapshot().unwrap().reserved_memory_bytes, 0);
        }
    }
}

#[test]
fn ancestor_close_after_its_flag_rmw_follows_the_common_commit_point() {
    for finalize in [false, true] {
        let (root, children, _) = chain(2, false);
        let leaf = children[1].accounting().clone();
        let target = children[0].accounting().clone();
        let reserved = root.descendant_snapshot().unwrap().reserved_memory_bytes;
        let (held_tx, held_rx) = mpsc::sync_channel(0);
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let guard = leaf.runtime_publication_guard();
            guard.original.commit_ancestry_while_open(|depth| {
                if depth == 1 {
                    held_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                }
            })
        });
        held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let (done_tx, done_rx) = mpsc::sync_channel(0);
        let closer = std::thread::spawn(move || {
            if finalize {
                let _ = target.finalize_at(None, Instant::now());
            } else {
                target.cancel_descendants().unwrap();
            }
            done_tx.send(()).unwrap();
        });
        let terminal_received = done_rx.recv_timeout(Duration::from_secs(3));
        let completed = terminal_received.is_ok();
        resume_tx.send(()).unwrap();
        let committed = worker.join().unwrap();
        if !completed {
            done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        }
        closer.join().unwrap();
        assert!(completed && committed);
        assert_eq!(
            root.descendant_snapshot().unwrap().reserved_memory_bytes,
            reserved
        );
        drop(children);
        assert_eq!(root.descendant_snapshot().unwrap().live_descendants, 0);
        assert_eq!(root.descendant_snapshot().unwrap().reserved_memory_bytes, 0);
    }
}

#[test]
fn unchecked_ancestor_closure_still_refuses_after_checked_ancestor_closes() {
    for finalize in [false, true] {
        let (root, children, _) = chain(2, false);
        let leaf = children[1].accounting().clone();
        let checked = children[0].accounting().clone();
        let unchecked = root.clone();
        let reserved = root.descendant_snapshot().unwrap().reserved_memory_bytes;
        let (held_tx, held_rx) = mpsc::sync_channel(0);
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let guard = leaf.runtime_publication_guard();
            guard.original.commit_ancestry_while_open(|depth| {
                if depth == 1 {
                    held_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                }
            })
        });
        held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let (done_tx, done_rx) = mpsc::sync_channel(0);
        let closer = std::thread::spawn(move || {
            if finalize {
                let _ = checked.finalize_at(None, Instant::now());
                let _ = unchecked.finalize_at(None, Instant::now());
            } else {
                checked.cancel_descendants().unwrap();
                unchecked.cancel_descendants().unwrap();
            }
            done_tx.send(()).unwrap();
        });
        let terminal_received = done_rx.recv_timeout(Duration::from_secs(3));
        let completed = terminal_received.is_ok();
        resume_tx.send(()).unwrap();
        let committed = worker.join().unwrap();
        if !completed {
            done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        }
        closer.join().unwrap();
        assert!(completed && !committed);
        assert_eq!(
            root.descendant_snapshot().unwrap().reserved_memory_bytes,
            reserved
        );
        drop(children);
        assert_eq!(root.descendant_snapshot().unwrap().live_descendants, 0);
        assert_eq!(root.descendant_snapshot().unwrap().reserved_memory_bytes, 0);
    }
}

#[test]
fn ancestor_commit_does_not_take_parent_accounting_locks() {
    let (root, children, _) = chain(2, false);
    let middle = children[0].accounting().clone();
    let leaf = children[1].accounting().clone();
    let locked_root = root.clone();
    let (held_tx, held_rx) = mpsc::sync_channel(0);
    let (release_tx, release_rx) = mpsc::sync_channel(0);
    let holder = std::thread::spawn(move || {
        middle.with_test_accounting_lock(|| {
            locked_root.with_test_accounting_lock(|| {
                held_tx.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            });
        });
    });
    held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let (done_tx, done_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let guard = leaf.runtime_publication_guard();
        done_tx.send(guard.commit_while_open()).unwrap();
    });
    let early = done_rx.recv_timeout(Duration::from_secs(3));
    let finished_while_locked = early.is_ok();
    release_tx.send(()).unwrap();
    let committed = match early {
        Ok(value) => value,
        Err(_) => done_rx.recv_timeout(Duration::from_secs(3)).unwrap(),
    };
    holder.join().unwrap();
    worker.join().unwrap();
    assert!(finished_while_locked && committed);
    drop(children);
    assert_eq!(root.descendant_snapshot().unwrap().live_descendants, 0);
}
