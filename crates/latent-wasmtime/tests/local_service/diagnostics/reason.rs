//! Closed diagnostic vocabulary derived from the existing private constructors.
use latent_core::{PlatformError, PlatformErrorCode};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reason {
    AdmissionAuthorityBusy,
    AdmissionAuthorityPoisoned,
    AdmissionControlBusy,
    AdmissionClockLeaseUncovered,
    AdmissionClockRegression,
    AdmissionDurabilityUncertain,
    AdmissionOwnerRetired,
    AdmissionRestartClockFloor,
    AdmissionVerificationBusy,
    SignatureClockRegression,
    SignatureTrustConflict,
    SignatureStaleProof,
    SchedulerShutdown,
    SchedulerHandoffClosed,
    SchedulerSequenceExhausted,
    SchedulerAllCellsQuarantined,
    QuotaStateUnavailable,
    PreparationReadyCapacity,
    PreparationReadyBytes,
    CompilerStopping,
    CompilerWaiterCapacity,
    CompilerGenerationAbandoned,
    CompilerWaiterGenerationExhausted,
    CompilerJobCapacity,
    CompilerQueueCapacity,
    CompilerJobGenerationExhausted,
    CompilerDocumentCapacity,
    CompilerJobNoLongerPending,
    CompilerDocumentAlreadyReserved,
    CompilerCreatorAbandoned,
    CompilerJobPanicked,
    CompilerJobAbandoned,
    ReleaseLifecycleBusy,
    ReleaseLifecycleUnavailable,
    AdmissionRepositoryRetired,
    Unclassified,
}

pub(super) fn classify(error: &PlatformError) -> Reason {
    // Exact shapes only: never scan, clone, format, or retain arbitrary details.
    // New or malformed details remain an explicit unclassified observation.
    let [detail] = error.details.as_slice() else {
        return if error.details.is_empty() {
            empty_detail_reason(error)
        } else {
            Reason::Unclassified
        };
    };
    let Some(reason) = detail.fields.get("reason").map(String::as_str) else {
        return Reason::Unclassified;
    };
    match (detail.kind.as_str(), detail.fields.len()) {
        ("admission.currentness", 1) if currentness_shape(error, reason) => match reason {
            "admission-authority-busy" => Reason::AdmissionAuthorityBusy,
            "admission-authority-poisoned" => Reason::AdmissionAuthorityPoisoned,
            "admission-control-busy" => Reason::AdmissionControlBusy,
            "admission-clock-lease-uncovered" => Reason::AdmissionClockLeaseUncovered,
            "admission-clock-regression" => Reason::AdmissionClockRegression,
            "admission-durability-uncertain" => Reason::AdmissionDurabilityUncertain,
            "admission-owner-retired" => Reason::AdmissionOwnerRetired,
            "admission-restart-clock-floor" => Reason::AdmissionRestartClockFloor,
            "admission-verification-busy" => Reason::AdmissionVerificationBusy,
            "signature-clock-regression" => Reason::SignatureClockRegression,
            "signature-trust-conflict" => Reason::SignatureTrustConflict,
            "signature-stale-proof" => Reason::SignatureStaleProof,
            _ => Reason::Unclassified,
        },
        ("scheduler.limit", 1)
            if error.code == PlatformErrorCode::Unavailable && error.retryable =>
        {
            match reason {
                "shutdown" => Reason::SchedulerShutdown,
                "handoff-closed" => Reason::SchedulerHandoffClosed,
                "sequence-exhausted" => Reason::SchedulerSequenceExhausted,
                "all-cells-quarantined" => Reason::SchedulerAllCellsQuarantined,
                _ => Reason::Unclassified,
            }
        }
        ("admission.limit", 3)
            if error.code == PlatformErrorCode::Unavailable
                && error.retryable
                && reason == "quota-state-unavailable"
                && detail.fields.get("scope").map(String::as_str) == Some("node")
                && detail.fields.get("dimension").map(String::as_str) == Some("quota") =>
        {
            Reason::QuotaStateUnavailable
        }
        _ => Reason::Unclassified,
    }
}

fn currentness_shape(error: &PlatformError, reason: &str) -> bool {
    // SupplyChainAuthority::unavailable and SignatureError::into use different
    // codes/retryability, even though they share this structured detail kind.
    let signature = matches!(
        reason,
        "signature-clock-regression" | "signature-trust-conflict" | "signature-stale-proof"
    );
    if signature {
        error.code == PlatformErrorCode::StateConflict && !error.retryable
    } else {
        error.code == PlatformErrorCode::Unavailable && error.retryable
    }
}

fn empty_detail_reason(error: &PlatformError) -> Reason {
    if error.code != PlatformErrorCode::Unavailable {
        return Reason::Unclassified;
    }
    // The compiler and lifecycle constructors currently have no structured
    // details. Match complete known tokens, never a prefix or substring.
    match (error.message.as_str(), error.retryable) {
        ("preparation-ready-capacity", true) => Reason::PreparationReadyCapacity,
        ("preparation-ready-bytes", true) => Reason::PreparationReadyBytes,
        ("compiler-stopping", true) => Reason::CompilerStopping,
        ("compiler-waiter-capacity", true) => Reason::CompilerWaiterCapacity,
        ("compiler-generation-abandoned", true) => Reason::CompilerGenerationAbandoned,
        ("compiler-waiter-generation-exhausted", true) => Reason::CompilerWaiterGenerationExhausted,
        ("compiler-job-capacity", true) => Reason::CompilerJobCapacity,
        ("compiler-queue-capacity", true) => Reason::CompilerQueueCapacity,
        ("compiler-job-generation-exhausted", true) => Reason::CompilerJobGenerationExhausted,
        ("compiler-document-capacity", true) => Reason::CompilerDocumentCapacity,
        ("compiler-job-no-longer-pending", true) => Reason::CompilerJobNoLongerPending,
        ("compiler-document-already-reserved", true) => Reason::CompilerDocumentAlreadyReserved,
        ("compiler-creator-abandoned", true) => Reason::CompilerCreatorAbandoned,
        ("compiler-job-panicked", true) => Reason::CompilerJobPanicked,
        ("compiler-job-abandoned", true) => Reason::CompilerJobAbandoned,
        ("release-lifecycle-busy", true) => Reason::ReleaseLifecycleBusy,
        ("release-lifecycle-unavailable", false) => Reason::ReleaseLifecycleUnavailable,
        ("admission-repository-retired", false) => Reason::AdmissionRepositoryRetired,
        _ => Reason::Unclassified,
    }
}
