//! Fixed resource profile material. Every package is independently signed and verified.
use super::*;

#[test]
#[ignore = "Explicit fixture exporter for tools/phase2_gate_resource.py"]
fn export_phase2_resource_fixture() {
    let output = std::env::var_os("LSF_PHASE2_RESOURCE_FIXTURE_ROOT")
        .expect("explicit resource fixture output root");
    let root = Path::new(&output);
    std::fs::create_dir(root).unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let key = generate_signing_key().unwrap();
    let publisher_public = *key.public_key();
    let publisher = LocalSigner::from_pkcs8(
        key.into_pkcs8(),
        PublisherId("publisher-a".into()),
        publisher_public,
    )
    .unwrap();
    let key = generate_signing_key().unwrap();
    let builder_public = *key.public_key();
    let builder =
        LocalBuilderSigner::from_pkcs8(key.into_pkcs8(), "builder-a".into(), builder_public)
            .unwrap();
    let policy = fresh_policy(now, &publisher_public, &builder_public);
    write_json(&root.join("policy.json"), &policy);
    let approved = SupplyChainPolicy::from_json(&serde_json::to_vec(&policy).unwrap()).unwrap();
    let mut identities = Vec::with_capacity(32);
    for ordinal in 0_u8..32 {
        let name = format!("capsule-{ordinal:02}");
        let directory = root.join(&name);
        std::fs::create_dir(&directory).unwrap();
        let mut input = packaging::capsule(packaging::component::Options::default());
        let component = input
            .layers
            .iter_mut()
            .find(|layer| layer.path == "component.wasm")
            .unwrap();
        // Custom section id=0, payload length=3, one-byte name=r, one-byte payload.
        // Neither the program nor its supported WIT surface changes.
        component.bytes.extend_from_slice(&[0, 3, 1, b'r', ordinal]);
        assert!(component.bytes.len() <= 64 * 1024);
        let component_digest = artifact_blob_digest(&component.bytes).to_string();
        packaging::mutate_json(&mut input, "capsule.json", |manifest| {
            manifest["component"]["digest"] = json!(component_digest);
        });
        let inventory = sbom::inventory(&input);
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
        let mut observed = observation(&subject);
        observed.started_at = now - 3;
        observed.finished_at = now - 2;
        let provenance = builder
            .sign_build(&subject, &observed, validity, ProvenanceLimits::default())
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
            1024 * 1024,
        )
        .unwrap();
        let mut deployment: Value = serde_json::from_slice(include_bytes!(
            "../../../../../../examples/echo-contract/deployment.json"
        ))
        .unwrap();
        deployment["metadata"] = json!({"name":name,"tenant":"tests"});
        deployment["spec"]["service"] = json!("tests/packaging");
        deployment["spec"]["release"] = json!(component_digest);
        deployment["spec"]["route"]["weight"] = json!(10000);
        deployment["spec"]["grants"] = json!([
            {"capability":packaging::component::CLOCK,"policy":"tests/clock"}
        ]);
        write_json(&directory.join("deployment.json"), &deployment);
        identities.push(json!({
            "name":name,
            "packageDigest":bundle.layout().digest().to_string(),
            "componentDigest":component_digest,
            "manifestDigest":artifact_blob_digest(bundle.manifest_bytes()).to_string()
        }));
    }
    write_json(
        &root.join("fixture.json"),
        &json!({
            "formatVersion":1,"profile":"phase2-dormant-32-r1",
            "tenant":"tests","service":"tests/packaging",
            "contract":packaging::component::CONTRACT,"function":"inspect",
            "input":[{"count":7,"outcome":{"ok":{"case":"empty"}}}],
            "verifiedAtUnixSeconds":now.to_string(),
            "proofAgeExpiresAtUnixSeconds":(now+601).to_string(),
            "expiresAtUnixSeconds":(now+1800).to_string(),
            "policyExpiresAtUnixSeconds":(now+3601).to_string(),
            "packages":identities,
            "syntheticTestEvidence":true,
            "provenance":"synthetic signed test observation; no actual build provenance claim"
        }),
    );
}
