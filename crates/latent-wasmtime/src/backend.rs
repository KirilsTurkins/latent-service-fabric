use std::collections::{BTreeSet, HashMap, VecDeque};
use std::fmt::Write as _;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

use latent_artifacts::CapsuleArtifact;
use latent_core::{
    ActivationId, BoxFuture, BudgetConsumption, ErrorDetail, Metadata, PlatformError,
    PlatformErrorCode, ReleaseDigest, ResourceBudget,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionReport, ExecutionRequest, GuestOutcome,
    PreparationKey, PreparedComponent,
};
use latent_manifest::ExecutionBackendKind;
use sha2::{Digest, Sha256};
use wasmtime::component::{Component, HasSelf, Linker};
use wasmtime::{Config, Engine, PoolingAllocationConfig, Store, WasmBacktraceDetails};

use crate::bindings;
use crate::containment::{
    bounded_text, classify_runtime_error, configure_epoch, interrupted_outcome, monotonic_deadline,
    platform_error, start_epoch_ticker, RuntimeResourceCounters, RuntimeResourceSnapshot,
    StopControl, MAX_DIAGNOSTIC_BYTES,
};
use crate::host::{
    hostcall_fuel_limit, ActivationHostContext, BoundedLogSink, HostCallTiming, HostState,
};
use crate::{WasmtimeEngineFactory, WasmtimeEngineProfile};

pub const BACKEND_ID: &str = "wasmtime-component-phase-0";
pub const WASMTIME_VERSION: &str = "47.0.3";
pub const ECHO_WORLD: &str = "examples:echo/service@0.1.0";
pub const ECHO_EXPORT: &str = "examples:echo/api@0.1.0";
pub const CONTEXT_IMPORT: &str = "latent:context/context@0.1.0";
pub const LOG_IMPORT: &str = "latent:log/log@0.1.0";
pub const ECHO_SUCCESS_MEDIA_TYPE: &str = "text/plain; charset=utf-8";
pub const ECHO_DOMAIN_ERROR_MEDIA_TYPE: &str = "application/vnd.latent.echo-error+json";

const EMPTY_MESSAGE_OUTPUT: &[u8] = br#"{"error":"empty-message"}"#;
const MESSAGE_TOO_LARGE_OUTPUT: &[u8] = br#"{"error":"message-too-large"}"#;
const INVOCATION_TIMING_MAXIMUM_ENTRIES: usize = 256;
const PHASE0_POOLING_MAX_COMPONENT_INSTANCE_BYTES: usize = 1024 * 1024;
const PHASE0_POOLING_MAX_CORE_INSTANCE_BYTES: usize = 1024 * 1024;

/// Bounded Wasmtime allocator modes that the Phase 0 profiling harness may
/// compare. The default remains on-demand allocation: pooling is an
/// experiment, not a change to the Phase 0 execution contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase0InstanceAllocator {
    OnDemand,
    Pooling,
}

impl Phase0InstanceAllocator {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::OnDemand => "on_demand",
            Self::Pooling => "pooling",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase0WasmtimeConfig {
    pub target_triple: String,
    pub cpu_feature_set: String,
    pub maximum_component_bytes: usize,
    pub maximum_memory_bytes: u64,
    pub maximum_fuel: u64,
    pub maximum_wasm_stack_bytes: usize,
    pub async_stack_bytes: usize,
    pub prepared_cache_maximum_entries: usize,
    pub prepared_cache_maximum_source_bytes: usize,
    /// When false, preparation remains usable by its current runner but is
    /// deliberately not reusable by a later `prepare` call.  This is a
    /// bounded profiling control for comparing a cold prepare with cache reuse;
    /// normal Phase 0 execution always leaves it enabled.
    pub prepared_cache_enabled: bool,
    pub invocation_log_maximum_entries: usize,
    pub invocation_log_maximum_bytes: usize,
    pub retained_log_maximum_entries: usize,
    pub retained_log_maximum_bytes: usize,
    pub epoch_deadline_ticks: u64,
    pub epoch_tick_interval_millis: u64,
    /// The allocator mode is part of the preparation-key compatibility
    /// material. Only the profiling harness selects the pooling experiment.
    pub instance_allocator: Phase0InstanceAllocator,
    /// Make Wasmtime's platform-default COW behavior explicit and measurable.
    pub copy_on_write_images: bool,
    /// Upper bound for every preallocated pooling resource. It is ignored by
    /// on-demand allocation and must be non-zero for the pooling experiment.
    pub pooling_maximum_instances: u32,
}

impl Default for Phase0WasmtimeConfig {
    fn default() -> Self {
        Self {
            target_triple: env!("LATENT_WASMTIME_HOST_TARGET").to_owned(),
            cpu_feature_set: "host-baseline".to_owned(),
            maximum_component_bytes: 16 * 1024 * 1024,
            maximum_memory_bytes: 64 * 1024 * 1024,
            maximum_fuel: 100_000_000,
            maximum_wasm_stack_bytes: 512 * 1024,
            async_stack_bytes: 2 * 1024 * 1024,
            prepared_cache_maximum_entries: 8,
            prepared_cache_maximum_source_bytes: 64 * 1024 * 1024,
            prepared_cache_enabled: true,
            invocation_log_maximum_entries: 8,
            invocation_log_maximum_bytes: 16 * 1024,
            retained_log_maximum_entries: 256,
            retained_log_maximum_bytes: 512 * 1024,
            epoch_deadline_ticks: 1,
            epoch_tick_interval_millis: 5,
            instance_allocator: Phase0InstanceAllocator::OnDemand,
            copy_on_write_images: true,
            pooling_maximum_instances: 1,
        }
    }
}

impl Phase0WasmtimeConfig {
    fn validate(&self) -> Result<(), PlatformError> {
        let invalid = self.target_triple != env!("LATENT_WASMTIME_HOST_TARGET")
            || self.cpu_feature_set.is_empty()
            || self.maximum_component_bytes == 0
            || self.maximum_memory_bytes == 0
            || self.maximum_fuel == 0
            || self.maximum_wasm_stack_bytes == 0
            || self.async_stack_bytes < self.maximum_wasm_stack_bytes
            || self.prepared_cache_maximum_entries == 0
            || self.prepared_cache_maximum_source_bytes == 0
            || self.invocation_log_maximum_entries == 0
            || self.invocation_log_maximum_bytes == 0
            || self.retained_log_maximum_entries == 0
            || self.retained_log_maximum_bytes == 0
            || self.epoch_deadline_ticks == 0
            || self.epoch_tick_interval_millis == 0
            || matches!(self.instance_allocator, Phase0InstanceAllocator::Pooling)
                && self.pooling_maximum_instances == 0;
        if invalid {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "invalid Phase 0 Wasmtime configuration",
                false,
            ));
        }
        Ok(())
    }

    fn configuration_digest(&self) -> String {
        let material = format!(
            "component-model=1;component-model-async=1;fuel=1;epoch=1;aggregate-memory=1;\
             hostcall-fuel=v2-echo-world-max-transfer;max-component={};max-memory={};\
             max-fuel={};wasm-stack={};async-stack={};cache-enabled={};cache-entries={};\
             cache-bytes={};invocation-log-entries={};invocation-log-bytes={};\
             retained-log-entries={};retained-log-bytes={};epoch-ticks={};\
             epoch-tick-ms={};allocator={};cow={};pooling-max-instances={};target={};cpu={}",
            self.maximum_component_bytes,
            self.maximum_memory_bytes,
            self.maximum_fuel,
            self.maximum_wasm_stack_bytes,
            self.async_stack_bytes,
            self.prepared_cache_enabled,
            self.prepared_cache_maximum_entries,
            self.prepared_cache_maximum_source_bytes,
            self.invocation_log_maximum_entries,
            self.invocation_log_maximum_bytes,
            self.retained_log_maximum_entries,
            self.retained_log_maximum_bytes,
            self.epoch_deadline_ticks,
            self.epoch_tick_interval_millis,
            self.instance_allocator.name(),
            self.copy_on_write_images,
            self.pooling_maximum_instances,
            self.target_triple,
            self.cpu_feature_set,
        );
        format!("blake3:{}", blake3::hash(material.as_bytes()).to_hex())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedCacheSnapshot {
    pub entries: usize,
    pub source_bytes: usize,
    pub maximum_entries: usize,
    pub maximum_source_bytes: usize,
}

/// Bounded timing-store state exposed to long-running resource probes.
///
/// Timing records are diagnostic data rather than activation-owned state.  The
/// snapshot makes their retention limit observable without exposing the timing
/// records themselves or allowing a benchmark to depend on their internals.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InvocationTimingStoreSnapshot {
    pub entries: usize,
    pub maximum_entries: usize,
}

