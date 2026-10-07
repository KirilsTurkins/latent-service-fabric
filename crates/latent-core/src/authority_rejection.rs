//! Bounded, rejection-only metadata shared by actual authority owners.
//!
//! Tokens describe an installation's lifetime; they confer no permission and
//! cannot be reset. The sealed weak observer executes only this lower-layer
//! bookkeeping. It cannot call a policy, artifact, provider, audit or I/O owner.

use crate::{PlatformError, PlatformErrorCode};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex, OnceLock, Weak,
};

/// Derived from the actual accepted mutation, never from an RPC authority hint.
#[derive(Clone, Copy)]
pub enum AuthorityRejection<'a> {
    PolicyTenant(&'a str),
    Publication {
        tenant: Option<&'a str>,
        publication: &'a str,
    },
    OwnerRetired,
}

mod sealed {
    pub trait Sealed {}
}

/// Only the compact lower-layer weak adapter implements this trait. Rejection
/// neither admits work nor refunds a physical or request reservation.
pub trait AuthorityRejectionObserver: sealed::Sealed + Send + Sync {
    fn reject(&self, target: AuthorityRejection<'_>) -> Result<(), PlatformError>;
}

struct Entry {
    tenant: Box<str>,
    publication: Box<str>,
    current: Weak<AtomicBool>,
}
struct Inner {
    entries: Mutex<Vec<Entry>>,
    maximum: usize,
    retired: AtomicBool,
    observer: OnceLock<Arc<WeakObserver>>,
}
impl Drop for Inner {
    fn drop(&mut self) {
        for entry in self
            .entries
            .get_mut()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .iter()
        {
            if let Some(current) = entry.current.upgrade() {
                current.store(false, Ordering::Release);
            }
        }
    }
}

/// Finite installation/lookup token registry. No documents, credentials,
/// physical owners, tasks, timers or native resources are retained here.
pub struct AuthorityRejectionOwner(Arc<Inner>);

/// A permanently rejectable installation stamp. This is descriptive metadata,
/// not a grant: the original policy/publication/provider gates remain required.
#[derive(Clone)]
pub struct AuthorityRejectionToken {
    current: Arc<AtomicBool>,
    owner: Weak<Inner>,
}
impl AuthorityRejectionToken {
    #[must_use]
    pub fn is_current(&self) -> bool {
        self.current.load(Ordering::Acquire)
            && self.owner.upgrade().is_some_and(|owner| {
                !owner.retired.load(Ordering::Acquire) && !owner.entries.is_poisoned()
            })
    }
    pub fn reject(&self) {
        self.current.store(false, Ordering::Release);
    }
}

impl AuthorityRejectionOwner {
    pub fn new(maximum: usize) -> Result<Self, PlatformError> {
        if !(1..=8192).contains(&maximum) {
            return Err(failure(PlatformErrorCode::InvalidArgument));
        }
        let mut entries = Vec::new();
        entries
            .try_reserve_exact(maximum)
            .map_err(|_| failure(PlatformErrorCode::ResourceExhausted))?;
        Ok(Self(Arc::new(Inner {
            entries: Mutex::new(entries),
            maximum,
            retired: AtomicBool::new(false),
            observer: OnceLock::new(),
        })))
    }

    #[must_use]
    pub fn observer(&self) -> Arc<dyn AuthorityRejectionObserver> {
        self.0
            .observer
            .get_or_init(|| Arc::new(WeakObserver(Arc::downgrade(&self.0))))
            .clone()
    }

