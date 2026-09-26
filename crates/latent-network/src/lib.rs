#![forbid(unsafe_code)]

mod address;
pub mod dns;

pub use address::{canonical, AddressPolicy};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NetworkError {
    InvalidConfiguration,
    PermissionDenied,
    DnsFailed,
    DeadlineExceeded,
    ResourceExhausted,
    Closed,
}

impl std::fmt::Display for NetworkError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::InvalidConfiguration => "network-configuration-invalid",
            Self::PermissionDenied => "network-destination-denied",
            Self::DnsFailed => "network-resolution-failed",
            Self::DeadlineExceeded => "network-deadline-exceeded",
            Self::ResourceExhausted => "network-capacity-exhausted",
            Self::Closed => "network-owner-closed",
        })
    }
}

impl std::error::Error for NetworkError {}
