use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use base64::Engine;
use latent_activation::{ActivationEnvelope, TraceContext};
use latent_artifacts::{ArtifactDescriptor, CapsuleArtifact, DevelopmentTestArtifact};
use latent_core::{
    ActivationBudget, ActivationId, ArtifactReference, CapabilityId, CellId, ClockSample,
    ContractId, EffectiveActivationBudget, FunctionId, InvocationPrincipal, Metadata,
    PrincipalKind, ResourceBudget, ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::{
    BoundImport, ExecutionBackend, ExecutionCancellation, ExecutionCancellationProbe,
    ExecutionCell, ExecutionCleanup, ExecutionRequest, GuestInterruptionKind, GuestOutcome,
};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
};
use latent_routing::InvocationTarget;
use latent_wasmtime::{WasmtimeComponentEngineFactory, WasmtimeConfig, WasmtimeHostServices};
use serde_json::{json, Value};

use crate::request::{Call, Request, RuntimeProfile, IMPORTS};

struct Cancellation(ActivationId, bool, Arc<ActivationBudget>);

impl ExecutionCancellationProbe for Cancellation {
    fn is_cancelled(&self) -> bool {
        self.1
    }
    fn reason(&self) -> Option<String> {
        self.1.then(|| "explicit-portable-test-cancellation".into())
    }
}
impl ExecutionCancellation for Cancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.0
    }
    fn is_cancelled(&self) -> bool {
        self.1
    }
    fn reason(&self) -> Option<String> {
        ExecutionCancellationProbe::reason(self)
    }
    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        Some(Arc::new(Self(self.0.clone(), self.1, self.2.clone())))
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        Some(&self.2)
    }
}

fn bytes(value: &str, maximum: usize) -> Result<Vec<u8>, &'static str> {
    let decoded = base64::engine::general_purpose::STANDARD
        .decode(value)
        .map_err(|_| "base64-input")?;
    if decoded.len() > maximum {
        return Err("decoded-byte-limit");
    }
    Ok(decoded)
}

fn artifact(request: &Request) -> Result<CapsuleArtifact, &'static str> {
    let component_bytes = bytes(&request.component, 16 * 1024 * 1024)?;
    let manifest = JsonManifestCodec::default()
        .decode_capsule(&bytes(&request.manifest, 1024 * 1024)?)
        .map_err(|_| "capsule-manifest")?;
    Phase1ManifestValidator
        .validate_capsule(&manifest)
        .map_err(|_| "capsule-semantics")?;
    let digest = latent_artifacts::content_digest(&component_bytes);
    if manifest.component_digest != digest || component_bytes.get(..8) != Some(b"\0asm\x0d\0\x01\0")
    {
        return Err("component-identity");
    }
    if manifest
        .imports
        .iter()
        .any(|import| !IMPORTS.contains(&import.contract.0.as_str()))
    {
        return Err("portable-import-unsupported-before-execution");
    }
    let contracts = latent_artifacts::decode_contract_metadata(
        &bytes(&request.contracts, 1024 * 1024)?,
        latent_artifacts::ContractMetadataLimits::default(),
    )
    .map_err(|_| "contract-metadata")?;
    Ok(CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://explicit-portable-test".into()),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
            size_bytes: u64::try_from(component_bytes.len()).map_err(|_| "component-size")?,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest,
        contracts,
        component_bytes,
    })
}

