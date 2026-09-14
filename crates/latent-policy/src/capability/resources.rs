use latent_core::PlatformError;
use serde::{Deserialize, Serialize};

use super::{identifier, invalid, publication, unique};

/// Per-operation ceilings, intersected with each independent grant and the
/// invocation's remaining allowance. This data does not reserve that allowance.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CapabilityCeiling {
    pub operations: u32,
    pub input_bytes: u64,
    pub output_bytes: u64,
    pub wall_time_millis: u64,
}

impl CapabilityCeiling {
    pub fn validate(self) -> Result<(), PlatformError> {
        if self.operations > 1_000_000
            || self.input_bytes > 64 * 1024 * 1024
            || self.output_bytes > 64 * 1024 * 1024
            || self.wall_time_millis > 300_000
        {
            return Err(invalid());
        }
        Ok(())
    }

    #[must_use]
    pub fn intersect(self, other: Self) -> Self {
        Self {
            operations: self.operations.min(other.operations),
            input_bytes: self.input_bytes.min(other.input_bytes),
            output_bytes: self.output_bytes.min(other.output_bytes),
            wall_time_millis: self.wall_time_millis.min(other.wall_time_millis),
        }
    }
}

/// Explicit normalized origin facts. The provider must derive these from the
/// actual request URL and apply its own separately approved transport authority.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HttpOrigin {
    pub scheme: String,
    pub host: String,
    pub port: u16,
}

impl HttpOrigin {
    fn valid(&self) -> bool {
        if !matches!(self.scheme.as_str(), "http" | "https")
            || self.port == 0
            || self.host.is_empty()
            || self.host.len() > 253
        {
            return false;
        }
        if let Ok(address) = self.host.parse::<std::net::IpAddr>() {
            return address.to_string() == self.host;
        }
        self.host.split('.').all(|label| {
            !label.is_empty()
                && label.len() <= 63
                && label.as_bytes()[0].is_ascii_alphanumeric()
                && label.as_bytes()[label.len() - 1].is_ascii_alphanumeric()
                && label
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
        })
    }
}

/// Closed, typed resource scopes. Empty allow-sets match nothing. A missing
/// additional grant constraint is represented outside this required rule type.
#[derive(Debug, Deserialize, Serialize)]
#[serde(
    tag = "kind",
    rename_all = "kebab-case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum ResourceConstraint {
    Context,
    Clock,
    Random,
    Log {
        levels: Vec<String>,
    },
    Http {
        origins: Vec<HttpOrigin>,
        methods: Vec<String>,
        paths: Vec<String>,
        path_prefixes: Vec<String>,
    },
    Blob {
        namespaces: Vec<String>,
    },
    Secrets {
        references: Vec<String>,
    },
    Events {
        subjects: Vec<String>,
    },
    Telemetry {
        names: Vec<String>,
    },
    Service {
        services: Vec<String>,
        publications: Vec<String>,
    },
}

/// A normalized host-side operation target. Guest labels are not evidence that
/// a provider will perform its I/O against this target.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResourceTarget<'a> {
    Context,
    Clock,
    Random,
    Log {
        level: &'a str,
    },
    Http {
        origin: &'a HttpOrigin,
        method: &'a str,
        path: &'a str,
    },
    Blob {
        namespace: &'a str,
    },
    Secrets {
        reference: &'a str,
    },
    Events {
        subject: &'a str,
    },
    Telemetry {
        name: &'a str,
    },
    Service {
        service: &'a str,
        publication: &'a str,
    },
}

impl ResourceTarget<'_> {
    pub(super) fn valid(&self) -> bool {
        match self {
            Self::Context | Self::Clock | Self::Random => true,
            Self::Log { level } => log_level(level),
            Self::Http {
                origin,
                method,
                path,
            } => origin.valid() && http_method(method) && http_path(path),
            Self::Blob { namespace } => identifier(namespace),
            Self::Secrets { reference } => identifier(reference),
            Self::Events { subject } => subject_name(subject),
            Self::Telemetry { name } => identifier(name),
            Self::Service {
                service,
                publication: id,
            } => identifier(service) && publication(id),
        }
    }
}

