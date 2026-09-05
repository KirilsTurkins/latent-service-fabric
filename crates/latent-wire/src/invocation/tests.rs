use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

use latent_activation::{
    ActivationOutcome, ActivationStatus, ActivationSuccess, ActivationSuccessSummary,
    RetainedActivationOutcome,
};
use latent_core::{
    ActivationId, ActivationPhase, ActivationTerminalState, BudgetConsumption, CancelDisposition,
    ContractId, DeclaredError, ErrorDetail, FunctionId, InvocationPrincipal, Metadata,
    PlatformError, PlatformErrorCode, PrincipalKind, ReleaseDigest, RevisionId, RouteGeneration,
    ServiceId, TenantId,
};
use latent_routing::InvocationTarget;
use prost::Message;
use tokio::sync::Notify;
use tonic::Code;

use super::*;

include!("test_parts/tests_01.rs");
include!("test_parts/tests_02.rs");
include!("test_parts/tests_03.rs");
include!("test_parts/tests_04.rs");
include!("test_parts/tests_05.rs");
include!("test_parts/tests_06.rs");
include!("test_parts/tests_07.rs");
