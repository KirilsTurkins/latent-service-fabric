use latent_core::PlatformError;
use latent_rpc::{
    control::v1 as proto,
    platform_error::{grpc_code, TryIntoDomainPlatformError},
};
use prost::Message;
use tonic::{metadata::MetadataMap, Code, Status};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FailureKind {
    InvalidConfiguration,
    InvalidRequest,
    Capacity,
    Deadline,
    Closed,
    Connection,
    InvalidResponse,
    Rejected,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RecoveryIdentity {
    pub activation_id: Option<String>,
    pub operation_id: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuditAcknowledgement {
    pub status: String,
    pub attempt_sequence: Option<u64>,
}

#[derive(Clone, PartialEq, Eq)]
pub struct UnsupportedWireValue {
    pub field: &'static str,
    pub value: String,
}

#[derive(Clone, PartialEq, Eq)]
pub struct RpcFailure {
    pub kind: FailureKind,
    pub grpc_code: Option<i32>,
    pub platform: Option<Box<PlatformError>>,
    pub dispatched: bool,
    pub outcome_known: bool,
    pub recovery: RecoveryIdentity,
    pub audit: Option<AuditAcknowledgement>,
    pub unsupported: Option<Box<UnsupportedWireValue>>,
}

impl std::fmt::Debug for RpcFailure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("RpcFailure")
            .field("kind", &self.kind)
            .field("grpc_code", &self.grpc_code)
            .field("dispatched", &self.dispatched)
            .field("outcome_known", &self.outcome_known)
            .field("recovery", &self.recovery)
            .field("audit", &self.audit)
            .finish_non_exhaustive()
    }
}

impl std::fmt::Display for RpcFailure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "bounded RPC failure: {:?}", self.kind)
    }
}

impl std::error::Error for RpcFailure {}

impl RpcFailure {
    pub(super) fn local(kind: FailureKind) -> Self {
        Self {
            kind,
            grpc_code: None,
            platform: None,
            dispatched: false,
            outcome_known: true,
            recovery: RecoveryIdentity::default(),
            audit: None,
            unsupported: None,
        }
    }

    pub(super) fn unsupported(field: &'static str, value: &str) -> Self {
        let mut result = Self::local(FailureKind::InvalidResponse);
        if value.len() <= 256 {
            result.unsupported = Some(Box::new(UnsupportedWireValue {
                field,
                value: value.into(),
            }));
        }
        result
    }

    pub(super) fn context(mut self, recovery: &RecoveryIdentity, dispatched: bool) -> Self {
        self.recovery = recovery.clone();
        self.dispatched = dispatched;
        if dispatched && self.kind != FailureKind::Rejected {
            self.outcome_known = false;
        }
        self
    }

    pub(super) fn received(
        self,
        recovery: &RecoveryIdentity,
        audit: Option<&AuditAcknowledgement>,
    ) -> Self {
        let mut result = self.context(recovery, true);
        result.audit = audit.cloned();
        result
    }

    pub(super) fn status(status: &Status) -> Self {
        let code = status.code();
        let known = matches!(
            code,
            Code::InvalidArgument
                | Code::PermissionDenied
                | Code::Unauthenticated
                | Code::AlreadyExists
                | Code::NotFound
                | Code::FailedPrecondition
                | Code::Aborted
                | Code::Unimplemented
        );
        let mut result = Self::local(
            if code == Code::DeadlineExceeded || timeout_source(status) {
                FailureKind::Deadline
            } else if known {
                FailureKind::Rejected
            } else {
                FailureKind::Connection
            },
        );
        result.grpc_code = Some(code as i32);
        result.outcome_known = known;
        if !status.details().is_empty() {
            match platform(status.details()) {
                Ok(value) if grpc_code(value.code) == code => {
                    result.platform = Some(Box::new(value));
                }
                Ok(_) => {
                    result.kind = FailureKind::InvalidResponse;
                    result.outcome_known = false;
                }
                Err(error) => {
                    result.kind = error.kind;
                    result.unsupported = error.unsupported;
                    result.outcome_known = false;
                }
            }
        }
        match audit(status.metadata()) {
            Ok(value) => result.audit = value,
            Err(error) => {
                result.kind = error.kind;
                result.unsupported = error.unsupported;
                result.outcome_known = false;
            }
        }
        if result.audit.as_ref().is_some_and(|audit| {
            matches!(
                audit.status.as_str(),
                "outcome-unknown" | "audit-unavailable"
            )
        }) {
            result.outcome_known = false;
        }
        result
    }
}

fn timeout_source(status: &Status) -> bool {
    let mut source: Option<&(dyn std::error::Error + 'static)> = Some(status);
    for _ in 0..8 {
        let Some(error) = source else {
            break;
        };
        if error.is::<tonic::TimeoutExpired>() {
            return true;
        }
        source = error.source();
    }
    false
}

impl From<RpcFailure> for crate::ClientTransportError {
    fn from(value: RpcFailure) -> Self {
        Self {
            message: value.to_string(),
            retryable: false,
        }
    }
}

pub(super) fn audit(metadata: &MetadataMap) -> Result<Option<AuditAcknowledgement>, RpcFailure> {
    let invalid = || RpcFailure::local(FailureKind::InvalidResponse);
    if metadata.get_all("latent-audit-status").iter().count() > 1
        || metadata.get_all("latent-audit-attempt").iter().count() > 1
    {
        return Err(invalid());
    }
    let state = metadata.get("latent-audit-status");
    let sequence = metadata.get("latent-audit-attempt");
    let Some(state) = state else {
        return if sequence.is_some() {
            Err(invalid())
        } else {
            Ok(None)
        };
    };
    let state = state.to_str().map_err(|_| invalid())?;
    if state.is_empty()
        || state.len() > 64
        || !state
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte == b'-')
    {
        return Err(RpcFailure::unsupported("audit.status", state));
    }
    let sequence = sequence
        .map(|sequence| {
            let text = sequence.to_str().map_err(|_| invalid())?;
            let value = text.parse::<u64>().map_err(|_| invalid())?;
            if value == 0 || value.to_string() != text {
                return Err(invalid());
            }
            Ok(value)
        })
        .transpose()?;
    if matches!(state, "durable" | "outcome-unknown") && sequence.is_none() {
        return Err(invalid());
    }
    Ok(Some(AuditAcknowledgement {
        status: state.into(),
        attempt_sequence: sequence,
    }))
}

fn platform(bytes: &[u8]) -> Result<PlatformError, RpcFailure> {
    let invalid = || RpcFailure::local(FailureKind::InvalidResponse);
    if bytes.len() > 8192 {
        return Err(invalid());
    }
    let error = proto::PlatformError::decode(bytes).map_err(|_| invalid())?;
    if error.code.len() > 64
        || error.message.len() > 4096
        || error.detail_items.len() > 16
        || error.detail_items.iter().any(|item| {
            item.kind.len() > 128
                || item.fields.len() > 32
                || item
                    .fields
                    .iter()
                    .any(|(key, value)| key.len() > 128 || value.len() > 1024)
        })
    {
        return Err(invalid());
    }
    error
        .try_into_domain()
        .map_err(|error| RpcFailure::unsupported("platform_error.code", error.code()))
}
