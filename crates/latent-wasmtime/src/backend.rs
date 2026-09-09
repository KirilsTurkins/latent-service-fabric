use std::collections::BTreeSet;
use std::fmt::Write as _;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Instant;

use latent_artifacts::{ArtifactPreparationIdentity, ArtifactRepository, CapsuleArtifact};
use latent_core::{
    ActivationClock, ActivationId, BoxFuture, BudgetConsumption, ContractId, Metadata,
    PlatformError, PlatformErrorCode, ResourceBudget,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionReport, ExecutionRequest, GuestOutcome,
    PreparationKey, PreparedActivation, PreparedComponent,
};
use sha2::{Digest, Sha256};
use wasmtime::component::{InstancePre, Val};
use wasmtime::{Engine, Store};

use crate::cache::{ActiveInstanceGate, PrepareAccess, PreparedCache, PreparedCacheSnapshot};
use crate::config::WasmtimeConfig;
use crate::containment::{
    bounded_text, classify_runtime_error, configure_epoch, interrupted_outcome, platform_error,
    EpochTicker, RuntimeResourceCounters, RuntimeResourceSnapshot, StopControl,
    MAX_DIAGNOSTIC_BYTES,
};
use crate::host::accounting::InvocationAccounting;
use crate::host::{
    validate_request_context, ActivationHostContext, BoundedLogSink, HostCallTiming, HostState,
};
use crate::invocation_input_observer::{
    InputTrace, InvocationInputDropReason, InvocationInputObserver, InvocationInputPhase,
};
use crate::preparation_observer::{PreparationJob, PreparationObserver, PreparationStage};
use crate::timing::{InvocationTimingStore, InvocationTimingStoreSnapshot, Phase0InvocationTiming};
use crate::{surface, values, ContextExposurePolicy, WasmtimeEngineProfile, WasmtimeHostServices};

#[cfg(test)]
mod dispatch_tests;
mod input;
mod owned;
mod preparation;
mod preparation_context;
mod readiness;
mod reclamation;
#[cfg(test)]
mod result_lifetime_tests;
use preparation_context::PreparationContext;
mod store;
use owned::WasmtimePreparedUse;
pub use preparation::PreparationActivitySnapshot;
use preparation::{Compilation, ComponentIntegrity, PreparationCounters};
use store::AccountedStore;

pub(crate) struct PreparedRuntime {
    pre: InstancePre<HostState>,
    declared_budget: ResourceBudget,
    surface: surface::Surface,
    descriptor: PreparedComponent,
    imports: Vec<ContractId>,
    authentication: Option<ArtifactPreparationIdentity>,
    metadata_bytes: usize,
    image_bytes: usize,
    // Runtime-owned costs retire only after all native and metadata fields.
    lifetime_charge: crate::cache::PreparedRuntimeCharge,
}

impl PreparedRuntime {
    pub(crate) fn descriptor(&self) -> &PreparedComponent {
        &self.descriptor
    }
}

impl crate::cache::TrackedPreparedValue for PreparedRuntime {
    fn runtime_charge(&self) -> &crate::cache::PreparedRuntimeCharge {
        &self.lifetime_charge
    }
}

/// Immutable compiled state and bounded diagnostics owned by one node factory.
pub(crate) struct SharedRuntime {
    // Join compiler jobs before the ticker, components and engine references.
    // Backends and affine ready/prepared owners retain this runtime until idle.
    pub(crate) compiler: Option<crate::compiler::CompilerPool<PreparedRuntime>>,
    epoch_ticker: EpochTicker,
    cache: Arc<PreparedCache<PreparedRuntime>>,
    instances: Arc<ActiveInstanceGate>,
    uncached_prepared: Arc<Mutex<Option<(String, Arc<PreparedRuntime>)>>>,
    pub(crate) log_sink: BoundedLogSink,
    clock: Arc<dyn ActivationClock>,
    clock_origin: Instant,
    context_policy: Arc<ContextExposurePolicy>,
    resources: RuntimeResourceCounters,
    timings: Mutex<InvocationTimingStore>,
    preparation: Arc<PreparationCounters>,
    pub(crate) preparation_observer: PreparationObserver,
    pub(crate) invocation_input_observer: InvocationInputObserver,
    preparation_context: Arc<PreparationContext>,
}
impl SharedRuntime {
    pub(crate) fn cache_accounting_snapshot(&self) -> crate::PreparedCacheAccountingSnapshot {
        self.cache.accounting_snapshot()
    }