    /// Called only inside the caller's current approved installation fence.
    /// Replacing a stamp permanently closes it, including already accepted work.
    /// This method does not verify or create the required approval itself.
    pub fn install(
        &self,
        tenant: &str,
        publication: &str,
        previous: Option<&AuthorityRejectionToken>,
    ) -> Result<AuthorityRejectionToken, PlatformError> {
        if !identity(tenant, 512) || !identity(publication, 256) {
            return Err(failure(PlatformErrorCode::InvalidArgument));
        }
        if previous.is_some_and(|previous| !previous.owner.ptr_eq(&Arc::downgrade(&self.0))) {
            return Err(failure(PlatformErrorCode::InvalidArgument));
        }
        // Every allocation precedes the no-I/O metadata acceptance below.
        let current = Arc::new(AtomicBool::new(true));
        let entry = Entry {
            tenant: tenant.into(),
            publication: publication.into(),
            current: Arc::downgrade(&current),
        };
        let mut entries = self
            .0
            .entries
            .lock()
            .map_err(|_| failure(PlatformErrorCode::Unavailable))?;
        if self.0.retired.load(Ordering::Acquire) {
            return Err(failure(PlatformErrorCode::Unavailable));
        }
        entries.retain(|entry| {
            entry
                .current
                .upgrade()
                .is_some_and(|current| current.load(Ordering::Acquire))
        });
        let replaced = previous.and_then(|previous| {
            entries
                .iter()
                .position(|entry| entry.current.ptr_eq(&Arc::downgrade(&previous.current)))
        });
        if replaced.is_none() && entries.len() >= self.0.maximum {
            return Err(failure(PlatformErrorCode::ResourceExhausted));
        }
        if let Some(previous) = previous {
            previous.reject();
        }
        if let Some(index) = replaced {
            entries[index] = entry;
        } else {
            entries.push(entry);
        }
        Ok(AuthorityRejectionToken {
            current,
            owner: Arc::downgrade(&self.0),
        })
    }
}

struct WeakObserver(Weak<Inner>);
impl sealed::Sealed for WeakObserver {}
impl AuthorityRejectionObserver for WeakObserver {
    fn reject(&self, target: AuthorityRejection<'_>) -> Result<(), PlatformError> {
        match target {
            AuthorityRejection::PolicyTenant(tenant) if !identity(tenant, 512) => {
                return Err(failure(PlatformErrorCode::InvalidArgument));
            }
            AuthorityRejection::Publication {
                tenant,
                publication,
            } if !identity(publication, 256)
                || tenant.is_some_and(|tenant| !identity(tenant, 512)) =>
            {
                return Err(failure(PlatformErrorCode::InvalidArgument));
            }
            _ => {}
        }
        let inner = self
            .0
            .upgrade()
            .ok_or_else(|| failure(PlatformErrorCode::Unavailable))?;
        let entries = inner
            .entries
            .lock()
            .map_err(|_| failure(PlatformErrorCode::Unavailable))?;
        if matches!(target, AuthorityRejection::OwnerRetired) {
            // The actual policy/catalog owner cannot be replaced inside this
            // registry after retirement or uncertain persistence. A new node
            // installation must use its new, explicitly bound owner.
            inner.retired.store(true, Ordering::Release);
        }
        for entry in entries.iter() {
            let matches = match target {
                AuthorityRejection::PolicyTenant(tenant) => entry.tenant.as_ref() == tenant,
                AuthorityRejection::Publication {
                    tenant,
                    publication,
                } => {
                    entry.publication.as_ref() == publication
                        && tenant.is_none_or(|tenant| entry.tenant.as_ref() == tenant)
                }
                AuthorityRejection::OwnerRetired => true,
            };
            if matches {
                if let Some(current) = entry.current.upgrade() {
                    current.store(false, Ordering::Release);
                }
            }
        }
        Ok(())
    }
}

/// Once-only, pre-exposure observer attachment on a real policy/catalog owner.
/// Existing stateless owners may expose without one; late retrofit is refused.
pub struct AuthorityRejectionRegistration {
    exposed: AtomicBool,
    gate: Mutex<()>,
    observer: OnceLock<Arc<dyn AuthorityRejectionObserver>>,
}
impl Default for AuthorityRejectionRegistration {
    fn default() -> Self {
        Self {
            exposed: AtomicBool::new(false),
            gate: Mutex::new(()),
            observer: OnceLock::new(),
        }
    }
}
impl AuthorityRejectionRegistration {
    /// Exact registered adapter identity, without deriving permission from IDs
    /// or equal limits. The registry returns one shared weak adapter instance.
    #[must_use]
    pub fn observes(&self, observer: &Arc<dyn AuthorityRejectionObserver>) -> bool {
        self.observer
            .get()
            .is_some_and(|installed| Arc::ptr_eq(installed, observer))
    }

    pub fn install(
        &self,
        observer: Arc<dyn AuthorityRejectionObserver>,
    ) -> Result<(), PlatformError> {
        let _guard = self
            .gate
            .try_lock()
            .map_err(|_| failure(PlatformErrorCode::Unavailable))?;
        if self.exposed.load(Ordering::Acquire) || self.observer.get().is_some() {
            return Err(failure(PlatformErrorCode::StateConflict));
        }
        self.observer
            .set(observer)
            .map_err(|_| failure(PlatformErrorCode::StateConflict))
    }

    pub fn expose(&self) -> Result<(), PlatformError> {
        if !self.exposed.load(Ordering::Acquire) {
            let _guard = self
                .gate
                .try_lock()
                .map_err(|_| failure(PlatformErrorCode::Unavailable))?;
            self.exposed.store(true, Ordering::Release);
        }
        Ok(())
    }

    /// The adapter invokes only bounded lower-layer rejection. The caller must
    /// hold its actual final mutation fence. This adapter releases its metadata
    /// lock before returning; no new lock or callback survives into caller I/O.
    pub fn reject(&self, target: AuthorityRejection<'_>) -> Result<(), PlatformError> {
        self.observer
            .get()
            .map_or(Ok(()), |observer| observer.reject(target))
    }
}

fn identity(value: &str, maximum: usize) -> bool {
    !value.is_empty() && value.len() <= maximum && !value.chars().any(char::is_control)
}
fn failure(code: PlatformErrorCode) -> PlatformError {
    PlatformError {
        code,
        message: "authority-rejection-fence".into(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests;
