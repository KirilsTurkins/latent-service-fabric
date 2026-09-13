//! Explicit, tiny, freshly signed test material for the separate CLI/node runner.
//! No signing key or invented production-build claim leaves this test process.
use super::*;
use latent_artifacts::ReleaseEvidenceUpload;
use latent_packaging::{PackageFile, PackageSource};
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

#[path = "operator_fixture/resources.rs"]
mod resources;

#[test]
#[ignore = "Explicit fixture exporter for tools/run_phase2_operator_workflow.py"]
fn export_operator_workflow_fixture() {
    let root = std::env::var_os("LSF_OPERATOR_FIXTURE_ROOT").expect("explicit fixture output root");
    let root = Path::new(&root);
    // Never overwrite an operator directory or emit fixtures during ordinary tests.
    std::fs::create_dir(root).unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let publisher_key = generate_signing_key().unwrap();
    let publisher_public = *publisher_key.public_key();
    let publisher = LocalSigner::from_pkcs8(
        publisher_key.into_pkcs8(),
        PublisherId("publisher-a".into()),
        publisher_public,
    )
    .unwrap();
    let builder_key = generate_signing_key().unwrap();
    let builder_public = *builder_key.public_key();
    let builder = LocalBuilderSigner::from_pkcs8(
        builder_key.into_pkcs8(),
        "builder-a".into(),
        builder_public,
    )
    .unwrap();
    let policy = fresh_policy(now, &publisher_public, &builder_public);
    write_json(&root.join("policy.json"), &policy);
    let approved = SupplyChainPolicy::from_json(&serde_json::to_vec(&policy).unwrap()).unwrap();
    for (name, alternate) in [("blue", false), ("green", true)] {
        let directory = root.join(name);
        std::fs::create_dir(&directory).unwrap();
        let mut input = packaging::capsule(packaging::component::Options::default());
        if alternate {
            let component = input
                .layers
                .iter_mut()
                .find(|layer| layer.path == "component.wasm")
                .unwrap();
            // An inert, valid custom section creates a distinct compatible revision.
            component.bytes.extend_from_slice(&[0, 2, 1, b'g']);
            let digest = artifact_blob_digest(&component.bytes).to_string();
            packaging::mutate_json(&mut input, "capsule.json", |manifest| {
                manifest["component"]["digest"] = json!(digest);
            });
        }
        let inventory = sbom::inventory(&input);
        export_source(&directory, &input, &inventory);
        let bundle = build_package_with_sbom(input, inventory, PackagingLimits::default()).unwrap();
        let subject = PackageSigningSubject::from_package(
            bundle.manifest_bytes(),
            bundle.config_bytes(),
            PackageLimits::default(),
        )
        .unwrap();
        let validity = SignatureValidity {
            issued_at: now - 1,
            expires_at: now + 1800,
        };
        let signature = publisher
            .sign_package(&subject, validity, SignatureLimits::default())
            .unwrap();
        let mut observation = observation(&subject);
        observation.started_at = now - 3;
        observation.finished_at = now - 2;
        let provenance = builder
            .sign_build(
                &subject,
                &observation,
                validity,
                ProvenanceLimits::default(),
            )
            .unwrap();
        let evidence = ReleaseEvidenceUpload {
            signatures: vec![AdmissionEvidence {
                manifest: signature.manifest_bytes().to_vec(),
                configuration: b"{}".to_vec(),
                payload: signature.payload_bytes().to_vec(),
            }],
            provenance: vec![AdmissionEvidence {
                manifest: provenance.manifest_bytes().to_vec(),
                configuration: b"{}".to_vec(),
                payload: provenance.payload_bytes().to_vec(),
            }],
            sboms: vec![],
        };
        crate::supply_chain::verify_package_once(
            &approved,
            crate::supply_chain::PackageVerificationRequest {
                tenant: &latent_core::TenantId("tests".into()),
                package: &bundle,
                evidence: &evidence,
                unix_seconds: now,
            },
        )
        .unwrap();
        latent_packaging::write_package_directory(&bundle, &directory.join("package")).unwrap();
        latent_packaging::write_package_evidence(
            bundle.layout().digest(),
            &evidence,
            &directory.join("evidence"),
            16 * 1024 * 1024,
        )
        .unwrap();
        let mut deployment: Value = serde_json::from_slice(include_bytes!(
            "../../../../../examples/echo-contract/deployment.json"
        ))
        .unwrap();
        deployment["metadata"] = json!({"name":name,"tenant":"tests"});
        deployment["spec"]["service"] = json!("tests/packaging");
        deployment["spec"]["release"] = json!(subject.component_digest().unwrap().to_string());
        deployment["spec"]["grants"] = json!([
            {"capability":packaging::component::CLOCK,"policy":"tests/clock"}
        ]);
        write_json(&directory.join("deployment.json"), &deployment);
    }
    write_json(
        &root.join("fixture.json"),
        &json!({
            "formatVersion":1,"tenant":"tests","service":"tests/packaging",
            "contract":packaging::component::CONTRACT,"function":"inspect",
            "input":[{"count":7,"outcome":{"ok":{"case":"empty"}}}],
            "expiresAtUnixSeconds":(now+1800).to_string(),
            "verifiedAtUnixSeconds":now.to_string(),
            "proofAgeExpiresAtUnixSeconds":(now+601).to_string(),
            "policyExpiresAtUnixSeconds":(now+3601).to_string(),
            "provenance":"synthetic signed test observation; no actual build provenance claim"
        }),
    );
}