/// Precise Phase 0 backend boundaries for one contained invocation.
///
/// `host_call_micros` is intentionally a subset of `guest_call_micros`, so
/// host-import work is observable without being counted twice in latency sums.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Phase0InvocationTiming {
    /// Validation, host-state/store construction, and instance preparation
    /// before entering the typed guest export.
    pub backend_setup_micros: u64,
    /// Time in the typed guest export call, including Wasmtime's automatic
    /// canonical-ABI component post-return before the call yields.
    pub guest_call_micros: u64,
    /// Time spent in Phase 0 host imports during the guest-call interval.
    pub host_call_micros: u64,
    pub host_call_count: u64,
    /// Host-visible post-return/result accounting after the typed guest call
    /// completes. Canonical-ABI post-return itself is included in
    /// `guest_call_micros` because Wasmtime completes it inside the safe typed
    /// call API.
    pub component_post_return_micros: u64,
    /// Store/instance/host-state, temporary-buffer, and runtime resource
    /// reclamation.
    pub activation_resource_reclamation_micros: u64,
    /// Guest result classification after activation resources are reclaimed.
    pub outcome_classification_micros: u64,
    /// Final cancellation/log cleanup and construction of the reusable proof.
    pub reusable_proof_micros: u64,
    /// End-to-end backend interval through return of the reusable proof.
    pub backend_total_micros: u64,
}

pub struct Phase0WasmtimeEngineFactory {
    config: Phase0WasmtimeConfig,
    engine: Engine,
    profile: WasmtimeEngineProfile,
    log_sink: BoundedLogSink,
}

impl Phase0WasmtimeEngineFactory {
    pub fn new(config: Phase0WasmtimeConfig) -> Result<Self, PlatformError> {
        config.validate()?;

        let mut engine_config = Config::new();
        engine_config.wasm_component_model(true);
        engine_config.wasm_component_model_async(true);
        engine_config.consume_fuel(true);
        engine_config.epoch_interruption(true);
        engine_config.max_wasm_stack(config.maximum_wasm_stack_bytes);
        engine_config.async_stack_size(config.async_stack_bytes);
        engine_config.memory_init_cow(config.copy_on_write_images);
        engine_config.wasm_backtrace_details(WasmBacktraceDetails::Disable);
        engine_config.wasm_backtrace_max_frames(None);
        if matches!(config.instance_allocator, Phase0InstanceAllocator::Pooling) {
            configure_bounded_pooling_allocator(&mut engine_config, &config)?;
        }

        let engine = Engine::new(&engine_config).map_err(|error| {
            platform_error(
                PlatformErrorCode::Internal,
                &format!(
                    "failed to construct Wasmtime engine: {}",
                    bounded_error(&error)
                ),
                false,
            )
        })?;
        start_epoch_ticker(
            &engine,
            Duration::from_millis(config.epoch_tick_interval_millis),
        )?;

        let configuration_digest = config.configuration_digest();
        let mut configuration = Metadata::new();
        configuration.insert("component-model".to_owned(), "enabled".to_owned());
        configuration.insert("component-model-async".to_owned(), "enabled".to_owned());
        configuration.insert("fuel".to_owned(), "enabled".to_owned());
        configuration.insert("epoch-interruption".to_owned(), "enabled".to_owned());
        configuration.insert(
            "epoch-tick-interval-millis".to_owned(),
            config.epoch_tick_interval_millis.to_string(),
        );
        configuration.insert(
            "memory-accounting".to_owned(),
            "aggregate-linear-memory".to_owned(),
        );
        configuration.insert(
            "hostcall-fuel".to_owned(),
            "per-call-echo-world-max-transfer".to_owned(),
        );
        configuration.insert(
            "maximum-memory-bytes".to_owned(),
            config.maximum_memory_bytes.to_string(),
        );
        configuration.insert(
            "maximum-wasm-stack-bytes".to_owned(),
            config.maximum_wasm_stack_bytes.to_string(),
        );
        configuration.insert(
            "async-stack-bytes".to_owned(),
            config.async_stack_bytes.to_string(),
        );
        configuration.insert(
            "instance-allocation-strategy".to_owned(),
            config.instance_allocator.name().to_owned(),
        );
        configuration.insert(
            "copy-on-write-images".to_owned(),
            config.copy_on_write_images.to_string(),
        );
        if matches!(config.instance_allocator, Phase0InstanceAllocator::Pooling) {
            configuration.insert(
                "pooling-maximum-instances".to_owned(),
                config.pooling_maximum_instances.to_string(),
            );
            configuration.insert(
                "pooling-linear-memory-keep-resident-bytes".to_owned(),
                "0".to_owned(),
            );
        }
        configuration.insert("ambient-wasi-authority".to_owned(), "none".to_owned());
        configuration.insert("configuration-digest".to_owned(), configuration_digest);

        let profile = WasmtimeEngineProfile {
            id: BACKEND_ID.to_owned(),
            wasmtime_version: WASMTIME_VERSION.to_owned(),
            target_triple: config.target_triple.clone(),
            cpu_feature_set: config.cpu_feature_set.clone(),
            pooling_allocator: matches!(
                config.instance_allocator,
                Phase0InstanceAllocator::Pooling
            ),
            copy_on_write_images: config.copy_on_write_images,
            async_support: true,
            fuel_enabled: true,
            epoch_interruption_enabled: true,
            configuration,
        };
        let log_sink = BoundedLogSink::new(
            config.retained_log_maximum_entries,
            config.retained_log_maximum_bytes,
        );

        Ok(Self {
            config,
            engine,
            profile,
            log_sink,
        })
    }

