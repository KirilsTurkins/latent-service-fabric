//! Deliberately malformed final import, signed as an untrusted package.
//! This does not claim that the normal semantic package builder emitted it.
use super::{package, packages, provenance, success, Fixture};
use crate::fixture::RuntimeIdentities;
use latent_artifacts::{
    package::{
        artifact_blob_digest, decode_config, decode_manifest, encode_config, encode_manifest,
        inspect_package, verify_layer_bytes, ArtifactDescriptor, LayerRole, PackageLayer,
        PackageLimits, LAYER_PATH_ANNOTATION, LAYER_ROLE_ANNOTATION,
    },
    ArtifactRepository,
};
use latent_core::{activation_runtime::RuntimeLimits, PlatformErrorCode, TenantId};
use latent_executor::ExecutionBackend;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_packaging::{
    BuildInputIdentity, BuildReceipt, BundleInput, LayerInput, PackageBundle, PackageInput,
    SbomLimits, BUILD_INPUTS_PATH, CYCLONEDX_JSON_MEDIA_TYPE, SBOM_PATH,
};
use std::{collections::BTreeMap, time::Duration};

#[path = "../../../../latent-packaging/tests/sbom_association/support.rs"]
#[allow(dead_code)]
mod sbom;

fn adversarial_input(base: PackageBundle, mutant: &[u8]) -> BundleInput {
    let limits = PackageLimits::default();
    let raw = base.into_input();
    let mut config = decode_config(&raw.configuration, limits).unwrap();
    let mut manifest = decode_manifest(&raw.manifest, limits).unwrap();
    let mut blobs: BTreeMap<_, _> = raw.layers.into_iter().collect();
    let mutant_digest = artifact_blob_digest(mutant);
    let mut input = PackageInput {
        kind: config.kind,
        name: config.name.clone(),
        version: config.version.clone(),
        entrypoint: config.entrypoint.clone(),
        annotations: config.annotations.clone(),
        layers: vec![],
    };
    for layer in &config.layers {
        let mut bytes = blobs.remove(&layer.path).unwrap();
        if layer.path == SBOM_PATH || layer.path == BUILD_INPUTS_PATH {
            continue;
        }
        if layer.role == LayerRole::Component {
            bytes = mutant.to_vec();
        } else if layer.role == LayerRole::CapsuleManifest {
            let mut value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
            value["component"]["digest"] = serde_json::json!(mutant_digest.as_str());
            let codec = JsonManifestCodec::default();
            let decoded = codec
                .decode_capsule(&serde_json::to_vec(&value).unwrap())
                .unwrap();
            bytes = codec.encode_capsule(&decoded).unwrap();
        }
        input.layers.push(LayerInput {
            path: layer.path.clone(),
            role: layer.role,
            media_type: layer.media_type.clone(),
            bytes,
        });
    }
    assert!(blobs.is_empty());
    let document =
        latent_packaging::generate_cyclonedx_sbom(sbom::inventory(&input), SbomLimits::default())
            .unwrap();
    input.layers.push(LayerInput {
        path: SBOM_PATH.into(),
        role: LayerRole::Asset,
        media_type: CYCLONEDX_JSON_MEDIA_TYPE.into(),
        bytes: document.bytes().to_vec(),
    });
    input.layers.sort_by(|a, b| a.path.cmp(&b.path));
    let inputs = input
        .layers
        .iter()
        .map(|layer| {
            let digest = artifact_blob_digest(&layer.bytes).to_string();
            BuildInputIdentity {
                path: layer.path.clone(),
                role: layer.role,
                input_digest: digest.clone(),
                input_size: layer.bytes.len() as u64,
                output_digest: digest,
                output_size: layer.bytes.len() as u64,
            }
        })
        .collect();
    let receipt = BuildReceipt {
        format_version: 1,
        operation: "package-supplied-artifacts".into(),
        packager: "latent-packaging".into(),
        packager_version: env!("CARGO_PKG_VERSION").into(),
        inputs,
    };
    input.layers.push(LayerInput {
        path: BUILD_INPUTS_PATH.into(),
        role: LayerRole::Asset,
        media_type: "application/json".into(),
        bytes: serde_json::to_vec(&receipt).unwrap(),
    });
    input.layers.sort_by(|a, b| a.path.cmp(&b.path));
    config.component_digest = Some(mutant_digest);
    config.layers = input
        .layers
        .iter()
        .map(|layer| PackageLayer {
            path: layer.path.clone(),
            role: layer.role,
            media_type: layer.media_type.clone(),
            digest: artifact_blob_digest(&layer.bytes),
            size: layer.bytes.len() as u64,
        })
        .collect();
    let configuration = encode_config(&config, limits).unwrap();
    manifest.config.digest = artifact_blob_digest(&configuration);
    manifest.config.size = configuration.len() as u64;
    manifest.layers = config
        .layers
        .iter()
        .map(|layer| ArtifactDescriptor {
            media_type: layer.media_type.clone(),
            digest: layer.digest.clone(),
            size: layer.size,
            annotations: Some(BTreeMap::from([
                (LAYER_PATH_ANNOTATION.into(), layer.path.clone()),
                (LAYER_ROLE_ANNOTATION.into(), layer.role.as_str().into()),
            ])),
        })
        .collect();
    let manifest = encode_manifest(&manifest, limits).unwrap();
    let layout = inspect_package(&manifest, &configuration, limits).unwrap();
    for (layer, actual) in layout.config().layers.iter().zip(&input.layers) {
        assert_eq!(layer.path, actual.path);
        verify_layer_bytes(layer, &actual.bytes, limits).unwrap();
    }
    BundleInput {
        manifest,
        configuration,
        layers: input
            .layers
            .into_iter()
            .map(|layer| (layer.path, layer.bytes))
            .collect(),
    }
}

