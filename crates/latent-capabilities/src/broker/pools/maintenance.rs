//! Explicit bounded operator recovery; never constructs guest authority.
use super::{
    client::ClientCore, Arc, AtomicBool, AtomicUsize, Charge, Inner, Instant, Kind, Ordering,
    PlatformError, ProviderClient, ProviderPools,
};
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
        self.inner.check()?;
        self.inner
            .active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| super::busy())?;
        let request = Request {
            maintenance: self.inner.clone(),
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
    pub(super) fn check_client(&self, client: &Arc<ClientCore>) -> Result<(), PlatformError> {
        if !Arc::ptr_eq(client, &self.inner.maintenance.client) {
            return Err(super::denied());
        }
        self.checkpoint()
    }
}
