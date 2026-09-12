use super::{capacity, DeploymentOperationLimits, Result};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

#[derive(Debug)]
pub(crate) struct Budget {
    pub(crate) limits: DeploymentOperationLimits,
    used: AtomicUsize,
    readers: AtomicUsize,
}
impl Budget {
    pub(crate) fn new(limits: DeploymentOperationLimits) -> Arc<Self> {
        Arc::new(Self {
            limits,
            used: AtomicUsize::new(1024),
            readers: AtomicUsize::new(0),
        })
    }
    pub(crate) fn reserve(self: &Arc<Self>, bytes: usize) -> Result<Charge> {
        self.used
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |used| {
                used.checked_add(bytes)
                    .filter(|v| *v <= self.limits.maximum_metadata_bytes)
            })
            .map_err(|_| capacity())?;
        Ok(Charge {
            owner: Arc::clone(self),
            bytes,
        })
    }
    pub(crate) fn read(self: &Arc<Self>, payload_bytes: usize) -> Result<DeploymentReadLease> {
        self.readers
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
                n.checked_add(1)
                    .filter(|n| *n <= self.limits.maximum_read_owners)
            })
            .map_err(|_| capacity())?;
        // Domain result, wire projection, encoded body and delayed frame may
        // coexist. The fixed audit helper allowance survives commit as well.
        let charge = self.reserve(
            payload_bytes
                .saturating_mul(4)
                .saturating_add(super::MAX_OPERATION_SCRATCH_BYTES + 512),
        );
        match charge {
            Ok(charge) => Ok(DeploymentReadLease(Arc::new(ReadCharge { charge }))),
            Err(error) => {
                self.readers.fetch_sub(1, Ordering::AcqRel);
                Err(error)
            }
        }
    }
    #[cfg(test)]
    pub(crate) fn used(&self) -> usize {
        self.used.load(Ordering::Acquire)
    }
}
#[derive(Debug)]
pub(crate) struct Charge {
    owner: Arc<Budget>,
    pub(crate) bytes: usize,
}
impl Charge {
    pub(crate) fn shrink(&mut self, bytes: usize) -> Result<()> {
        if bytes > self.bytes {
            return Err(capacity());
        }
        self.owner
            .used
            .fetch_sub(self.bytes - bytes, Ordering::AcqRel);
        self.bytes = bytes;
        Ok(())
    }
}
impl Drop for Charge {
    fn drop(&mut self) {
        self.owner.used.fetch_sub(self.bytes, Ordering::AcqRel);
    }
}
#[derive(Debug)]
struct ReadCharge {
    charge: Charge,
}
impl Drop for ReadCharge {
    fn drop(&mut self) {
        self.charge.owner.readers.fetch_sub(1, Ordering::AcqRel);
    }
}
/// Shared accounting only; it retains no catalog, route graph or root lock.
#[derive(Debug, Clone)]
pub struct DeploymentReadLease(Arc<ReadCharge>);
impl DeploymentReadLease {
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        self.0.charge.bytes
    }
}
#[derive(Debug)]
pub struct DeploymentOperationRead<T> {
    value: T,
    lease: DeploymentReadLease,
}
impl<T> DeploymentOperationRead<T> {
    pub(crate) fn new(value: T, lease: DeploymentReadLease) -> Self {
        Self { value, lease }
    }
    #[must_use]
    pub fn value(&self) -> &T {
        &self.value
    }
    #[must_use]
    pub fn into_parts(self) -> (T, DeploymentReadLease) {
        (self.value, self.lease)
    }
}