fn observation(component: &[u8], source: &[u8]) -> latent_signing::BuildObservation {
    let mut value = provenance::observation();
    value.source.repository = "https://github.com/KirilsTurkins/latent-service-fabric".into();
    value.component_digest = artifact_blob_digest(component).into_string();
    value.component_size = component.len() as u64;
    value.source.snapshot_digest = artifact_blob_digest(source).into_string();
    let material = value
        .materials
        .iter_mut()
        .find(|row| row.name == "source-snapshot")
        .unwrap();
    material.digest = value.source.snapshot_digest.clone();
    material.size = source.len() as u64;
    value
}

#[tokio::test]
#[ignore = "requires the prepared Java timer component and its validated unknown-import mutant"]
async fn signed_unknown_final_import_is_refused_before_execution_and_fresh_tenant_succeeds() {
    assert_eq!(
        std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(),
        Ok("java")
    );
    let fixture = std::path::PathBuf::from(std::env::var_os("LSF_JAVA_TIMER_FIXTURE").unwrap());
    let control =
        std::path::PathBuf::from(std::env::var_os("LSF_SDK694_FINAL_IMPORT_CONTROL").unwrap());
    let original = std::fs::read(fixture.join("build/component.wasm")).unwrap();
    let mutant = std::fs::read(control.join("component.wasm")).unwrap();
    let source = std::fs::read(fixture.join("src/Capsule.java")).unwrap();
    let wit = std::fs::read_to_string(fixture.join("wit/service.wit")).unwrap();
    let compile_bytes = std::fs::read(fixture.join("FIBERS-COMPILE.json")).unwrap();
    let compile: serde_json::Value = serde_json::from_slice(&compile_bytes).unwrap();
    let prepared_bytes = std::fs::read(control.join("PREPARED.json")).unwrap();
    let prepared: serde_json::Value = serde_json::from_slice(&prepared_bytes).unwrap();
    assert_eq!(
        source.as_slice(),
        include_bytes!("../../../../../sdk/java-guest/fibers/conformance/timers/Capsule.java")
    );
    assert_eq!(
        compile["componentDigest"],
        artifact_blob_digest(&original).as_str()
    );
    assert_eq!(
        compile["sourceDigest"],
        artifact_blob_digest(&source).as_str()
    );
    assert_eq!(compile["fixture"], "timers");
    assert_eq!(compile["profile"], "teavm-activation-fibers-v1");
    assert_eq!(compile["status"], "component-built-unqualified");
    assert_eq!(
        prepared["schemaVersion"],
        "latent.java.final-import.preparation.v1"
    );
    assert_eq!(prepared["status"], "prepared");
    assert_eq!(prepared["scope"], "test-only-adversarial-declaration");
    assert_eq!(prepared["runtimeOutcome"], "not-executed");
    assert_eq!(
        prepared["validatorFeatures"],
        "cm-threading,cm-async-stackful,cm-more-async-builtins"
    );
    assert_eq!(
        prepared["unknownInterface"],
        "diagnostic:unknown/final-import@0.1.0"
    );
    assert_eq!(
        prepared["componentDigest"],
        artifact_blob_digest(&original).as_str()
    );
    assert_eq!(
        prepared["mutantDigest"],
        artifact_blob_digest(&mutant).as_str()
    );
    assert_eq!(
        prepared["sourceDigest"],
        artifact_blob_digest(&source).as_str()
    );
    assert_eq!(
        prepared["witDigest"],
        artifact_blob_digest(wit.as_bytes()).as_str()
    );
    assert_eq!(
        prepared["compileReceiptDigest"],
        artifact_blob_digest(&compile_bytes).as_str()
    );
    assert!(original.len() <= 64 * 1024 * 1024);
    assert!(mutant.len() > original.len() && mutant.len() - original.len() <= 128);
    assert!(mutant.starts_with(&original));
    let suffix = &mutant[original.len()..];
    assert_eq!(prepared["suffixBytes"], suffix.len());
    assert_eq!(
        prepared["suffixDigest"],
        artifact_blob_digest(suffix).as_str()
    );
    assert_eq!(
        suffix
            .windows(b"diagnostic:unknown/final-import@0.1.0".len())
            .filter(|window| *window == b"diagnostic:unknown/final-import@0.1.0")
            .count(),
        1
    );

    let caller = packages::java_activation_runtime(original.clone(), &wit);
    let release = packages::release(&caller);
    let callee = packages::callee(42);
    let coherent_original = adversarial_input(
        packages::java_activation_runtime(original.clone(), &wit),
        &original,
    );
    let coherent_original = latent_packaging::inspect_bundle(
        coherent_original,
        latent_packaging::PackagingLimits::default(),
    )
    .expect("the rebuilt envelope passes normal inspection with the original component");
    let adversarial = adversarial_input(
        packages::java_activation_runtime(original.clone(), &wit),
        &mutant,
    );
    let mut source_record = source.clone();
    source_record.extend_from_slice(wit.as_bytes());
    source_record.extend_from_slice(&compile_bytes);
    let mut adversarial_source = source_record.clone();
    adversarial_source.extend_from_slice(&prepared_bytes);
    adversarial_source.extend_from_slice(include_bytes!("unknown_import.rs"));
    adversarial_source.extend_from_slice(artifact_blob_digest(&mutant).as_str().as_bytes());
    let tenant_a = TenantId("tenant-a".into());
    let tenant_b = TenantId("tenant-b".into());
    // This fixture's policy authorizes the same ephemeral publisher for both
    // tenant-a and tenant-b; the signed tenant-a control below proves the
    // former through normal enforced admission rather than relying on that
    // policy construction detail.
    let signers = package::Signers::for_tenant(latent_signing::PROVENANCE_BUILD_TYPE, &tenant_b);
    let bad = signers.adversarial_upload(adversarial, &observation(&mutant, &adversarial_source));
    let coherent_upload = signers.upload_for_tenant(
        &coherent_original,
        &observation(&original, &source_record),
        &tenant_a,
    );
    let good =
        signers.upload_for_tenant(&caller, &observation(&original, &source_record), &tenant_b);
    let good_callee = signers.upload_for_tenant(
        &callee,
        &observation(callee.blob("component.wasm").unwrap(), &source_record),
        &tenant_b,
    );
    // Use a separate empty catalog with the exact same policy and publisher
    // keys so the coherent tenant-a control cannot conflict with tenant-b's
    // publication of the same original component digest in the main catalog.
    let control_root = tempfile::tempdir().unwrap();
    let control_policy =
        latent_policy::supply_chain::SupplyChainPolicy::from_json(&signers.policy_document)
            .unwrap();
    let control_catalog = package::catalog(
        control_root.path(),
        control_policy,
        Some(packages::budget().memory_bytes),
    );
    let mut control_preflight_called = false;
    let control_entry = control_catalog
        .admit_package(&tenant_a, coherent_upload, &mut |_| {
            control_preflight_called = true;
            Ok(())
        })
        .await
        .expect("same-tenant coherent original passes enforced admission");
    assert!(control_preflight_called);
    assert_eq!(control_entry.tenant.as_ref(), Some(&tenant_a));
    assert_eq!(control_entry.descriptor.release_digest, release);
    assert!(control_catalog
        .get_catalog_entry(&tenant_a, &release)
        .await
        .unwrap()
        .is_some());
    let root = tempfile::tempdir().unwrap();
    let catalog = package::catalog(
        root.path(),
        signers.policy,
        Some(packages::budget().memory_bytes),
    );
    for upload in [good, good_callee] {
        catalog
            .admit_package(&tenant_b, upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    let limits = RuntimeLimits {
        tasks: 5,
        executors: 3,
        queued_work: 8,
        waits: 8,
        timers: 2,
        results: 8,
        native_owners: 2,
    };
    let f = Fixture::with_named_activation_runtime(
        1,
        (catalog, caller, callee),
        limits,
        120_000,
        RuntimeIdentities {
            tenant: tenant_b.clone(),
            ..RuntimeIdentities::default()
        },
    )
    .await;
    f.idle().await;
    let stores_before = f.backend.resource_snapshot().stores_created;
    assert_eq!(stores_before, 0);
    assert!(f.observations.starts.lock().unwrap().is_empty());
    let mut preflight_called = false;
    let error = f
        .catalog
        .admit_package(&tenant_a, bad, &mut |_| {
            preflight_called = true;
            Ok(())
        })
        .await
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
    assert_eq!(error.message, "component-world-identity-mismatch");
    assert!(!preflight_called);
    assert_eq!(f.backend.resource_snapshot().stores_created, stores_before);
    assert!(f.observations.starts.lock().unwrap().is_empty());
    let rejected_release = latent_core::ReleaseDigest(artifact_blob_digest(&mutant).into_string());
    assert!(f
        .catalog
        .get_catalog_entry(&tenant_a, &rejected_release)
        .await
        .unwrap()
        .is_none());
    f.idle().await;
    // As in the existing signed Java timer owner, bound cold component
    // preparation separately from the fresh activation's original deadline.
    // This occurs only after the rejected package has been observed.
    let publication = f
        .catalog
        .execution_eligibility_selected(&release, None)
        .unwrap()
        .unwrap()
        .publication()
        .clone();
    let mut key = f.backend.preparation_key(&release).unwrap();
    key.publication = Some(publication);
    let ready = tokio::time::timeout(
        Duration::from_secs(600),
        f.backend
            .prepare_ready_from_repository(f.catalog.clone(), key),
    )
    .await
    .expect("bounded signed Java preparation setup")
    .expect("prepare the exact signed Java publication");
    let prepared_owner = f.backend.materialize_ready(ready).unwrap();
    drop(prepared_owner);
    assert_eq!(f.backend.resource_snapshot().stores_created, stores_before);
    f.idle().await;
    let result = success(
        f.manager
            .start(f.request("sdk694-fresh-tenant-b", 0))
            .unwrap()
            .await,
    );
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&result.output).unwrap(),
        [42]
    );
    assert!(result.consumption.cpu_fuel > 0);
    assert!(result.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
    assert!(f.backend.resource_snapshot().stores_created > stores_before);
    f.idle().await;
    eprintln!("SDK694_UNKNOWN_IMPORT same_tenant_control=accepted admission=component-world-identity-mismatch rejected_stores=0 fresh_tenant=tenant-b result=42");
}
