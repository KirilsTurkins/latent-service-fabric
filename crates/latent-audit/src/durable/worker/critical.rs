use super::{
    closed, codec, error, invalid, store, ticket, unavailable, Arc, AtomicBool, AtomicU64,
    AuditAppendTicket, AuditBeginTicket, AuditHandle, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult, AuditReason, AuditRecordData, Finish, Ordering,
    Pending, Result,
};
pub struct AuditCriticalReservation {
    pending: Option<Arc<Pending>>,
}
pub struct AuditAttempt {
    pending: Option<Arc<Pending>>,
}
impl AuditHandle {
    /// Reject-only shape and complete-envelope size validation. Does not reserve
    /// journal capacity or authorize a control mutation.
    pub fn preflight_conclusion(
        &self,
        attempt: &AuditOperationAttempt,
        conclusion: &AuditOperationConclusion,
    ) -> Result<()> {
        codec::attempt(attempt)?;
        codec::conclusion(conclusion)?;
        let conclusion = codec::normalize(conclusion, self.shared.limits.maximum_record_bytes)?;
        codec::envelope(
            &attempt.scope,
            &attempt.actor,
            AuditRecordData::Outcome {
                attempt_sequence: u64::MAX,
                conclusion,
            },
            self.shared.limits.maximum_record_bytes,
        )
    }
    pub fn try_reserve_critical(
        &self,
        attempt: &AuditOperationAttempt,
    ) -> Result<AuditCriticalReservation> {
        codec::attempt(attempt)?;
        let mut s = self.shared.lock()?;
        self.shared.queue_room(&s, 16384)?;
        if s.pending.is_some() {
            return Err(error(
                latent_core::PlatformErrorCode::ResourceExhausted,
                "audit-critical-pending",
            ));
        }
        self.shared.record_room(&s, 2)?;
        let attempt = codec::normalize(attempt, self.shared.limits.maximum_record_bytes)?;
        codec::envelope(
            &attempt.scope,
            &attempt.actor,
            AuditRecordData::Attempt(attempt.clone()),
            self.shared.limits.maximum_record_bytes,
        )?;
        let pending = Arc::new(Pending {
            shared: Arc::downgrade(&self.shared),
            attempt,
            sequence: AtomicU64::new(0),
            started: AtomicBool::new(false),
            abandoned: AtomicBool::new(false),
            finishing: AtomicBool::new(false),
            recovered: false,
            begun: AtomicBool::new(false),
        });
        s.reserved_records += 2;
        s.reserved_bytes += 2 * self.shared.limits.maximum_record_bytes;
        s.queued_bytes += 16384;
        s.pending = Some(pending.clone());
        Ok(AuditCriticalReservation {
            pending: Some(pending),
        })
    }
    pub fn reconcile(
        &self,
        sequence: u64,
        conclusion: AuditOperationConclusion,
    ) -> Result<AuditAppendTicket> {
        codec::conclusion(&conclusion)?;
        let p = {
            let s = self.shared.lock()?;
            if s.closed || s.summary.recovery_pending {
                return Err(unavailable());
            }
            s.pending
                .as_ref()
                .filter(|p| p.recovered && p.sequence.load(Ordering::Acquire) == sequence)
                .cloned()
                .ok_or_else(invalid)?
        };
        Ok(finish(p, conclusion))
    }
}
impl AuditCriticalReservation {
    pub fn begin(mut self) -> AuditBeginTicket {
        let pending = self.pending.take().expect("affine reservation");
        let (reply, ticket) = ticket::channel();
        if let Some(shared) = pending.shared.upgrade() {
            let mut s = shared
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if s.closed || s.summary.recovery_pending {
                drop(s);
                abandon(&pending);
                reply.send(Err(closed()));
            } else {
                s.begin = Some((pending, reply));
                drop(s);
                shared.wake.notify_one();
            }
        } else {
            reply.send(Err(closed()));
        }
        AuditBeginTicket(ticket)
    }
}
impl Drop for AuditCriticalReservation {
    fn drop(&mut self) {
        if let Some(p) = self.pending.take() {
            abandon(&p);
        }
    }
}
impl AuditAttempt {
    pub(super) fn new(pending: Arc<Pending>) -> Self {
        Self {
            pending: Some(pending),
        }
    }
    #[must_use]
    pub fn sequence(&self) -> u64 {
        self.pending
            .as_ref()
            .expect("live attempt")
            .sequence
            .load(Ordering::Acquire)
    }
    pub fn mutation_started(&mut self) -> Result<()> {
        let p = self.pending.as_ref().ok_or_else(invalid)?;
        let shared = p.shared.upgrade().ok_or_else(closed)?;
        let s = shared.state.lock().map_err(|_| unavailable())?;
        if s.closed
            || s.summary.recovery_pending
            || p.finishing.load(Ordering::Acquire)
            || p.sequence.load(Ordering::Acquire) == 0
            || !s.pending.as_ref().is_some_and(|o| Arc::ptr_eq(o, p))
        {
            return Err(unavailable());
        }
        p.started.store(true, Ordering::Release);
        Ok(())
    }
    #[must_use]
    pub fn finish(mut self, conclusion: AuditOperationConclusion) -> AuditAppendTicket {
        finish(self.pending.take().expect("affine attempt"), conclusion)
    }
}
impl Drop for AuditAttempt {
    fn drop(&mut self) {
        if let Some(p) = self.pending.take() {
            abandon(&p);
        }
    }
}
fn abandon(p: &Arc<Pending>) {
    p.abandoned.store(true, Ordering::Release);
    if let Some(s) = p.shared.upgrade() {
        s.wake.notify_one();
    }
}
#[expect(
    clippy::needless_pass_by_value,
    reason = "Consume the terminal owner and caller conclusion while normalizing the queued record and handling abandonment"
)]
fn finish(p: Arc<Pending>, conclusion: AuditOperationConclusion) -> AuditAppendTicket {
    let (reply, ticket) = ticket::channel();
    let result = (|| {
        codec::conclusion(&conclusion)?;
        let shared = p.shared.upgrade().ok_or_else(closed)?;
        let mut s = shared.state.lock().map_err(|_| unavailable())?;
        if s.summary.recovery_pending
            || s.finish.is_some()
            || !s.pending.as_ref().is_some_and(|o| Arc::ptr_eq(o, &p))
            || p.finishing.load(Ordering::Acquire)
        {
            return Err(unavailable());
        }
        let conclusion = codec::normalize(&conclusion, shared.limits.maximum_record_bytes)?;
        codec::envelope(
            &p.attempt.scope,
            &p.attempt.actor,
            AuditRecordData::Outcome {
                attempt_sequence: p.sequence.load(Ordering::Acquire),
                conclusion: conclusion.clone(),
            },
            shared.limits.maximum_record_bytes,
        )?;
        p.finishing.store(true, Ordering::Release);
        s.finish = Some(Finish {
            pending: p.clone(),
            conclusion,
            reply,
        });
        drop(s);
        shared.wake.notify_one();
        Ok(())
    })();
    // `reply` moves only after every fallible step. For errors create a completed
    // ticket while the abandoned pending row retains its terminal allowance.
    if let Err(error) = result {
        abandon(&p);
        let (r, t) = ticket::channel();
        r.send(Err(error));
        return AuditAppendTicket(t);
    }
    AuditAppendTicket(ticket)
}
pub(super) fn abandoned(p: &Pending) -> AuditOperationConclusion {
    let started = p.started.load(Ordering::Acquire);
    AuditOperationConclusion {
        canary_decision: None,
        result: if started {
            AuditOperationResult::Unknown
        } else {
            AuditOperationResult::NotStarted
        },
        reason: if started {
            AuditReason::MutationUncertain
        } else {
            AuditReason::NotStarted
        },
        receipt_digest: None,
        identities: p.attempt.identities.clone(),
        replay: p.attempt.replay,
        occurred_at_unix_millis: store::now(),
    }
}