fn execution(
    call: &Call,
    prepared: latent_executor::PreparedComponent,
    ceiling: &ResourceBudget,
    owned: &DevelopmentTestArtifact,
    profile: RuntimeProfile,
) -> Result<ExecutionRequest, &'static str> {
    let (fuel, memory) = call.budgets(profile)?;
    let id = ActivationId(call.id.clone());
    let budget = ResourceBudget {
        cpu_fuel: fuel,
        memory_bytes: memory,
        wall_time_limit_millis: Some(call.timeout_millis),
        log_bytes: ceiling.log_bytes.min(16384),
        child_calls: 0,
        outbound_requests: ceiling.outbound_requests.min(8),
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        effect_count: 0,
    };
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "host-clock")?
            .as_millis(),
    )
    .map_err(|_| "host-clock-range")?;
    let deadline = now
        .checked_add(call.timeout_millis)
        .ok_or("host-clock-overflow")?;
    Ok(ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: id.clone(),
            root_activation_id: id,
            parent_activation_id: None,
            principal: InvocationPrincipal {
                subject: "portable-test".into(),
                kind: PrincipalKind::Service,
                tenant: owned.eligibility().tenant().cloned(),
                service: Some(ServiceId(call.service.clone())),
                claims: Metadata::new(),
            },
            target: InvocationTarget {
                tenant: owned.eligibility().tenant().expect("test tenant").clone(),
                service: ServiceId(call.service.clone()),
                contract: ContractId(call.contract.clone()),
                function: FunctionId(call.function.clone()),
                route: None,
            },
            resolved_revision: Some(crate::providers::revision(call, owned)),
            deadline_unix_millis: Some(deadline),
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("portable-test".into()),
                span_id: SpanId(call.id.clone()),
                trace_flags: 0,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget.clone(),
            metadata: Metadata::new(),
            input: bytes(&call.input, 1024 * 1024)?,
            input_media_type: latent_wasmtime::WIT_VALUES_MEDIA_TYPE.into(),
        },
        prepared,
        cell: ExecutionCell {
            id: CellId("portable-shared-cell".into()),
            class: "controlled-test".into(),
            maximum_memory_bytes: memory,
            metadata: Metadata::new(),
        },
        imports: call
            .grants
            .iter()
            .map(|grant| BoundImport {
                capability: CapabilityId(grant.clone()),
                contract: grant.clone(),
                opaque_handle: call.id.clone(),
            })
            .collect(),
        budget,
    })
}

fn payload(raw: &[u8], media: &str) -> Value {
    json!({"encoding":"base64", "data":base64::engine::general_purpose::STANDARD.encode(raw),
        "byteLength":raw.len().to_string(), "mediaType":media})
}

