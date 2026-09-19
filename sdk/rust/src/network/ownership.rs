use super::{ClientLimits, FailureKind, RpcFailure};
use std::{future::Future, sync::Arc};
use tokio::sync::{watch, Notify, OwnedSemaphorePermit, Semaphore};

pub(super) struct Resources {
    pub limits: ClientLimits,
    pub calls: Arc<Semaphore>,
    pub bytes: Arc<Semaphore>,
    pub tasks: Arc<Semaphore>,
    pub sockets: Arc<Semaphore>,
    pub closed: watch::Sender<bool>,
    pub retired: Notify,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ClientUsage {
    pub active_calls: usize,
    pub reserved_message_bytes: usize,
    pub executor_tasks: usize,
    pub sockets: usize,
    pub closed: bool,
}

impl Resources {
    pub fn new(limits: ClientLimits) -> Arc<Self> {
        let (closed, _) = watch::channel(false);
        Arc::new(Self {
            limits,
            calls: Arc::new(Semaphore::new(limits.maximum_calls)),
            bytes: Arc::new(Semaphore::new(limits.maximum_reserved_bytes)),
            tasks: Arc::new(Semaphore::new(limits.maximum_calls * 2 + 4)),
            sockets: Arc::new(Semaphore::new(1)),
            closed,
            retired: Notify::new(),
        })
    }

    pub fn close(&self) {
        self.closed.send_replace(true);
        self.calls.close();
    }

    pub fn begin(self: &Arc<Self>, encoded: usize) -> Result<Arc<Lease>, RpcFailure> {
        if *self.closed.borrow() {
            return Err(RpcFailure::local(FailureKind::Closed));
        }
        if encoded > self.limits.maximum_request_bytes {
            return Err(RpcFailure::local(FailureKind::Capacity));
        }
        let reserved = u32::try_from(2 * (encoded + self.limits.maximum_response_bytes) + 32768)
            .map_err(|_| RpcFailure::local(FailureKind::Capacity))?;
        let slot = self
            .calls
            .clone()
            .try_acquire_owned()
            .map_err(|_| RpcFailure::local(FailureKind::Capacity))?;
        let bytes = self
            .bytes
            .clone()
            .try_acquire_many_owned(reserved)
            .map_err(|_| RpcFailure::local(FailureKind::Capacity))?;
        Ok(Arc::new(Lease {
            slot: Some(slot),
            bytes: Some(bytes),
            resources: Arc::clone(self),
        }))
    }

    pub fn usage(&self) -> ClientUsage {
        ClientUsage {
            active_calls: self.limits.maximum_calls - self.calls.available_permits(),
            reserved_message_bytes: self.limits.maximum_reserved_bytes
                - self.bytes.available_permits(),
            executor_tasks: self.limits.maximum_calls * 2 + 4 - self.tasks.available_permits(),
            sockets: 1 - self.sockets.available_permits(),
            closed: *self.closed.borrow(),
        }
    }
}

pub(super) struct Lease {
    slot: Option<OwnedSemaphorePermit>,
    bytes: Option<OwnedSemaphorePermit>,
    resources: Arc<Resources>,
}

impl Drop for Lease {
    fn drop(&mut self) {
        self.bytes.take();
        self.slot.take();
        self.resources.retired.notify_waiters();
    }
}

pub(super) struct WorkLease {
    pub permit: Option<OwnedSemaphorePermit>,
    pub resources: Arc<Resources>,
}

impl Drop for WorkLease {
    fn drop(&mut self) {
        self.permit.take();
        self.resources.retired.notify_waiters();
    }
}

#[derive(Clone)]
pub(super) struct Executor(pub Arc<Resources>);

impl<Work> hyper::rt::Executor<Work> for Executor
where
    Work: Future<Output = ()> + Send + 'static,
{
    fn execute(&self, future: Work) {
        if *self.0.closed.borrow() {
            return;
        }
        let Ok(permit) = self.0.tasks.clone().try_acquire_owned() else {
            self.0.close();
            return;
        };
        let lease = WorkLease {
            permit: Some(permit),
            resources: Arc::clone(&self.0),
        };
        let mut closed = self.0.closed.subscribe();
        tokio::spawn(async move {
            let _lease = lease;
            if *closed.borrow() {
                drop(future);
                return;
            }
            tokio::select! {
                biased;
                _ = closed.changed() => {},
                () = future => {},
            }
        });
    }
}