fn fresh_policy(now: u64, publisher: &[u8; 32], builder: &[u8; 32]) -> Value {
    // Reuse the accepted schema, replacing all temporal/key identities together.
    let mut policy = Fixture::new().policy;
    for field in [
        None,
        Some("publisher"),
        Some("builder"),
        Some("publisherRevocations"),
        Some("builderRevocations"),
    ] {
        let document = if let Some(field) = field {
            &mut policy[field]
        } else {
            &mut policy
        };
        document["validFrom"] = json!(now - 60);
        document["validUntil"] = json!(now + 3600);
    }
    for (field, key) in [("publisher", publisher), ("builder", builder)] {
        policy[field]["maxProofAgeSeconds"] = json!(600);
        policy[field]["keys"][0]["publicKey"] = json!(STANDARD.encode(key));
        policy[field]["keys"][0]["validFrom"] = json!(now - 60);
        policy[field]["keys"][0]["validUntil"] = json!(now + 3600);
    }
    policy["publisherRevocations"]["policyDigest"] = json!(PublisherPolicy::from_json(
        &serde_json::to_vec(&policy["publisher"]).unwrap(),
        SignatureLimits::default(),
    )
    .unwrap()
    .digest()
    .to_string());
    policy["builderRevocations"]["policyDigest"] = json!(BuilderPolicy::from_json(
        &serde_json::to_vec(&policy["builder"]).unwrap(),
        ProvenanceLimits::default(),
    )
    .unwrap()
    .digest()
    .to_string());
    policy
}

fn export_source(
    directory: &Path,
    input: &latent_packaging::PackageInput,
    inventory: &latent_packaging::SbomInventory,
) {
    let inputs = directory.join("inputs");
    std::fs::create_dir(&inputs).unwrap();
    for layer in &input.layers {
        let path = inputs.join(&layer.path);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, &layer.bytes).unwrap();
    }
    let source = PackageSource {
        format_version: 1,
        kind: input.kind,
        name: input.name.clone(),
        version: input.version.clone(),
        entrypoint: input.entrypoint.clone(),
        annotations: input.annotations.clone(),
        layers: input
            .layers
            .iter()
            .map(|layer| PackageFile {
                path: layer.path.clone(),
                source: layer.path.clone(),
                role: layer.role,
                media_type: layer.media_type.clone(),
            })
            .collect(),
    };
    write_json(&directory.join("package-source.json"), &source);
    write_json(&directory.join("sbom-inputs.json"), inventory);
}

fn write_json(path: &Path, value: &impl serde::Serialize) {
    std::fs::write(path, serde_json::to_vec(value).unwrap()).unwrap();
}
