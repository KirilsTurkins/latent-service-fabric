use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::{
    artifact_blob_digest, encode_wit_lock, LayerRole, PackageKind, PackageLimits, WitLock,
    WitLockedPackage,
};
use latent_artifacts::{AdmissionEvidence, ReleaseEvidenceUpload};
use latent_core::{PublisherId, TenantId};
use latent_packaging::{
    build_package_with_sbom, LayerInput, PackageInput, PackagingLimits, SbomDependencyCompleteness,
    SbomDigestScope, SbomEntryKind, SbomEntryOrigin, SbomInventory, SbomInventoryEntry,
};
use latent_policy::supply_chain::{
    verify_package_once, PackageVerificationRequest, SupplyChainPolicy,
};
use latent_signing::{
    generate_signing_key, BuildMaterial, BuildObservation, BuildParameters, BuildRecipe,
    BuildSource, BuilderPolicy, LocalBuilderSigner, LocalSigner, PackageSigningSubject,
    ProvenanceLimits, PublisherPolicy, SignatureLimits, SignatureValidity, PROVENANCE_BUILD_TYPE,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::error::Error;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const TEST_REPOSITORY: &str = "https://example.invalid/native-vm-test-observation";
const PUBLISHER: &str = "native-vm-test-publisher";
const BUILDER: &str = "native-vm-test-builder";

fn read(path: &Path) -> Result<Vec<u8>> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.len() > 16 * 1024 * 1024 {
        return Err("test input is not a bounded regular file".into());
    }
    let mut result = Vec::new();
    fs::File::open(path)?
        .take(16 * 1024 * 1024 + 1)
        .read_to_end(&mut result)?;
    if result.len() > 16 * 1024 * 1024 {
        return Err("test input limit".into());
    }
    Ok(result)
}

fn write_json(path: &Path, value: &Value) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > 1024 * 1024 {
        return Err("test document limit".into());
    }
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?
        .write_all(&bytes)?;
    Ok(())
}

fn layer(path: &str, role: LayerRole, media: &str, bytes: Vec<u8>) -> LayerInput {
    LayerInput {
        path: path.into(),
        role,
        media_type: media.into(),
        bytes,
    }
}

fn package(bundled: &Path) -> Result<latent_packaging::PackageBundle> {
    let example = bundled.join("examples/echo");
    let contracts = read(&example.join("contracts.json"))?;
    let component = read(&example.join("echo-capsule.wasm"))?;
    let manifest = read(&example.join("capsule.json"))?;
    let capsule: Value = serde_json::from_slice(&manifest)?;
    if capsule["component"]["digest"] != artifact_blob_digest(&component).to_string() {
        return Err("bundled echo identity mismatch".into());
    }
    let mut input = PackageInput {
        kind: PackageKind::Capsule,
        name: "native-vm-echo-test".into(),
        version: "0.1.0".into(),
        entrypoint: "component.wasm".into(),
        annotations: BTreeMap::from([("org.latent.test-only".into(), "native-runtime-vm".into())]),
        layers: vec![
            layer(
                "component.wasm",
                LayerRole::Component,
                "application/wasm",
                component,
            ),
            layer(
                "capsule.json",
                LayerRole::CapsuleManifest,
                "application/vnd.latent.capsule.manifest.v1+json",
                manifest,
            ),
            layer(
                "contracts.json",
                LayerRole::Contracts,
                "application/vnd.latent.contracts.v1+json",
                contracts.clone(),
            ),
        ],
    };
    let mut packages = Vec::new();
    for (identifier, path, supplied, dependencies) in [
        (
            "examples:echo@0.1.0",
            "wit/echo.wit",
            "wit/echo.wit",
            vec!["latent:context@0.1.0".into(), "latent:log@0.1.0".into()],
        ),
        (
            "latent:context@0.1.0",
            "wit/context.wit",
            "wit/context.wit",
            vec![],
        ),
        ("latent:log@0.1.0", "wit/log.wit", "wit/log.wit", vec![]),
    ] {
        let bytes = read(&example.join(supplied))?;
        packages.push(WitLockedPackage {
            id: identifier.into(),
            source_path: path.into(),
            digest: artifact_blob_digest(&bytes),
            dependencies,
        });
        input
            .layers
            .push(layer(path, LayerRole::Asset, "text/plain", bytes));
    }
    let lock = WitLock {
        format_version: 1,
        world: "examples:echo/service@0.1.0".into(),
        contracts_digest: artifact_blob_digest(&contracts),
        packages,
    };
    input.layers.push(layer(
        "wit-lock.json",
        LayerRole::WitLock,
        "application/vnd.latent.wit-lock.v1+json",
        encode_wit_lock(&lock, PackageLimits::default()).map_err(|_| "fixture-wit-lock")?,
    ));
    let entries = input
        .layers
        .iter()
        .filter(|item| matches!(item.role, LayerRole::Asset | LayerRole::Component))
        .map(|item| {
            let wit = lock
                .packages
                .iter()
                .find(|entry| entry.source_path == item.path);
            let (name, version) = wit.map_or((item.path.clone(), None), |entry| {
                let (name, version) = entry
                    .id
                    .rsplit_once('@')
                    .expect("fixed WIT package version");
                (name.into(), Some(version.into()))
            });
            SbomInventoryEntry {
                kind: if wit.is_some() {
                    SbomEntryKind::WitPackage
                } else {
                    SbomEntryKind::Component
                },
                name,
                version,
                source: None,
                license_expression: None,
                digest: Some(artifact_blob_digest(&item.bytes)),
                digest_scope: Some(if wit.is_some() {
                    SbomDigestScope::WitSource
                } else {
                    SbomDigestScope::OutputBytes
                }),
                size: Some(item.bytes.len() as u64),
                path: Some(item.path.clone()),
                manifest_digest: None,
                manifest_size: None,
                origin: SbomEntryOrigin::PackageInput,
            }
        })
        .collect();
    let inventory = SbomInventory {
        format_version: 1,
        package_kind: input.kind,
        package_name: input.name.clone(),
        package_version: input.version.clone(),
        dependency_completeness: SbomDependencyCompleteness::DeclaredInputsIncomplete,
        source_snapshot_digest: None,
        entries,
    };
    Ok(
        build_package_with_sbom(input, inventory, PackagingLimits::default())
            .map_err(|_| "fixture-package-build")?,
    )
}

