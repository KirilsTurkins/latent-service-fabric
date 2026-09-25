//! Explicit volatile test policies feeding the ordinary capability broker.
use crate::request::{Call, Fixtures};
use base64::Engine;
use latent_artifacts::DevelopmentTestArtifact;
use latent_capabilities::broker::{
    metrics::{MetricActivationLimits, MetricProvider, METRICS_CAPABILITY},
    random::{RandomError, RandomLimits, RandomProvider, TestEntropy, RANDOM_CAPABILITY},
    ActivationCapabilityBroker, ActivationCapabilityRuntime, CapabilityBindingSpec,
    CapabilityBrokerLimits, CapabilityPlanSource, CompiledCapabilityPlan, ProviderReference,
};
use latent_core::{Metadata, PlatformError, RevisionId, RouteGeneration, SystemActivationClock};
use latent_policy::capability::{MutationRequest, PolicyStore, PolicyStoreLimits, RecordKind};
use latent_routing::{InvocationTarget, ResolvedRevision};
use latent_telemetry::custom::{CustomMetricLimits, CustomMetricsConfig, TenantMetricsPolicy};
use latent_telemetry::{
    LocalSinkConfig, StructuredLocalSink, TelemetryPipelineConfig, TelemetryRuntime,
};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    sync::Arc,
    time::{Duration, Instant},
};
mod builtins;
mod http;

struct Plans(BTreeMap<String, Arc<CompiledCapabilityPlan>>);
impl CapabilityPlanSource for Plans {
    fn plan(
        &self,
        revision: &ResolvedRevision,
    ) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
        self.0
            .get(&revision.revision.0)
            .cloned()
            .ok_or_else(|| PlatformError {
                code: latent_core::PlatformErrorCode::PermissionDenied,
                message: "unknown-portable-plan".into(),
                retryable: false,
                details: Vec::new(),
            })
    }
}
struct FixedEntropy(Vec<u8>);
impl TestEntropy for FixedEntropy {
    fn fill(&self, bytes: &mut [u8]) -> Result<(), RandomError> {
        for (index, byte) in bytes.iter_mut().enumerate() {
            *byte = self.0[index % self.0.len()];
        }
        Ok(())
    }
}
#[derive(Clone)]
struct Binding {
    capability: &'static str,
    provider: ProviderReference,
    operations: Vec<String>,
    policies: Vec<String>,
    denied_policies: Vec<String>,
    id: String,
}

pub struct Providers {
    pub runtime: Arc<ActivationCapabilityRuntime>,
    pub broker: Arc<ActivationCapabilityBroker>,
    pub clock: Arc<SystemActivationClock>,
    pub entropy: &'static str,
    pub metrics: Option<Arc<MetricProvider>>,
    exporter: Option<TelemetryRuntime>,
    metric_sink: Option<Arc<StructuredLocalSink>>,
    _policies: Arc<PolicyStore>,
    _builtins: Vec<latent_capabilities::broker::ProviderRegistration>,
    http: Option<http::Installed>,
    pub http_requests: usize,
}

pub fn revision(call: &Call, artifact: &DevelopmentTestArtifact) -> ResolvedRevision {
    ResolvedRevision {
        target: InvocationTarget {
            tenant: artifact
                .eligibility()
                .tenant()
                .expect("test tenant")
                .clone(),
            service: latent_core::ServiceId(call.service.clone()),
            contract: latent_core::ContractId(call.contract.clone()),
            function: latent_core::FunctionId(call.function.clone()),
            route: None,
        },
        revision: RevisionId(call.id.clone()),
        release: artifact.artifact().descriptor.release_digest.clone(),
        publication: Some(artifact.eligibility().publication().clone()),
        route_generation: RouteGeneration(1),
        attributes: Metadata::new(),
    }
}