    pub fn preparation_key(&self, release: ReleaseDigest) -> PreparationKey {
        PreparationKey {
            release,
            engine_version: self.profile.wasmtime_version.clone(),
            engine_configuration_digest: self
                .profile
                .configuration
                .get("configuration-digest")
                .cloned()
                .expect("factory always records its configuration digest"),
            target_triple: self.profile.target_triple.clone(),
            cpu_feature_set: self.profile.cpu_feature_set.clone(),
        }
    }

    pub fn log_sink(&self) -> BoundedLogSink {
        self.log_sink.clone()
    }

    pub fn create_backend_instance(&self) -> Phase0WasmtimeBackend {
        Phase0WasmtimeBackend::new(
            self.engine.clone(),
            self.profile.clone(),
            self.config.clone(),
            self.log_sink.clone(),
        )
    }
}

fn configure_bounded_pooling_allocator(
    engine_config: &mut Config,
    config: &Phase0WasmtimeConfig,
) -> Result<(), PlatformError> {
    let maximum_memory_bytes = usize::try_from(config.maximum_memory_bytes).map_err(|_| {
        platform_error(
            PlatformErrorCode::InvalidArgument,
            "Phase 0 pooling memory limit does not fit the host address size",
            false,
        )
    })?;
    let total_core_instances =
        config
            .pooling_maximum_instances
            .checked_mul(4)
            .ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::InvalidArgument,
                    "Phase 0 pooling core-instance capacity overflowed",
                    false,
                )
            })?;
    let total_memories_and_tables =
        config
            .pooling_maximum_instances
            .checked_mul(2)
            .ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::InvalidArgument,
                    "Phase 0 pooling memory/table capacity overflowed",
                    false,
                )
            })?;

    // The experiment must retain only resources needed by the fixed cell
    // capacity. In particular, do not inherit Wasmtime's broad defaults or
    // retain warm linear memory after a store drops.
    let mut pooling = PoolingAllocationConfig::new();
    pooling
        .total_component_instances(config.pooling_maximum_instances)
        .total_core_instances(total_core_instances)
        .total_memories(total_memories_and_tables)
        .total_tables(total_memories_and_tables)
        .total_stacks(config.pooling_maximum_instances)
        .max_component_instance_size(PHASE0_POOLING_MAX_COMPONENT_INSTANCE_BYTES)
        .max_core_instance_size(PHASE0_POOLING_MAX_CORE_INSTANCE_BYTES)
        .max_core_instances_per_component(4)
        .max_memories_per_component(2)
        .max_tables_per_component(2)
        .max_memory_size(maximum_memory_bytes)
        .max_unused_warm_slots(0)
        .decommit_batch_size(1)
        .async_stack_keep_resident(0)
        .linear_memory_keep_resident(0)
        .table_keep_resident(0);
    engine_config.memory_reservation(config.maximum_memory_bytes);
    engine_config.memory_reservation_for_growth(0);
    engine_config.memory_guard_size(0);
    engine_config.allocation_strategy(pooling);
    Ok(())
}

impl WasmtimeEngineFactory for Phase0WasmtimeEngineFactory {
    fn profile(&self) -> &WasmtimeEngineProfile {
        &self.profile
    }

    fn create_backend(&self) -> Result<Box<dyn ExecutionBackend>, PlatformError> {
        Ok(Box::new(self.create_backend_instance()))
    }
}

struct PreparedRuntime {
    key: PreparationKey,
    pre: bindings::ServicePre<HostState>,
    declared_budget: ResourceBudget,
}

struct PreparedCache {
    entries: HashMap<String, Arc<PreparedRuntime>>,
    insertion_order: VecDeque<String>,
    source_sizes: HashMap<String, usize>,
    source_bytes: usize,
    maximum_entries: usize,
    maximum_source_bytes: usize,
}

impl PreparedCache {
    fn new(maximum_entries: usize, maximum_source_bytes: usize) -> Self {
        Self {
            entries: HashMap::new(),
            insertion_order: VecDeque::new(),
            source_sizes: HashMap::new(),
            source_bytes: 0,
            maximum_entries,
            maximum_source_bytes,
        }
    }

