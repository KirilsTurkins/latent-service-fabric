use std::collections::BTreeSet;
use std::fmt::Write as _;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

use latent_artifacts::CapsuleArtifact;
use latent_core::{
    ActivationId, BoxFuture, BudgetConsumption, Metadata, PlatformError, PlatformErrorCode,
    ResourceBudget,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionReport, ExecutionRequest, GuestOutcome,
    PreparationKey, PreparedComponent,
};
use latent_manifest::{ExecutionBackendKind, StateModel, ThreadingModel};
use sha2::{Digest, Sha256};
use wasmtime::component::{Component, HasSelf, InstancePre, Linker, Val};
use wasmtime::{Engine, Store};

use crate::bindings;
use crate::cache::{ActiveInstanceGate, PrepareAccess, PreparedCache, PreparedCacheSnapshot};
use crate::config::{WasmtimeConfig, PHASE0_BACKEND_ID};
use crate::containment::{
    bounded_text, classify_runtime_error, configure_epoch, interrupted_outcome, monotonic_deadline,
    platform_error, RuntimeResourceCounters, RuntimeResourceSnapshot, StopControl,
    MAX_DIAGNOSTIC_BYTES,
};
use crate::host::{
    validate_request_context, ActivationHostContext, BoundedLogSink, HostCallTiming, HostState,
};
use crate::timing::{InvocationTimingStore, InvocationTimingStoreSnapshot, Phase0InvocationTiming};
use crate::{surface, values, WasmtimeEngineProfile};

struct PreparedRuntime {
    pre: InstancePre<HostState>,
    declared_budget: ResourceBudget,
    surface: surface::Surface,
    descriptor: PreparedComponent,
}

/// Immutable compiled state and bounded diagnostics owned by one node factory.
pub(crate) struct SharedRuntime {
    cache: Arc<PreparedCache<PreparedRuntime>>,
    instances: Arc<ActiveInstanceGate>,
    uncached_prepared: Mutex<Option<(String, Arc<PreparedRuntime>)>>,
    pub(crate) log_sink: BoundedLogSink,
    resources: RuntimeResourceCounters,
    timings: Mutex<InvocationTimingStore>,
}
impl SharedRuntime {
    pub(crate) fn new(config: &WasmtimeConfig) -> Result<Self, PlatformError> {
        Ok(Self {
            cache: Arc::new(PreparedCache::new(config.cache_limits())?),
            instances: Arc::new(ActiveInstanceGate::new(config.active_instance_limit())?),
            uncached_prepared: Mutex::new(None),
            log_sink: BoundedLogSink::new(
                config.retained_log_maximum_entries,
                config.retained_log_maximum_bytes,
            ),
            resources: RuntimeResourceCounters::default(),
            timings: Mutex::new(InvocationTimingStore::new(256)),
        })
    }
}

