use std::time::Duration;

use super::NATIVE_RESERVATION_METADATA_BYTES;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NativeAdmissionClass {
    Ordinary,
    Recovery,
}

impl NativeAdmissionClass {
    pub(super) const fn index(self) -> usize {
        match self {
            Self::Ordinary => 0,
            Self::Recovery => 1,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NativeBufferClass {
    Request,
    Work,
    Response,
}

impl NativeBufferClass {
    pub(super) const fn index(self) -> usize {
        match self {
            Self::Request => 0,
            Self::Work => 1,
            Self::Response => 2,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct NativeCapacityPartition {
    pub slots: usize,
    pub bytes: u64,
    pub maximum_reservation_bytes: u64,
}

#[derive(Debug, Clone, Copy)]
pub struct NativeCapacityLimits {
    pub ordinary: NativeCapacityPartition,
    pub recovery: NativeCapacityPartition,
    pub maximum_lifetime: Duration,
}

impl Default for NativeCapacityLimits {
    fn default() -> Self {
        Self {
            ordinary: NativeCapacityPartition {
                slots: 128,
                bytes: 256 * 1024 * 1024,
                maximum_reservation_bytes: 64 * 1024 * 1024,
            },
            recovery: NativeCapacityPartition {
                slots: 8,
                bytes: 32 * 1024 * 1024,
                maximum_reservation_bytes: 32 * 1024 * 1024,
            },
            maximum_lifetime: Duration::from_mins(3),
        }
    }
}

impl NativeCapacityLimits {
    pub(super) fn partition(self, class: NativeAdmissionClass) -> NativeCapacityPartition {
        match class {
            NativeAdmissionClass::Ordinary => self.ordinary,
            NativeAdmissionClass::Recovery => self.recovery,
        }
    }

    pub(super) fn validate(self) -> Result<(), NativeCapacityError> {
        if !(1..=1024).contains(&self.ordinary.slots)
            || !(1..=128).contains(&self.recovery.slots)
            || self.ordinary.bytes > 4 * 1024 * 1024 * 1024
            || self.recovery.bytes > 512 * 1024 * 1024
            || !(Duration::from_millis(1)..=Duration::from_hours(1))
                .contains(&self.maximum_lifetime)
            || [self.ordinary, self.recovery].into_iter().any(|partition| {
                partition.maximum_reservation_bytes < NATIVE_RESERVATION_METADATA_BYTES
                    || partition.maximum_reservation_bytes > partition.bytes
            })
        {
            return Err(NativeCapacityError::InvalidLimits);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Default)]
pub struct NativeReservationRequest {
    pub request_bytes: u64,
    pub work_bytes: u64,
    pub response_bytes: u64,
}

impl NativeReservationRequest {
    pub(super) fn payload_bytes(self) -> Result<u64, NativeCapacityError> {
        self.request_bytes
            .checked_add(self.work_bytes)
            .and_then(|bytes| bytes.checked_add(self.response_bytes))
            .ok_or(NativeCapacityError::InvalidRequest)
    }

    pub(super) const fn capacities(self) -> [u64; 3] {
        [self.request_bytes, self.work_bytes, self.response_bytes]
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NativeCapacityError {
    InvalidLimits,
    InvalidRequest,
    AdmissionClosed,
    Quarantined,
    DeadlineExceeded,
    DeadlineTooLong,
    ReservationTooLarge,
    SlotsFull,
    BytesFull,
    BufferLimit,
    BufferTooLarge,
    AllocationFailed,
    Poisoned,
    DrainWaiterBusy,
    Exhausted,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct NativePartitionSnapshot {
    pub slots: usize,
    pub bytes: u64,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct NativeCapacitySnapshot {
    pub ordinary: NativePartitionSnapshot,
    pub recovery: NativePartitionSnapshot,
    pub ordinary_admission_closed: bool,
    pub admission_closed: bool,
    pub quarantined: bool,
}

impl NativeCapacitySnapshot {
    #[must_use]
    pub const fn physically_retired(self) -> bool {
        self.ordinary.slots == 0
            && self.ordinary.bytes == 0
            && self.recovery.slots == 0
            && self.recovery.bytes == 0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NativeCapacityShutdown {
    pub clean: bool,
    pub snapshot: NativeCapacitySnapshot,
}
