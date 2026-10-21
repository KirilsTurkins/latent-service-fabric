//! Bounded error resources retain the actual typed host category, never text.
use super::{exports::wasi::io, latent::http::streaming as raw, quota::Slot};

pub struct HttpError {
    pub cause: raw::HttpError,
    pub _slot: Slot,
}

impl io::error::GuestError for HttpError {
    fn to_debug_string(&self) -> String {
        match self.cause {
            raw::HttpError::InvalidUrl => "latent-http-invalid-url",
            raw::HttpError::InvalidRequest => "latent-http-invalid-request",
            raw::HttpError::PermissionDenied => "latent-http-permission-denied",
            raw::HttpError::RequestTooLarge => "latent-http-request-too-large",
            raw::HttpError::ResponseTooLarge => "latent-http-response-too-large",
            raw::HttpError::DeadlineExceeded => "latent-http-deadline-exceeded",
            raw::HttpError::Cancelled => "latent-http-cancelled",
            raw::HttpError::BudgetExhausted => "latent-http-budget-exhausted",
            raw::HttpError::DnsFailed => "latent-http-dns-failed",
            raw::HttpError::TlsFailed => "latent-http-tls-failed",
            raw::HttpError::ConnectionFailed => "latent-http-connection-failed",
            raw::HttpError::Unavailable => "latent-http-unavailable",
            raw::HttpError::Uncertain => "latent-http-uncertain",
            raw::HttpError::InvalidState => "latent-http-invalid-state",
            raw::HttpError::UnexpectedEof => "latent-http-unexpected-eof",
            raw::HttpError::UnsupportedEncoding => "latent-http-unsupported-encoding",
        }
        .into()
    }
}
