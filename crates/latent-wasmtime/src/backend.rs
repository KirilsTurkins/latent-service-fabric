use std::collections::{BTreeSet, HashMap, VecDeque};
use std::fmt::Write as _;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Instant;

use latent_artifacts::CapsuleArtifact;
use latent_core::{
    BoxFuture, BudgetConsumption, ErrorDetail, Metadata, PlatformError, PlatformErrorCode,
    ReleaseDigest, ResourceBudget,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionRequest, GuestOutcome, GuestTrap,
    PreparationKey, PreparedComponent,
};
use latent_manifest::ExecutionBackendKind;
use sha2::{Digest, Sha256};
use wasmtime::component::{Component, HasSelf, Linker};
use wasmtime::{Config, Engine, Store, WasmBacktraceDetails};

use crate::bindings;
use crate::host::{
    hostcall_fuel_limit, ActivationHostContext, BoundedLogSink, HostState,
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
const MAX_DIAGNOSTIC_BYTES: usize = 512;

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
    pub invocation_log_maximum_entries: usize,
    pub invocation_log_maximum_bytes: usize,
    pub retained_log_maximum_entries: usize,
    pub retained_log_maximum_bytes: usize,
    pub epoch_deadline_ticks: u64,
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
            invocation_log_maximum_entries: 8,
            invocation_log_maximum_bytes: 16 * 1024,
            retained_log_maximum_entries: 256,
            retained_log_maximum_bytes: 512 * 1024,
            epoch_deadline_ticks: 1,
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
            || self.epoch_deadline_ticks == 0;
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
             max-fuel={};wasm-stack={};async-stack={};cache-entries={};\
             cache-bytes={};invocation-log-entries={};invocation-log-bytes={};\
             retained-log-entries={};retained-log-bytes={};epoch-ticks={};target={};cpu={}",
            self.maximum_component_bytes,
            self.maximum_memory_bytes,
            self.maximum_fuel,
            self.maximum_wasm_stack_bytes,
            self.async_stack_bytes,
            self.prepared_cache_maximum_entries,
            self.prepared_cache_maximum_source_bytes,
            self.invocation_log_maximum_entries,
            self.invocation_log_maximum_bytes,
            self.retained_log_maximum_entries,
            self.retained_log_maximum_bytes,
            self.epoch_deadline_ticks,
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
        engine_config.wasm_backtrace_details(WasmBacktraceDetails::Disable);
        engine_config.wasm_backtrace_max_frames(None);

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

        let configuration_digest = config.configuration_digest();
        let mut configuration = Metadata::new();
        configuration.insert("component-model".to_owned(), "enabled".to_owned());
        configuration.insert("component-model-async".to_owned(), "enabled".to_owned());
        configuration.insert("fuel".to_owned(), "enabled".to_owned());
        configuration.insert("epoch-interruption".to_owned(), "enabled".to_owned());
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
        configuration.insert("ambient-wasi-authority".to_owned(), "none".to_owned());
        configuration.insert("configuration-digest".to_owned(), configuration_digest);

        let profile = WasmtimeEngineProfile {
            id: BACKEND_ID.to_owned(),
            wasmtime_version: WASMTIME_VERSION.to_owned(),
            target_triple: config.target_triple.clone(),
            cpu_feature_set: config.cpu_feature_set.clone(),
            pooling_allocator: false,
            copy_on_write_images: false,
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

pub struct Phase0WasmtimeBackend {
    engine: Engine,
    profile: WasmtimeEngineProfile,
    config: Phase0WasmtimeConfig,
    cache: Mutex<PreparedCache>,
    log_sink: BoundedLogSink,
    stores_created: AtomicU64,
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
            config,
            log_sink,
            stores_created: AtomicU64::new(0),
        }
    }

    pub fn cache_snapshot(&self) -> PreparedCacheSnapshot {
        self.lock_cache().snapshot()
    }

    pub fn stores_created(&self) -> u64 {
        self.stores_created.load(Ordering::Relaxed)
    }

    pub fn log_sink(&self) -> BoundedLogSink {
        self.log_sink.clone()
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
        if self.lock_cache().get(&handle).is_some() {
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
        self.lock_cache()
            .insert(handle.clone(), artifact.component_bytes.len(), runtime)?;
        Ok(self.prepared_descriptor(key.clone(), handle, component_digest))
    }

    async fn invoke_inner(
        &self,
        request: ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
    ) -> Result<GuestOutcome, PlatformError> {
        if cancellation.activation_id() != &request.activation.activation_id {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "cancellation handle belongs to a different activation",
                false,
            ));
        }
        if cancellation.is_cancelled() {
            return Ok(GuestOutcome::Interrupted {
                reason: cancellation.reason().map_or_else(
                    || "cancelled before guest execution".to_owned(),
                    |reason| bounded_text(&reason, MAX_DIAGNOSTIC_BYTES),
                ),
                consumption: BudgetConsumption::default(),
            });
        }
        if request.prepared.backend != BACKEND_ID {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "prepared component belongs to another execution backend",
                false,
            ));
        }

        let runtime = self
            .lock_cache()
            .get(&request.prepared.opaque_handle)
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

        let input = String::from_utf8(request.activation.input.clone()).map_err(|_| {
            platform_error(
                PlatformErrorCode::InvalidArgument,
                "the Phase 0 echo input must be valid UTF-8",
                false,
            )
        })?;
        let activation_id = request.activation.activation_id.clone();
        let host_context = ActivationHostContext::new(
            activation_id.clone(),
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

        let started = Instant::now();
        self.stores_created.fetch_add(1, Ordering::Relaxed);
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
        #[cfg(target_has_atomic = "64")]
        store.set_epoch_deadline(self.config.epoch_deadline_ticks);

        let instance = runtime
            .pre
            .instantiate_async(&mut store)
            .await
            .map_err(|error| {
                platform_error(
                    PlatformErrorCode::DependencyFailed,
                    &format!("component instantiation failed: {}", bounded_error(&error)),
                    false,
                )
            })?;
        let call_result = instance
            .examples_echo_api()
            .call_echo(&mut store, &input)
            .await;

        let remaining_fuel = store.get_fuel().unwrap_or(0);
        let wall_time_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let consumption = BudgetConsumption {
            cpu_fuel: request.budget.cpu_fuel.saturating_sub(remaining_fuel),
            peak_memory_bytes: store.data().limiter.peak_memory_bytes(),
            wall_time_micros,
            log_bytes: store.data().logs.bytes(),
            ..BudgetConsumption::default()
        };
        let logs = store.data().logs.entries();

        drop(instance);
        drop(store);
        self.log_sink.publish(logs);

        match call_result {
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
            Err(error) => Ok(GuestOutcome::Trapped {
                trap: GuestTrap {
                    code: "guest-trap".to_owned(),
                    message: bounded_error(&error),
                    guest_backtrace: Vec::new(),
                    metadata: Metadata::new(),
                },
                consumption,
            }),
        }
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
        metadata.insert("cache".to_owned(), "bounded-node-owned".to_owned());
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
            self.lock_cache().remove(&prepared.opaque_handle);
            Ok(())
        })
    }
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

fn platform_error(code: PlatformErrorCode, message: &str, retryable: bool) -> PlatformError {
    PlatformError {
        code,
        message: bounded_text(message, MAX_DIAGNOSTIC_BYTES),
        retryable,
        details: Vec::new(),
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

fn bounded_text(value: &str, maximum_bytes: usize) -> String {
    if value.len() <= maximum_bytes {
        return value.to_owned();
    }
    let mut end = maximum_bytes;
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    value[..end].to_owned()
}
