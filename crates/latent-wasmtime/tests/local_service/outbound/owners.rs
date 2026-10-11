//! The existing normal-node composition gains original bounded provider owners.
//! No fixture executor, private activation ledger or alternate grant source.
use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime},
    network::{STREAM_CAPABILITY, STREAM_PROFILE},
    pools::{ProviderPoolLimits, ProviderPools},
    ActivationCapabilityBroker,
};
use latent_control_store::bindings::{BindingDefinition, ConfiguredBindingProvider};
use latent_core::{CapabilityId, PolicyId, PublicationId, ServiceId, TenantId};
use latent_manifest::{BindingMode, CapabilityGrantSpec, JsonManifestCodec, ManifestCodec};
use latent_policy::capability::{MutationRequest, PolicyStore, RecordKind};
use latent_streams::{StreamLifecycle, StreamMaintenanceStop, StreamProviderConfig};
use serde_json::json;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

pub const POLICY: &str = "outbound-policy";
pub const BINDING: &str = "outbound-installed";
const SERVICE: &str = "outbound-streams";
const OPERATIONS: [&str; 8] = [
    "connect",
    "read",
    "write",
    "ready",
    "inspect",
    "shutdown",
    "close",
    "chunk-bytes",
];

pub fn grants() -> Vec<CapabilityGrantSpec> {
    vec![CapabilityGrantSpec::new(
        CapabilityId(STREAM_CAPABILITY.into()),
        PolicyId(POLICY.into()),
    )]
}

pub struct Owners {
    pub lifecycle: Arc<StreamLifecycle>,
    pub pools: Arc<ProviderPools>,
    pub io: Arc<IoRuntime>,
    stop: Option<StreamMaintenanceStop>,
    maintenance: Option<tokio::task::JoinHandle<Result<(), latent_streams::StreamError>>>,
}
impl Owners {
    pub fn install(
        broker: &Arc<ActivationCapabilityBroker>,
        policies: &PolicyStore,
        publication: &PublicationId,
        configuration: &StreamProviderConfig,
    ) -> Self {
        let io = Arc::new(IoRuntime::new(IoLimits::default()).unwrap());
        let pools = Arc::new(
            ProviderPools::new(
                broker.clone(),
                io.clone(),
                tokio::runtime::Handle::current(),
                ProviderPoolLimits::default(),
            )
            .unwrap(),
        );
        let lifecycle = Arc::new(
            StreamLifecycle::install_for_qualification(
                pools.clone(),
                SERVICE,
                1,
                configuration.clone(),
            )
            .unwrap(),
        );
        let reference = lifecycle.reference().unwrap();
        let endpoints: Vec<_> = configuration
            .destinations
            .iter()
            .map(|destination| destination.endpoint.clone())
            .collect();
        let documents = [
            (
                POLICY,
                RecordKind::Policy,
                json!({"formatVersion":1,"tenant":"tenant-a","rules":[{
                    "id":"stream","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
                    "services":["caller"],"publications":[publication.as_str()],"capability":STREAM_CAPABILITY,
                    "operations":OPERATIONS,"resources":{"kind":"stream","endpoints":endpoints},"requireAudit":false,
                    "ceiling":{"operations":128,"inputBytes":8_000_000,"outputBytes":8_000_000,"wallTimeMillis":5000}
                }]}),
            ),
            (
                BINDING,
                RecordKind::ProviderBinding,
                json!({"formatVersion":1,"tenant":"tenant-a","capability":STREAM_CAPABILITY,
                "providerProfile":STREAM_PROFILE,"configurationDigest":reference.configuration_digest(),
                "configurationEpoch":1,"restriction":{"operations":[]}}),
            ),
        ];
        for (id, kind, document) in documents {
            let bytes = serde_json::to_vec(&document).unwrap();
            policies
                .mutate(
                    MutationRequest {
                        tenant: "tenant-a",
                        actor: "operator",
                        id,
                        kind,
                        operation_id: id,
                        expected_revision: 0,
                        document: Some(&bytes),
                    },
                    Instant::now() + Duration::from_secs(10),
                    |_| Ok(()),
                )
                .unwrap();
        }
        let maintenance = lifecycle.maintenance().unwrap();
        let stop = Some(maintenance.stop_handle());
        let maintenance = Some(tokio::spawn(maintenance.run()));
        Self {
            lifecycle,
            pools,
            io,
            stop,
            maintenance,
        }
    }

    pub fn definition() -> BindingDefinition {
        let document = json!({"apiVersion":latent_manifest::MANIFEST_API_VERSION,"kind":"Binding",
            "metadata":{"name":"outbound-caller","tenant":"tenant-a"},
            "spec":{"consumer":{"service":"caller","contract":STREAM_CAPABILITY},
                "provider":{"service":SERVICE,"contract":STREAM_CAPABILITY},"mode":"host"}});
        BindingDefinition {
            manifest: JsonManifestCodec::default()
                .decode_binding(&serde_json::to_vec(&document).unwrap())
                .unwrap(),
            provider_binding_id: BINDING.into(),
            allowed_modes: vec![BindingMode::Host],
            restriction_json: br#"{"operations":[]}"#.to_vec(),
        }
    }
    pub fn provider(&self) -> ConfiguredBindingProvider {
        ConfiguredBindingProvider {
            tenant: TenantId("tenant-a".into()),
            service: ServiceId(SERVICE.into()),
            reference: self.lifecycle.reference().unwrap(),
            local_deployment: None,
        }
    }
    pub async fn shutdown(mut self) {
        let deadline = Instant::now() + Duration::from_secs(2);
        self.lifecycle.retire();
        self.stop.as_ref().unwrap().stop();
        tokio::time::timeout_at(deadline.into(), self.maintenance.take().unwrap())
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        drop(self.stop.take());
        let status = self.lifecycle.status().unwrap();
        assert_eq!(status.maintenance_owners, 0);
        assert_eq!(status.usage.owners, 0);
        assert_eq!(
            self.io.snapshot(),
            latent_capabilities::broker::io::IoSnapshot::default()
        );
        let snapshot = self.pools.shutdown(deadline).await.unwrap();
        assert!(snapshot.is_clean(), "{snapshot:?}");
    }
}
impl Drop for Owners {
    fn drop(&mut self) {
        self.lifecycle.retire();
        if let Some(stop) = &self.stop {
            stop.stop();
        }
    }
}
