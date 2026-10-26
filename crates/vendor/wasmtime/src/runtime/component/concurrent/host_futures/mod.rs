//! Host future backing selected without retaining a native-memory factory.
//!
//! None preserves the original upstream set. Paid initialization and individual
//! task allocations receive the Store's original Memory only during admission.
//! Transferred sets, TaskSlots and escaped Wakers contain owner tokens only.

use super::pending_future::HostTaskFuture;
use crate::Result;
use crate::runtime::native_memory::Memory;
use core::pin::Pin;
use core::task::{Context, Poll};
use futures::stream::{FuturesUnordered, Stream};

mod abort;
mod paid;
mod paid_arc;
#[cfg(test)]
mod tests;

pub(crate) struct HostFutureSet(Kind);

enum Kind {
    Legacy(FuturesUnordered<HostTaskFuture>),
    // A mode flag with lazy physical initialization, never a factory Arc.
    Paid(Option<paid::FuturesUnordered<HostTaskFuture>>),
}

pub(super) struct TaskSlot(TaskKind);

enum TaskKind {
    Legacy,
    Paid(paid::PreparedTask<HostTaskFuture>),
}

impl HostFutureSet {
    pub(super) fn new(paid: bool) -> Self {
        if paid {
            Self(Kind::Paid(None))
        } else {
            Self(Kind::Legacy(FuturesUnordered::new()))
        }
    }

    pub(super) fn ensure(&mut self, memory: &Memory) -> Result<()> {
        if let Kind::Paid(set @ None) = &mut self.0 {
            // Construct both headers locally; publish only after both succeed.
            *set = Some(paid::FuturesUnordered::try_new(memory)?);
        }
        Ok(())
    }

    pub(super) fn push_prepared(&self, slot: TaskSlot, future: HostTaskFuture) {
        match (&self.0, slot.0) {
            (Kind::Legacy(set), TaskKind::Legacy) => set.push(future),
            (Kind::Paid(Some(set)), TaskKind::Paid(slot)) => set.push_prepared(slot, future),
            _ => unreachable!("future publication requires matching pre-effect preparation"),
        }
    }
}

impl TaskSlot {
    pub(super) fn prepare(memory: &Memory) -> Result<Self> {
        match memory {
            None => Ok(Self(TaskKind::Legacy)),
            Some(_) => Ok(Self(TaskKind::Paid(paid::PreparedTask::new(memory)?))),
        }
    }
}

impl Stream for HostFutureSet {
    type Item = crate::Result<()>;
    fn poll_next(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        match &mut self.get_mut().0 {
            Kind::Legacy(set) => Pin::new(set).poll_next(cx),
            Kind::Paid(Some(set)) => Pin::new(set).poll_next(cx),
            Kind::Paid(None) => unreachable!("paid driver must initialize before polling"),
        }
    }
}
