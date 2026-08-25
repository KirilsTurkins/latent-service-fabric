//! Reproducible Phase 0 activation, containment, pool, and resource baseline probe.
//!
//! This executable is deliberately an observational benchmark harness. It composes
//! the same fixed cell pool, Wasmtime backend, prepared component, and activation
//! runner as the `latentd phase0-spike` path, retains them across all samples, and
//! emits raw JSON plus a concise Markdown report. Its numbers are not production
//! SLOs or competitive claims.

#![forbid(unsafe_code)]
#![allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss,
    clippy::format_collect,
    clippy::large_futures,
    clippy::map_unwrap_or,
    clippy::needless_pass_by_value,
    clippy::similar_names,
    clippy::single_match_else,
    clippy::struct_excessive_bools,
    clippy::too_many_arguments,
    clippy::too_many_lines,
    clippy::type_complexity
)]

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::{self, Write as _};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use clap::{Parser, ValueEnum};
use latent_activation::{ActivationEnvelope, ActivationManager, ActivationOutcome, TraceContext};
use latent_artifacts::{ArtifactDescriptor, CapsuleArtifact};
use latent_core::{
    ActivationId, ArtifactReference, BudgetConsumption, CapabilityId, ContractId, FunctionId,
    InvocationPrincipal, Metadata, NodeId, PlatformError, PlatformErrorCode, PrincipalKind,
    ReleaseDigest, ResourceBudget, ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::{BoundImport, ExecutionBackend};
use latent_manifest::{
    CapsuleManifest, ContractExport, ContractImport, ExecutionBackendKind, ExecutionRequirements,
    ObjectMetadata, StateModel, ThreadingModel,
};
use latent_node::{ActivationRunnerSnapshot, Phase0ActivationRunner, Phase0ActivationRunnerConfig};
use latent_routing::InvocationTarget;
use latent_scheduler::{CellClass, CellPool, CellPoolSnapshot, FixedCellPool, FixedCellPoolConfig};
use latent_wasmtime::{
    Phase0WasmtimeBackend, Phase0WasmtimeConfig, Phase0WasmtimeEngineFactory,
    PreparedCacheSnapshot, RuntimeResourceSnapshot, CONTEXT_IMPORT, ECHO_DOMAIN_ERROR_MEDIA_TYPE,
    ECHO_EXPORT, ECHO_SUCCESS_MEDIA_TYPE, LOG_IMPORT,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest as _, Sha256};
use tokio::runtime::Builder;
use tokio::sync::Barrier;

const SCHEMA_VERSION: &str = "latent.phase0.baseline.v1";
const SURFACE: &str = "latentd.phase0-baseline";
const NODE_ID: &str = "phase0-baseline-node-0";
const TRACE_ID: &str = "phase0-baseline-trace-00000001";
const SPAN_ID: &str = "baseline-span-01";
const WASMTIME_WORKSPACE_PIN: &str = "47.0.3";
const COMPONENT_MAXIMUM_BYTES: usize = 64 * 1024 * 1024;
const PREPARED_CACHE_MAXIMUM_ENTRIES: usize = 1;
const PREPARED_CACHE_MAXIMUM_BYTES: usize = 64 * 1024 * 1024;
const LOG_MAXIMUM_ENTRIES: usize = 64;
const LOG_MAXIMUM_BYTES: usize = 64 * 1024;
const EPOCH_TICK_INTERVAL_MILLIS: u64 = 1;
const DEFAULT_FUEL: u64 = 1_000_000_000_000;
const DEFAULT_MEMORY_BYTES: u64 = 16 * 1024 * 1024;
const DEFAULT_MEMORY_PRESSURE_BYTES: u64 = 4 * 1024 * 1024;
const DEFAULT_TIMEOUT_MILLIS: u64 = 25;
const DEFAULT_CANCELLATION_MILLIS: u64 = 5;
const DEFAULT_MAXIMUM_TIMEOUT_OVERSHOOT_MILLIS: u64 = 500;
const DEFAULT_RSS_GROWTH_ALLOWANCE_BYTES: u64 = 64 * 1024 * 1024;
const DEFAULT_FD_GROWTH_ALLOWANCE: u64 = 2;
const FIXTURE_TRAP: &str = "__latent_test_trap";
const FIXTURE_INFINITE: &str = "__latent_test_infinite";
const FIXTURE_MEMORY: &str = "__latent_test_memory";
const FIXTURE_DELAYED_ECHO_PREFIX: &str = "__latent_test_delayed_echo:";

include!("phase0_baseline/definitions.rs");
include!("phase0_baseline/run.rs");
include!("phase0_baseline/activation.rs");
include!("phase0_baseline/throughput.rs");
include!("phase0_baseline/artifact.rs");
include!("phase0_baseline/analysis.rs");
include!("phase0_baseline/report.rs");