/// Generic interface/function dispatch with a fresh store for every invocation.
pub struct WasmtimeBackend {
    engine: Engine,
    profile: WasmtimeEngineProfile,
    pub(crate) config: WasmtimeConfig,
    shared: Arc<SharedRuntime>,
}
impl WasmtimeBackend {
    pub(crate) fn new(
        engine: Engine,
        profile: WasmtimeEngineProfile,
        config: WasmtimeConfig,
        shared: Arc<SharedRuntime>,
    ) -> Self {
        Self {
            engine,
            profile,
            config,
            shared,
        }
    }
    #[must_use]
    pub fn cache_snapshot(&self) -> PreparedCacheSnapshot {
        self.shared.cache.snapshot()
    }
    #[must_use]
    pub fn stores_created(&self) -> u64 {
        self.resource_snapshot().stores_created
    }
    #[must_use]
    pub fn resource_snapshot(&self) -> RuntimeResourceSnapshot {
        self.shared.resources.snapshot()
    }
    #[must_use]
    pub fn invocation_timing_snapshot(&self) -> InvocationTimingStoreSnapshot {
        self.lock_timings().snapshot()
    }
    #[must_use]
    pub fn log_sink(&self) -> BoundedLogSink {
        self.shared.log_sink.clone()
    }
    #[must_use]
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
        let identity = crate::preparation_metadata::identity(
            artifact,
            self.config.maximum_artifact_metadata_bytes,
            self.config.value_codec_limits.max_depth,
        )?;
        self.validate_key(artifact, key)?;
        self.validate_manifest(artifact)?;
        let component_digest = self.validate_component_bytes(artifact)?;
        let handle = prepared_handle(key, &component_digest, &identity.digest);
        let reserved_metadata = identity
            .bytes
            .checked_add(self.config.maximum_artifact_metadata_bytes)
            .ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::ResourceExhausted,
                    "prepared metadata reservation overflowed",
                    false,
                )
            })?;
        // The reservation lives through all synchronous compilation and validation,
        // including unwind. No store or component instance is created here.
        let reservation = match self.shared.cache.begin(
            handle.clone(),
            artifact.component_bytes.len(),
            reserved_metadata,
        )? {
            PrepareAccess::Hit(runtime) => return Ok(runtime.descriptor.clone()),
            PrepareAccess::Compile(reservation) => reservation,
        };
        let component =
            Component::new(&self.engine, &artifact.component_bytes).map_err(|error| {
                platform_error(
                    PlatformErrorCode::CorruptArtifact,
                    &format!("component validation failed: {}", bounded_error(&error)),
                    false,
                )
            })?;
        let surface = surface::validate(&component, &self.engine, artifact, &self.config)?;
        let metadata_bytes = identity
            .bytes
            .checked_add(surface.retained_bytes)
            .ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::ResourceExhausted,
                    "prepared metadata accounting overflowed",
                    false,
                )
            })?;
        let pre = self.link_component(&component)?;
        if self.profile.id == PHASE0_BACKEND_ID {
            crate::phase0::validate_prepared(&pre)?;
        }
        let image = component.image_range();
        let image_bytes = image.end.addr().saturating_sub(image.start.addr());
        let descriptor =
            self.prepared_descriptor(artifact, key.clone(), handle.clone(), component_digest);
        let runtime = Arc::new(PreparedRuntime {
            pre,
            declared_budget: artifact.manifest.execution.resource_budget_ceiling.clone(),
            surface,
            descriptor: descriptor.clone(),
        });
        if self.config.prepared_cache_enabled {
            reservation.publish_with_metadata(runtime, image_bytes, metadata_bytes)?;
        } else {
            if image_bytes > self.config.prepared_cache_maximum_compiled_image_bytes {
                return Err(platform_error(
                    PlatformErrorCode::ResourceExhausted,
                    "compiled component image exceeds the configured limit",
                    false,
                ));
            }
            let mut slot = self.lock_uncached_prepared();
            if slot.is_some() {
                return Err(platform_error(
                    PlatformErrorCode::StateConflict,
                    "cache-disabled preparation is still owned by an active runner",
                    true,
                ));
            }
            *slot = Some((handle, runtime));
            drop(slot);
            drop(reservation);
        }
        Ok(descriptor)
    }
    fn validate_component_bytes(
        &self,
        artifact: &CapsuleArtifact,
    ) -> Result<String, PlatformError> {
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
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "component content digest does not match the capsule manifest",
                false,
            ));
        }
        Ok(component_digest)
    }

    fn link_component(
        &self,
        component: &Component,
    ) -> Result<InstancePre<HostState>, PlatformError> {
        let mut linker = Linker::<HostState>::new(&self.engine);
        bindings::Service::add_to_linker::<_, HasSelf<_>>(&mut linker, |state| state).map_err(
            |error| {
                platform_error(
                    PlatformErrorCode::Internal,
                    &format!("failed to bind host imports: {}", bounded_error(&error)),
                    false,
                )
            },
        )?;
        let pre = linker.instantiate_pre(component).map_err(|error| {
            platform_error(
                PlatformErrorCode::IncompatibleContract,
                &format!(
                    "component imports cannot be resolved: {}",
                    bounded_error(&error)
                ),
                false,
            )
        })?;
        Ok(pre)
    }

    async fn invoke_inner(
        &self,
        request: ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
    ) -> Result<GuestOutcome, PlatformError> {
        validate_request_context(&request, self.config.maximum_artifact_metadata_bytes)?;
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
        request: ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        timing: &mut Phase0InvocationTiming,
    ) -> Result<GuestOutcome, PlatformError> {
        let setup_started = Instant::now();
        let _active_invocation = self.shared.resources.active_invocation();

        if let Some(outcome) =
            cancellation_before_execution(&request.activation.activation_id, cancellation)?
        {
            return Ok(outcome);
        }
        if request.prepared.backend != self.profile.id {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "prepared component belongs to another execution backend",
                false,
            ));
        }

        let instance_permit = self.shared.instances.try_acquire()?;
        let runtime = self
            .prepared_runtime(&request.prepared.opaque_handle)
            .ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::NotFound,
                    "prepared component is absent or has been evicted",
                    true,
                )
            })?;
        let function = self.requested_function(&runtime, &request)?;
        let temporary_buffer_guard = self.shared.resources.temporary_buffer();
        let input = values::decode_params(
            &function.params,
            &request.activation.input,
            &request.activation.input_media_type,
            self.config.value_codec_limits,
        )?;

        let cancellation_probe = cancellation.probe();
        let cancellation_guard = cancellation_probe
            .as_ref()
            .map(|_| self.shared.resources.cancellation_probe());
        let deadline = invocation_deadline(&request, cancellation)?;
        let stop = Arc::new(StopControl::new(deadline, cancellation_probe));
        if let Some(kind) = stop.observe() {
            return Ok(interrupted_outcome(
                kind,
                stop.reason(kind),
                BudgetConsumption::default(),
            ));
        }

        let contained_execution_started = Instant::now();
        let host_state_guard = self.shared.resources.host_state();
        let store_guard = self.shared.resources.store();
        let mut store = self.invocation_store(&request, &stop)?;

        let component_instance_guard = self.shared.resources.component_instance();
        let mut output = vec![Val::Bool(false); function.results.len()];
        let call_result = call_export(
            &runtime,
            function,
            &mut store,
            &input,
            &mut output,
            timing,
            setup_started,
        )
        .await;
        // Wasmtime 47's safe dynamic call completes canonical ABI post-return
        // before resolving, including propagation of post-return traps.
        let component_post_return_started = Instant::now();
        let (consumption, logs) =
            invocation_accounting(&store, &request, contained_execution_started, timing);
        let memory_exhausted = call_result
            .as_ref()
            .err()
            .is_some_and(is_memory_limit_error);
        timing.component_post_return_micros = elapsed_micros(component_post_return_started);

        let encoded = call_result.as_ref().ok().map(|()| {
            values::encode_result(&function.results, &output, self.config.value_codec_limits)
        });
        // Cleanup order is intentional: after the guest call and its
        // component-model post-return complete, the actual component instance,
        // store/host state, temporary input, and all activation-owned guards
        // are reclaimed before a reusable proof escapes.
        let reclamation_started = Instant::now();
        drop(store);
        drop(component_instance_guard);
        drop(store_guard);
        drop(host_state_guard);
        drop(input);
        drop(output);
        drop(runtime);
        drop(instance_permit);
        drop(temporary_buffer_guard);
        timing.activation_resource_reclamation_micros = elapsed_micros(reclamation_started);

        let classification_started = Instant::now();
        let outcome =
            classify_call_result(call_result, encoded, &stop, memory_exhausted, consumption);
        timing.outcome_classification_micros = elapsed_micros(classification_started);

        let reusable_proof_started = Instant::now();
        drop(stop);
        drop(cancellation_guard);
        self.shared.log_sink.publish(logs);
        timing.reusable_proof_micros = elapsed_micros(reusable_proof_started);
        outcome
    }

    fn requested_function<'a>(
        &self,
        runtime: &'a PreparedRuntime,
        request: &ExecutionRequest,
    ) -> Result<&'a surface::Function, PlatformError> {
        if runtime.descriptor.key != request.prepared.key {
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
        Self::validate_bound_imports(request, &runtime.surface.imports)?;
        self.validate_invocation_budget(&request.budget, &runtime.declared_budget)?;
        let function = runtime
            .surface
            .functions
            .get(&(
                request.activation.target.contract.0.clone(),
                request.activation.target.function.0.clone(),
            ))
            .ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::InvalidArgument,
                    "requested contract/function is absent from the prepared component",
                    false,
                )
            })?;
        Ok(function)
    }

    fn invocation_store(
        &self,
        request: &ExecutionRequest,
        stop: &Arc<StopControl>,
    ) -> Result<Store<HostState>, PlatformError> {
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
        let host_state = HostState::with_config(host_context, maximum_memory_bytes, &self.config);

        let mut store = Store::new(&self.engine, host_state);
        store.set_hostcall_fuel(self.config.hostcall_fuel);
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
            Arc::clone(stop),
            self.config.epoch_deadline_ticks,
        );

        Ok(store)
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
        if manifest.world.0.is_empty()
            || manifest.execution.backend != ExecutionBackendKind::WasmComponent
            || !matches!(
                manifest.execution.threading,
                ThreadingModel::SingleThreaded | ThreadingModel::Reentrant
            )
            || manifest.execution.state_model != StateModel::Stateless
        {
            return Err(platform_error(PlatformErrorCode::IncompatibleContract, "backend requires a named world with stateless, single-threaded or reentrant Wasm Component execution", false));
        }
        let declared = &manifest.execution.resource_budget_ceiling;
        if declared.memory_bytes == 0
            || declared.memory_bytes > self.config.maximum_memory_bytes
            || declared.cpu_fuel == 0
            || declared.cpu_fuel > self.config.maximum_fuel
            || declared.wall_time_limit_millis == Some(0)
        {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "capsule-declared resource limits exceed the engine profile",
                false,
            ));
        }
        Ok(())
    }
    fn validate_bound_imports(
        request: &ExecutionRequest,
        required: &BTreeSet<String>,
    ) -> Result<(), PlatformError> {
        let actual = request
            .imports
            .iter()
            .map(|import| import.contract.as_str())
            .collect::<BTreeSet<_>>();
        if request.imports.len() != required.len()
            || actual.len() != required.len()
            || !required.iter().all(|name| actual.contains(name.as_str()))
            || request
                .imports
                .iter()
                .any(|import| import.opaque_handle.is_empty())
        {
            return Err(platform_error(
                PlatformErrorCode::IncompatibleContract,
                "execution request does not bind the prepared component's imports",
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
            || declared.wall_time_limit_millis.is_some_and(|limit| {
                requested
                    .wall_time_limit_millis
                    .is_none_or(|requested| requested > limit)
            })
            || requested.wall_time_limit_millis == Some(0)
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
        artifact: &CapsuleArtifact,
        key: PreparationKey,
        handle: String,
        component_digest: String,
    ) -> PreparedComponent {
        let mut metadata = Metadata::new();
        metadata.insert("world".to_owned(), artifact.manifest.world.0.clone());
        metadata.insert(
            "imports".to_owned(),
            artifact
                .manifest
                .imports
                .iter()
                .map(|entry| entry.contract.0.as_str())
                .collect::<Vec<_>>()
                .join(","),
        );
        metadata.insert(
            "exports".to_owned(),
            artifact
                .manifest
                .exports
                .iter()
                .map(|entry| entry.contract.0.as_str())
                .collect::<Vec<_>>()
                .join(","),
        );
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
            "compiled-component,linker,dynamic-indices".to_owned(),
        );
        metadata.insert("ambient-authority".to_owned(), "none".to_owned());
        PreparedComponent {
            key,
            backend: self.profile.id.clone(),
            opaque_handle: handle,
            metadata,
        }
    }
    fn lock_uncached_prepared(&self) -> MutexGuard<'_, Option<(String, Arc<PreparedRuntime>)>> {
        self.shared
            .uncached_prepared
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn prepared_runtime(&self, handle: &str) -> Option<Arc<PreparedRuntime>> {
        if self.config.prepared_cache_enabled {
            self.shared.cache.get(handle)
        } else {
            self.lock_uncached_prepared()
                .as_ref()
                .and_then(|(candidate, runtime)| (candidate == handle).then(|| Arc::clone(runtime)))
        }
    }

    fn lock_timings(&self) -> MutexGuard<'_, InvocationTimingStore> {
        self.shared
            .timings
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl ExecutionBackend for WasmtimeBackend {
    fn backend_id(&self) -> &str {
        &self.profile.id
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
            if let Err(error) =
                validate_request_context(&request, self.config.maximum_artifact_metadata_bytes)
            {
                return ExecutionReport::reusable(Err(error));
            }
            let activation_id = request.activation.activation_id.clone();
            let outcome = self.invoke_inner(request, cancellation).await;
            let proof_started = Instant::now();
            let report = ExecutionReport::reusable(outcome);
            self.lock_timings()
                .update_reusable_proof(&activation_id.0, elapsed_micros(proof_started));
            report
        })
    }

    fn release(&self, prepared: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async move {
            if prepared.backend != self.profile.id {
                return Err(platform_error(
                    PlatformErrorCode::InvalidArgument,
                    "prepared component belongs to another execution backend",
                    false,
                ));
            }
            if self.config.prepared_cache_enabled {
                self.shared
                    .cache
                    .remove_matching(&prepared.opaque_handle, |runtime| {
                        runtime.descriptor.key == prepared.key
                    });
            } else {
                let mut uncached = self.lock_uncached_prepared();
                if uncached.as_ref().is_some_and(|(handle, runtime)| {
                    handle == &prepared.opaque_handle && runtime.descriptor.key == prepared.key
                }) {
                    *uncached = None;
                }
            }
            Ok(())
        })
    }
}

