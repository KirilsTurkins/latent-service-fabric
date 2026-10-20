//! Signed ordinary-source fixture under the unchanged development TCP provider.
use super::*;

pub(super) fn configuration(port: u16) -> StreamProviderConfig {
    StreamProviderConfig {
        format_version: 1,
        profile: latent_capabilities::broker::network::STREAM_PROFILE.into(),
        limits: StreamLimits::default(),
        destinations: vec![StreamDestination {
            tls: None,
            endpoint: StreamEndpoint {
                host: "127.0.0.1".into(),
                port,
                transport: StreamTransport::Tcp,
            },
            addresses: AddressPolicy {
                networks: vec!["127.0.0.1/32".parse().unwrap()],
                special_addresses: vec!["127.0.0.1".parse().unwrap()],
            },
            resolution: StreamResolution::Static {
                addresses: vec!["127.0.0.1".parse().unwrap()],
            },
        }],
    }
}

pub(super) async fn configured(root: &std::path::Path, port: u16) -> Fixture {
    let prepared = std::path::PathBuf::from(
        std::env::var_os("LSF_GO_SMTP_TLS_FIXTURE").expect("compile the guarded Go fixture"),
    );
    let record: serde_json::Value =
        serde_json::from_slice(&std::fs::read(prepared.join("GO-SMTP-TLS-COMPILE.json")).unwrap())
            .unwrap();
    let source = std::fs::read(prepared.join("src/main.go")).unwrap();
    let component = std::fs::read(prepared.join("build/component.wasm")).unwrap();
    assert_eq!(source, SOURCE);
    assert_eq!(
        std::fs::read_to_string(prepared.join("wit/world.wit")).unwrap(),
        WORLD
    );
    assert_eq!(record["profile"], PROFILE);
    assert_eq!(record["sourceUnchanged"], true);
    assert_eq!(
        record["sourceDigest"],
        latent_artifacts::package::artifact_blob_digest(&source).as_str()
    );
    assert_eq!(
        record["componentDigest"],
        latent_artifacts::package::artifact_blob_digest(&component).as_str()
    );
    let caller = packages::go_network_runtime(component, WORLD);
    let callee = packages::callee(42);
    // This signs the actual in-process native fixture package construction.
    // The separate retained compile observation binds the real Go compiler;
    // this is not a released standalone authoring/packager qualification.
    let signers = package::Signers::new(latent_signing::PROVENANCE_BUILD_TYPE);
    let mut uploads = vec![];
    for (bundle, original) in [
        (&caller, source.as_slice()),
        (
            &callee,
            include_bytes!("../local_service/component.rs").as_slice(),
        ),
    ] {
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = bundle.layout().component_release().unwrap().0;
        observation.component_size = bundle.blob("component.wasm").unwrap().len() as u64;
        let mut capture = original.to_vec();
        capture.extend_from_slice(include_bytes!("../local_service/packages.rs"));
        if std::ptr::eq(bundle, &caller) {
            capture.extend_from_slice(WORLD.as_bytes());
            capture.extend_from_slice(
                &std::fs::read(prepared.join("GO-SMTP-TLS-COMPILE.json")).unwrap(),
            );
        }
        observation.source.snapshot_digest =
            latent_artifacts::package::artifact_blob_digest(&capture).into_string();
        let material = observation
            .materials
            .iter_mut()
            .find(|material| material.name == "source-snapshot")
            .unwrap();
        material
            .digest
            .clone_from(&observation.source.snapshot_digest);
        material.size = capture.len() as u64;
        uploads.push(signers.upload(bundle, &observation));
    }
    let catalog = package::catalog(root, signers.policy, Some(packages::budget().memory_bytes));
    for upload in uploads {
        catalog
            .admit_package(&TenantId("tenant-a".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    Fixture::with_runtime_outbound_streams(
        (catalog, caller, callee),
        latent_core::activation_runtime::RuntimeLimits {
            tasks: 16,
            executors: 2,
            queued_work: 2,
            waits: 4,
            timers: 2,
            results: 2,
            native_owners: 2,
        },
        configuration(port),
    )
    .await
}

pub(super) fn request(
    f: &Fixture,
    id: &str,
    mode: u32,
    port: u16,
    root_pem: &str,
) -> ActivationRequest {
    let mut request = f.request(id, mode);
    request.target.contract = ContractId(CONTRACT.into());
    request.input = serde_json::to_vec(&json!([mode, json!({"address": format!("127.0.0.1:{port}"), "rootPem": root_pem, "serverName": "mail.stream.test"}).to_string()])).unwrap();
    request
}

pub(super) fn returned(receipt: latent_node::ActivationReceipt, expected: &str, contacts: u32) {
    let ActivationOutcome::Succeeded(success) = receipt.outcome else {
        panic!("{:?}", receipt.outcome);
    };
    assert_eq!(
        serde_json::from_slice::<Vec<String>>(&success.output).unwrap(),
        [expected]
    );
    assert_eq!(success.consumption.outbound_requests, contacts);
    assert!(success.consumption.cpu_fuel > 0);
    assert!(success.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
}

pub(super) async fn idle(f: &Fixture, label: &str) {
    f.idle().await;
    let owners = f.streams.as_ref().unwrap();
    assert_eq!(
        owners.lifecycle.status().unwrap().usage,
        latent_streams::StreamUsage::default()
    );
    assert_eq!(
        owners.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    assert_eq!(owners.pools.snapshot().unwrap().connections, 0);
    assert_eq!(owners.pools.snapshot().unwrap().running_requests, 0);
    println!(
        "GO_SMTP_OWNER {}",
        json!({"case":label,"stores":0,"instances":0,"streamOwners":0,"ioOwners":0,"kernelRetirementQualified":false})
    );
}

pub(super) fn observed(label: &str, mode: u32, result: &str, contacts: u64) {
    println!(
        "GO_SMTP_CASE {}",
        json!({"case":label,"mode":mode,"result":result,"contacts":contacts})
    );
}
