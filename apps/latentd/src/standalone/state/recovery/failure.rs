use latent_state::{
    embedded::StoreError, protected_store::ProtectedStoreError, store_io::StoreIoError,
};
use serde::Serialize;

/// Finite producer-owned codes; no paths, error strings or record bytes.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase", tag = "owner", content = "reason")]
pub(super) enum Failure {
    Protected(&'static str),
    Storage(&'static str),
    Worker(&'static str),
}
impl From<ProtectedStoreError> for Failure {
    fn from(error: ProtectedStoreError) -> Self {
        match error {
            ProtectedStoreError::Store(error) => Self::from(error),
            ProtectedStoreError::Io(error) => Self::from(error),
            ProtectedStoreError::InvalidConfiguration => Self::Protected("invalidConfiguration"),
            ProtectedStoreError::UnsupportedPlatform => Self::Protected("unsupportedPlatform"),
            ProtectedStoreError::UnsupportedFilesystem => Self::Protected("unsupportedFilesystem"),
            ProtectedStoreError::UnsafeRoot => Self::Protected("unsafeRoot"),
            ProtectedStoreError::ForeignView => Self::Protected("foreignView"),
            ProtectedStoreError::CommitUncertain => Self::Protected("commitUncertain"),
        }
    }
}
impl From<StoreError> for Failure {
    fn from(error: StoreError) -> Self {
        Self::Storage(match error {
            StoreError::Invalid => "invalid",
            StoreError::Capacity => "capacity",
            StoreError::Conflict => "conflict",
            StoreError::Corrupt => "corrupt",
            StoreError::UnsupportedFormat => "unsupportedFormat",
            StoreError::Unavailable => "unavailable",
            StoreError::CommitUncertain => "commitUncertain",
            StoreError::SnapshotExpired => "snapshotExpired",
        })
    }
}
impl From<StoreIoError> for Failure {
    fn from(error: StoreIoError) -> Self {
        Self::Worker(match error {
            StoreIoError::InvalidLimits => "invalidLimits",
            StoreIoError::AdmissionClosed => "admissionClosed",
            StoreIoError::RecoveryUnavailable => "recoveryUnavailable",
            StoreIoError::QueueFull => "queueFull",
            StoreIoError::AcceptedFull => "acceptedFull",
            StoreIoError::ByteBudget => "byteBudget",
            StoreIoError::JobTooLarge => "jobTooLarge",
            StoreIoError::Exhausted => "exhausted",
            StoreIoError::Poisoned => "poisoned",
            StoreIoError::WorkerStartFailed => "workerStartFailed",
            StoreIoError::RecoveryRequired => "recoveryRequired",
            StoreIoError::InitializationFailed => "initializationFailed",
            StoreIoError::NotStarted => "notStarted",
            StoreIoError::FinalizationFailed => "finalizationFailed",
            StoreIoError::DrainWaiterBusy => "drainWaiterBusy",
            StoreIoError::AlreadyDelivered => "alreadyDelivered",
        })
    }
}