    pub(crate) fn prepared_runtime_observer(&self) -> crate::PreparedRuntimeObserver {
        self.cache.prepared_runtime_observer()
    }

    pub(crate) fn new(
        config: &WasmtimeConfig,
        services: WasmtimeHostServices,
        epoch_ticker: EpochTicker,
        engine: Engine,
        profile: WasmtimeEngineProfile,
    ) -> Result<Self, PlatformError> {
        let cache = Arc::new(PreparedCache::new_tracked(config.cache_limits())?);
        let preparation = Arc::new(PreparationCounters::default());
        let preparation_observer = PreparationObserver::new(config.maximum_concurrent_preparations);
        let uncached_prepared = Arc::new(Mutex::new(None));
        let preparation_context = Arc::new(PreparationContext {
            engine,
            profile: profile.clone(),
            config: config.clone(),
            preparation: Arc::clone(&preparation),
            observer: preparation_observer.clone(),
            uncached: Arc::clone(&uncached_prepared),
            next_untrusted: std::sync::atomic::AtomicU64::new(0),
            runtime_ledger: cache
                .runtime_ledger()
                .expect("factory tracks runtime lifetimes"),
        });
        let compiler = if profile.id == crate::config::GENERIC_BACKEND_ID {
            Some(crate::compiler::CompilerPool::new(
                config,
                Arc::clone(&cache),
                preparation_observer.clone(),
                |runtime: &PreparedRuntime| (runtime.metadata_bytes, runtime.image_bytes),
            )?)
        } else {
            None
        };
        Ok(Self {
            epoch_ticker,
            cache,
            instances: Arc::new(ActiveInstanceGate::new(config.active_instance_limit())?),
            uncached_prepared,
            log_sink: BoundedLogSink::with_target(
                config.retained_log_maximum_entries,
                config.retained_log_maximum_bytes,
                services.log_sink,
            ),
            clock_origin: services.clock.monotonic_now(),
            clock: services.clock,
            context_policy: Arc::new(config.context_policy.clone()),
            resources: RuntimeResourceCounters::default(),
            timings: Mutex::new(InvocationTimingStore::new(256)),
            preparation,
            preparation_observer,
            invocation_input_observer: InvocationInputObserver::new(),
            preparation_context,
            compiler,
        })
    }

    pub(crate) fn shutdown(&mut self) -> Result<(), PlatformError> {
        // Unique ownership is established by the factory before this call. No
        // cache, diagnostics, or backend lock is held while joining the worker.
        let compiler = self
            .compiler
            .as_mut()
            .map_or(Ok(()), crate::compiler::CompilerPool::stop_and_join);
        let epoch = self.epoch_ticker.stop_and_join();
        compiler.and(epoch)
    }