    fn get(&mut self, handle: &str) -> Option<Arc<PreparedRuntime>> {
        let entry = self.entries.get(handle).cloned()?;
        if let Some(position) = self
            .insertion_order
            .iter()
            .position(|candidate| candidate == handle)
        {
            self.insertion_order.remove(position);
        }
        self.insertion_order.push_back(handle.to_owned());
        Some(entry)
    }

    fn insert(
        &mut self,
        handle: String,
        source_bytes: usize,
        runtime: Arc<PreparedRuntime>,
    ) -> Result<(), PlatformError> {
        if source_bytes > self.maximum_source_bytes {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "component exceeds the bounded prepared-cache byte capacity",
                false,
            ));
        }

        self.remove(&handle);
        while self.entries.len() >= self.maximum_entries
            || self.source_bytes.saturating_add(source_bytes) > self.maximum_source_bytes
        {
            let Some(evicted) = self.insertion_order.pop_front() else {
                break;
            };
            self.remove(&evicted);
        }

        self.source_bytes = self.source_bytes.saturating_add(source_bytes);
        self.source_sizes.insert(handle.clone(), source_bytes);
        self.entries.insert(handle.clone(), runtime);
        self.insertion_order.push_back(handle);
        Ok(())
    }

    fn remove(&mut self, handle: &str) {
        self.entries.remove(handle);
        if let Some(source_bytes) = self.source_sizes.remove(handle) {
            self.source_bytes = self.source_bytes.saturating_sub(source_bytes);
        }
        if let Some(position) = self
            .insertion_order
            .iter()
            .position(|candidate| candidate == handle)
        {
            self.insertion_order.remove(position);
        }
    }

    fn snapshot(&self) -> PreparedCacheSnapshot {
        PreparedCacheSnapshot {
            entries: self.entries.len(),
            source_bytes: self.source_bytes,
            maximum_entries: self.maximum_entries,
            maximum_source_bytes: self.maximum_source_bytes,
        }
    }
}

struct InvocationTimingStore {
    entries: HashMap<String, Phase0InvocationTiming>,
    insertion_order: VecDeque<String>,
    maximum_entries: usize,
}

impl InvocationTimingStore {
    fn new(maximum_entries: usize) -> Self {
        Self {
            entries: HashMap::new(),
            insertion_order: VecDeque::new(),
            maximum_entries,
        }
    }

    fn insert(&mut self, activation_id: String, timing: Phase0InvocationTiming) {
        self.remove(&activation_id);
        while self.entries.len() >= self.maximum_entries {
            let Some(oldest) = self.insertion_order.pop_front() else {
                break;
            };
            self.entries.remove(&oldest);
        }
        self.insertion_order.push_back(activation_id.clone());
        self.entries.insert(activation_id, timing);
    }

    fn update_reusable_proof(&mut self, activation_id: &str, elapsed_micros: u64) {
        if let Some(timing) = self.entries.get_mut(activation_id) {
            timing.reusable_proof_micros =
                timing.reusable_proof_micros.saturating_add(elapsed_micros);
            timing.backend_total_micros =
                timing.backend_total_micros.saturating_add(elapsed_micros);
        }
    }

    fn remove(&mut self, activation_id: &str) -> Option<Phase0InvocationTiming> {
        let timing = self.entries.remove(activation_id)?;
        if let Some(position) = self
            .insertion_order
            .iter()
            .position(|candidate| candidate == activation_id)
        {
            self.insertion_order.remove(position);
        }
        Some(timing)
    }

    fn snapshot(&self) -> InvocationTimingStoreSnapshot {
        InvocationTimingStoreSnapshot {
            entries: self.entries.len(),
            maximum_entries: self.maximum_entries,
        }
    }
}

pub struct Phase0WasmtimeBackend {
    engine: Engine,
    profile: WasmtimeEngineProfile,
    config: Phase0WasmtimeConfig,
    cache: Mutex<PreparedCache>,
    /// A single runner-scoped prepared runtime used only by the explicit
    /// cache-disabled measurement.  It is not consulted by `prepare` for
    /// reuse and is removed by `release`, so it cannot become node cache.
    uncached_prepared: Mutex<Option<(String, Arc<PreparedRuntime>)>>,
    log_sink: BoundedLogSink,
    resources: RuntimeResourceCounters,
    timings: Mutex<InvocationTimingStore>,
}

impl Phase0WasmtimeBackend {
    fn new(
        engine: Engine,
        profile: WasmtimeEngineProfile,
        config: Phase0WasmtimeConfig,
        log_sink: BoundedLogSink,
    ) -> Self {
        Self {
            engine,
            profile,
            cache: Mutex::new(PreparedCache::new(
                config.prepared_cache_maximum_entries,
                config.prepared_cache_maximum_source_bytes,
            )),
            uncached_prepared: Mutex::new(None),
            config,
            log_sink,
            resources: RuntimeResourceCounters::default(),
            timings: Mutex::new(InvocationTimingStore::new(
                INVOCATION_TIMING_MAXIMUM_ENTRIES,
            )),
        }
    }

    pub fn cache_snapshot(&self) -> PreparedCacheSnapshot {
        self.lock_cache().snapshot()
    }

    pub fn stores_created(&self) -> u64 {
        self.resources.snapshot().stores_created
    }

    pub fn resource_snapshot(&self) -> RuntimeResourceSnapshot {
        self.resources.snapshot()
    }

    /// Returns the bounded diagnostic timing-store occupancy.
    #[must_use]
    pub fn invocation_timing_snapshot(&self) -> InvocationTimingStoreSnapshot {
        self.lock_timings().snapshot()
    }

    pub fn log_sink(&self) -> BoundedLogSink {
        self.log_sink.clone()
    }

    /// Returns and removes the timing record for one contained invocation.
    /// The internal store is bounded so observing timings cannot retain an
    /// unbounded activation history.
    pub fn take_invocation_timing(
        &self,
        activation_id: &ActivationId,
    ) -> Option<Phase0InvocationTiming> {
        self.lock_timings().remove(&activation_id.0)
    }

