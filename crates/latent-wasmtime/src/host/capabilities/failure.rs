//! Only closed, validated capability diagnostics survive the original error.
use latent_core::{error::ADMISSION_CURRENTNESS_REASONS, PlatformError, PlatformErrorCode};

#[derive(Debug)]
pub(crate) struct HostCapabilityFailure {
    code: PlatformErrorCode,
    currentness_reason: Option<&'static str>,
}

impl HostCapabilityFailure {
    pub(crate) fn from_error(error: &PlatformError) -> Self {
        Self {
            code: error.code,
            currentness_reason: currentness_reason(error),
        }
    }

    pub(crate) fn code(&self) -> PlatformErrorCode {
        self.code
    }

    pub(crate) fn currentness_reason(&self) -> Option<&'static str> {
        self.currentness_reason
    }
}

impl std::fmt::Display for HostCapabilityFailure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "capability admission: {:?}", self.code)
    }
}
impl std::error::Error for HostCapabilityFailure {}

pub(crate) fn host_error(error: PlatformError) -> wasmtime::Error {
    let failure = HostCapabilityFailure::from_error(&error);
    // Never retain the original message, policy, token, provider location or
    // arbitrary detail. The optional reason points into a fixed closed list.
    drop(error);
    wasmtime::Error::new(failure)
}

fn currentness_reason(error: &PlatformError) -> Option<&'static str> {
    let [detail] = error.details.as_slice() else {
        return None;
    };
    if detail.kind != "admission.currentness" || detail.fields.len() != 1 {
        return None;
    }
    let supplied = detail.fields.get("reason")?;
    let reason = ADMISSION_CURRENTNESS_REASONS
        .iter()
        .copied()
        .find(|known| *known == supplied)?;
    let signature = matches!(
        reason,
        "signature-clock-regression" | "signature-trust-conflict" | "signature-stale-proof"
    );
    let expected = if signature {
        (PlatformErrorCode::StateConflict, false)
    } else {
        (PlatformErrorCode::Unavailable, true)
    };
    ((error.code, error.retryable) == expected).then_some(reason)
}

#[cfg(test)]
mod tests;
