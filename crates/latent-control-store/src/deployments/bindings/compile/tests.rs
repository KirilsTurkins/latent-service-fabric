use super::*;
use latent_core::{BindingId, ServiceId, TenantId};
use latent_manifest::{BindingEndpoint, BindingManifest, ObjectMetadata};
fn definition(consumer: &str, provider: &str, mode: BindingMode) -> BindingDefinition {
    let endpoint = |service: &str| BindingEndpoint {
        service: ServiceId(service.into()),
        contract: ContractId("latent:random/random@0.1.0".into()),
        route: None,
    };
    BindingDefinition {
        manifest: BindingManifest {
            api_version: "latent.dev/v1alpha1".into(),
            id: BindingId(consumer.into()),
            metadata: ObjectMetadata {
                namespace: None,
                name: consumer.into(),
                tenant: Some(TenantId("a".into())),
                labels: Metadata::new(),
                annotations: Metadata::new(),
            },
            consumer: endpoint(consumer),
            provider: endpoint(provider),
            mode,
        },
        provider_binding_id: "installed".into(),
        allowed_modes: vec![BindingMode::Host, BindingMode::IsolatedLocal],
        restriction_json: br#"{"operations":[]}"#.to_vec(),
    }
}
#[test]
fn graph_checks_auto_local_edges_and_rejects_cycle_depth_and_bounded_work() {
    let a = definition("a", "b", BindingMode::IsolatedLocal);
    let b = definition("b", "c", BindingMode::Auto);
    assert!(graph(&[a.clone(), b.clone()], 3).is_ok());
    assert!(graph(&[a.clone(), b.clone()], 2).is_err());
    let c = definition("c", "a", BindingMode::Auto);
    assert!(graph(&[a, b, c], 16).is_err());
    let mut host = definition("a", "a", BindingMode::Host);
    assert!(graph(&[host.clone()], 2).is_ok());
    host.manifest.mode = BindingMode::Auto;
    assert!(graph(&[host], 2).is_err());
}