#[expect(
    clippy::too_many_lines,
    reason = "retain the test artifact and provider owners through invocation, cleanup checks and receipt creation"
)]
pub async fn run(request: Request) -> Result<Value, &'static str> {
    let fixture_digest = latent_artifacts::content_digest(
        &serde_json::to_vec(&request.fixtures).map_err(|_| "portable-fixture-identity")?,
    );
    let artifact = artifact(&request)?;
    let tenant = artifact
        .manifest
        .metadata
        .tenant
        .clone()
        .unwrap_or(TenantId("portable-test".into()));
    let owned =
        DevelopmentTestArtifact::new(artifact, tenant).map_err(|_| "portable-artifact-owner")?;
    let artifact = owned.artifact();
    let mut providers =
        crate::providers::Providers::new(&owned, &request.fixtures, &request.calls)?;
    let mut config = WasmtimeConfig {
        maximum_memory_bytes: request.runtime_profile.maximum_memory(),
        maximum_fuel: 10_000_000_000,
        prepared_cache_maximum_entries: 1,
        maximum_concurrent_preparations: 1,
        ..WasmtimeConfig::default()
    };
    if matches!(request.runtime_profile, RuntimeProfile::Java) {
        config.fuel_async_yield_interval = Some(100_000);
        config.install_java_guest();
    }
    let factory = WasmtimeComponentEngineFactory::with_catalog(
        config,
        WasmtimeHostServices {
            clock: providers.clock.clone(),
            currentness_read_wait: None,
            log_sink: None,
            capabilities: Some(providers.runtime.clone()),
        },
        owned.authority(),
    )
    .map_err(|_| "portable-engine-configuration")?;
    let backend = factory.create_backend_instance();
    let mut key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    key.publication = Some(owned.eligibility().publication().clone());
    let prepared = backend
        .prepare_development_test(&owned, &key)
        .map_err(|error| {
            let message = error.message.chars().filter(|c| !c.is_control()).take(256).collect::<String>();
            eprintln!("{}", json!({"stage":"component-preparation","code":error.code.wire_code(),"message":message}));
            "portable-component-preparation-rejected"
        })?;
    let mut results = Vec::with_capacity(request.calls.len());
    for call in request.calls {
        let request = execution(
            &call,
            prepared.clone(),
            &artifact.manifest.execution.resource_budget_ceiling,
            &owned,
            request.runtime_profile,
        )?;
        let accounting = ActivationBudget::with_profile(
            EffectiveActivationBudget::admit_profile_at(
                latent_core::BudgetProfile::Phase3,
                &request.budget,
                &request.budget,
                &artifact.manifest.execution.resource_budget_ceiling,
                request.activation.deadline_unix_millis,
                ClockSample::system_now(),
            )
            .map_err(|_| "portable-activation-budget")?,
            latent_core::BudgetProfile::Phase3,
        )
        .map_err(|_| "portable-activation-budget-profile")?;
        let cancellation = Cancellation(
            ActivationId(call.id.clone()),
            call.cancel_before_start,
            Arc::new(accounting),
        );
        let report = backend.invoke_contained(request, &cancellation).await;
        if report.cleanup != ExecutionCleanup::Reusable {
            return Err("portable-cleanup-unconfirmed");
        }
        let (category, data) = match report.outcome {
            Ok(GuestOutcome::Returned {
                output,
                output_media_type,
                ..
            }) => (
                "success",
                json!({"payload":payload(&output, &output_media_type)}),
            ),
            Ok(GuestOutcome::DeclaredError { error, .. }) => (
                "declared-error",
                json!({"payload":payload(&error.payload, &error.media_type)}),
            ),
            Ok(GuestOutcome::Trapped { .. }) => ("platform-failure", json!({"code":"guest-trap"})),
            Ok(GuestOutcome::Interrupted { kind, .. }) => {
                let code = match kind {
                    GuestInterruptionKind::Cancelled => "cancelled",
                    GuestInterruptionKind::DeadlineExceeded => "deadline-exceeded",
                    GuestInterruptionKind::FuelExhausted => "fuel-exhausted",
                    GuestInterruptionKind::MemoryExhausted => "memory-exhausted",
                };
                ("platform-failure", json!({"code":code}))
            }
            Err(error) => ("platform-failure", json!({"code":error.code.wire_code()})),
        };
        let resources = backend.resource_snapshot();
        if resources.active_invocations != 0
            || resources.live_stores != 0
            || resources.live_host_states != 0
            || resources.live_component_instances != 0
            || resources.live_temporary_buffers != 0
            || resources.live_cancellation_probes != 0
        {
            return Err("portable-live-resource-leak");
        }
        let logs = backend
            .log_sink()
            .snapshot_for(&ActivationId(call.id.clone()));
        backend.log_sink().clear();
        providers.check_idle()?;
        let error = if category == "platform-failure" {
            data.clone()
        } else {
            Value::Null
        };
        results.push(json!({"id":call.id,"category":category,"outcomeKnown":true,"data":data,
            "error":error,"cleanup":"reusable","logs":logs,"storesCreated":resources.stores_created.to_string()}));
        if serde_json::to_vec(&results)
            .map_err(|_| "portable-output-encoding")?
            .len()
            > 2 * 1024 * 1024
        {
            return Err("portable-aggregate-output-limit");
        }
    }
    providers.shutdown().await?;
    let metrics = providers.metrics.as_ref().map(|provider| {
        let s = provider.snapshot(); json!({"accepted":s.accepted,"attempted":s.attempted,"invalid":s.invalid,"exhausted":s.exhausted})
    });
    Ok(
        json!({"schemaVersion":"latent.dev.portable-result.v1","environment":"portable",
        "trust":"controlled-development-test", "productionNode":false,"category":"success",
        "runtimeProfile":request.runtime_profile,
        "clock":"system-clock-nondeterministic","entropy":providers.entropy,
        "fixtures":{"sha256":fixture_digest.0,"random":request.fixtures.entropy.is_some(),
            "metrics": !request.fixtures.metrics.is_empty(),"http":request.fixtures.http.is_some()},
        "httpFixtureRequests": providers.http_requests,"metrics":metrics,
        "component":artifact.descriptor.release_digest.0,"os":std::env::consts::OS,"architecture":std::env::consts::ARCH,
        "wasmtime":latent_wasmtime::WASMTIME_VERSION,"supportedImports":IMPORTS,"results":results,
        "excludedChecks":["node-admission","deployment","management-authentication","linux-protected-files",
            "PSI","isolated-compilation","native-cache","production-performance"]}),
    )
}
