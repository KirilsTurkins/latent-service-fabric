//! Keep real original Arc/Weak storage charged through its final deallocation.
use super::{arc_bytes, NodeMetadataError, NodeMetadataOwner, NodeMetadataReservation};
use std::{
    marker::PhantomData,
    ops::Deref,
    sync::{Arc, Weak},
};

struct Charge(NodeMetadataReservation);

/// No Weak/raw billing Arc or guard can escape. Every final clone uses
/// into_inner, so the actual billing Arc is freed before its affine refund.
#[derive(Default)]
pub struct NodeMetadataLease(Option<Arc<Charge>>);

impl Clone for NodeMetadataLease {
    fn clone(&self) -> Self {
        Self(self.0.as_ref().map(Arc::clone))
    }
}

impl Drop for NodeMetadataLease {
    fn drop(&mut self) {
        if let Some(charge) = self.0.take() {
            drop(Arc::into_inner(charge));
        }
    }
}

impl NodeMetadataLease {
    #[must_use]
    pub fn reserved_bytes(&self) -> usize {
        self.0.as_ref().map_or(0, |charge| charge.0.bytes())
    }

    #[must_use]
    pub fn is_from_owner(&self, owner: &NodeMetadataOwner) -> bool {
        self.0
            .as_ref()
            .is_some_and(|charge| charge.0.is_from_owner(owner))
    }
}

// Field order is physical ownership: actual Arc/Weak before its lease. A weak
// retains only allocation/header capacity, never the original payload's life.
pub struct NodeMetadataArc<T> {
    inner: Arc<T>,
    lease: NodeMetadataLease,
}

pub struct NodeMetadataWeak<T> {
    inner: Weak<T>,
    lease: NodeMetadataLease,
}

pub struct NodeMetadataPreparation<T> {
    lease: NodeMetadataLease,
    payload: PhantomData<T>,
}

impl<T> NodeMetadataArc<T> {
    pub fn allocation_bytes(extra: usize) -> Result<usize, NodeMetadataError> {
        arc_bytes::<T>()?
            .checked_add(arc_bytes::<Charge>()?)
            .and_then(|bytes| bytes.checked_add(extra))
            .ok_or(NodeMetadataError::ArithmeticOverflow)
    }

    /// Reserve both actual Arc allocations and the separately checked owned
    /// payload envelope BEFORE building T or allocating its backing buffers.
    pub fn prepare(
        owner: &NodeMetadataOwner,
        extra: usize,
    ) -> Result<NodeMetadataPreparation<T>, NodeMetadataError> {
        Self::prepare_class(owner, extra, false)
    }
    pub fn prepare_fixed(
        owner: &NodeMetadataOwner,
        extra: usize,
    ) -> Result<NodeMetadataPreparation<T>, NodeMetadataError> {
        Self::prepare_class(owner, extra, true)
    }
    fn prepare_class(
        owner: &NodeMetadataOwner,
        extra: usize,
        fixed: bool,
    ) -> Result<NodeMetadataPreparation<T>, NodeMetadataError> {
        let bytes = Self::allocation_bytes(extra)?;
        let original = if fixed {
            owner.reserve_fixed(bytes)?
        } else {
            owner.reserve(bytes)?
        };
        Ok(NodeMetadataPreparation {
            lease: NodeMetadataLease(Some(Arc::new(Charge(original)))),
            payload: PhantomData,
        })
    }

    /// Legacy control-only path. It has no physical accounting claim and must
    /// never be selected by funded standalone journal/broker composition.
    #[must_use]
    pub fn unaccounted(value: T) -> Self {
        Self {
            inner: Arc::new(value),
            lease: NodeMetadataLease::default(),
        }
    }

    #[must_use]
    pub fn downgrade(&self) -> NodeMetadataWeak<T> {
        NodeMetadataWeak {
            inner: Arc::downgrade(&self.inner),
            lease: self.lease.clone(),
        }
    }

    #[must_use]
    pub fn is_unique(&self) -> bool {
        Arc::strong_count(&self.inner) == 1 && Arc::weak_count(&self.inner) == 0
    }
    #[must_use]
    pub fn ptr_eq(left: &Self, right: &Self) -> bool {
        Arc::ptr_eq(&left.inner, &right.inner)
    }

    #[must_use]
    pub fn lease(&self) -> NodeMetadataLease {
        self.lease.clone()
    }
}

impl<T> NodeMetadataPreparation<T> {
    #[must_use]
    pub fn lease(&self) -> NodeMetadataLease {
        self.lease.clone()
    }

    #[must_use]
    pub fn allocate(self, value: T) -> NodeMetadataArc<T> {
        NodeMetadataArc {
            inner: Arc::new(value),
            lease: self.lease,
        }
    }
}

impl<T> Clone for NodeMetadataArc<T> {
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
            lease: self.lease.clone(),
        }
    }
}

impl<T> Deref for NodeMetadataArc<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.inner
    }
}

impl<T> Clone for NodeMetadataWeak<T> {
    fn clone(&self) -> Self {
        Self {
            inner: Weak::clone(&self.inner),
            lease: self.lease.clone(),
        }
    }
}

impl<T> NodeMetadataWeak<T> {
    #[must_use]
    pub fn upgrade(&self) -> Option<NodeMetadataArc<T>> {
        Some(NodeMetadataArc {
            inner: self.inner.upgrade()?,
            lease: self.lease.clone(),
        })
    }
}
