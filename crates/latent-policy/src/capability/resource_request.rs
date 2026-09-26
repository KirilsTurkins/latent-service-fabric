use super::{invalid, HttpOrigin, ResourceTarget};
use latent_core::PlatformError;
use serde::{Deserialize, Serialize};

/// Closed descriptive explanation input. A provider must instead derive the
/// corresponding target from its actual operation, never trust this JSON as
/// proof of destination, configuration authority or a live capability handle.
#[derive(Debug, Deserialize, Serialize)]
#[serde(
    tag = "kind",
    rename_all = "kebab-case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum ResourceRequest {
    Context,
    Clock,
    Random,
    Log {
        level: String,
    },
    Http {
        origin: HttpOrigin,
        method: String,
        path: String,
    },
    Blob {
        namespace: String,
    },
    Secrets {
        reference: String,
    },
    Events {
        subject: String,
    },
    Telemetry {
        name: String,
    },
    Service {
        service: String,
        publication: String,
    },
}
impl ResourceRequest {
    pub fn parse(bytes: &[u8]) -> Result<Self, PlatformError> {
        if bytes.len() > 4096 {
            return Err(invalid());
        }
        super::preflight(bytes)?;
        let value: Self = serde_json::from_slice(bytes).map_err(|_| invalid())?;
        if !value.target().valid() {
            return Err(invalid());
        }
        Ok(value)
    }
    #[must_use]
    pub fn target(&self) -> ResourceTarget<'_> {
        match self {
            Self::Context => ResourceTarget::Context,
            Self::Clock => ResourceTarget::Clock,
            Self::Random => ResourceTarget::Random,
            Self::Log { level } => ResourceTarget::Log { level },
            Self::Http {
                origin,
                method,
                path,
            } => ResourceTarget::Http {
                origin,
                method,
                path,
            },
            Self::Blob { namespace } => ResourceTarget::Blob { namespace },
            Self::Secrets { reference } => ResourceTarget::Secrets { reference },
            Self::Events { subject } => ResourceTarget::Events { subject },
            Self::Telemetry { name } => ResourceTarget::Telemetry { name },
            Self::Service {
                service,
                publication,
            } => ResourceTarget::Service {
                service,
                publication,
            },
        }
    }
}