impl Providers {
    #[expect(
        clippy::too_many_lines,
        reason = "compose the scoped policies, providers and cleanup owners together"
    )]
    pub fn new(
        artifact: &DevelopmentTestArtifact,
        fixtures: &Fixtures,
        calls: &[Call],
    ) -> Result<Self, &'static str> {
        let policies = Arc::new(
            PolicyStore::for_development_test(artifact, PolicyStoreLimits::default(), [71; 32])
                .map_err(|_| "portable-policy-owner")?,
        );
        let clock = Arc::new(SystemActivationClock);
        let broker = Arc::new(
            ActivationCapabilityBroker::new(
                artifact.authority(),
                policies.clone(),
                clock.clone(),
                CapabilityBrokerLimits::default(),
            )
            .map_err(|_| "portable-broker")?,
        );
        let (random, entropy) = if let Some(encoded) = &fixtures.entropy {
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(encoded)
                .map_err(|_| "entropy-fixture-base64")?;
            if bytes.is_empty() || bytes.len() > 4096 {
                return Err("entropy-fixture-bound");
            }
            (
                RandomProvider::for_test(
                    &broker,
                    1,
                    RandomLimits::default(),
                    Arc::new(FixedEntropy(bytes)),
                ),
                "fixed-byte-cycle-fixture",
            )
        } else {
            (
                RandomProvider::system(&broker, 1, RandomLimits::default()),
                "system-entropy-nondeterministic",
            )
        };
        let random = random.map_err(|_| "portable-random-provider")?;
        let (mut bindings, builtins) = builtins::install(&broker, &policies, artifact, calls)?;
        bindings.push(install(
            &policies,
            artifact,
            calls,
            "random",
            RANDOM_CAPABILITY,
            random.reference(),
            &["bytes", "u64-value"],
            &json!({"kind":"random"}),
        )?);
        let mut exporter = None;
        let mut metric_sink = None;
        let mut metrics = None;
        if !fixtures.metrics.is_empty() {
            let sink = Arc::new(
                StructuredLocalSink::new(LocalSinkConfig::default())
                    .map_err(|_| "portable-metric-sink")?,
            );
            let (handle, worker) =
                TelemetryRuntime::spawn(TelemetryPipelineConfig::default(), sink.clone())
                    .map_err(|_| "portable-metric-worker")?;
            let config = CustomMetricsConfig {
                limits: CustomMetricLimits::default(),
                tenants: vec![TenantMetricsPolicy {
                    tenant: artifact
                        .eligibility()
                        .tenant()
                        .expect("test tenant")
                        .0
                        .clone(),
                    metrics: fixtures.metrics.clone(),
                }],
            };
            let provider = MetricProvider::install(
                &broker,
                handle,
                1,
                config,
                MetricActivationLimits::default(),
            )
            .map_err(|_| "portable-metric-descriptors")?;
            bindings.push(install(&policies, artifact, calls, "metrics", METRICS_CAPABILITY, provider.reference(),
                &["emit-metric"], &json!({"kind":"telemetry","names":fixtures.metrics.iter().map(|item| &item.name).collect::<Vec<_>>()}))?);
            metrics = Some(provider);
            exporter = Some(worker);
            metric_sink = Some(sink);
        }
        let http = fixtures
            .http
            .as_ref()
            .map(|fixture| http::install(&broker, &policies, artifact, calls, fixture))
            .transpose()?;
        if let Some((binding, _)) = &http {
            bindings.push(binding.clone());
        }
        let http = http.map(|(_, installed)| installed);
        let plans = compile(&broker, artifact, calls, &bindings)?;
        let runtime = Arc::new(ActivationCapabilityRuntime::new(
            broker.clone(),
            Arc::new(Plans(plans)),
        ));
        runtime
            .install_random(random)
            .map_err(|_| "portable-random-install")?;
        if let Some(provider) = &metrics {
            runtime
                .install_metrics(provider.clone())
                .map_err(|_| "portable-metrics-install")?;
        }
        if let Some(installed) = &http {
            runtime
                .install_http(Arc::new(installed.provider.clone()))
                .map_err(|_| "portable-http-install")?;
        }
        Ok(Self {
            runtime,
            broker,
            clock,
            entropy,
            metrics,
            exporter,
            metric_sink,
            _policies: policies,
            _builtins: builtins,
            http,
            http_requests: 0,
        })
    }

    pub fn check_idle(&self) -> Result<(), &'static str> {
        let r = self.broker.snapshot();
        if (r.sessions, r.handles, r.calls, r.results, r.buffer_bytes) != (0, 0, 0, 0, 0) {
            return Err("portable-provider-resource-leak");
        }
        if let Some(http) = &self.http {
            http.check_idle()?;
        }
        Ok(())
    }

    pub fn metric_observation(&self) -> Result<Option<Value>, &'static str> {
        let Some(provider) = &self.metrics else {
            return Ok(None);
        };
        if self.exporter.is_some() {
            return Err("portable-metrics-exporter-not-joined");
        }
        let snapshot = provider.snapshot();
        let registry = provider
            .registry()
            .snapshot()
            .map_err(|_| "portable-metrics-snapshot")?;
        if !registry.retired || registry.queued_bytes != 0 {
            return Err("portable-metrics-queue-not-reclaimed");
        }
        let sink = self
            .metric_sink
            .as_ref()
            .ok_or("portable-metrics-sink-unavailable")?;
        let mut count = 0;
        let mut records = Vec::with_capacity(16);
        for record in sink.records() {
            if let latent_telemetry::TelemetryRecord::CustomMetric(metric) = record {
                count += 1;
                if records.len() == 16 {
                    records.remove(0);
                }
                let point = metric.point();
                records.push(json!({"name":point.name,"unit":point.unit,"valueBits":format!("{:016x}",point.value.to_bits())}));
            }
        }
        let retained = sink.snapshot();
        Ok(Some(
            json!({"accepted":snapshot.accepted,"attempted":snapshot.attempted,"invalid":snapshot.invalid,
            "exhausted":snapshot.exhausted,"unavailable":snapshot.unavailable,"queuedBytes":registry.queued_bytes,
            "retired":registry.retired,"capturedRecords":count,"truncated":count>records.len(),
            "sinkEvictedEntries":retained.evicted_entries,"sinkDroppedOversized":retained.dropped_oversized,"records":records}),
        ))
    }

    pub async fn shutdown(&mut self) -> Result<(), &'static str> {
        self.check_idle()?;
        if let Some(provider) = &self.metrics {
            provider.retire();
        }
        if let Some(http) = &mut self.http {
            self.http_requests = http.shutdown().await?;
        }
        if let Some(worker) = self.exporter.take() {
            worker
                .shutdown()
                .await
                .map_err(|_| "portable-metric-shutdown")?;
        }
        Ok(())
    }
}

