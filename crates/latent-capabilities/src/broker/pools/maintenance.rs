//! Explicit bounded operator recovery; never constructs guest authority.
use super::{
    client::ClientCore, Arc, AtomicBool, AtomicUsize, Charge, Inner, Instant, Kind, Ordering,
    PlatformError, ProviderClient, ProviderPools,
};
use std::future::Future;
use std::time::Duration;

pub struct ProviderMaintenance {
    inner: Arc<Maintenance>,
}
struct Maintenance {
    owner: Arc<Inner>,
    client: Arc<ClientCore>,
    deadline: Instant,
    remaining: AtomicUsize,
    active: AtomicBool,
    _metadata: Charge,
    _slot: Charge,
}
/// One sequential recovery request. Clones retain the same physical owner;
/// they do not allocate another request or return its cleanup permit early.
#[derive(Clone)]
pub struct MaintenanceRequest {
    inner: Arc<Request>,
}
struct Request {
    maintenance: Arc<Maintenance>,
    remaining_operations: AtomicUsize,
    _memory: Option<Charge>,
}
impl Drop for Request {
    fn drop(&mut self) {
        self.maintenance.active.store(false, Ordering::Release);
    }
}
impl Drop for Maintenance {
    fn drop(&mut self) {
        self.owner.changed.notify_waiters();
    }
}
impl ProviderPools {
    /// The trusted adapter confines recovery to its configured endpoint and
    /// durable inventory. This permit supplies resource ownership, not policy
    /// authorization, and cannot be used to create an invocation session.
    pub fn maintenance<T: Send + 'static>(
        &self,
        client: &Arc<ProviderClient<T>>,
        deadline: Instant,
        maximum_requests: usize,
    ) -> Result<ProviderMaintenance, PlatformError> {
        let now = Instant::now();
        if deadline <= now
            || deadline.saturating_duration_since(now) > Duration::from_mins(2)
            || !(1..=64).contains(&maximum_requests)
            || client
                .core
                .owner
                .upgrade()
                .is_none_or(|owner| !Arc::ptr_eq(&owner, &self.inner))
        {
            return Err(super::denied());
        }
        self.inner.check()?;
        if client.core.epoch.retired.load(Ordering::Acquire) {
            return Err(super::denied());
        }
        let metadata = self.inner.quotas.acquire(Kind::Metadata, 4096)?;
        let slot = self.inner.quotas.acquire(Kind::Cleanup, 1)?;
        Ok(ProviderMaintenance {
            inner: Arc::new(Maintenance {
                owner: self.inner.clone(),
                client: client.core.clone(),
                deadline,
                remaining: AtomicUsize::new(maximum_requests),
                active: AtomicBool::new(false),
                _metadata: metadata,
                _slot: slot,
            }),
        })
    }
}
impl ProviderMaintenance {
    pub fn begin_request(&self) -> Result<MaintenanceRequest, PlatformError> {
        self.begin_owned_request(1, None)
    }

    pub(super) fn begin_deferred_request(
        &self,
        maximum_operations: usize,
        memory_bytes: usize,
    ) -> Result<MaintenanceRequest, PlatformError> {
        if !(1..=16).contains(&maximum_operations) || !(4096..=1024 * 1024).contains(&memory_bytes)
        {
            return Err(super::denied());
        }
        self.begin_owned_request(maximum_operations, Some(memory_bytes))
    }

    fn begin_owned_request(
        &self,
        maximum_operations: usize,
        memory_bytes: Option<usize>,
    ) -> Result<MaintenanceRequest, PlatformError> {
        self.inner.check()?;
        // The actual request and every physical connection clone retain this
        // prepaid buffer charge. Dropping a response cannot refund a live socket.
        let memory = memory_bytes
            .map(|bytes| self.inner.owner.quotas.acquire(Kind::Metadata, bytes))
            .transpose()?;
        self.inner
            .active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| super::busy())?;
        let request = Request {
            maintenance: self.inner.clone(),
            remaining_operations: AtomicUsize::new(maximum_operations),
            _memory: memory,
        };
        self.inner
            .remaining
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_sub(1))
            .map_err(|_| super::capacity())?;
        Ok(MaintenanceRequest {
            inner: Arc::new(request),
        })
    }
}
impl Maintenance {
    fn check(&self) -> Result<(), PlatformError> {
        self.owner.check()?;
        if self.client.epoch.retired.load(Ordering::Acquire) {
            return Err(super::denied());
        }
        if Instant::now() >= self.deadline {
            return Err(super::super::error(
                latent_core::PlatformErrorCode::DeadlineExceeded,
                "provider-maintenance-deadline",
            ));
        }
        Ok(())
    }
}
impl MaintenanceRequest {
    pub fn checkpoint(&self) -> Result<(), PlatformError> {
        self.inner.maintenance.check()
    }
    #[must_use]
    pub fn deadline(&self) -> Instant {
        self.inner.maintenance.deadline
    }

    pub(super) fn begin_operation(&self) -> Result<(), PlatformError> {
        self.checkpoint()?;
        self.inner
            .remaining_operations
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_sub(1))
            .map_err(|_| super::capacity())?;
        Ok(())
    }

    pub(super) async fn wait_for<F: Future>(&self, future: F) -> Result<F::Output, PlatformError> {
        tokio::pin!(future);
        loop {
            let changed = self.inner.maintenance.owner.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            self.checkpoint()?;
            tokio::select! {
                biased;
                () = &mut changed => {},
                () = tokio::time::sleep_until(tokio::time::Instant::from_std(self.deadline())) => self.checkpoint()?,
                result = &mut future => { self.checkpoint()?; return Ok(result); }
            }
        }
    }
    pub(super) fn check_client(&self, client: &Arc<ClientCore>) -> Result<(), PlatformError> {
        if !Arc::ptr_eq(client, &self.inner.maintenance.client) {
            return Err(super::denied());
        }
        self.checkpoint()
    }
}