    fn prepare_inner(
        &self,
        artifact: &CapsuleArtifact,
        key: &PreparationKey,
    ) -> Result<PreparedComponent, PlatformError> {
        self.validate_key(artifact, key)?;
        self.validate_manifest(artifact)?;

        if artifact.component_bytes.is_empty() {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "component artifact is empty",
                false,
            ));
        }
        if artifact.component_bytes.len() > self.config.maximum_component_bytes {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "component artifact exceeds the configured byte limit",
                false,
            ));
        }

        let component_digest = sha256_digest(&artifact.component_bytes);
        if artifact.manifest.component_digest.0 != component_digest {
            return Err(error_with_detail(
                PlatformErrorCode::CorruptArtifact,
                "component content digest does not match the capsule manifest",
                "component-digest-mismatch",
                [
                    ("expected", artifact.manifest.component_digest.0.clone()),
                    ("actual", component_digest.clone()),
                ],
            ));
        }
        let handle = prepared_handle(key, &component_digest);
        if self.config.prepared_cache_enabled && self.lock_cache().get(&handle).is_some() {
            return Ok(self.prepared_descriptor(key.clone(), handle, component_digest));
        }

        let component =
            Component::new(&self.engine, &artifact.component_bytes).map_err(|error| {
                platform_error(
                    PlatformErrorCode::CorruptArtifact,
                    &format!("component validation failed: {}", bounded_error(&error)),
                    false,
                )
            })?;
        self.validate_component_surface(&component)?;

        let mut linker = Linker::<HostState>::new(&self.engine);
        bindings::Service::add_to_linker::<_, HasSelf<_>>(&mut linker, |state| state).map_err(
            |error| {
                platform_error(
                    PlatformErrorCode::Internal,
                    &format!(
                        "failed to bind Phase 0 host imports: {}",
                        bounded_error(&error)
                    ),
                    false,
                )
            },
        )?;
        let instance_pre = linker.instantiate_pre(&component).map_err(|error| {
            platform_error(
                PlatformErrorCode::IncompatibleContract,
                &format!(
                    "component imports cannot be resolved by the Phase 0 host: {}",
                    bounded_error(&error)
                ),
                false,
            )
        })?;
        let pre = bindings::ServicePre::new(instance_pre).map_err(|error| {
            platform_error(
                PlatformErrorCode::IncompatibleContract,
                &format!(
                    "component does not expose the typed echo world: {}",
                    bounded_error(&error)
                ),
                false,
            )
        })?;

        let runtime = Arc::new(PreparedRuntime {
            key: key.clone(),
            pre,
            declared_budget: artifact.manifest.execution.resource_budget_ceiling.clone(),
        });
        if self.config.prepared_cache_enabled {
            self.lock_cache()
                .insert(handle.clone(), artifact.component_bytes.len(), runtime)?;
        } else {
            let mut uncached = self.lock_uncached_prepared();
            if uncached.is_some() {
                return Err(platform_error(
                    PlatformErrorCode::StateConflict,
                    "cache-disabled preparation is still owned by an active runner",
                    true,
                ));
            }
            *uncached = Some((handle.clone(), runtime));
        }
        Ok(self.prepared_descriptor(key.clone(), handle, component_digest))
    }

    async fn invoke_inner(
        &self,
        request: ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
    ) -> Result<GuestOutcome, PlatformError> {
        let activation_id = request.activation.activation_id.clone();
        let started = Instant::now();
        let mut timing = Phase0InvocationTiming::default();
        let outcome = self
            .invoke_inner_timed(request, cancellation, &mut timing)
            .await;
        timing.backend_total_micros = elapsed_micros(started);
        self.lock_timings().insert(activation_id.0, timing);
        outcome
    }

    async fn invoke_inner_timed(
        &self,
        mut request: ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        timing: &mut Phase0InvocationTiming,
    ) -> Result<GuestOutcome, PlatformError> {
        let setup_started = Instant::now();
        let _active_invocation = self.resources.active_invocation();

        if cancellation.activation_id() != &request.activation.activation_id {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "cancellation handle belongs to a different activation",
                false,
            ));
        }
        if cancellation.is_cancelled() {
            return Ok(interrupted_outcome(
                latent_executor::GuestInterruptionKind::Cancelled,
                cancellation.reason().map_or_else(
                    || "cancelled before guest execution".to_owned(),
                    |reason| bounded_text(&reason, MAX_DIAGNOSTIC_BYTES),
                ),
                BudgetConsumption::default(),
            ));
        }
        if request.prepared.backend != BACKEND_ID {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "prepared component belongs to another execution backend",
                false,
            ));
        }

        let runtime = self
            .prepared_runtime(&request.prepared.opaque_handle)
            .ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::NotFound,
                    "prepared component is absent or has been evicted",
                    true,
                )
            })?;
        if runtime.key != request.prepared.key {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "prepared component key does not match the cached runtime",
                false,
            ));
        }
        if request.activation.budget != request.budget {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "execution request budget differs from the activation envelope budget",
                false,
            ));
        }
        if request.activation.target.contract.0 != ECHO_EXPORT
            || request.activation.target.function.0 != "echo"
        {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "the Phase 0 backend supports only examples:echo/api@0.1.0#echo",
                false,
            ));
        }
        if request.activation.input_media_type != ECHO_SUCCESS_MEDIA_TYPE {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "the Phase 0 echo input media type must be UTF-8 text",
                false,
            ));
        }
        self.validate_bound_imports(&request)?;
        self.validate_invocation_budget(&request.budget, &runtime.declared_budget)?;

        let cancellation_probe = cancellation.probe();
        let cancellation_guard = cancellation_probe
            .as_ref()
            .map(|_| self.resources.cancellation_probe());
        let deadline = monotonic_deadline(request.activation.deadline_unix_millis)?;
        let stop = Arc::new(StopControl::new(deadline, cancellation_probe));
        if let Some(kind) = stop.observe() {
            return Ok(interrupted_outcome(
                kind,
                stop.reason(kind),
                BudgetConsumption::default(),
            ));
        }

        let effective_memory = request
            .budget
            .memory_bytes
            .min(request.cell.maximum_memory_bytes)
            .min(self.config.maximum_memory_bytes);
        let maximum_memory_bytes = usize::try_from(effective_memory).map_err(|_| {
            platform_error(
                PlatformErrorCode::ResourceExhausted,
                "effective memory budget cannot be represented on this host",
                false,
            )
        })?;
        if maximum_memory_bytes == 0 {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "effective memory budget is zero",
                false,
            ));
        }

        let temporary_buffer_guard = self.resources.temporary_buffer();
        let input =
            String::from_utf8(std::mem::take(&mut request.activation.input)).map_err(|_| {
                platform_error(
                    PlatformErrorCode::InvalidArgument,
                    "the Phase 0 echo input must be valid UTF-8",
                    false,
                )
            })?;
        let host_context = ActivationHostContext::new(
            request.activation.activation_id.clone(),
            request.activation.root_activation_id.clone(),
            request.activation.parent_activation_id.clone(),
            request.activation.principal.clone(),
            request.activation.trace.trace_id.0.clone(),
            request.activation.trace.span_id.0.clone(),
            request.activation.trace.trace_flags,
            request.activation.trace.baggage.clone(),
            request.activation.deadline_unix_millis,
            request.budget.clone(),
            request.activation.metadata.clone(),
        );
        let host_state = HostState::new(
            host_context,
            maximum_memory_bytes,
            self.config.invocation_log_maximum_entries,
            self.config.invocation_log_maximum_bytes,
        );

        let contained_execution_started = Instant::now();
        let host_state_guard = self.resources.host_state();
        let store_guard = self.resources.store();
        let mut store = Store::new(&self.engine, host_state);
        store.set_hostcall_fuel(hostcall_fuel_limit(
            self.config.invocation_log_maximum_bytes,
            request.budget.log_bytes,
        ));
        store.limiter(|state| &mut state.limiter);
        store.set_fuel(request.budget.cpu_fuel).map_err(|error| {
            platform_error(
                PlatformErrorCode::Internal,
                &format!(
                    "failed to initialize invocation fuel: {}",
                    bounded_error(&error)
                ),
                false,
            )
        })?;
        configure_epoch(
            &mut store,
            Arc::clone(&stop),
            self.config.epoch_deadline_ticks,
        );

        let component_instance_guard = self.resources.component_instance();
        let (call_result, component_instance) =
            match runtime.pre.instantiate_async(&mut store).await {
                Ok(instance) => {
                    timing.backend_setup_micros = elapsed_micros(setup_started);
                    let guest_call_started = Instant::now();
                    let result = instance
                        .examples_echo_api()
                        .call_echo(&mut store, &input)
                        .await;
                    timing.guest_call_micros = elapsed_micros(guest_call_started);
                    (result, Some(instance))
                }
                Err(error) => {
                    timing.backend_setup_micros = elapsed_micros(setup_started);
                    (Err(error), None)
                }
            };

        // The generated typed call completes Wasmtime's canonical-ABI
        // post-return before it yields. This explicit boundary separates that
        // completed guest/component call from the host-side result extraction
        // and subsequent resource reclamation below.
        let component_post_return_started = Instant::now();
        let remaining_fuel = store.get_fuel().unwrap_or(0);
        let wall_time_micros = elapsed_micros(contained_execution_started);
        let HostCallTiming {
            calls: host_call_count,
            elapsed_micros: host_call_micros,
        } = store.data().host_call_timing();
        let consumption = BudgetConsumption {
            cpu_fuel: request.budget.cpu_fuel.saturating_sub(remaining_fuel),
            peak_memory_bytes: store.data().limiter.peak_memory_bytes(),
            wall_time_micros,
            log_bytes: store.data().logs.bytes(),
            ..BudgetConsumption::default()
        };
        let logs = store.data().logs.entries();
        let memory_exhausted = call_result
            .as_ref()
            .err()
            .is_some_and(is_memory_limit_error);
        timing.host_call_count = host_call_count;
        timing.host_call_micros = host_call_micros;
        timing.component_post_return_micros = elapsed_micros(component_post_return_started);

        // Cleanup order is intentional: after the guest call and its
        // component-model post-return complete, the actual component instance,
        // store/host state, temporary input, and all activation-owned guards
        // are reclaimed before a reusable proof escapes.
        let reclamation_started = Instant::now();
        drop(component_instance);
        drop(component_instance_guard);
        drop(store);
        drop(store_guard);
        drop(host_state_guard);
        drop(input);
        drop(temporary_buffer_guard);
        timing.activation_resource_reclamation_micros = elapsed_micros(reclamation_started);

        let classification_started = Instant::now();
        let outcome = match call_result {
            Ok(Ok(output)) => Ok(GuestOutcome::Returned {
                output: output.into_bytes(),
                output_media_type: ECHO_SUCCESS_MEDIA_TYPE.to_owned(),
                consumption,
            }),
            Ok(Err(bindings::exports::examples::echo::api::EchoError::EmptyMessage)) => {
                Ok(GuestOutcome::Returned {
                    output: EMPTY_MESSAGE_OUTPUT.to_vec(),
                    output_media_type: ECHO_DOMAIN_ERROR_MEDIA_TYPE.to_owned(),
                    consumption,
                })
            }
            Ok(Err(bindings::exports::examples::echo::api::EchoError::MessageTooLarge)) => {
                Ok(GuestOutcome::Returned {
                    output: MESSAGE_TOO_LARGE_OUTPUT.to_vec(),
                    output_media_type: ECHO_DOMAIN_ERROR_MEDIA_TYPE.to_owned(),
                    consumption,
                })
            }
            Err(error) => classify_runtime_error(&error, &stop, memory_exhausted, consumption),
        };
        timing.outcome_classification_micros = elapsed_micros(classification_started);

        let reusable_proof_started = Instant::now();
        drop(stop);
        drop(cancellation_guard);
        self.log_sink.publish(logs);
        timing.reusable_proof_micros = elapsed_micros(reusable_proof_started);
        outcome
    }

    fn validate_key(
        &self,
        artifact: &CapsuleArtifact,
        key: &PreparationKey,
    ) -> Result<(), PlatformError> {
        if key.release != artifact.descriptor.release_digest {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "preparation release does not match the artifact descriptor",
                false,
            ));
        }
        let expected_digest = self
            .profile
            .configuration
            .get("configuration-digest")
            .expect("profile always contains a configuration digest");
        if key.engine_version != self.profile.wasmtime_version
            || &key.engine_configuration_digest != expected_digest
            || key.target_triple != self.profile.target_triple
            || key.cpu_feature_set != self.profile.cpu_feature_set
        {
            return Err(platform_error(
                PlatformErrorCode::IncompatibleContract,
                "preparation key does not match the active Wasmtime engine profile",
                false,
            ));
        }
        Ok(())
    }

    fn validate_manifest(&self, artifact: &CapsuleArtifact) -> Result<(), PlatformError> {
        let manifest = &artifact.manifest;
        if manifest.world.0 != ECHO_WORLD {
            return Err(error_with_detail(
                PlatformErrorCode::IncompatibleContract,
                "capsule declares an unexpected WIT world",
                "unexpected-world",
                [
                    ("expected", ECHO_WORLD.to_owned()),
                    ("actual", manifest.world.0.clone()),
                ],
            ));
        }
        if manifest.execution.backend != ExecutionBackendKind::WasmComponent {
            return Err(platform_error(
                PlatformErrorCode::IncompatibleContract,
                "capsule does not select the Wasm Component execution backend",
                false,
            ));
        }

        let exports = manifest
            .exports
            .iter()
            .map(|export| export.contract.0.as_str())
            .collect::<BTreeSet<_>>();
        if exports != BTreeSet::from([ECHO_EXPORT]) {
            return Err(platform_error(
                PlatformErrorCode::IncompatibleContract,
                "capsule exports do not match the Phase 0 echo contract",
                false,
            ));
        }
        let imports = manifest
            .imports
            .iter()
            .map(|import| import.contract.0.as_str())
            .collect::<BTreeSet<_>>();
        if imports != BTreeSet::from([CONTEXT_IMPORT, LOG_IMPORT])
            || manifest.imports.iter().any(|import| import.optional)
        {
            return Err(platform_error(
                PlatformErrorCode::IncompatibleContract,
                "capsule imports do not match the two required Phase 0 host capabilities",
                false,
            ));
        }

        let declared = &manifest.execution.resource_budget_ceiling;
        if declared.memory_bytes == 0
            || declared.memory_bytes > self.config.maximum_memory_bytes
            || declared.cpu_fuel == 0
            || declared.cpu_fuel > self.config.maximum_fuel
        {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "capsule-declared resource limits exceed the Phase 0 engine profile",
                false,
            ));
        }
        Ok(())
    }

    fn validate_component_surface(&self, component: &Component) -> Result<(), PlatformError> {
        let component_type = component.component_type();
        let imports = component_type
            .imports(&self.engine)
            .map(|(name, _)| name.to_owned())
            .collect::<BTreeSet<_>>();
        let exports = component_type
            .exports(&self.engine)
            .map(|(name, _)| name.to_owned())
            .collect::<BTreeSet<_>>();
        let expected_imports = BTreeSet::from([CONTEXT_IMPORT.to_owned(), LOG_IMPORT.to_owned()]);
        let expected_exports = BTreeSet::from([ECHO_EXPORT.to_owned()]);
        if imports != expected_imports || exports != expected_exports {
            return Err(error_with_detail(
                PlatformErrorCode::IncompatibleContract,
                "component import/export surface does not match the Phase 0 echo world",
                "unexpected-component-surface",
                [
                    ("imports", imports.into_iter().collect::<Vec<_>>().join(",")),
                    ("exports", exports.into_iter().collect::<Vec<_>>().join(",")),
                ],
            ));
        }
        Ok(())
    }

    fn validate_bound_imports(&self, request: &ExecutionRequest) -> Result<(), PlatformError> {
        let imports = request
            .imports
            .iter()
            .map(|import| import.contract.as_str())
            .collect::<BTreeSet<_>>();
        if imports != BTreeSet::from([CONTEXT_IMPORT, LOG_IMPORT])
            || request.imports.len() != 2
            || request
                .imports
                .iter()
                .any(|import| import.opaque_handle.is_empty())
        {
            return Err(platform_error(
                PlatformErrorCode::IncompatibleContract,
                "execution request does not bind exactly the context and log imports",
                false,
            ));
        }
        Ok(())
    }

    fn validate_invocation_budget(
        &self,
        requested: &ResourceBudget,
        declared: &ResourceBudget,
    ) -> Result<(), PlatformError> {
        if requested.cpu_fuel == 0
            || requested.cpu_fuel > declared.cpu_fuel
            || requested.cpu_fuel > self.config.maximum_fuel
            || requested.memory_bytes == 0
            || requested.memory_bytes > declared.memory_bytes
            || requested.memory_bytes > self.config.maximum_memory_bytes
            || requested.child_calls > declared.child_calls
            || requested.outbound_requests > declared.outbound_requests
            || requested.state_read_bytes > declared.state_read_bytes
            || requested.state_write_bytes > declared.state_write_bytes
            || requested.blob_read_bytes > declared.blob_read_bytes
            || requested.blob_write_bytes > declared.blob_write_bytes
            || requested.log_bytes > declared.log_bytes
            || requested.effect_count > declared.effect_count
        {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "invocation budget exceeds the capsule or engine limit",
                false,
            ));
        }
        Ok(())
    }

    fn prepared_descriptor(
        &self,
        key: PreparationKey,
        handle: String,
        component_digest: String,
    ) -> PreparedComponent {
        let mut metadata = Metadata::new();
        metadata.insert("world".to_owned(), ECHO_WORLD.to_owned());
        metadata.insert(
            "imports".to_owned(),
            format!("{CONTEXT_IMPORT},{LOG_IMPORT}"),
        );
        metadata.insert("exports".to_owned(), ECHO_EXPORT.to_owned());
        metadata.insert("component-digest".to_owned(), component_digest);
        metadata.insert(
            "cache".to_owned(),
            if self.config.prepared_cache_enabled {
                "bounded-node-owned"
            } else {
                "runner-scoped-no-reuse"
            }
            .to_owned(),
        );
        metadata.insert(
            "resident-state".to_owned(),
            "compiled-component,linker,typed-indices".to_owned(),
        );
        metadata.insert("ambient-authority".to_owned(), "none".to_owned());
        PreparedComponent {
            key,
            backend: BACKEND_ID.to_owned(),
            opaque_handle: handle,
            metadata,
        }
    }

    fn lock_cache(&self) -> MutexGuard<'_, PreparedCache> {
        self.cache
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn lock_uncached_prepared(&self) -> MutexGuard<'_, Option<(String, Arc<PreparedRuntime>)>> {
        self.uncached_prepared
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn prepared_runtime(&self, handle: &str) -> Option<Arc<PreparedRuntime>> {
        if self.config.prepared_cache_enabled {
            self.lock_cache().get(handle)
        } else {
            self.lock_uncached_prepared()
                .as_ref()
                .and_then(|(candidate, runtime)| (candidate == handle).then(|| Arc::clone(runtime)))
        }
    }

    fn lock_timings(&self) -> MutexGuard<'_, InvocationTimingStore> {
        self.timings
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl ExecutionBackend for Phase0WasmtimeBackend {
    fn backend_id(&self) -> &str {
        BACKEND_ID
    }

    fn prepare<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        Box::pin(async move { self.prepare_inner(artifact, key) })
    }

    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async move { self.invoke_inner(request, cancellation).await })
    }

    fn invoke_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            let activation_id = request.activation.activation_id.clone();
            let outcome = self.invoke_inner(request, cancellation).await;
            let proof_started = Instant::now();
            let report = ExecutionReport::reusable(outcome);
            self.lock_timings()
                .update_reusable_proof(&activation_id.0, elapsed_micros(proof_started));
            report
        })
    }

    fn release<'a>(
        &'a self,
        prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            if prepared.backend != BACKEND_ID {
                return Err(platform_error(
                    PlatformErrorCode::InvalidArgument,
                    "prepared component belongs to another execution backend",
                    false,
                ));
            }
            if self.config.prepared_cache_enabled {
                self.lock_cache().remove(&prepared.opaque_handle);
            } else {
                let mut uncached = self.lock_uncached_prepared();
                if uncached
                    .as_ref()
                    .is_some_and(|(handle, _)| handle == &prepared.opaque_handle)
                {
                    *uncached = None;
                }
            }
            Ok(())
        })
    }
}

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn is_memory_limit_error(error: &wasmtime::Error) -> bool {
    let message = error.to_string().to_ascii_lowercase();
    message.contains("aggregate linear-memory budget exceeded")
        || message.contains("memory minimum size")
        || message.contains("memory size") && message.contains("limit")
}