#[expect(
    clippy::too_many_arguments,
    reason = "keep the exact provider identity, imported operations and policy resource scope separate"
)]
fn install(
    store: &PolicyStore,
    artifact: &DevelopmentTestArtifact,
    calls: &[Call],
    name: &str,
    capability: &'static str,
    provider: ProviderReference,
    operations: &[&str],
    resources: &Value,
) -> Result<Binding, &'static str> {
    let tenant = &artifact.eligibility().tenant().expect("test tenant").0;
    let services = calls
        .iter()
        .map(|call| call.service.as_str())
        .collect::<std::collections::BTreeSet<_>>();
    let binding = format!("{name}-binding");
    let policy = json!({"formatVersion":1,"tenant":tenant,"rules":[{"id":"explicit-test-grant","effect":"allow","requireAudit":false,
        "principals":[{"kind":"service","subject":"portable-test"}],"services":services,
        "publications":[artifact.eligibility().publication().as_str()],"capability":capability,"operations":operations,"resources":resources,
        "ceiling":{"operations":1,"inputBytes":65536,"outputBytes":65536,"wallTimeMillis":5000}}]});
    let provider_doc = json!({"formatVersion":1,"tenant":tenant,"capability":capability,"providerProfile":provider.profile(),
        "configurationDigest":provider.configuration_digest(),"configurationEpoch":1,"restriction":{"operations":[]}});
    let deny_name = format!("deny-{name}");
    let mut denied = policy.clone();
    denied["rules"][0]["effect"] = json!("deny");
    for (id, kind, value) in [
        (name, RecordKind::Policy, policy),
        (&deny_name, RecordKind::Policy, denied),
        (&binding, RecordKind::ProviderBinding, provider_doc),
    ] {
        let bytes = serde_json::to_vec(&value).map_err(|_| "portable-policy-encoding")?;
        store
            .mutate(
                MutationRequest {
                    tenant,
                    actor: "controlled-test",
                    id,
                    kind,
                    operation_id: id,
                    expected_revision: 0,
                    document: Some(&bytes),
                },
                Instant::now() + Duration::from_secs(5),
                |_| Ok(()),
            )
            .map_err(|_| "portable-policy-validation")?;
    }
    Ok(Binding {
        capability,
        provider,
        operations: operations.iter().map(|value| (*value).into()).collect(),
        policies: vec![name.into()],
        denied_policies: vec![name.into(), deny_name],
        id: binding,
    })
}

fn compile(
    broker: &ActivationCapabilityBroker,
    artifact: &DevelopmentTestArtifact,
    calls: &[Call],
    bindings: &[Binding],
) -> Result<BTreeMap<String, Arc<CompiledCapabilityPlan>>, &'static str> {
    let mut plans = BTreeMap::new();
    let definition =
        latent_artifacts::package::artifact_blob_digest(b"explicit-portable-test-bindings-v1");
    for call in calls {
        let specs = bindings
            .iter()
            .filter(|binding| call.grants.iter().any(|grant| grant == binding.capability))
            .map(|binding| CapabilityBindingSpec {
                definition_digest: Some(&definition),
                provider: &binding.provider,
                imported_operations: &binding.operations,
                policy_ids: if call
                    .denied_capabilities
                    .iter()
                    .any(|capability| capability == binding.capability)
                {
                    &binding.denied_policies
                } else {
                    &binding.policies
                },
                provider_binding_id: &binding.id,
                deployment_restriction_json: br#"{"operations":[]}"#,
            })
            .collect::<Vec<_>>();
        let plan = broker
            .compile_invocation_plan(
                &revision(call, artifact),
                Some(&latent_core::DeploymentId("portable-test".into())),
                &specs,
                artifact.eligibility(),
                &[],
                &[],
                &[],
                None,
                Instant::now() + Duration::from_secs(5),
            )
            .map_err(|_| "portable-plan-compilation")?;
        plans.insert(call.id.clone(), plan);
    }
    Ok(plans)
}
