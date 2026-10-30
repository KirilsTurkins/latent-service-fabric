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
        canonical_host(&self.host)
    }
}

// The pinned IpAddr Display emits at most eight four-digit hex groups and
// seven colons. IPv4 and IPv4-mapped forms are shorter (15 and 22 bytes).
struct CanonicalIpText {
    bytes: [u8; 39],
    used: usize,
}

impl CanonicalIpText {
    fn new() -> Self {
        Self {
            bytes: [0; 39],
            used: 0,
        }
    }

    fn as_bytes(&self) -> &[u8] {
        &self.bytes[..self.used]
    }
}

impl std::fmt::Write for CanonicalIpText {
    fn write_str(&mut self, value: &str) -> std::fmt::Result {
        let end = self.used.checked_add(value.len()).ok_or(std::fmt::Error)?;
        let destination = self.bytes.get_mut(self.used..end).ok_or(std::fmt::Error)?;
        destination.copy_from_slice(value.as_bytes());
        self.used = end;
        Ok(())
    }
}

fn canonical_host(host: &str) -> bool {
    if host.is_empty() || host.len() > 253 {
        return false;
    }
    if let Ok(address) = host.parse::<std::net::IpAddr>() {
        let mut text = CanonicalIpText::new();
        return std::fmt::write(&mut text, format_args!("{address}")).is_ok()
            && text.as_bytes() == host.as_bytes();
    }
    host.split('.').all(|label| {
        !label.is_empty()
            && label.len() <= 63
            && label.as_bytes()[0].is_ascii_alphanumeric()
            && label.as_bytes()[label.len() - 1].is_ascii_alphanumeric()
            && label
                .bytes()
                .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
    })
}

/// Opaque bytes need their own endpoint authority. Neither transport authorizes
/// an HTTP method/path or asserts the protocol carried by the guest's bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum StreamTransport {
    Tcp,
    HostTls,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StreamEndpoint {
    pub host: String,
    pub port: u16,
    pub transport: StreamTransport,
}

impl StreamEndpoint {
    pub fn validate(&self) -> Result<(), PlatformError> {
        if self.port == 0
            || !canonical_host(&self.host)
            || (self.host.parse::<std::net::IpAddr>().is_err()
                && (self
                    .host
                    .rsplit('.')
                    .next()
                    .is_some_and(|label| label.bytes().all(|byte| byte.is_ascii_digit()))
                    || self.host.strip_prefix("0x").is_some_and(|suffix| {
                        !suffix.is_empty() && suffix.bytes().all(|byte| byte.is_ascii_hexdigit())
                    })))
            || matches!(self.host.parse::<std::net::IpAddr>(), Ok(std::net::IpAddr::V6(value)) if value.to_ipv4_mapped().is_some())
        {
            return Err(invalid());
        }
        Ok(())
    }
}

/// Host-approved recovery domain; guest claims cannot widen it to shared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum RecoveryScopeKind {
    OriginalCaller,
    ServiceIntegration,
    Delegated,
    Shared,
}

