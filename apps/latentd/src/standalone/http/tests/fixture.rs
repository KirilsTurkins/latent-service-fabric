use crate::{
    config::NodeConfig,
    standalone::{start::Catalogs, RuntimeThreads, StandaloneNode},
};
use latent_artifacts::{self as artifacts, ArtifactRepository, CapsuleArtifact};
use latent_control_store::{http_routes::*, DeploymentStore, DirectoryDeploymentRepository};
use latent_core::{
    ArtifactReference, ContractId, DeploymentId, FunctionId, InterfaceId, Metadata, TenantId,
    TriggerId,
};
use latent_ingress::http;
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
};
use latent_routing::{InvocationTarget, RouteResolver};
use serde_json::{json, Value};
use std::{sync::Arc, time::Duration};
use tempfile::TempDir;
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
};

pub const TOKEN: &str = "invoke-token-0000000000000000000000000000";
pub const OTHER: &str = "second-token-0000000000000000000000000000";
pub const AUTHORITY: &str = "web.example.test";

pub struct Fixture {
    pub node: StandaloneNode,
    pub deployments: Arc<DirectoryDeploymentRepository>,
    pub artifacts: Arc<artifacts::DirectoryArtifactRepository>,
    pub root: TempDir,
}
pub fn config(root: &TempDir) -> Value {
    let mut value = super::config::config();
    value["dataDirectory"] = json!(root.path().join("node"));
    value["execution"] = json!({"maximumCpuFuel":10_000_000_000u64, "maximumWallTimeMillis":5000, "maximumLogBytes":0});
    value["cells"] = json!([{"class":"standard", "capacity":1, "queueCapacity":2, "maximumMemoryBytes":67_108_864}]);
    value["httpIngress"]["limits"] = json!({"maximumConnections":4, "maximumExchanges":2, "maximumBufferBytes":10_485_760,
        "headerTimeoutMillis":200, "bodyTimeoutMillis":200, "idleTimeoutMillis":200, "writeTimeoutMillis":300,
        "handshakeTimeoutMillis":200, "maximumConnectionAgeMillis":30_000, "maximumRequestsPerConnection":100});
    value
}
impl Fixture {
    pub async fn start(root: TempDir, value: Value, component: Option<Vec<u8>>) -> Self {
        let settings = serde_json::from_value::<NodeConfig>(value)
            .unwrap()
            .derive()
            .unwrap();
        let catalogs = Catalogs::open(&settings).await.unwrap();
        let artifacts = catalogs.artifacts.clone();
        let deployments = catalogs.deployments.clone();
        if let Some(bytes) = component {
            publish(&catalogs, bytes, settings.http.as_ref().unwrap().scheme).await;
        }
        let node = Box::pin(StandaloneNode::start_with_catalogs(
            settings,
            catalogs,
            tokio::runtime::Handle::current(),
            RuntimeThreads::default(),
        ))
        .await
        .unwrap();
        Self {
            node,
            deployments,
            artifacts,
            root,
        }
    }
    pub async fn connect(&self) -> TcpStream {
        TcpStream::connect(self.node.http_endpoint().unwrap())
            .await
            .unwrap()
    }
    pub async fn idle(&self) {
        wait(|| {
            self.node
                .http_snapshot()
                .is_some_and(|s| s.connections == 0 && s.exchanges == 0)
                && self.node.manager.journal().snapshot().active == 0
        })
        .await;
        assert_eq!(self.node.quotas.usage().unwrap().active_activations, 0);
        assert_eq!(self.node.backend.resource_snapshot().live_stores, 0);
    }
    pub async fn shutdown(self) -> TempDir {
        drop(self.deployments);
        drop(self.artifacts);
        let report = self.node.shutdown().await.unwrap();
        assert!(report.clean);
        assert!(report.http.unwrap().clean());
        self.root
    }
}
pub async fn wait(mut condition: impl FnMut() -> bool) {
    tokio::time::timeout(Duration::from_secs(8), async {
        while !condition() {
            tokio::time::sleep(Duration::from_millis(2)).await;
        }
    })
    .await
    .expect("bounded observable transition");
}
pub fn request(method: &str, path: &str, token: &str, length: usize, close: bool) -> String {
    format!("{method} {path} HTTP/1.1\r\nHost: {AUTHORITY}\r\nAuthorization: Bearer {token}\r\nContent-Length: {length}\r\nConnection: {}\r\n\r\n", if close { "close" } else { "keep-alive" })
}
pub async fn response<S: AsyncRead + Unpin>(socket: &mut S) -> (u16, String, Vec<u8>) {
    tokio::time::timeout(Duration::from_secs(8), async {
        let mut bytes = Vec::new();
        while !bytes.ends_with(b"\r\n\r\n") {
            assert!(bytes.len() < 32768);
            bytes.push(socket.read_u8().await.expect("response head"));
        }
        let head = String::from_utf8(bytes).unwrap();
        let status = head.split_whitespace().nth(1).unwrap().parse().unwrap();
        let length: usize = head
            .lines()
            .find_map(|line| line.strip_prefix("Content-Length: "))
            .unwrap_or("0")
            .parse()
            .unwrap();
        assert!(length <= http::MAX_RESPONSE_BODY);
        let mut body = vec![0; length];
        socket.read_exact(&mut body).await.unwrap();
        (status, head, body)
    })
    .await
    .unwrap()
}
pub async fn call(fixture: &Fixture, path: &str) -> (u16, String, Vec<u8>) {
    let mut socket = fixture.connect().await;
    socket
        .write_all(request("GET", path, TOKEN, 0, true).as_bytes())
        .await
        .unwrap();
    response(&mut socket).await
}
pub fn context(operation: &str, generation: u64) -> artifacts::ReleaseMutationContext {
    artifacts::ReleaseMutationContext {
        scope: artifacts::LifecycleScope::Tenant(TenantId("tests".into())),
        actor: actor(),
        operation: Some(artifacts::ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: generation,
        }),
    }
}
pub fn actor() -> artifacts::ReleaseActor {
    artifacts::ReleaseActor {
        subject: "http-test".into(),
        kind: artifacts::ReleaseActorKind::Host,
    }
}