fn is_memory_limit_error(error: &wasmtime::Error) -> bool {
    let message = error.to_string().to_ascii_lowercase();
    message.contains("aggregate linear-memory budget exceeded")
        || message.contains("memory minimum size")
        || message.contains("memory size") && message.contains("limit")
}

fn prepared_handle(key: &PreparationKey, component_digest: &str, metadata_digest: &str) -> String {
    let material = format!(
        "{}\n{}\n{}\n{}\n{}\n{}\n{}",
        key.release.0,
        key.engine_version,
        key.engine_configuration_digest,
        key.target_triple,
        key.cpu_feature_set,
        component_digest,
        metadata_digest,
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

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}
fn bounded_error(error: &wasmtime::Error) -> String {
    bounded_text(&error.to_string(), MAX_DIAGNOSTIC_BYTES)
}

fn invocation_deadline(
    request: &ExecutionRequest,
    cancellation: &dyn ExecutionCancellation,
) -> Result<Option<Instant>, PlatformError> {
    if let Some(admitted) = cancellation.effective_deadline() {
        // Preserve the admission clock sample: queued time consumes this grant.
        let relative = request
            .budget
            .wall_time_limit_millis
            .map(|millis| {
                admitted
                    .admitted_at_monotonic()
                    .checked_add(Duration::from_millis(millis))
                    .ok_or_else(|| {
                        platform_error(
                            PlatformErrorCode::InvalidArgument,
                            "relative invocation deadline is out of range",
                            false,
                        )
                    })
            })
            .transpose()?;
        let envelope = request
            .activation
            .deadline_unix_millis
            .map(|deadline| {
                admitted
                    .admitted_at_monotonic()
                    .checked_add(Duration::from_millis(
                        deadline.saturating_sub(admitted.admitted_at_unix_millis()),
                    ))
                    .ok_or_else(|| {
                        platform_error(
                            PlatformErrorCode::InvalidArgument,
                            "absolute invocation deadline is out of range",
                            false,
                        )
                    })
            })
            .transpose()?;
        return Ok(earliest_deadline(
            earliest_deadline(admitted.monotonic(), relative),
            envelope,
        ));
    }
    let absolute = monotonic_deadline(request.activation.deadline_unix_millis)?;
    // Compatibility callers without an admission token get a bounded execution
    // interval. Node orchestration supplies the original token in Phase 1.
    let relative = request
        .budget
        .wall_time_limit_millis
        .map(|millis| {
            Instant::now()
                .checked_add(Duration::from_millis(millis))
                .ok_or_else(|| {
                    platform_error(
                        PlatformErrorCode::InvalidArgument,
                        "relative invocation deadline is out of range",
                        false,
                    )
                })
        })
        .transpose()?;
    Ok(earliest_deadline(absolute, relative))
}
fn earliest_deadline(first: Option<Instant>, second: Option<Instant>) -> Option<Instant> {
    match (first, second) {
        (Some(first), Some(second)) => Some(first.min(second)),
        (first, second) => first.or(second),
    }
}

async fn call_export(
    runtime: &PreparedRuntime,
    function: &surface::Function,
    store: &mut Store<HostState>,
    input: &[Val],
    output: &mut [Val],
    timing: &mut Phase0InvocationTiming,
    setup_started: Instant,
) -> wasmtime::Result<()> {
    match runtime.pre.instantiate_async(&mut *store).await {
        Ok(instance) => {
            timing.backend_setup_micros = elapsed_micros(setup_started);
            let guest_call_started = Instant::now();
            let result = match instance.get_func(&mut *store, function.index) {
                Some(func) => func.call_async(&mut *store, input, output).await,
                None => Err(wasmtime::Error::msg(
                    "validated component function index is absent",
                )),
            };
            timing.guest_call_micros = elapsed_micros(guest_call_started);
            result
        }
        Err(error) => {
            timing.backend_setup_micros = elapsed_micros(setup_started);
            Err(error)
        }
    }
}

fn classify_call_result(
    call_result: wasmtime::Result<()>,
    encoded: Option<Result<values::EncodedResult, PlatformError>>,
    stop: &StopControl,
    memory_exhausted: bool,
    consumption: BudgetConsumption,
) -> Result<GuestOutcome, PlatformError> {
    match call_result {
        Ok(()) => match encoded.expect("successful call encoded its values") {
            Ok(values::EncodedResult::Returned(output)) => Ok(GuestOutcome::Returned {
                output,
                output_media_type: values::MEDIA_TYPE.to_owned(),
                consumption,
            }),
            Ok(values::EncodedResult::DeclaredError(error)) => {
                Ok(GuestOutcome::DeclaredError { error, consumption })
            }
            Err(error) => Ok(GuestOutcome::Trapped {
                trap: latent_executor::GuestTrap {
                    code: if error.code == PlatformErrorCode::ResourceExhausted {
                        "result-limit-exceeded"
                    } else {
                        "invalid-component-result"
                    }
                    .to_owned(),
                    message: bounded_text(&error.message, MAX_DIAGNOSTIC_BYTES),
                    guest_backtrace: Vec::new(),
                    metadata: Metadata::from([(
                        "result-codec-error".to_owned(),
                        format!("{:?}", error.code),
                    )]),
                },
                consumption,
            }),
        },
        Err(error) => classify_runtime_error(&error, stop, memory_exhausted, consumption),
    }
}

fn invocation_accounting(
    store: &Store<HostState>,
    request: &ExecutionRequest,
    contained_execution_started: Instant,
    timing: &mut Phase0InvocationTiming,
) -> (BudgetConsumption, Vec<crate::host::CapturedLog>) {
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
    timing.host_call_count = host_call_count;
    timing.host_call_micros = host_call_micros;
    (consumption, logs)
}

fn cancellation_before_execution(
    activation_id: &ActivationId,
    cancellation: &dyn ExecutionCancellation,
) -> Result<Option<GuestOutcome>, PlatformError> {
    if cancellation.activation_id() != activation_id {
        return Err(platform_error(
            PlatformErrorCode::InvalidArgument,
            "cancellation handle belongs to a different activation",
            false,
        ));
    }
    if cancellation.is_cancelled() {
        return Ok(Some(interrupted_outcome(
            latent_executor::GuestInterruptionKind::Cancelled,
            cancellation.reason().map_or_else(
                || "cancelled before guest execution".to_owned(),
                |reason| bounded_text(&reason, MAX_DIAGNOSTIC_BYTES),
            ),
            BudgetConsumption::default(),
        )));
    }
    Ok(None)
}
