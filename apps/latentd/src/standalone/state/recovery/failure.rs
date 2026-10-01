use latent_effects::{
    authority::AuthorityError, dispatch_store::DispatchStoreError, runtime::DispatcherError,
};
use latent_state::{
    embedded::StoreError, protected_store::ProtectedStoreError, store_io::StoreIoError,
};
use serde::Serialize;

/// Finite producer-owned codes; no paths, error strings or record bytes.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase", tag = "owner", content = "reason")]
pub(in crate::standalone) enum Failure {
    Platform(&'static str),
    Dispatcher(&'static str),
    Authority(&'static str),
    Protected(&'static str),
    Storage(&'static str),
    Worker(&'static str),
}
impl From<&latent_core::PlatformError> for Failure {
    fn from(error: &latent_core::PlatformError) -> Self {
        Self::Platform(error.code.wire_code())
    }
}
impl From<DispatcherError> for Failure {
    fn from(error: DispatcherError) -> Self {
        match error {
            DispatcherError::InvalidConfiguration => Self::Dispatcher("invalidConfiguration"),
            DispatcherError::UnsupportedOrdering => Self::Dispatcher("unsupportedOrdering"),
            DispatcherError::InvalidAdapter => Self::Dispatcher("invalidAdapter"),
            DispatcherError::CheckpointRequired => Self::Dispatcher("checkpointRequired"),
            DispatcherError::AdmissionClosed => Self::Dispatcher("admissionClosed"),
            DispatcherError::Authority(error) => Self::from(error),
            DispatcherError::Store(error) => Self::from(error),
            DispatcherError::ProtectedStore(error) => Self::from(error),
            DispatcherError::Worker(error) => Self::from(error),
        }
    }
}
impl From<DispatchStoreError> for Failure {
    fn from(error: DispatchStoreError) -> Self {
        match error {
            DispatchStoreError::Storage(error) => Self::from(error),
            DispatchStoreError::Authority(error) => Self::from(error),
            DispatchStoreError::StaleEpoch => Self::Dispatcher("staleEpoch"),
        }
    }
}
impl From<AuthorityError> for Failure {
    fn from(error: AuthorityError) -> Self {
        Self::Authority(match error {
            AuthorityError::Invalid => "invalid",
            AuthorityError::Capacity => "capacity",
            AuthorityError::PolicyBlocked => "policyBlocked",
            AuthorityError::UnsupportedFormat => "unsupportedFormat",
            AuthorityError::Expired => "expired",
            AuthorityError::ClockDiscontinuity => "clockDiscontinuity",
            AuthorityError::Stale => "stale",
            AuthorityError::Unavailable => "unavailable",
        })
    }
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
