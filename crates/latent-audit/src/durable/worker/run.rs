use super::{
    critical, increment, Arc, AuditAttempt, AuditOperationConclusion, AuditPage, AuditRecordData,
    Command, DurableAuditAck, Finish, Ordering, Pending, Result, Shared, State, Store,
};
enum Work {
    Command(Command),
    Finish(Finish),
    Abandon(Arc<Pending>),
    Stop,
}
#[expect(
    clippy::too_many_lines,
    reason = "One bounded worker state machine keeps reservation refunds and completion ordering visible together"
)]
pub(super) fn run(shared: Arc<Shared>, mut store: Store) {
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
                s = shared
                    .wake
                    .wait(s)
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
            }
        };
        match work {
            Work::Stop => break,
            Work::Finish(f) => {
                let result = complete(&shared, &mut store, &f.pending, f.conclusion);
                f.reply.send(result);
            }
            Work::Abandon(p) => {
                let _ = complete(&shared, &mut store, &p, critical::abandoned(&p));
            }
            Work::Command(command) => {
                let cost = command.cost();
                match command {
                    Command::Observe(o) => {
                        let was_unhealthy = store.unhealthy;
                        let result = store.append(
                            o.scope.clone(),
                            o.actor.clone(),
                            AuditRecordData::Observation(o),
                        );
                        let mut s = shared
                            .state
                            .lock()
                            .unwrap_or_else(std::sync::PoisonError::into_inner);
                        if result.is_ok() || was_unhealthy || !store.unhealthy {
                            refund(&shared, &mut s, 1);
                        }
                        if result.is_err() {
                            increment(&shared.dropped);
                        }
                        update(&mut s, &store);
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
                        update(&mut s, &store);
                        if let Ok(ack) = &result {
                            refund(&shared, &mut s, 1);
                            p.sequence.store(ack.sequence, Ordering::Release);
                        } else {
                            p.abandoned.store(true, Ordering::Release);
                        }
                        drop(s);
                        reply.send(result.map(|_| AuditAttempt::new(p)));
                    }
                    Command::Query(q, deadline, lease, reply) => {
                        let result = store
                            .query(&q, deadline, shared.dropped.load(Ordering::Relaxed))
                            .map(|(records, coverage, next)| AuditPage {
                                records,
                                coverage,
                                next,
                                lease,
                            });
                        if result.as_ref().err().is_some_and(|e| {
                            e.code == latent_core::PlatformErrorCode::CorruptArtifact
                        }) {
                            store.unhealthy = true;
                            let mut s = shared
                                .state
                                .lock()
                                .unwrap_or_else(std::sync::PoisonError::into_inner);
                            update(&mut s, &store);
                        }
                        reply.send(result);
                    }
                }
                let mut s = shared
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                s.queued_bytes -= cost;
            }
        }
    }
    // The real filesystem owner retires before publishing actual completion.
    drop(store);
    drop(shared);
}
fn complete(
    shared: &Shared,
    store: &mut Store,
    p: &Pending,
    conclusion: AuditOperationConclusion,
) -> Result<DurableAuditAck> {
    let result = store.append(
        p.attempt.scope.clone(),
        p.attempt.actor.clone(),
        AuditRecordData::Outcome {
            attempt_sequence: p.sequence.load(Ordering::Acquire),
            conclusion,
        },
    );
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
