//! Hardened Phase 1 generic invocation, cancellation, and status service.
//!
//! The module implements the generated Tonic server contract from `latent-rpc`
//! without owning a listener, socket, executor, or activation lifecycle. A node
//! composition injects an [`InvocationRuntime`], which is implemented by the
//! single activation manager and its bounded status index.

#![forbid(unsafe_code)]

use std::fmt;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationOutcome, ActivationStatus};
use latent_core::{
    ActivationId, BoxFuture, CancelDisposition, IdempotencyKey, InvocationPrincipal, Metadata,
    PlatformError, PlatformErrorCode, PrincipalKind, ReleaseDigest, ResourceBudget, RevisionId,
    RouteGeneration,
};
use latent_routing::InvocationTarget;
use prost::Message;
use tokio::sync::Notify;
use tonic::{Code, Request, Response, Status};

pub use latent_rpc::invocation::v1 as proto;
pub use proto::invocation_service_client::InvocationServiceClient;
pub use proto::invocation_service_server::{InvocationService, InvocationServiceServer};

mod conversion;
mod validation;

pub use conversion::{
    activation_status_from_proto, activation_status_to_proto, budget_from_proto, budget_to_proto,
    cancel_disposition_from_proto, cancel_disposition_to_proto, consumption_from_proto,
    consumption_to_proto, declared_error_from_proto, declared_error_to_proto,
    invocation_request_from_proto, invocation_request_to_proto, invocation_response_from_proto,
    invocation_response_to_proto, platform_error_from_proto, platform_error_to_proto,
    InvocationConversionError,
};

include!("invocation/service_parts/service_01.rs");
include!("invocation/service_parts/service_02.rs");
include!("invocation/service_parts/service_03.rs");

#[cfg(test)]
mod tests;