fn policy(now: u64, publisher: &[u8; 32], builder: &[u8; 32]) -> Result<Value> {
    let publisher = json!({"formatVersion":1,"scope":"native-vm-test","generation":1,
        "validFrom":now-60,"validUntil":now+7200,"maxSignatureLifetimeSeconds":7200,"maxProofAgeSeconds":3600,
        "keys":[{"publisherId":PUBLISHER,"publicKey":STANDARD.encode(publisher),"validFrom":now-60,"validUntil":now+7200}]});
    let builder = json!({"formatVersion":1,"scope":"native-vm-test","generation":1,
        "validFrom":now-60,"validUntil":now+7200,"maxSignatureLifetimeSeconds":7200,"maxProofAgeSeconds":3600,
        "keys":[{"builderId":BUILDER,"publicKey":STANDARD.encode(builder),"validFrom":now-60,"validUntil":now+7200}],
        "requirements":[{"builderId":BUILDER,"buildType":PROVENANCE_BUILD_TYPE,
                         "sourceRepository":TEST_REPOSITORY,"requireReproducible":false}]});
    let publisher_digest =
        PublisherPolicy::from_json(&serde_json::to_vec(&publisher)?, SignatureLimits::default())?
            .digest()
            .to_string();
    let builder_digest =
        BuilderPolicy::from_json(&serde_json::to_vec(&builder)?, ProvenanceLimits::default())?
            .digest()
            .to_string();
    Ok(
        json!({"formatVersion":1,"generation":1,"scope":"native-vm-test","validFrom":now-60,"validUntil":now+7200,
        "tenants":[{"tenant":"examples","publishers":[PUBLISHER]}],"publisher":publisher,"builder":builder,
        "publisherRevocations":{"formatVersion":1,"scope":"native-vm-test","policyDigest":publisher_digest,
            "generation":1,"validFrom":now-60,"validUntil":now+7200,"revokedKeys":[],"revokedPublishers":[]},
        "builderRevocations":{"formatVersion":1,"scope":"native-vm-test","policyDigest":builder_digest,
            "generation":1,"validFrom":now-60,"validUntil":now+7200,"revokedKeys":[],"revokedBuilders":[]},
        "sbom":{"formatVersion":1,"embedded":"required","detached":"optional","requireSource":[],"requireLicense":[]}}),
    )
}

