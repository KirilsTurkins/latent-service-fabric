//! Read-only escaped recovery custody. Every clone shares the original paid
//! Pending allocation and graph; the single-row container is entirely inline.
use super::{AuditArc, AuditOperationAttempt, Ordering, Pending};

#[derive(Clone)]
pub struct AuditPendingAttemptView {
    pending: AuditArc<Pending>,
    sequence: u64,
}
impl AuditPendingAttemptView {
    #[must_use]
    pub fn sequence(&self) -> u64 {
        self.sequence
    }
    #[must_use]
    pub fn attempt(&self) -> &AuditOperationAttempt {
        &self.pending.attempt
    }
}

#[derive(Clone, Default)]
pub struct AuditPendingAttempts(Option<AuditPendingAttemptView>);
impl AuditPendingAttempts {
    pub(super) fn from_pending(pending: Option<&AuditArc<Pending>>) -> Self {
        Self(pending.and_then(|pending| {
            let sequence = pending.sequence.load(Ordering::Acquire);
            (sequence > 0).then(|| AuditPendingAttemptView {
                pending: pending.clone(),
                sequence,
            })
        }))
    }
    #[must_use]
    pub fn len(&self) -> usize {
        usize::from(self.0.is_some())
    }
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_none()
    }
    #[must_use]
    pub fn first(&self) -> Option<&AuditPendingAttemptView> {
        self.0.as_ref()
    }
}
impl IntoIterator for AuditPendingAttempts {
    type Item = AuditPendingAttemptView;
    type IntoIter = std::option::IntoIter<AuditPendingAttemptView>;
    fn into_iter(self) -> Self::IntoIter {
        self.0.into_iter()
    }
}