impl ResourceConstraint {
    pub fn validate(&self) -> Result<(), PlatformError> {
        let valid = match self {
            Self::Context | Self::Clock | Self::Random => true,
            Self::Log { levels } => unique(levels, |value| log_level(value)),
            Self::Http {
                origins,
                methods,
                paths,
                path_prefixes,
            } => {
                unique(origins, HttpOrigin::valid)
                    && unique(methods, |value| http_method(value))
                    && unique(paths, |value| http_path(value))
                    && unique(path_prefixes, |value| {
                        http_path(value) && value.ends_with('/')
                    })
            }
            Self::Blob { namespaces } => unique(namespaces, |value| identifier(value)),
            Self::Secrets { references } => unique(references, |value| identifier(value)),
            Self::Events { subjects } => unique(subjects, |value| subject_name(value)),
            Self::Telemetry { names } => unique(names, |value| identifier(value)),
            Self::Service {
                services,
                publications,
            } => {
                unique(services, |value| identifier(value))
                    && unique(publications, |value| publication(value))
            }
        };
        if valid {
            Ok(())
        } else {
            Err(invalid())
        }
    }

    pub(super) fn compatible(&self, contract: &str) -> bool {
        matches!(
            (self, contract),
            (Self::Context, "latent:context/context@0.1.0")
                | (
                    Self::Clock,
                    "latent:clock/monotonic@0.1.0" | "latent:clock/wall@0.1.0"
                )
                | (Self::Random, "latent:random/random@0.1.0")
                | (Self::Log { .. }, "latent:log/log@0.1.0")
                | (
                    Self::Http { .. },
                    "latent:http/client@0.2.0" | "latent:http/streaming@0.3.0"
                )
                | (
                    Self::Blob { .. },
                    "latent:blob/blob@0.1.0" | "latent:blob/blob@0.2.0"
                )
                | (Self::Secrets { .. }, "latent:secrets/reader@0.1.0")
                | (Self::Events { .. }, "latent:events/publisher@0.2.0")
                | (Self::Telemetry { .. }, "latent:telemetry/custom@0.1.0")
                | (Self::Service { .. }, "latent:service/invoke@0.1.0")
        )
    }

    pub(super) fn covers(&self, target: &ResourceTarget<'_>) -> bool {
        if !target.valid() {
            return false;
        }
        match (self, target) {
            (Self::Context, ResourceTarget::Context)
            | (Self::Clock, ResourceTarget::Clock)
            | (Self::Random, ResourceTarget::Random) => true,
            (Self::Log { levels }, ResourceTarget::Log { level }) => contains(levels, level),
            (
                Self::Http {
                    origins,
                    methods,
                    paths,
                    path_prefixes,
                },
                ResourceTarget::Http {
                    origin,
                    method,
                    path,
                },
            ) => {
                origins.contains(origin)
                    && contains(methods, method)
                    && (contains(paths, path)
                        || path_prefixes.iter().any(|prefix| path.starts_with(prefix)))
            }
            (Self::Blob { namespaces }, ResourceTarget::Blob { namespace }) => {
                contains(namespaces, namespace)
            }
            (Self::Secrets { references }, ResourceTarget::Secrets { reference }) => {
                contains(references, reference)
            }
            (Self::Events { subjects }, ResourceTarget::Events { subject }) => {
                contains(subjects, subject)
            }
            (Self::Telemetry { names }, ResourceTarget::Telemetry { name }) => {
                contains(names, name)
            }
            (
                Self::Service {
                    services,
                    publications,
                },
                ResourceTarget::Service {
                    service,
                    publication,
                },
            ) => contains(services, service) && contains(publications, publication),
            _ => false,
        }
    }
}

fn contains(values: &[String], requested: &str) -> bool {
    values.iter().any(|value| value == requested)
}
fn log_level(value: &str) -> bool {
    matches!(value, "trace" | "debug" | "info" | "warn" | "error")
}
fn http_method(value: &str) -> bool {
    matches!(
        value,
        "GET" | "HEAD" | "POST" | "PUT" | "PATCH" | "DELETE" | "OPTIONS"
    )
}
fn subject_name(value: &str) -> bool {
    identifier(value) && value.split('.').all(|part| !part.is_empty())
}
fn http_path(value: &str) -> bool {
    value.starts_with('/')
        && value.len() <= 2048
        && value.is_ascii()
        && !value
            .bytes()
            .any(|byte| byte <= b' ' || byte == 0x7f || b"%\\?#".contains(&byte))
        && !value
            .split('/')
            .any(|segment| matches!(segment, "." | ".."))
}