fn prepared_handle(key: &PreparationKey, component_digest: &str) -> String {
    let material = format!(
        "{}\n{}\n{}\n{}\n{}\n{}",
        key.release.0,
        key.engine_version,
        key.engine_configuration_digest,
        key.target_triple,
        key.cpu_feature_set,
        component_digest,
    );
    format!("wasmtime:{}", blake3::hash(material.as_bytes()).to_hex())
}

fn sha256_digest(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity("sha256:".len() + digest.len() * 2);
    output.push_str("sha256:");
    for byte in digest {
        write!(&mut output, "{byte:02x}").expect("writing to String cannot fail");
    }
    output
}

#[cfg(test)]
mod timing_tests {
    use super::{InvocationTimingStore, Phase0InvocationTiming};

    #[test]
    fn timing_store_snapshot_reports_bounded_occupancy() {
        let mut store = InvocationTimingStore::new(2);
        assert_eq!(store.snapshot().entries, 0);
        assert_eq!(store.snapshot().maximum_entries, 2);

        store.insert("first".to_owned(), Phase0InvocationTiming::default());
        store.insert("second".to_owned(), Phase0InvocationTiming::default());
        assert_eq!(store.snapshot().entries, 2);

        store.insert("third".to_owned(), Phase0InvocationTiming::default());
        assert_eq!(store.snapshot().entries, 2);
        assert!(store.remove("first").is_none());
        assert!(store.remove("second").is_some());
        assert_eq!(store.snapshot().entries, 1);
    }
}