async fn publish(catalogs: &Catalogs, bytes: Vec<u8>, scheme: http::Scheme) {
    let codec = JsonManifestCodec::default();
    let artifact = artifact(bytes);
    let release = artifact.descriptor.release_digest.clone();
    let budget = artifact.manifest.execution.resource_budget_ceiling.clone();
    let publication = catalogs
        .artifacts
        .publish_managed(
            context("publish", 0),
            artifacts::ManagedPublicationUpload::Local(artifact),
            &mut |_| Ok(()),
        )
        .await
        .unwrap()
        .publication;
    let mut value: Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../examples/echo-contract/deployment.json"
    )))
    .unwrap();
    value["metadata"] = json!({"name":"web", "tenant":"tests"});
    value["spec"]["service"] = json!("web");
    value["spec"]["release"] = json!(release.0);
    value["spec"]["publication"] = json!(publication.id.as_str());
    value["spec"]["grants"] =
        json!([{"capability":"latent:context/context@0.1.0", "policy":"test/context"}]);
    let mut deployment = codec
        .decode_deployment(&serde_json::to_vec(&value).unwrap())
        .unwrap();
    deployment.resources = budget;
    catalogs.deployments.apply(deployment).await.unwrap();
    let selected = catalogs
        .deployments
        .resolve(
            &InvocationTarget {
                tenant: TenantId("tests".into()),
                service: latent_core::ServiceId("web".into()),
                contract: ContractId(http::CONTRACT.into()),
                function: FunctionId(http::FUNCTION.into()),
                route: Some("web".into()),
            },
            None,
        )
        .unwrap();
    let version = catalogs
        .deployments
        .get_versioned(&TenantId("tests".into()), &DeploymentId("web".into()))
        .await
        .unwrap()
        .unwrap()
        .generation;
    for method in ["GET", "POST", "HEAD"] {
        let id = format!("web-{}", method.to_lowercase());
        let state = catalogs
            .deployments
            .get_trigger(&TenantId("tests".into()), &TriggerId(id.clone()))
            .unwrap()
            .value()
            .state_version;
        let definition = json!({"apiVersion":"latent.dev/v1alpha1", "kind":"HttpTrigger", "metadata":{"name":id, "tenant":"tests"},
            "spec":{"target":{"service":"web", "contract":http::CONTRACT, "function":"handle", "route":"web", "publication":publication.id.as_str(), "revision":selected.revision.0, "deploymentGeneration":version},
                "configuration":{"profile":"buffered-v1", "scheme":if scheme == http::Scheme::Http { "http" } else { "https" }, "host":AUTHORITY, "path":"/", "pathMatch":"prefix", "method":method}}});
        let prepared = catalogs
            .deployments
            .prepare_trigger_operation(TriggerOperationRequest::Apply {
                context: TriggerOperationContext {
                    tenant: TenantId("tests".into()),
                    actor: actor(),
                    operation_id: id,
                    expected_state_version: state,
                },
                manifest: codec
                    .decode_trigger(&serde_json::to_vec(&definition).unwrap())
                    .unwrap(),
                expected_generation: 0,
            })
            .unwrap();
        catalogs
            .deployments
            .commit_trigger_operation(prepared)
            .unwrap()
            .value()
            .durability
            .as_ref()
            .unwrap();
    }
}
fn artifact(bytes: Vec<u8>) -> CapsuleArtifact {
    let digest = artifacts::content_digest(&bytes);
    let mut value: Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../examples/echo-contract/capsule.json"
    )))
    .unwrap();
    value["metadata"] = json!({"name":"web", "tenant":"tests"});
    value["component"]["digest"] = json!(digest.0);
    // A tenant-owned world exports the shared, unprivileged web interface.
    // The catalog deliberately rejects a tenant claiming the platform world.
    value["component"]["world"] = json!("tests:web/service@0.1.0");
    value["exports"] = json!([http::CONTRACT]);
    value["imports"] = json!([{"contract":"latent:context/context@0.1.0", "optional":false}]);
    value["execution"]["threading"] = json!("single-threaded");
    value["execution"]["limits"]["cpuFuel"] = json!(10_000_000_000u64);
    value["execution"]["limits"]["memoryBytes"] = json!(67_108_864);
    value["execution"]["limits"]["wallTimeLimitMillis"] = json!(5000);
    value["execution"]["limits"]["logBytes"] = json!(0);
    value["execution"]["snapshotEligible"] = json!(false);
    value["execution"]["fusionEligible"] = json!(false);
    let manifest = JsonManifestCodec::default()
        .decode_capsule(&serde_json::to_vec(&value).unwrap())
        .unwrap();
    Phase1ManifestValidator::new()
        .validate_capsule(&manifest)
        .unwrap();
    let contract = ContractId(http::CONTRACT.into());
    let signature = artifacts::content_digest(include_bytes!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../wit/platform/web/package.wit"
    )))
    .0;
    CapsuleArtifact {
        descriptor: artifacts::ArtifactDescriptor {
            reference: ArtifactReference("local://http-test".into()),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
            size_bytes: bytes.len() as u64,
            publisher: None,
            layers: vec![],
            annotations: Metadata::new(),
        },
        manifest,
        component_bytes: bytes,
        contracts: vec![artifacts::ContractDescriptor {
            id: contract.clone(),
            package_name: "latent:web".into(),
            semantic_version: "0.1.0".into(),
            dependencies: vec![],
            digest: signature.clone(),
            interfaces: vec![artifacts::InterfaceDescriptor {
                id: InterfaceId(contract.0),
                documentation: None,
                digest: signature,
                functions: vec![artifacts::FunctionDescriptor {
                    id: FunctionId("handle".into()),
                    name: "handle".into(),
                    asynchronous: true,
                    parameters: vec![artifacts::FieldDescriptor {
                        name: "request".into(),
                        value_type: artifacts::ValueType::Record("request".into()),
                        documentation: None,
                    }],
                    results: vec![artifacts::FieldDescriptor {
                        name: "response".into(),
                        value_type: artifacts::ValueType::Record("response".into()),
                        documentation: None,
                    }],
                    documentation: None,
                    attributes: Metadata::new(),
                }],
            }],
        }],
    }
}
