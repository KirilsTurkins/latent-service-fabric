//! Finite node-owned ingress work shares the provider's tenant and running limits.
use super::{
    admission::{self, Tenant},
    client::ClientCore,
    limits, Arc, AtomicUsize, Charge, Inner, Instant, Kind, Ordering, PlatformError,
    ProviderClient, ProviderPools,
};
use std::{future::Future, time::Duration};

/// Trusted trigger work, never guest capability authority. Clones retain one
/// actual request until its buffers and sockets retire; they mint no new budget.
#[derive(Clone)]
pub struct IngressRequest {
    inner: Arc<Request>,
}
struct Request {
    owner: Arc<Inner>,
    client: Arc<ClientCore>,
    tenant: Arc<Tenant>,
    deadline: Instant,
    remaining: AtomicUsize,
    _metadata: Charge,
    running: Option<Charge>,
}
impl Drop for Request {
    fn drop(&mut self) {
        self.tenant.requests.fetch_sub(1, Ordering::AcqRel);
        self.tenant.running.fetch_sub(1, Ordering::AcqRel);
        self.client
            .epoch
            .usage
            .requests
            .fetch_sub(1, Ordering::AcqRel);
        self.client
            .epoch
            .usage
            .running
            .fetch_sub(1, Ordering::AcqRel);
        drop(self.running.take());
        self.owner.changed.notify_waiters();
    }
}
impl ProviderPools {
    /// Reserve before pulling. A trusted operator binding supplies the tenant;
    /// no event field may choose it. Includes staging/receipt memory and one
    /// running slot, with no queue or use of reserved recovery capacity.
    pub fn ingress<T: Send + 'static>(
        &self,
        client: &Arc<ProviderClient<T>>,
        tenant_id: &str,
        deadline: Instant,
        maximum_operations: usize,
        memory_bytes: usize,
    ) -> Result<IngressRequest, PlatformError> {
        let now = Instant::now();
        if deadline <= now
            || deadline.duration_since(now) > Duration::from_mins(1)
            || !(1..=16).contains(&maximum_operations)
            || !(4096..=1024 * 1024).contains(&memory_bytes)
            || client
                .core
                .owner
                .upgrade()
                .is_none_or(|owner| !Arc::ptr_eq(&owner, &self.inner))
        {
            return Err(super::denied());
        }
        let mut state = self.inner.state.try_lock().map_err(|_| super::busy())?;
        self.inner.check()?;
        if client.core.epoch.retired.load(Ordering::Acquire) {
            return Err(super::denied());
        }
        let limits = self.inner.quotas.limits()?;
        let metadata = self.inner.quotas.acquire(Kind::Metadata, memory_bytes)?;
        let running = self.inner.quotas.acquire(Kind::Running, 1)?;
        let tenant = admission::tenant(&mut state, &self.inner, tenant_id)?;
        let counters = [
            (&tenant.requests, limits.maximum_requests_per_tenant),
            (&tenant.running, limits.maximum_running_per_tenant),
            (
                &client.core.epoch.usage.requests,
                limits.maximum_requests_per_provider,
            ),
            (
                &client.core.epoch.usage.running,
                limits.maximum_running_per_provider,
            ),
        ];
        for (index, (counter, maximum)) in counters.iter().enumerate() {
            if let Err(failure) = limits::increment(counter, 1, *maximum) {
                for (previous, _) in &counters[..index] {
                    previous.fetch_sub(1, Ordering::AcqRel);
                }
                return Err(failure);
            }
        }
        Ok(IngressRequest {
            inner: Arc::new(Request {
                owner: self.inner.clone(),
                client: client.core.clone(),
                tenant,
                deadline,
                remaining: AtomicUsize::new(maximum_operations),
                _metadata: metadata,
                running: Some(running),
            }),
        })
    }
}
impl IngressRequest {
    pub fn checkpoint(&self) -> Result<(), PlatformError> {
        self.inner.owner.check()?;
        if self.inner.client.epoch.retired.load(Ordering::Acquire) {
            return Err(super::denied());
        }
        if Instant::now() >= self.inner.deadline {
            return Err(super::super::error(
                latent_core::PlatformErrorCode::DeadlineExceeded,
                "provider-ingress-deadline",
            ));
        }
        Ok(())
    }
    #[must_use]
    pub fn deadline(&self) -> Instant {
        self.inner.deadline
    }
    /// Consume a finite protocol operation before writing its request.
    pub fn begin_operation(&self) -> Result<(), PlatformError> {
        self.checkpoint()?;
        self.inner
            .remaining
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_sub(1))
            .map_err(|_| super::capacity())?;
        Ok(())
    }
    pub async fn wait_for<F: Future>(&self, future: F) -> Result<F::Output, PlatformError> {
        tokio::pin!(future);
        loop {
            let changed = self.inner.owner.changed.notified();
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
        if !Arc::ptr_eq(client, &self.inner.client) {
            return Err(super::denied());
        }
        self.checkpoint()
    }
}
