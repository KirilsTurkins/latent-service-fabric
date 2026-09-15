use latent_telemetry::{custom::*, MetricKind};
pub fn config() -> CustomMetricsConfig {
    let metrics = [
        ("requests", MetricKind::Counter),
        ("inflight", MetricKind::UpDownCounter),
        ("temperature", MetricKind::Gauge),
        ("latency", MetricKind::Histogram),
    ]
    .into_iter()
    .map(|(name, kind)| CustomMetricDescriptor {
        name: name.into(),
        kind,
        unit: "1".into(),
        labels: vec![CustomMetricLabel {
            key: "region".into(),
            values: vec!["east".into(), "west".into()],
        }],
        histogram_upper_bounds: if kind == MetricKind::Histogram {
            vec![0.0, 10.0]
        } else {
            vec![]
        },
    })
    .collect::<Vec<_>>();
    CustomMetricsConfig {
        limits: CustomMetricLimits::default(),
        tenants: vec![
            TenantMetricsPolicy {
                tenant: "tests".into(),
                metrics: metrics.clone(),
            },
            TenantMetricsPolicy {
                tenant: "other".into(),
                metrics,
            },
        ],
    }
}

use super::*;
pub(super) fn compile(
    broker: &ActivationCapabilityBroker,
    revision: &ResolvedRevision,
    publication: &ReleaseUseEligibility,
    provider: &ProviderReference,
) -> Arc<CompiledCapabilityPlan> {
    broker
        .compile_invocation_plan(
            revision,
            Some(&latent_core::DeploymentId("metrics-deployment".into())),
            &[CapabilityBindingSpec {
                definition_digest: Some(&latent_artifacts::package::artifact_blob_digest(
                    b"metrics-fixture-binding-v1",
                )),
                provider,
                imported_operations: &["emit-metric".into()],
                policy_ids: &["p".into()],
                provider_binding_id: "binding",
                deployment_restriction_json: br#"{"operations":[]}"#,
            }],
            publication,
            &[],
            &[],
            &[],
            None,
            Instant::now() + Duration::from_secs(10),
        )
        .unwrap()
}

pub(super) fn install(
    store: &PolicyStore,
    publication: &ReleaseUseEligibility,
    provider: &ProviderReference,
    required: bool,
    tenant: &str,
) {
    for (id, kind, value) in [
        (
            "p",
            RecordKind::Policy,
            json!({"formatVersion":1,"tenant":tenant,"rules":[{
                "id":"allow", "effect":"allow", "requireAudit":required,"principals":[{"kind":"service","subject":"generic-test"}],
                "services":["generic"], "publications":[publication.publication().as_str()], "capability":component::CAP,
                "operations":["emit-metric"], "resources":{"kind":"telemetry","names":["requests","inflight","temperature","latency"]},
                "ceiling":{"operations":1,"inputBytes":4096,"outputBytes":4096,"wallTimeMillis":5000}
            }]}),
        ),
        (
            "binding",
            RecordKind::ProviderBinding,
            json!({"formatVersion":1,"tenant":tenant,"capability":component::CAP,
            "providerProfile":provider.profile(),"configurationDigest":provider.configuration_digest(),"configurationEpoch":1,"restriction":{"operations":[]}}),
        ),
    ] {
        store
            .mutate(
                MutationRequest {
                    tenant,
                    actor: "operator",
                    id,
                    kind,
                    operation_id: id,
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&value).unwrap()),
                },
                Instant::now() + Duration::from_secs(10),
                |_| Ok(()),
            )
            .unwrap();
    }
}
