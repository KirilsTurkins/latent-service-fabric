use crate::CellClass;
use latent_core::{ActivationId, ErrorDetail, Metadata, PlatformError, PlatformErrorCode};
use std::time::{SystemTime, UNIX_EPOCH};

pub(super) trait WallClock: Send + Sync {
    fn now_unix_millis(&self) -> u64;
}

#[derive(Debug, Default)]
pub(super) struct SystemWallClock;

impl WallClock for SystemWallClock {
    fn now_unix_millis(&self) -> u64 {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        u64::try_from(millis).unwrap_or(u64::MAX)
    }
}

pub(super) fn len_u32(length: usize) -> u32 {
    u32::try_from(length).expect("pool collection length is bounded by u32 configuration")
}

pub(super) fn sequence_exhausted() -> PlatformError {
    pool_error(
        PlatformErrorCode::Internal,
        "cell-pool identifier sequence exhausted",
        false,
        "cell-pool.sequence-exhausted",
        [("scope", "phase0")],
    )
}

pub(super) fn all_quarantined_error(
    activation_id: &ActivationId,
    quarantined: usize,
) -> PlatformError {
    pool_error(
        PlatformErrorCode::Unavailable,
        "all configured cells are quarantined",
        true,
        "cell-pool.all-quarantined",
        [
            ("activation_id", activation_id.0.clone()),
            ("quarantined", quarantined.to_string()),
        ],
    )
}

pub(super) fn deadline_error(activation_id: &ActivationId, deadline: u64) -> PlatformError {
    pool_error(
        PlatformErrorCode::DeadlineExceeded,
        "cell acquisition deadline expired while waiting",
        false,
        "cell-pool.deadline-exceeded",
        [
            ("activation_id", activation_id.0.clone()),
            ("deadline_unix_millis", deadline.to_string()),
        ],
    )
}

pub(super) fn cancelled_error(activation_id: &ActivationId) -> PlatformError {
    pool_error(
        PlatformErrorCode::Cancelled,
        "cell acquisition was cancelled while waiting",
        false,
        "cell-pool.waiter-cancelled",
        [("activation_id", activation_id.0.clone())],
    )
}

pub(super) fn pool_error<I, K, V>(
    code: PlatformErrorCode,
    message: impl Into<String>,
    retryable: bool,
    kind: &str,
    fields: I,
) -> PlatformError
where
    I: IntoIterator<Item = (K, V)>,
    K: Into<String>,
    V: Into<String>,
{
    let fields: Metadata = fields
        .into_iter()
        .map(|(key, value)| (key.into(), value.into()))
        .collect();
    PlatformError {
        code,
        message: message.into(),
        retryable,
        details: vec![ErrorDetail {
            kind: kind.to_owned(),
            fields,
        }],
    }
}

pub(super) fn cell_class_name(class: CellClass) -> &'static str {
    match class {
        CellClass::Tiny => "tiny",
        CellClass::Small => "small",
        CellClass::Standard => "standard",
        CellClass::Large => "large",
        CellClass::ExtraLarge => "extra-large",
    }
}
