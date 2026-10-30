//! The original node metadata allowance, shared by its journal and broker.
//!
//! This is heap admission only. It cannot authorize execution, extend an
//! activation or pay for an operating-system worker stack. The bootstrap bank
//! is one finite node infrastructure object; consumers share its exact owner,
//! never a second allowance reconstructed from a name or matching limit.
mod shared;
pub use shared::{NodeMetadataArc, NodeMetadataLease, NodeMetadataPreparation, NodeMetadataWeak};

use std::{
    alloc::Layout,
    sync::{
        atomic::{AtomicU64, AtomicUsize, Ordering},
        Arc,
    },
};

const ALLOCATION_BOOKKEEPING: usize = 64;
pub const MAXIMUM_NODE_METADATA_BYTES: usize = 256 * 1024 * 1024;
const _: () = assert!(MAXIMUM_NODE_METADATA_BYTES <= u32::MAX as usize);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NodeMetadataError {
    InvalidCapacity,
    ArithmeticOverflow,
    Exhausted,
    Busy,
}

#[derive(Debug)]
struct Bank {
    maximum: usize,
    usage: AtomicU64,
}

/// Clones share one original allowance. No Weak or raw Arc can escape.
#[derive(Clone, Debug)]
pub struct NodeMetadataOwner(Arc<Bank>);

/// Affine admission. Keep this after every physical allocation it pays for.
#[derive(Debug)]
pub struct NodeMetadataReservation {
    owner: NodeMetadataOwner,
    bytes: usize,
    fixed: bool,
}

fn arc_bytes<T>() -> Result<usize, NodeMetadataError> {
    // The pinned Rust ArcInner is repr(C): strong/weak AtomicUsize then T.
    Layout::new::<[AtomicUsize; 2]>()
        .extend(Layout::new::<T>())
        .map_err(|_| NodeMetadataError::ArithmeticOverflow)?
        .0
        .pad_to_align()
        .size()
        .checked_add(ALLOCATION_BOOKKEEPING)
        .ok_or(NodeMetadataError::ArithmeticOverflow)
}

/// Coherent observations from the original node bank. Only total occupancy is
/// an admission quantity; fixed/transient are conserved descriptive subsets.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NodeMetadataSnapshot {
    pub maximum_bytes: usize,
    pub reserved_bytes: usize,
    pub fixed_reserved_bytes: usize,
    pub transient_reserved_bytes: usize,
}
fn packed(total: usize, fixed: usize) -> u64 {
    total as u64 | ((fixed as u64) << 32)
}
fn unpack(usage: u64) -> (usize, usize) {
    (
        (usage & u64::from(u32::MAX)) as usize,
        (usage >> 32) as usize,
    )
}

impl NodeMetadataOwner {
    /// Admit the fixed bootstrap bank before allocating its real Arc. The same
    /// ceiling subsequently governs all journal and broker metadata owners.
    pub fn new(maximum: usize) -> Result<Self, NodeMetadataError> {
        let base = Self::bootstrap_bytes()?;
        if maximum < base || maximum > MAXIMUM_NODE_METADATA_BYTES {
            return Err(NodeMetadataError::InvalidCapacity);
        }
        Ok(Self(Arc::new(Bank {
            maximum,
            usage: AtomicU64::new(packed(base, base)),
        })))
    }

    pub fn bootstrap_bytes() -> Result<usize, NodeMetadataError> {
        arc_bytes::<Bank>()
    }

    #[must_use]
    pub fn maximum_bytes(&self) -> usize {
        self.0.maximum
    }

    /// Includes the fixed bank while that physical node owner is alive.
    #[must_use]
    pub fn occupied_bytes(&self) -> usize {
        self.snapshot().reserved_bytes
    }

    #[must_use]
    pub fn same_owner(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.0, &other.0)
    }

    #[must_use]
    pub fn snapshot(&self) -> NodeMetadataSnapshot {
        let (total, fixed) = unpack(self.0.usage.load(Ordering::Acquire));
        NodeMetadataSnapshot {
            maximum_bytes: self.maximum_bytes(),
            reserved_bytes: total,
            fixed_reserved_bytes: fixed,
            transient_reserved_bytes: total - fixed,
        }
    }
    pub fn reserve(&self, bytes: usize) -> Result<NodeMetadataReservation, NodeMetadataError> {
        self.reserve_class(bytes, false)
    }
    /// Same original allowance, classified as persistent node backing only for
    /// observation. This cannot grant capacity separately from the total bank.
    pub fn reserve_fixed(
        &self,
        bytes: usize,
    ) -> Result<NodeMetadataReservation, NodeMetadataError> {
        self.reserve_class(bytes, true)
    }
    fn reserve_class(
        &self,
        bytes: usize,
        fixed: bool,
    ) -> Result<NodeMetadataReservation, NodeMetadataError> {
        let mut usage = self.0.usage.load(Ordering::Acquire);
        for _ in 0..16 {
            let (occupied, fixed_bytes) = unpack(usage);
            let next = occupied
                .checked_add(bytes)
                .ok_or(NodeMetadataError::ArithmeticOverflow)?;
            if next > self.maximum_bytes() {
                return Err(NodeMetadataError::Exhausted);
            }
            let next_fixed = if fixed {
                fixed_bytes
                    .checked_add(bytes)
                    .ok_or(NodeMetadataError::ArithmeticOverflow)?
            } else {
                fixed_bytes
            };
            match self.0.usage.compare_exchange_weak(
                usage,
                packed(next, next_fixed),
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    return Ok(NodeMetadataReservation {
                        owner: self.clone(),
                        bytes,
                        fixed,
                    })
                }
                Err(actual) => usage = actual,
            }
        }
        Err(NodeMetadataError::Busy)
    }
}

impl NodeMetadataReservation {
    #[must_use]
    pub fn bytes(&self) -> usize {
        self.bytes
    }

    #[must_use]
    pub fn is_from_owner(&self, owner: &NodeMetadataOwner) -> bool {
        self.owner.same_owner(owner)
    }
}

impl Drop for NodeMetadataReservation {
    fn drop(&mut self) {
        self.owner.0.usage.fetch_sub(
            packed(self.bytes, if self.fixed { self.bytes } else { 0 }),
            Ordering::AcqRel,
        );
    }
}

#[cfg(test)]
mod tests;