/// Exact tuples avoid synthesizing a cross-product of unrelated grants.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StateResourceScope {
    pub namespace: String,
    pub incarnation: u64,
    #[serde(deserialize_with = "explicit_entity")]
    pub entity: Option<String>,
    pub recovery_kind: RecoveryScopeKind,
    pub recovery_scope: String,
    pub result_policy: String,
}
impl StateResourceScope {
    fn valid(&self) -> bool {
        state_identifier(&self.namespace)
            && self.incarnation != 0
            && self
                .entity
                .as_ref()
                .is_none_or(|value| state_identifier(value))
            && identifier(&self.recovery_scope)
            && identifier(&self.result_policy)
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
    Stream {
        endpoints: Vec<StreamEndpoint>,
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
    State {
        scopes: Vec<StateResourceScope>,
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
    Stream {
        endpoint: &'a StreamEndpoint,
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
    State {
        namespace: &'a str,
        incarnation: u64,
        entity: Option<&'a str>,
        recovery_kind: RecoveryScopeKind,
        recovery_scope: &'a str,
        result_policy: &'a str,
    },
}

impl ResourceTarget<'_> {
    /// Validate only the closed target grammar, without allocating a JSON DTO.
    /// This is not a policy decision, provider installation, or execution grant.
    /// Serialized explanation inputs retain their separate document bounds.
    #[must_use]
    pub fn is_valid(&self) -> bool {
        self.valid()
    }

    pub(super) fn valid(&self) -> bool {
        match self {
            Self::Context | Self::Clock | Self::Random => true,
            Self::Log { level } => log_level(level),
            Self::Http {
                origin,
                method,
                path,
            } => origin.valid() && http_method(method) && http_path(path),
            Self::Stream { endpoint } => endpoint.validate().is_ok(),
            Self::Blob { namespace } => identifier(namespace),
            Self::Secrets { reference } => identifier(reference),
            Self::Events { subject } => subject_name(subject),
            Self::Telemetry { name } => identifier(name),
            Self::Service {
                service,
                publication: id,
            } => identifier(service) && publication(id),
            Self::State {
                namespace,
                incarnation,
                entity,
                recovery_scope,
                result_policy,
                ..
            } => {
                state_identifier(namespace)
                    && *incarnation != 0
                    && entity.is_none_or(state_identifier)
                    && identifier(recovery_scope)
                    && identifier(result_policy)
            }
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
            Self::Stream { endpoints } => unique(endpoints, |value| value.validate().is_ok()),
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
            Self::State { scopes } => unique(scopes, StateResourceScope::valid),
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
            (
                Self::Context,
                "latent:context/context@0.1.0" | "latent:runtime-native/threads@0.1.0"
            ) | (
                Self::Clock,
                "latent:clock/monotonic@0.1.0"
                    | "latent:clock/wall@0.1.0"
                    | "latent:runtime/activation@0.1.0"
            ) | (Self::Random, "latent:random/random@0.1.0")
                | (Self::Log { .. }, "latent:log/log@0.1.0")
                | (
                    Self::Http { .. },
                    "latent:http/client@0.2.0"
                        | "latent:http/streaming@0.3.0"
                        | "latent:http/phase-timing@0.4.0"
                )
                | (Self::Stream { .. }, "latent:network/streams@0.1.0")
                | (
                    Self::Blob { .. },
                    "latent:blob/blob@0.1.0" | "latent:blob/blob@0.2.0"
                )
                | (Self::Secrets { .. }, "latent:secrets/reader@0.1.0")
                | (Self::Events { .. }, "latent:events/publisher@0.2.0")
                | (Self::Telemetry { .. }, "latent:telemetry/custom@0.1.0")
                | (Self::Service { .. }, "latent:service/invoke@0.1.0")
                | (
                    Self::State { .. },
                    "latent:state/key-value@0.2.0" | "latent:intents/staging@0.1.0"
                )
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
            (Self::Stream { endpoints }, ResourceTarget::Stream { endpoint }) => {
                endpoints.contains(endpoint)
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
            (
                Self::State { scopes },
                ResourceTarget::State {
                    namespace,
                    incarnation,
                    entity,
                    recovery_kind,
                    recovery_scope,
                    result_policy,
                },
            ) => scopes.iter().any(|scope| {
                scope.namespace == *namespace
                    && scope.incarnation == *incarnation
                    && scope.entity.as_deref() == *entity
                    && scope.recovery_kind == *recovery_kind
                    && scope.recovery_scope == *recovery_scope
                    && scope.result_policy == *result_policy
            }),
            _ => false,
        }
    }
}

fn contains(values: &[String], requested: &str) -> bool {
    values.iter().any(|value| value == requested)
}
pub(super) fn explicit_entity<'de, D: serde::Deserializer<'de>>(
    decoder: D,
) -> Result<Option<String>, D::Error> {
    Option::<String>::deserialize(decoder)
}
fn state_identifier(value: &str) -> bool {
    !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
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

#[cfg(test)]
mod stream_tests {
    use super::*;
    fn endpoint() -> StreamEndpoint {
        StreamEndpoint {
            host: "mail.example".into(),
            port: 587,
            transport: StreamTransport::Tcp,
        }
    }
    #[test]
    fn endpoint_scope_is_exact_and_cannot_be_derived_from_http_authority() {
        let endpoint = endpoint();
        let streams = ResourceConstraint::Stream {
            endpoints: vec![endpoint.clone()],
        };
        assert!(streams.validate().is_ok());
        assert!(streams.covers(&ResourceTarget::Stream {
            endpoint: &endpoint
        }));
        let http = ResourceConstraint::Http {
            origins: vec![HttpOrigin {
                scheme: "https".into(),
                host: endpoint.host.clone(),
                port: endpoint.port,
            }],
            methods: vec!["POST".into()],
            paths: vec![],
            path_prefixes: vec!["/".into()],
        };
        assert!(!http.covers(&ResourceTarget::Stream {
            endpoint: &endpoint
        }));
        assert!(!http.compatible("latent:network/streams@0.1.0"));
        assert!(!streams.compatible("latent:http/client@0.2.0"));
        for alternate in [
            StreamEndpoint {
                port: 465,
                ..endpoint.clone()
            },
            StreamEndpoint {
                host: "alternate.example".into(),
                ..endpoint.clone()
            },
            StreamEndpoint {
                transport: StreamTransport::HostTls,
                ..endpoint.clone()
            },
        ] {
            assert!(!streams.covers(&ResourceTarget::Stream {
                endpoint: &alternate
            }));
        }
    }
    #[test]
    fn malformed_ambiguous_and_wildcard_endpoints_fail_closed() {
        for host in [
            "",
            "MAIL.EXAMPLE",
            "mail.example.",
            "*.example",
            "user@mail.example",
            "https://mail.example",
            "127.000.0.1",
            "127.1",
            "2130706433",
            "0x7f000001",
            "0x7f.0.0.1",
            "[::1]",
            "::ffff:127.0.0.1",
            "a..example",
            "-a.example",
        ] {
            assert!(
                StreamEndpoint {
                    host: host.into(),
                    ..endpoint()
                }
                .validate()
                .is_err(),
                "{host}"
            );
        }
        assert!(StreamEndpoint {
            port: 0,
            ..endpoint()
        }
        .validate()
        .is_err());
        for host in ["mail.example", "127.0.0.1", "::1", "2001:db8::1"] {
            assert!(StreamEndpoint {
                host: host.into(),
                ..endpoint()
            }
            .validate()
            .is_ok());
        }
        let endpoint = endpoint();
        assert!(ResourceConstraint::Stream {
            endpoints: vec![endpoint.clone(), endpoint]
        }
        .validate()
        .is_err());
        assert!(!ResourceConstraint::Stream { endpoints: vec![] }.covers(
            &ResourceTarget::Stream {
                endpoint: &self::endpoint()
            }
        ));
    }

    #[test]
    fn canonical_ip_stack_spelling_preserves_original_display_and_host_gates() {
        use std::net::IpAddr;

        // The allocated Display oracle belongs only to this ordinary semantic
        // control; it is not an activation-memory or allocator measurement.
        for (input, canonical) in [
            ("0.0.0.0", "0.0.0.0"),
            ("127.0.0.1", "127.0.0.1"),
            ("255.255.255.255", "255.255.255.255"),
            ("::", "::"),
            ("::1", "::1"),
            ("0:0:0:0:0:0:0:1", "::1"),
            ("2001:0DB8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
            ("2001:db8:0:1:1:1:1:1", "2001:db8:0:1:1:1:1:1"),
            ("2001:db8::1:1:1:1:1", "2001:db8:0:1:1:1:1:1"),
            ("2001:0:0:1:0:0:1:1", "2001::1:0:0:1:1"),
            ("2001:0:0:1::1:1", "2001::1:0:0:1:1"),
            ("1:1:1:1:1:1:0:0", "1:1:1:1:1:1::"),
            ("0:0:1:1:1:1:1:1", "::1:1:1:1:1:1"),
            ("::192.0.2.128", "::c000:280"),
            ("::ffff:c000:280", "::ffff:192.0.2.128"),
            ("::ffff:255.255.255.255", "::ffff:255.255.255.255"),
            (
                "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
                "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
            ),
        ] {
            let address: IpAddr = input.parse().unwrap();
            let original = address.to_string();
            assert_eq!(original, canonical, "{input}");
            let mut text = CanonicalIpText::new();
            std::fmt::write(&mut text, format_args!("{address}")).unwrap();
            assert_eq!(text.as_bytes(), canonical.as_bytes(), "{input}");
            assert!(text.used <= 39);
            assert!(canonical_host(canonical), "{canonical}");
            assert_eq!(canonical_host(input), original == input, "{input}");
        }
        assert_eq!("255.255.255.255".len(), 15);
        assert_eq!("::ffff:255.255.255.255".len(), 22);
        assert_eq!("ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff".len(), 39);

        for host in ["localhost", "example.test", "a-b.example", "127.00.0.1"] {
            assert!(canonical_host(host), "{host}");
        }
        let domain = format!(
            "{}.{}.{}.{}",
            "a".repeat(63),
            "b".repeat(63),
            "c".repeat(63),
            "d".repeat(61)
        );
        assert_eq!(domain.len(), 253);
        assert!(canonical_host(&domain));
        assert!(!canonical_host(&(domain + "d")));
        assert!(!canonical_host(&"a".repeat(64)));
        for host in ["", "UPPER.example", "a..example", "-a.example", "[::1]"] {
            assert!(!canonical_host(host), "{host}");
        }
        let mapped = "::ffff:192.0.2.128";
        assert!(ResourceTarget::Http {
            origin: &HttpOrigin {
                scheme: "http".into(),
                host: mapped.into(),
                port: 80,
            },
            method: "GET",
            path: "/",
        }
        .is_valid());
        assert!(StreamEndpoint {
            host: mapped.into(),
            ..endpoint()
        }
        .validate()
        .is_err());
        assert!(StreamEndpoint {
            host: "127.00.0.1".into(),
            ..endpoint()
        }
        .validate()
        .is_err());
    }

    #[test]
    fn canonical_ip_fixed_writer_refuses_whole_overflowing_chunks() {
        use std::fmt::Write;
        use std::net::IpAddr;

        let longest = "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff";
        let address: IpAddr = longest.parse().unwrap();
        let mut exact = CanonicalIpText::new();
        write!(&mut exact, "{address}").unwrap();
        assert_eq!(exact.used, 39);
        assert_eq!(exact.as_bytes(), longest.as_bytes());
        let bytes = exact.bytes;
        assert!(exact.write_str("x").is_err());
        assert_eq!(exact.used, 39);
        assert_eq!(exact.bytes, bytes);

        let mut split = CanonicalIpText::new();
        split.write_str("::").unwrap();
        split.write_str("ffff:").unwrap();
        split.write_str("255.255.255.255").unwrap();
        assert_eq!(split.as_bytes(), b"::ffff:255.255.255.255");
        let bytes = split.bytes;
        let used = split.used;
        assert!(split.write_str("012345678901234567").is_err());
        assert_eq!(split.used, used);
        assert_eq!(split.bytes, bytes);
        split.write_str("01234567890123456").unwrap();
        assert_eq!(split.used, 39);
    }
}
