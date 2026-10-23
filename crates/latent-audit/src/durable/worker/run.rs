use super::{
    critical, increment, AuditArc, AuditAttempt, AuditOperationConclusion, AuditOwned, AuditPage,
    AuditRecordData, Command, Finish, Heap, Ordering, OwnedDurableAuditAck, PageData, Pending,
    Reply, Result, Shared, SharedOwner, State, Store,
};
enum Work {
    Command(Command),
    Finish(Finish),
    Abandon(AuditArc<Pending>),
    Stop,
}
enum Completion {
    Begin(Reply<AuditAttempt>, Result<AuditAttempt>),
    Query(Reply<AuditPage>, Result<AuditPage>),
}
impl Completion {
    fn publish(self) {
        match self {
            Self::Begin(reply, result) => reply.send(result),
            Self::Query(reply, result) => reply.send(result),
        }
    }
}
pub(super) fn run(shared: SharedOwner<Shared>, mut store: Store) {
    loop {
        let work = {
            let mut s = shared
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            loop {
                if let Some(f) = s.finish.take() {
                    break Work::Finish(f);
                }
                if let Some((p, r)) = s.begin.take() {
                    p.begun.store(true, Ordering::Release);
                    break Work::Command(Command::Begin(p, r));
                }
                if let Some(p) = s.pending.clone() {
                    if !p.finishing.load(Ordering::Acquire)
                        && (p.abandoned.load(Ordering::Acquire)
                            || (s.closed
                                && p.sequence.load(Ordering::Acquire) == 0
                                && !p.begun.load(Ordering::Acquire)))
                    {
                        if p.sequence.load(Ordering::Acquire) == 0
                            && !p.begun.load(Ordering::Acquire)
                        {
                            s.pending = None;
                            s.reserved_records -= 2;
                            s.reserved_bytes -= 2 * shared.limits.maximum_record_bytes;
                            s.queued_bytes -= 16384;
                        } else if p.sequence.load(Ordering::Acquire) == 0 {
                            if !store.unhealthy {
                                s.pending = None;
                                refund(&shared, &mut s, 2);
                            }
                        } else if !store.unhealthy {
                            p.finishing.store(true, Ordering::Release);
                            break Work::Abandon(p);
                        }
                    }
                }
                if let Some(c) = s.queue.pop_front() {
                    break Work::Command(c);
                }
                if s.closed
                    && (s.pending.is_none()
                        || store.unhealthy
                        || s.pending.as_ref().is_some_and(|p| p.recovered))
                {
                    s.summary.recovery_pending |= s.pending.is_some();
                    break Work::Stop;
                }
                #[cfg(any(test, feature = "test-support"))]
                {
                    s.waiting = true;
                    shared.wake.notify_all();
                }
                s = shared
                    .wake
                    .wait(s)
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                #[cfg(any(test, feature = "test-support"))]
                {
                    s.waiting = false;
                }
            }
        };
        match work {
            Work::Stop => break,
            Work::Finish(f) => {
                let result = complete(&shared, &mut store, &f.pending, f.conclusion);
                f.reply.send(result);
            }
            Work::Abandon(p) => match critical::abandoned(&p) {
                Ok(conclusion) => {
                    let _ = complete(&shared, &mut store, &p, conclusion);
                }
                Err(_) => {
                    store.unhealthy = true;
                    let mut state = shared
                        .state
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner);
                    update(&mut state, &store);
                }
            },
            Work::Command(command) => {
                let cost = command.cost();
                let completion = execute_command(&shared, &mut store, command);
                // execute_command has consumed the command and retired its
                // inputs and I/O temporaries. Pending attempts and returned
                // pages retain their separate record/response reservations.
                let mut s = shared
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                s.queued_bytes -= cost;
                drop(s);
                if let Some(completion) = completion {
                    completion.publish();
                }
            }
        }
    }
    // The real filesystem owner retires before publishing actual completion.
    drop(store);
    drop(shared);
}
fn execute_command(shared: &Shared, store: &mut Store, command: Command) -> Option<Completion> {
    match command {
        Command::Observe(o) => {
            let was_unhealthy = store.unhealthy;
            let result = o.with_value(|o| {
                store.append(
                    o.scope.clone(),
                    o.actor.clone(),
                    AuditRecordData::Observation(o),
                )
            });
            let mut s = shared
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if result.is_ok() || was_unhealthy || !store.unhealthy {
                refund(shared, &mut s, 1);
            }
            if result.is_err() {
                increment(&shared.dropped);
            }
            update(&mut s, store);
            None
        }
        Command::Begin(p, reply) => {
            let result = store.append(
                p.attempt.scope.clone(),
                p.attempt.actor.clone(),
                AuditRecordData::Attempt(p.attempt.clone()),
            );
            let mut s = shared
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            update(&mut s, store);
            if let Ok(ack) = &result {
                refund(shared, &mut s, 1);
                p.sequence.store(ack.sequence, Ordering::Release);
            } else {
                p.abandoned.store(true, Ordering::Release);
            }
            drop(s);
            Some(Completion::Begin(
                reply,
                result.map(|_| AuditAttempt::new(p)),
            ))
        }
        Command::Query(q, deadline, lease, prepared, reply) => {
            let result = store
                .query_with_custody(
                    &q,
                    deadline,
                    shared.dropped.load(Ordering::Relaxed),
                    |bytes| {
                        lease
                            .0
                            .prepare_record(bytes, shared.limits.maximum_record_bytes)
                    },
                )
                .map(|(records, coverage, next)| {
                    let data = PageData {
                        records,
                        coverage,
                        next,
                        metadata: shared.metadata.clone(),
                        lease,
                    };
                    AuditPage {
                        data: if let Some(prepared) = prepared {
                            prepared.allocate(data)
                        } else {
                            SharedOwner::unaccounted(data)
                        },
                    }
                });
            drop(q);
            if result
                .as_ref()
                .err()
                .is_some_and(|e| e.code == latent_core::PlatformErrorCode::CorruptArtifact)
            {
                store.unhealthy = true;
                let mut s = shared
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                update(&mut s, store);
            }
            Some(Completion::Query(reply, result))
        }
    }
}
fn complete(
    shared: &Shared,
    store: &mut Store,
    p: &Pending,
    conclusion: AuditOwned<AuditOperationConclusion>,
) -> Result<OwnedDurableAuditAck> {
    // Acknowledgement admission is part of the same fallible terminal attempt.
    // Even refusal before append must run the original finishing/abandon repair.
    let result = p.memory.prepare_owned(512).and_then(|ack_part| {
        conclusion
            .with_value(|conclusion| {
                store.append(
                    p.attempt.scope.clone(),
                    p.attempt.actor.clone(),
                    AuditRecordData::Outcome {
                        attempt_sequence: p.sequence.load(Ordering::Acquire),
                        conclusion,
                    },
                )
            })
            .and_then(|ack| {
                let heap = ack.heap_bytes()?;
                Ok(OwnedDurableAuditAck(AuditOwned::new(ack, ack_part, heap)))
            })
    });
    let mut s = shared
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    update(&mut s, store);
    if result.is_ok() {
        refund(shared, &mut s, 1);
        s.pending = None;
    } else if !store.unhealthy {
        p.finishing.store(false, Ordering::Release);
        p.abandoned.store(true, Ordering::Release);
    }
    result
}
fn refund(shared: &Shared, s: &mut State, count: usize) {
    s.reserved_records -= count;
    s.reserved_bytes -= count * shared.limits.maximum_record_bytes;
}
fn update(s: &mut State, store: &Store) {
    let (records, bytes, next) = store.summary();
    s.summary.retained_records = records;
    s.summary.retained_bytes = bytes;
    s.summary.next_sequence = next;
    s.summary.unknown_outcomes = store.unknown;
    s.summary.recovery_pending = store.unhealthy;
    s.summary.stage_bytes = if store.unhealthy { 68 * 1024 } else { 0 };
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use crate::durable::{
        memory::AuditCallMemory,
        tests::{attempt, conclusion, Directory},
        worker::{control_tests, AtomicBool, AtomicU64},
    };
    use latent_core::node_metadata::NodeMetadataOwner;

    // Fill only unallocated Part capacity through the real admission API.
    // No future storage is confirmed and no reservation/peak is fabricated.
    fn fill_pending_capacity(
        memory: &AuditCallMemory,
        envelope: usize,
    ) -> crate::durable::memory::Part {
        let (mut low, mut high) = (0, envelope);
        for _ in 0..32 {
            if low == high {
                break;
            }
            let middle = low + (high - low).div_ceil(2);
            match memory.prepare_owned(middle) {
                Ok(probe) => {
                    drop(probe);
                    low = middle;
                }
                Err(_) => high = middle - 1,
            }
        }
        assert_eq!(low, high);
        memory.prepare_owned(low).unwrap()
    }

    #[test]
    fn ack_admission_refusal_repairs_original_pending_finish_and_actual_abandon_drains() {
        let directory = Directory::new();
        let limits = crate::AuditLimits {
            maximum_records: 32,
            ..Default::default()
        };
        // Existing legacy Store fixture isolates the worker's terminal-error
        // mechanism; the failed ack uses the real original node reservation.
        let (mut store, shared, handle) =
            control_tests::deferred_journal(&directory.0.join("audit"), limits);
        let owner = NodeMetadataOwner::new(8 * 1024 * 1024).unwrap();
        let baseline = owner.occupied_bytes();
        let envelope = AuditCallMemory::envelope_bytes(limits.maximum_record_bytes).unwrap();
        let memory = AuditCallMemory::node(&owner, envelope).unwrap();
        let prepared = memory
            .prepare_arc::<Pending>(
                AuditCallMemory::owned_heap_bound(limits.maximum_record_bytes).unwrap(),
            )
            .unwrap();
        let record = attempt();
        store
            .append(
                record.scope.clone(),
                record.actor.clone(),
                AuditRecordData::Attempt(record.clone()),
            )
            .unwrap();
        let heap = record.heap_bytes().unwrap();
        let pending = prepared.allocate(
            Pending {
                shared: shared.downgrade(),
                attempt: record,
                sequence: AtomicU64::new(1),
                started: AtomicBool::new(false),
                abandoned: AtomicBool::new(false),
                finishing: AtomicBool::new(true),
                memory: memory.clone(),
                recovered: false,
                begun: AtomicBool::new(true),
            },
            heap,
        );
        {
            let mut state = shared.state.lock().unwrap();
            update(&mut state, &store);
            state.pending = Some(pending.clone());
            state.reserved_records = 1;
            state.reserved_bytes = limits.maximum_record_bytes;
        }
        let part = memory
            .prepare_owned(AuditCallMemory::owned_heap_bound(limits.maximum_record_bytes).unwrap())
            .unwrap();
        let terminal = conclusion();
        let terminal_heap = terminal.heap_bytes().unwrap();
        let terminal = AuditOwned::new(terminal, part, terminal_heap);
        let padding = fill_pending_capacity(&memory, envelope);
        assert!(memory.prepare_owned(1).is_err());
        let before = handle.snapshot();
        let original = owner.snapshot();
        let failure = complete(&shared, &mut store, &pending, terminal)
            .err()
            .unwrap();
        assert_eq!(
            failure.code,
            latent_core::PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(handle.snapshot(), before);
        assert_eq!(owner.snapshot(), original);
        assert!(!store.unhealthy);
        assert!(!pending.finishing.load(Ordering::Acquire));
        assert!(pending.abandoned.load(Ordering::Acquire));
        {
            let state = shared.state.lock().unwrap();
            assert!(AuditArc::ptr_eq(state.pending.as_ref().unwrap(), &pending));
            assert_eq!(state.reserved_records, 1);
            assert_eq!(state.reserved_bytes, limits.maximum_record_bytes);
        }
        drop(padding);
        handle.close();
        run(shared.clone(), store);
        let final_state = handle.snapshot();
        assert_eq!(final_state.retained_records, 2);
        assert_eq!(final_state.next_sequence, 3);
        assert_eq!(final_state.pending_attempts, 0);
        assert_eq!(final_state.reserved_records, 0);
        assert_eq!(final_state.reserved_bytes, 0);
        assert!(!final_state.recovery_pending);
        drop(pending);
        drop(memory);
        drop(handle);
        drop(shared);
        assert_eq!(owner.occupied_bytes(), baseline);
    }
}