fn synthetic_observation(subject: &PackageSigningSubject, now: u64) -> BuildObservation {
    let marker = b"synthetic native VM test observation, not actual build provenance";
    let digest = artifact_blob_digest(marker).to_string();
    BuildObservation {
        format_version: 1,
        build_type: PROVENANCE_BUILD_TYPE.into(),
        source: BuildSource {
            repository: TEST_REPOSITORY.into(),
            revision: "0".repeat(40),
            snapshot_digest: digest.clone(),
            repository_trust: "operator-asserted".into(),
            capture: "git-archive-allowlist".into(),
        },
        component_digest: subject
            .component_digest()
            .expect("capsule component")
            .to_string(),
        component_size: subject.component_size().expect("capsule size"),
        materials: [
            "build-recipe",
            "cargo",
            "dependency-lock",
            "rustc",
            "source-snapshot",
            "toolchain-config",
            "wasm-tools",
        ]
        .into_iter()
        .map(|name| BuildMaterial {
            name: name.into(),
            digest: digest.clone(),
            size: marker.len() as u64,
        })
        .collect(),
        parameters: BuildRecipe::Rust(BuildParameters {
            cargo_package: "latent-toolchain-smoke".into(),
            cargo_example: "echo-capsule".into(),
            target: "wasm32-unknown-unknown".into(),
            profile: "release".into(),
            locked: true,
            incremental: false,
        }),
        started_at: now - 3,
        finished_at: now - 2,
        reproducibility: "not-checked".into(),
        hermetic: false,
        dependency_completeness: "lockfile-only".into(),
    }
}

fn export(bundled: &Path, output: &Path) -> Result<()> {
    fs::create_dir(output)?;
    let bundle = package(bundled)?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let publisher_key = generate_signing_key()?;
    let publisher_public = *publisher_key.public_key();
    let publisher = LocalSigner::from_pkcs8(
        publisher_key.into_pkcs8(),
        PublisherId(PUBLISHER.into()),
        publisher_public,
    )?;
    let builder_key = generate_signing_key()?;
    let builder_public = *builder_key.public_key();
    let builder =
        LocalBuilderSigner::from_pkcs8(builder_key.into_pkcs8(), BUILDER.into(), builder_public)?;
    let policy = policy(now, &publisher_public, &builder_public)?;
    let subject = PackageSigningSubject::from_package(
        bundle.manifest_bytes(),
        bundle.config_bytes(),
        PackageLimits::default(),
    )?;
    let validity = SignatureValidity {
        issued_at: now - 1,
        expires_at: now + 3600,
    };
    let signature = publisher.sign_package(&subject, validity, SignatureLimits::default())?;
    let provenance = builder.sign_build(
        &subject,
        &synthetic_observation(&subject, now),
        validity,
        ProvenanceLimits::default(),
    )?;
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
    let approved = SupplyChainPolicy::from_json(&serde_json::to_vec(&policy)?)
        .map_err(|_| "fixture-policy")?;
    verify_package_once(
        &approved,
        PackageVerificationRequest {
            tenant: &TenantId("examples".into()),
            package: &bundle,
            evidence: &evidence,
            unix_seconds: now,
        },
    )
    .map_err(|_| "fixture-public-verification")?;
    latent_packaging::write_package_directory(&bundle, &output.join("package"))
        .map_err(|_| "fixture-package-export")?;
    latent_packaging::write_package_evidence(
        bundle.layout().digest(),
        &evidence,
        &output.join("evidence"),
        16 * 1024 * 1024,
    )
    .map_err(|_| "fixture-evidence-export")?;
    write_json(&output.join("policy.json"), &policy)?;
    write_json(
        &output.join("fixture.json"),
        &json!({"formatVersion":1,"syntheticTestTrust":true,
        "componentDigest":subject.component_digest().expect("capsule component").to_string(),
        "packageDigest":bundle.layout().digest().to_string(),"expiresAtUnixSeconds":now+3600,
        "privateKeysExported":false,"runtimeDefaultTrust":false,"actualBuildProvenanceClaim":false}),
    )?;
    Ok(())
}

fn main() {
    let arguments: Vec<_> = std::env::args_os().skip(1).collect();
    if arguments.len() != 3 || arguments[0] != "--test-only" {
        eprintln!("usage: latent-native-vm-fixture --test-only BUNDLED_ROOT NEW_OUTPUT");
        std::process::exit(2);
    }
    if export(Path::new(&arguments[1]), Path::new(&arguments[2])).is_err() {
        eprintln!("native VM test fixture generation failed");
        std::process::exit(1);
    }
    println!(
        "fresh public-only test trust exported; no runtime defaults or build provenance claim"
    );
}