fn error_with_detail<const N: usize>(
    code: PlatformErrorCode,
    message: &str,
    kind: &str,
    fields: [(&str, String); N],
) -> PlatformError {
    let fields = fields
        .into_iter()
        .map(|(name, value)| (name.to_owned(), bounded_text(&value, MAX_DIAGNOSTIC_BYTES)))
        .collect();
    PlatformError {
        code,
        message: bounded_text(message, MAX_DIAGNOSTIC_BYTES),
        retryable: false,
        details: vec![ErrorDetail {
            kind: kind.to_owned(),
            fields,
        }],
    }
}

fn bounded_error(error: &wasmtime::Error) -> String {
    bounded_text(&error.to_string(), MAX_DIAGNOSTIC_BYTES)
}

#[cfg(test)]
mod tests {
    use super::{Phase0InstanceAllocator, Phase0WasmtimeConfig, Phase0WasmtimeEngineFactory};
    use crate::WasmtimeEngineFactory as _;

    #[test]
    fn profiles_explicit_bounded_allocator_and_cow_experiments() {
        let on_demand = Phase0WasmtimeConfig::default();
        let on_demand_factory =
            Phase0WasmtimeEngineFactory::new(on_demand.clone()).expect("default factory builds");
        assert!(!on_demand_factory.profile().pooling_allocator);
        assert!(on_demand_factory.profile().copy_on_write_images);
        assert_eq!(
            on_demand_factory
                .profile()
                .configuration
                .get("instance-allocation-strategy")
                .map(String::as_str),
            Some("on_demand")
        );

        let pooling = Phase0WasmtimeConfig {
            instance_allocator: Phase0InstanceAllocator::Pooling,
            copy_on_write_images: false,
            pooling_maximum_instances: 2,
            ..on_demand
        };
        let pooling_factory =
            Phase0WasmtimeEngineFactory::new(pooling).expect("bounded pooling factory builds");
        assert!(pooling_factory.profile().pooling_allocator);
        assert!(!pooling_factory.profile().copy_on_write_images);
        assert_eq!(
            pooling_factory
                .profile()
                .configuration
                .get("pooling-linear-memory-keep-resident-bytes")
                .map(String::as_str),
            Some("0")
        );
    }

    #[test]
    fn rejects_an_unbounded_pooling_experiment() {
        let config = Phase0WasmtimeConfig {
            instance_allocator: Phase0InstanceAllocator::Pooling,
            pooling_maximum_instances: 0,
            ..Phase0WasmtimeConfig::default()
        };
        assert!(Phase0WasmtimeEngineFactory::new(config).is_err());
    }
}
