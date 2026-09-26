use super::*;
use latent_artifacts::{ArtifactRepository, ReleaseUseEligibility};
use latent_core::PlatformError;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_policy::supply_chain::{SupplyChainAuthority, SupplyChainClock, SystemSupplyChainClock};
use serde_json::json;
use std::sync::{atomic::AtomicU64, mpsc};

#[path = "../guest_sdk/package.rs"]
mod package;
#[path = "../../../latent-packaging/tests/fixtures/mod.rs"]
mod packaging;
#[path = "../../../latent-signing/tests/build_provenance/support.rs"]
#[allow(dead_code)]
mod provenance;
#[path = "../../../latent-packaging/tests/sbom_association/support.rs"]
#[allow(dead_code)]
mod sbom;

struct Clock(AtomicU64);
impl SupplyChainClock for Clock {
    fn now(&self) -> Result<u64, PlatformError> {
        Ok(self.0.load(Ordering::Acquire))
    }
}

pub struct Fixture {
    pub guest: super::fixture::Fixture,
    eligibility: ReleaseUseEligibility,
    clock: Arc<Clock>,
    _authority: Arc<SupplyChainAuthority>,
}
impl Fixture {
    pub async fn new(wait: bool) -> Self {
        let root = tempfile::tempdir().unwrap();
        let bundle = bundle();
        let release = bundle.layout().component_release().unwrap();
        let signers = package::Signers::new(latent_signing::PROVENANCE_BUILD_TYPE);
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = release.0.clone();
        observation.component_size = bundle
            .layers()
            .iter()
            .find(|layer| layer.path() == "component.wasm")
            .unwrap()
            .bytes()
            .len() as u64;
        let upload = signers.upload(&bundle, &observation);
        let clock = Arc::new(Clock(AtomicU64::new(SystemSupplyChainClock.now().unwrap())));
        let authority = Arc::new(
            SupplyChainAuthority::open_with_runtime(
                &root.path().join("trust"),
                signers.policy,
                clock.clone(),
                5,
                Arc::new(support::config().detected_runtime_profile().unwrap()),
            )
            .unwrap(),
        );
        let catalog = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                root.path().join("catalog"),
                Default::default(),
                Default::default(),
                authority.clone(),
            )
            .unwrap(),
        );
        catalog
            .admit_package(&TenantId("tests".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
        let eligibility = catalog
            .execution_eligibility_selected(&release, None)
            .unwrap()
            .unwrap();
        let timer = wait.then(|| {
            Arc::new(latent_node::CurrentnessReadTimer)
                as Arc<dyn latent_executor::PreparationReadWait>
        });
        let guest = super::fixture::Fixture::from_publication(
            root,
            catalog,
            eligibility.clone(),
            None,
            timer,
        )
        .await;
        Self {
            guest,
            eligibility,
            clock,
            _authority: authority,
        }
    }

    pub fn hold_after_first_sample(&self) -> Arc<Mutex<Option<Fence>>> {
        let held = Arc::new(Mutex::new(None));
        let keep = Arc::clone(&held);
        let eligibility = self.eligibility.clone();
        *self.guest.clock.hook.lock().unwrap() = Some(Box::new(move || {
            *keep.lock().unwrap() = Some(Fence::hold(&eligibility));
        }));
        held
    }

    pub fn expire_original_lease(&self) {
        self.clock.0.fetch_add(6, Ordering::AcqRel);
    }
}

fn bundle() -> latent_packaging::PackageBundle {
    use latent_artifacts::package::{
        artifact_blob_digest, encode_wit_lock, WitLock, WitLockedPackage,
    };
    let bytes = component::bytes();
    let source = format!("package tests:broker@0.1.0; interface api {{ read: func() -> u64; }} world service {{ import {}; export api; }}", component::CAP).into_bytes();
    let function = json!({"id":"read","name":"read","asynchronous":false,"parameters":[],
        "results":[{"name":"result","value_type":"U64","documentation":null}],"documentation":null,"attributes":{}});
    let mut interface =
        json!({"id":component::CONTRACT,"functions":[function],"documentation":null});
    interface["digest"] =
        json!(artifact_blob_digest(&serde_json::to_vec(&interface).unwrap()).as_str());
    let mut contract = json!({"id":component::CONTRACT,"package_name":"tests:broker","semantic_version":"0.1.0","interfaces":[interface],"dependencies":[]});
    contract["digest"] =
        json!(artifact_blob_digest(&serde_json::to_vec(&contract).unwrap()).as_str());
    let contracts =
        serde_json::to_vec(&json!({"format_version":1,"contracts":[contract]})).unwrap();
    let mut artifact = support::artifact_bytes(bytes.clone(), &[component::CONTRACT]);
    artifact.manifest.world = ContractId("tests:broker/service@0.1.0".into());
    artifact
        .manifest
        .imports
        .push(latent_manifest::ContractImport {
            contract: ContractId(component::CAP.into()),
            optional: false,
        });
    let manifest = JsonManifestCodec::default()
        .encode_capsule(&artifact.manifest)
        .unwrap();
    let lock = WitLock {
        format_version: 1,
        world: "tests:broker/service@0.1.0".into(),
        contracts_digest: artifact_blob_digest(&contracts),
        packages: vec![
            WitLockedPackage {
                id: "latent:clock@0.1.0".into(),
                source_path: "wit/clock.wit".into(),
                digest: artifact_blob_digest(packaging::component::CLOCK_WIT),
                dependencies: vec![],
            },
            WitLockedPackage {
                id: "tests:broker@0.1.0".into(),
                source_path: "wit/service.wit".into(),
                digest: artifact_blob_digest(&source),
                dependencies: vec!["latent:clock@0.1.0".into()],
            },
        ],
    };
    let mut input = packaging::capsule(Default::default());
    input.version = artifact.manifest.semantic_version.clone();
    for layer in &mut input.layers {
        layer.bytes = match layer.path.as_str() {
            "component.wasm" => bytes.clone(),
            "capsule.json" => manifest.clone(),
            "contracts.json" => contracts.clone(),
            "wit-lock.json" => encode_wit_lock(&lock, Default::default()).unwrap(),
            "wit/service.wit" => source.clone(),
            _ => layer.bytes.clone(),
        };
    }
    let inventory = sbom::inventory(&input);
    latent_packaging::build_package_with_sbom(input, inventory, Default::default()).unwrap()
}

pub struct Fence {
    release: Option<mpsc::SyncSender<()>>,
    worker: Option<std::thread::JoinHandle<Result<(), PlatformError>>>,
}
impl Fence {
    fn hold(eligibility: &ReleaseUseEligibility) -> Self {
        let grant = eligibility.admission().unwrap().clone();
        let (entered_send, entered) = mpsc::sync_channel(1);
        let (release, released) = mpsc::sync_channel(1);
        let worker = std::thread::spawn(move || {
            grant.with_current(&mut |_| {
                entered_send.send(()).unwrap();
                released.recv_timeout(Duration::from_secs(10)).unwrap();
                Ok(())
            })
        });
        let owner = Self {
            release: Some(release),
            worker: Some(worker),
        };
        entered.recv_timeout(Duration::from_secs(5)).unwrap();
        owner
    }
    pub fn release(mut self) {
        self.release.take().unwrap().send(()).unwrap();
        self.worker.take().unwrap().join().unwrap().unwrap();
    }
}
impl Drop for Fence {
    fn drop(&mut self) {
        if let Some(release) = self.release.take() {
            let _ = release.send(());
        }
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}
