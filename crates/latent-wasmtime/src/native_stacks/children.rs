//! Pre-start native admission and an exact-child physical retirement fence.
//! Only an authenticated canonical-thread shim may consume the pending permit.

use super::*;
use latent_core::activation_runtime::RuntimeToken;

pub(super) struct Children {
    entries: Vec<Arc<Child>>,
    pub(super) pending: Option<Permit>,
    maximum: usize,
}

pub(crate) struct Child {
    token: RuntimeToken,
    runtime: ActivationRuntime,
    // 0: pre-start, 1: actual stack mapped, 2: unmapped, 3: uncertain release.
    phase: AtomicU32,
    changed: tokio::sync::Notify,
    waiter: Mutex<Option<RuntimeOwner>>,
    _metadata: HostMemoryReservation,
}

impl Child {
    pub(crate) fn token(&self) -> RuntimeToken {
        self.token
    }
    pub(crate) fn physically_retired(&self) -> bool {
        self.phase.load(Ordering::Acquire) == 2
    }
    pub(crate) fn retirement_failed(&self) -> bool {
        self.phase.load(Ordering::Acquire) == 3
    }
    pub(crate) async fn changed(&self) {
        let changed = self.changed.notified();
        tokio::pin!(changed);
        let _ = changed.as_mut().enable();
        if self.phase.load(Ordering::Acquire) < 2 {
            changed.await;
        }
    }
    pub(crate) fn prepare_wait(&self, continuation: RuntimeToken) -> Result<(), PlatformError> {
        let mut waiter = self
            .waiter
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if waiter.is_some() {
            return Err(failure("native-child-join-already-owned"));
        }
        // The exact child retains this original Wait through result lowering.
        // The caller reaps it only after consuming the actual completion; trap
        // and cancellation paths retain it until the actual Store is dropped.
        *waiter = Some(self.runtime.register(OwnerKind::Wait, Some(continuation))?);
        Ok(())
    }
    pub(super) fn mapped(&self) {
        assert_eq!(self.phase.swap(1, Ordering::AcqRel), 0);
    }
    pub(super) fn unmapped(&self) {
        assert_eq!(self.phase.swap(2, Ordering::AcqRel), 1);
        self.changed.notify_waiters();
    }
    pub(super) fn uncertain(&self) {
        self.phase.store(3, Ordering::Release);
        self.changed.notify_waiters();
    }
}

impl Children {
    pub(super) fn new(maximum: usize) -> Result<Self, PlatformError> {
        let mut entries = Vec::new();
        entries
            .try_reserve_exact(maximum)
            .map_err(|_| failure("native-child-table-allocation"))?;
        Ok(Self {
            entries,
            pending: None,
            maximum,
        })
    }
}

impl StackContext {
    pub(crate) fn reserve_child(
        &self,
        continuation: RuntimeToken,
    ) -> Result<Arc<Child>, PlatformError> {
        let mut children = self
            .children
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        // A fixed shim starts the newly admitted thread immediately. At most
        // one unconsumed permit exists, so the allocator cannot assign a lease
        // to a different suspended child. Untrusted direct builtins stay closed.
        if children.pending.is_some() {
            return Err(failure("native-child-prestart-capacity"));
        }
        if children.entries.len() >= children.maximum {
            return Err(crate::containment::platform_error(
                PlatformErrorCode::ResourceExhausted,
                "native-child-metadata-capacity",
                false,
            ));
        }
        let owner = self
            .runtime
            .register(OwnerKind::Native, Some(continuation))?;
        let token = owner.token();
        let memory = self
            .budget
            .reserve_host_memory(self.mapped as u64)
            .map_err(|error| error.to_platform_error())?;
        let mut metadata = self
            .budget
            .reserve_host_memory((std::mem::size_of::<Child>() + 128) as u64)
            .map_err(|error| error.to_platform_error())?;
        metadata.confirm();
        let child = Arc::new(Child {
            token,
            runtime: self.runtime.clone(),
            phase: AtomicU32::new(0),
            changed: tokio::sync::Notify::new(),
            waiter: Mutex::new(None),
            _metadata: metadata,
        });
        children.pending = Some(Permit {
            _owner: owner,
            memory,
            child: Some(Arc::clone(&child)),
        });
        children.entries.push(Arc::clone(&child));
        Ok(child)
    }

    pub(crate) fn child(&self, token: RuntimeToken) -> Result<Arc<Child>, PlatformError> {
        self.children
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .entries
            .iter()
            .find(|child| child.token == token)
            .cloned()
            .ok_or_else(|| failure("native-child-token"))
    }

    pub(crate) fn reap_child(&self, token: RuntimeToken) -> Result<(), PlatformError> {
        let mut children = self
            .children
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let index = children
            .entries
            .iter()
            .position(|child| child.token == token)
            .ok_or_else(|| failure("native-child-token"))?;
        if !children.entries[index].physically_retired()
            || children.entries[index]
                .waiter
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .is_none()
        {
            return Err(failure("native-child-retirement-unproven"));
        }
        drop(children.entries.swap_remove(index));
        Ok(())
    }
}
