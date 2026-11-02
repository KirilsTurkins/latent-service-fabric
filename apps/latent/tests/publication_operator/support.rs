//! Fixed-size test listener and real native owners; child output uses the existing
//! bounded process owner. This is a CLI/transport/storage test, not a node soak.
#[path = "artifact.rs"]
mod artifact;
use super::process::{Output, Process, CALLER, FOREIGN, OPERATOR};
use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
    LifecycleScope, ManagedPublicationUpload, ReleaseActor, ReleaseActorKind,
    ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};
use latent_audit::{AuditHandle, AuditLimits, AuditWorker, DirectoryPhase2AuditJournal};
use latent_control_store::{DirectoryDeploymentRepository, DirectoryDeploymentRepositoryConfig};
use latent_core::{
    BoxFuture, InvocationPrincipal, Metadata, PlatformError, PrincipalKind, SystemActivationClock,
    TenantId,
};
use latent_node::{InventoryReporter, NodeInventory};
use latent_wire::{
    invocation::{AuthenticatedInvocationContext, LocalPrincipalPolicy},
    management::{
        LocalManagementPolicy, ManagementLimits, ManagementServiceAdapter, ManagementServices,
    },
};
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    pin::Pin,
    process::{Command, Stdio},
    sync::Arc,
    task::{Context, Poll},
    time::{Duration, Instant},
};
use tokio::{
    net::{TcpListener, TcpStream},
    runtime::Runtime,
    sync::oneshot,
    task::JoinHandle,
};
use tonic::{service::interceptor::InterceptedService, Request, Status};
struct NoInventory;
impl InventoryReporter for NoInventory {
    fn snapshot(&self) -> BoxFuture<'_, Result<NodeInventory, PlatformError>> {
        Box::pin(async { panic!("publication CLI must not issue inventory RPCs") })
    }
}
struct Incoming(TcpListener);
impl tonic::codegen::tokio_stream::Stream for Incoming {
    type Item = std::io::Result<TcpStream>;
    fn poll_next(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        self.0
            .poll_accept(cx)
            .map(|v| Some(v.map(|(stream, _)| stream)))
    }
}
fn authenticate(mut request: Request<()>) -> Result<Request<()>, Status> {
    let credential = request
        .metadata()
        .get("authorization")
        .and_then(|v| v.to_str().ok());
    let (subject, tenant, kind) = if credential == Some(format!("Bearer {OPERATOR}").as_str()) {
        ("operator", "acme", PrincipalKind::Administrator)
    } else if credential == Some(format!("Bearer {CALLER}").as_str()) {
        ("caller", "acme", PrincipalKind::User)
    } else if credential == Some(format!("Bearer {FOREIGN}").as_str()) {
        ("foreign", "other", PrincipalKind::Administrator)
    } else {
        return Err(Status::unauthenticated("fixed test credential required"));
    };
    request
        .extensions_mut()
        .insert(AuthenticatedInvocationContext::new(InvocationPrincipal {
            subject: subject.into(),
            tenant: Some(TenantId(tenant.into())),
            kind,
            service: None,
            claims: Metadata::new(),
        }));
    Ok(request)
}
pub(super) struct Harness {
    runtime: Runtime,
    pub artifacts: Arc<DirectoryArtifactRepository>,
    _control: Arc<DirectoryDeploymentRepository>,
    pub audit: AuditHandle,
    worker: AuditWorker,
    stop: Option<oneshot::Sender<()>>,
    server: Option<JoinHandle<Result<(), tonic::transport::Error>>>,
    profile: PathBuf,
}
impl Harness {
    pub fn open(root: &Path, records: usize) -> Self {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .unwrap();
        let artifacts = Arc::new(
            DirectoryArtifactRepository::open(
                root.join("releases"),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let (audit, worker) = DirectoryPhase2AuditJournal::open(
            root.join("audit"),
            AuditLimits {
                maximum_records: records,
                ..AuditLimits::default()
            },
        )
        .unwrap();
        runtime
            .block_on(latent_artifacts::reconcile_publication_maintenance_audit(
                &audit, &artifacts,
            ))
            .unwrap();
        let control = Arc::new(
            runtime
                .block_on(DirectoryDeploymentRepository::open_with_catalog(
                    root.join("control"),
                    artifacts.clone(),
                    DirectoryDeploymentRepositoryConfig::default(),
                    artifacts.lifecycle_authority(),
                    Arc::new(
                        latent_manifest::RuntimeCompatibilityProfile::new(
                            "wasmtime",
                            "48.0.7",
                            "x86_64-unknown-linux-gnu",
                            &["x86_64.sse2"],
                            65536,
                            1000,
                        )
                        .unwrap(),
                    ),
                ))
                .unwrap(),
        );
        control
            .bind_publication_reference_authority(&artifacts)
            .unwrap();
        let adapter = ManagementServiceAdapter::new(
            ManagementServices {
                audit: Some(audit.clone()),
                rollouts: None,
                artifacts: artifacts.clone(),
                deployments: control.clone(),
                routes: control.clone(),
                inventory: Arc::new(NoInventory),
                principals: Arc::new(LocalPrincipalPolicy),
                authorization: Arc::new(LocalManagementPolicy),
                clock: Arc::new(SystemActivationClock),
            },
            ManagementLimits::default(),
        )
        .unwrap()
        .with_web_catalog(artifacts.clone())
        .unwrap();
        let listener = runtime.block_on(TcpListener::bind("127.0.0.1:0")).unwrap();
        let endpoint = format!("http://{}", listener.local_addr().unwrap());
        let (stop, done) = oneshot::channel();
        let server = runtime.spawn(
            tonic::transport::Server::builder()
                .concurrency_limit_per_connection(4)
                .add_service(InterceptedService::new(
                    adapter.release_server(),
                    authenticate,
                ))
                .serve_with_incoming_shutdown(Incoming(listener), async {
                    let _ = done.await;
                }),
        );
        let profile = root.join("client.json");
        fs::write(&profile,serde_json::to_vec(&json!({"formatVersion":1,"defaultProfile":"operator","profiles":[
            {"name":"operator","endpoint":endpoint,"tenant":"acme","token":OPERATOR,"rpcTimeoutMillis":4000},
            {"name":"caller","endpoint":endpoint,"tenant":"acme","token":CALLER,"rpcTimeoutMillis":4000},
            {"name":"foreign","endpoint":endpoint,"tenant":"other","token":FOREIGN,"rpcTimeoutMillis":4000}
        ]})).unwrap()).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&profile, fs::Permissions::from_mode(0o600)).unwrap();
        }
        Self {
            runtime,
            artifacts,
            _control: control,
            audit,
            worker,
            stop: Some(stop),
            server: Some(server),
            profile,
        }
    }
    pub fn retired(&self, name: &str) -> String {
        let context = ReleaseMutationContext {
            scope: LifecycleScope::Tenant(TenantId("acme".into())),
            actor: ReleaseActor {
                subject: "fixture".into(),
                kind: ReleaseActorKind::Host,
            },
            operation: None,
        };
        let publication = self
            .runtime
            .block_on(self.artifacts.publish_managed(
                context.clone(),
                ManagedPublicationUpload::Local(artifact::artifact("acme", name, name)),
                &mut |_| Ok(()),
            ))
            .unwrap()
            .publication;
        self.artifacts
            .change_publication_lifecycle(
                ReleaseMutationContext {
                    operation: Some(ReleaseOperationPrecondition {
                        operation_id: format!("retire-{name}"),
                        expected_generation: 1,
                    }),
                    ..context
                },
                &publication,
                ReleaseLifecycleAction::Retire,
                ReleaseLifecycleReason::OperatorRetirement,
                &mut |_| Ok(()),
            )
            .unwrap();
        publication.id.into_string()
    }
    pub fn run(&self, profile: &str, args: &[&str]) -> Output {
        let mut cmd = Command::new(env!("CARGO_BIN_EXE_latent"));
        cmd.arg("--config")
            .arg(&self.profile)
            .args([
                "--profile",
                profile,
                "--output",
                "json",
                "release",
                "retention",
            ])
            .args(args)
            .stdin(Stdio::null());
        Process::spawn(cmd, Duration::from_secs(5)).wait()
    }
    pub fn call(&self, args: &[&str]) -> Value {
        self.run("operator", args).json(0, "success")
    }
    pub fn selected(&self, p: &str) -> (String, String) {
        let v = self.call(&["snapshot", "--publication", p]);
        (
            v["data"]["catalogFence"].as_str().unwrap().into(),
            format!(
                "{}={}",
                p,
                v["data"]["entries"][0]["target"]["expectedGeneration"]
                    .as_str()
                    .unwrap()
            ),
        )
    }
}
impl Drop for Harness {
    fn drop(&mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        if let Some(mut server) = self.server.take() {
            let stopped = self.runtime.block_on(async {
                tokio::time::timeout(Duration::from_secs(5), &mut server).await
            });
            if stopped.is_err() {
                server.abort();
            }
            if !std::thread::panicking() {
                assert!(stopped.unwrap().unwrap().is_ok());
            }
        }
        self.audit.close();
        let result = self
            .worker
            .join_until(Instant::now() + Duration::from_secs(5));
        if !std::thread::panicking() {
            assert!(result.unwrap());
        }
    }
}