    #[cfg(test)]
    pub(crate) fn epoch_observation(&self) -> crate::containment::EpochObservation {
        self.epoch_ticker.observation()
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
    #[must_use]
    pub fn compiler_snapshot(&self) -> crate::PreparationCompilerSnapshot {
        self.shared
            .compiler
            .as_ref()
            .map_or_else(Default::default, |pool| pool.observer().snapshot())
    }
    /// Bounded stage observations that do not retain a runtime owner.
    #[must_use]
    pub fn preparation_observer(&self) -> PreparationObserver {
        self.shared.preparation_observer.clone()
    }
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
    /// Returns the actual descriptor only when exactly one resident matches.
    /// This bounded diagnostic scan performs no fetch, promotion or hit/miss
    /// accounting. Different source identities can share a preparation key;
    /// such an ambiguous lookup returns `None`.
    #[must_use]
    pub fn cached_preparation(&self, key: &PreparationKey) -> Option<PreparedComponent> {
        self.shared.cache.cached_preparation(key)
    }
    /// Measured residency with optional unique prepared-runtime costs.
    #[must_use]
    pub fn cache_accounting_snapshot(&self) -> crate::PreparedCacheAccountingSnapshot {
        self.shared.cache_accounting_snapshot()
    }
    /// Retains diagnostic counters without retaining the cache or native owners.
    #[must_use]
    pub fn prepared_runtime_observer(&self) -> crate::PreparedRuntimeObserver {
        self.shared.prepared_runtime_observer()
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
        self.prepare_runtime(artifact, key)
            .map(|runtime| runtime.descriptor.clone())
    }

    fn prepare_runtime(
        &self,
        artifact: &CapsuleArtifact,
        key: &PreparationKey,
    ) -> Result<Arc<PreparedRuntime>, PlatformError> {
        let job = self.shared.preparation_observer.begin(&key.release);
        let runtime =
            self.prepare_runtime_with_integrity(artifact, key, ComponentIntegrity::Verify, &job)?;
        job.complete();
        Ok(runtime)
    }

    fn prepare_runtime_with_integrity(
        &self,
        artifact: &CapsuleArtifact,
        key: &PreparationKey,
        integrity: ComponentIntegrity,
        job: &PreparationJob,
    ) -> Result<Arc<PreparedRuntime>, PlatformError> {
        let validation = job.stage(PreparationStage::MetadataValidation);
        let identity = self
            .shared
            .preparation_context
            .metadata_identity(artifact)?;
        self.shared
            .preparation_context
            .validate_key(artifact, key)?;
        self.shared
            .preparation_context
            .validate_manifest(artifact)?;
        let component_digest = self
            .shared
            .preparation_context
            .component_identity(artifact, key, integrity)?;
        let handle = prepared_handle(key, &component_digest, &identity.digest);
        let metadata_bytes = preparation::retained_metadata_bytes(identity.bytes, None)?;
        let reserved_metadata = self
            .shared
            .preparation_context
            .reserved_metadata(metadata_bytes)?;
        validation.complete();
        // The reservation lives through all synchronous compilation and validation,
        // including unwind. No store or component instance is created here.
        let reservation = match self.shared.cache.begin(
            handle.clone(),
            artifact.component_bytes.len(),
            reserved_metadata,
        )? {
            PrepareAccess::Hit(runtime) => return Ok(runtime),
            PrepareAccess::Compile(reservation) => reservation,
        };
        self.shared.preparation_context.compile_runtime(
            artifact,
            key,
            Compilation {
                handle,
                component_digest,
                metadata_bytes,
                authentication: None,
            },
            reservation,
            job,
        )
    }

    async fn invoke_inner_timed(
        &self,
        mut request: ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        timing: &mut Phase0InvocationTiming,
        prepared: Option<WasmtimePreparedUse>,
        input_trace: Option<&InputTrace>,
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

        // Both paths own one permit before retaining a runtime. A prepared use
        // transfers its original reservation and never looks in the cache again.
        let (instance_permit, runtime) =
            self.invocation_runtime(prepared, &request.prepared.opaque_handle)?;
        let function = self.requested_function(&runtime, &request)?;
        let temporary_buffer_guard = self.shared.resources.temporary_buffer();
        let raw_input = input::RawInvocationInput::new(
            std::mem::take(&mut request.activation.input),
            input_trace,
        );
        let input = values::decode_params(
            &function.params,
            raw_input.bytes(),
            &request.activation.input_media_type,
            self.config.value_codec_limits,
        )?;

        let cancellation_probe = cancellation.probe();
        let cancellation_guard = cancellation_probe
            .as_ref()
            .map(|_| self.shared.resources.cancellation_probe());
        let accounting =
            match InvocationAccounting::new(&request, cancellation, self.shared.clock.as_ref()) {
                Ok(accounting) => accounting,
                Err(error) if error.code == PlatformErrorCode::DeadlineExceeded => {
                    return Ok(interrupted_outcome(
                        latent_executor::GuestInterruptionKind::DeadlineExceeded,
                        bounded_text(&error.message, MAX_DIAGNOSTIC_BYTES),
                        BudgetConsumption::default(),
                    ));
                }
                Err(error) => return Err(error),
            };
        let stop = Arc::new(StopControl::with_clock(
            accounting.deadline().monotonic(),
            cancellation_probe,
            Arc::clone(&self.shared.clock),
        ));
        if let Some(kind) = stop.observe() {
            return Ok(interrupted_outcome(
                kind,
                stop.reason(kind),
                BudgetConsumption::default(),
            ));
        }

        let contained_execution_started = self.shared.clock.monotonic_now();
        let host_state_guard = self.shared.resources.host_state();
        let store_guard = self.shared.resources.store();
        let mut store = AccountedStore::new(self.invocation_store(request, &stop, accounting)?);
        // Decoding and every borrowed validation have completed. The Store now
        // owns only the moved context; destroy the actual raw input before call.
        raw_input.release(InvocationInputDropReason::BeforeGuestCall);

        let component_instance_guard = self.shared.resources.component_instance();
        let mut output = vec![Val::Bool(false); function.results.len()];
        if let Some(trace) = input_trace {
            trace.stage(InvocationInputPhase::BeforeCallExport);
        }
        let call_result = call_export(
            &runtime,
            function,
            &mut store,
            &input,
            &mut output,
            timing,
            setup_started,
            input_trace,
        )
        .await;
        // Wasmtime 47's safe dynamic call completes canonical ABI post-return
        // before resolving, including propagation of post-return traps.
        let component_post_return_started = Instant::now();
        let wall_time_micros = u64::try_from(
            self.shared
                .clock
                .monotonic_now()
                .saturating_duration_since(contained_execution_started)
                .as_micros(),
        )
        .unwrap_or(u64::MAX);
        let (consumption, accounting_error) =
            invocation_accounting(&mut store, wall_time_micros, timing);
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
        drop(temporary_buffer_guard);
        timing.activation_resource_reclamation_micros = elapsed_micros(reclamation_started);

        let outcome = reclamation::finish(runtime, instance_permit, timing, || {
            classify_call_result(
                call_result,
                encoded,
                &stop,
                memory_exhausted,
                consumption,
                accounting_error,
            )
        });

        let reusable_proof_started = Instant::now();
        drop(stop);
        drop(cancellation_guard);
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
        Self::validate_bound_imports(&request.imports, &runtime.surface.imports)?;
        self.validate_invocation_budget(&request.budget, &runtime.declared_budget)?;
        let function = runtime
            .surface
            .function(
                &request.activation.target.contract.0,
                &request.activation.target.function.0,
            )
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
        request: ExecutionRequest,
        stop: &Arc<StopControl>,
        accounting: InvocationAccounting,
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

        let host_context =
            ActivationHostContext::from_request(request, accounting.deadline().unix_millis());
        let initial_fuel = accounting.initial_fuel();
        let host_state = HostState::with_config(
            host_context,
            maximum_memory_bytes,
            &self.config,
            accounting,
            Arc::clone(&self.shared.context_policy),
            Arc::clone(&self.shared.clock),
            self.shared.clock_origin,
            self.shared.log_sink.clone(),
        );

        let mut store = Store::new(&self.engine, host_state);
        store.set_hostcall_fuel(self.config.hostcall_fuel);
        store.limiter(|state| &mut state.limiter);
        store.set_fuel(initial_fuel).map_err(|error| {
            platform_error(
                PlatformErrorCode::Internal,
                &format!(
                    "failed to initialize invocation fuel: {}",
                    bounded_error(&error)
                ),
                false,
            )
        })?;
        store
            .fuel_async_yield_interval(self.config.fuel_async_yield_interval)
            .map_err(|error| {
                platform_error(
                    PlatformErrorCode::Internal,
                    &format!(
                        "failed to configure cooperative fuel yielding: {}",
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

    fn validate_bound_imports(
        imports: &[latent_executor::BoundImport],
        required: &BTreeSet<String>,
    ) -> Result<(), PlatformError> {
        // Validated component surfaces admit at most the four known host
        // interfaces. Count each required contract exactly once without a
        // temporary allocated set, preserving arbitrary binding order.
        if imports.len() != required.len()
            || !required.iter().all(|name| {
                imports
                    .iter()
                    .filter(|import| import.contract == *name)
                    .count()
                    == 1
            })
            || imports.iter().any(|import| import.opaque_handle.is_empty())
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
    fn prepare_ready_from_repository<'a>(
        &'a self,
        repository: Arc<dyn ArtifactRepository>,
        key: PreparationKey,
    ) -> BoxFuture<'a, Result<latent_executor::PreparedReadiness, PlatformError>> {
        Box::pin(self.prepare_ready_repository(repository, key))
    }

    fn materialize_ready(
        &self,
        ready: latent_executor::PreparedReadiness,
    ) -> Result<PreparedActivation, PlatformError> {
        self.materialize_readiness(ready)
    }
    fn backend_id(&self) -> &str {
        &self.profile.id
    }

    fn preparation_key(
        &self,
        release: &latent_core::ReleaseDigest,
    ) -> Result<PreparationKey, PlatformError> {
        Ok(self.key_for_release(release))
    }

    fn prepare_for_use<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<latent_executor::PreparedUse, PlatformError>> {
        Box::pin(async move { self.prepare_owned(artifact, key) })
    }

    fn prepare_from_repository<'a>(
        &'a self,
        repository: &'a dyn ArtifactRepository,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedActivation, PlatformError>> {
        Box::pin(self.prepare_repository(repository, key))
    }

    fn invoke_prepared_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        prepared: latent_executor::PreparedUse,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move { self.invoke_owned(request, prepared, cancellation).await })
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
        Box::pin(async move { self.invoke_inner(request, cancellation, None).await })
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
            let outcome = self.invoke_inner(request, cancellation, None).await;
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

#[expect(
    clippy::too_many_arguments,
    reason = "The optional neutral input trace accompanies the existing call and timing arguments without changing their boundaries."
)]
async fn call_export(
    runtime: &PreparedRuntime,
    function: &surface::Function,
    store: &mut Store<HostState>,
    input: &[Val],
    output: &mut [Val],
    timing: &mut Phase0InvocationTiming,
    setup_started: Instant,
    input_trace: Option<&InputTrace>,
) -> wasmtime::Result<()> {
    match runtime.pre.instantiate_async(&mut *store).await {
        Ok(instance) => {
            timing.backend_setup_micros = elapsed_micros(setup_started);
            let guest_call_started = Instant::now();
            let result = match instance.get_func(&mut *store, function.index) {
                Some(func) => {
                    if let Some(trace) = input_trace {
                        trace.stage(InvocationInputPhase::GuestCallStart);
                    }
                    func.call_async(&mut *store, input, output).await
                }
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
    accounting_error: Option<PlatformError>,
) -> Result<GuestOutcome, PlatformError> {
    if let Some(error) = accounting_error {
        // Even a superseded trap can own native backtrace/image state.
        drop(call_result);
        return Ok(GuestOutcome::Trapped {
            trap: latent_executor::GuestTrap {
                code: "budget-accounting-failed".to_owned(),
                message: bounded_text(&error.message, MAX_DIAGNOSTIC_BYTES),
                guest_backtrace: Vec::new(),
                metadata: Metadata::new(),
            },
            consumption,
        });
    }
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
    store: &mut Store<HostState>,
    wall_time_micros: u64,
    timing: &mut Phase0InvocationTiming,
) -> (BudgetConsumption, Option<PlatformError>) {
    let remaining_fuel = store.get_fuel().unwrap_or(0);
    let peak_memory = store.data().limiter.peak_memory_bytes();
    let accounting_error = store
        .data_mut()
        .accounting
        .observe_runtime(remaining_fuel, peak_memory)
        .err();
    let HostCallTiming {
        calls: host_call_count,
        elapsed_micros: host_call_micros,
    } = store.data().host_call_timing();
    let consumption = BudgetConsumption {
        cpu_fuel: store
            .data()
            .accounting
            .initial_fuel()
            .saturating_sub(remaining_fuel),
        peak_memory_bytes: store.data().limiter.peak_memory_bytes(),
        wall_time_micros,
        log_bytes: store.data().logs.bytes(),
        ..BudgetConsumption::default()
    };
    timing.host_call_count = host_call_count;
    timing.host_call_micros = host_call_micros;
    (consumption, accounting_error)
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
