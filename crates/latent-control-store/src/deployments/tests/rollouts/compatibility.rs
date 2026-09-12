use super::super::supply_chain::authority;
#[path = "../../../../../latent-packaging/tests/fixtures/mod.rs"]
mod packages;

use super::*;
use latent_artifacts::{
    decode_contract_metadata, AdmissionStorageLimits, ArtifactDescriptor, ArtifactRepository,
    CapsuleArtifact, ContractMetadataLimits, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, FieldDescriptor, PackageAdmissionUpload, ValueType,
};
use latent_core::{ArtifactReference, Metadata};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_packaging::{build_package, PackageBundle, PackagingLimits};

#[test]
fn unknown_named_types_and_breaking_local_shapes_never_create_a_rollout_or_routes() {
    for (old_type, candidate_type) in [
        (
            ValueType::Record("opaque".into()),
            ValueType::Record("opaque".into()),
        ),
        (ValueType::U32, ValueType::String),
    ] {
        let root = TempRoot::new();
        let releases = Arc::new(Releases::default());
        let store = open(&root, &releases);
        let request = setup(&store, &releases);
        for (marker, ty) in [("rollout-old", old_type), ("rollout-new", candidate_type)] {
            let digest = latent_artifacts::content_digest(marker.as_bytes());
            releases
                .values
                .write()
                .unwrap()
                .get_mut(&digest)
                .unwrap()
                .contracts[0]
                .interfaces[0]
                .functions[0]
                .parameters = vec![FieldDescriptor {
                name: "value".into(),
                value_type: ty,
                documentation: None,
            }];
        }
        let before = std::fs::read(root.0.join("catalog.json")).unwrap();
        assert_code(
            run(store.prepare_rollout(request)),
            Code::IncompatibleContract,
        );
        assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
        assert_eq!(run(store.list()).unwrap().len(), 1);
        assert!(store.get_rollout(&alice(), &id()).unwrap().is_none());
        assert_eq!(
            store
                .get_rollout_operation(&alice(), &id(), "start")
                .unwrap(),
            RolloutOperationLookup::Unknown
        );
    }
}

fn package(changed_shape: bool, changed_bytes: bool) -> PackageBundle {
    let mut input = packages::capsule(packages::component::Options {
        signed_record_field: changed_shape,
        ..Default::default()
    });
    if changed_shape {
        let source = input
            .layers
            .iter_mut()
            .find(|layer| layer.path == "wit/service.wit")
            .unwrap();
        source.bytes = String::from_utf8(source.bytes.clone())
            .unwrap()
            .replace("value: u32", "value: s32")
            .into_bytes();
        let digest = latent_artifacts::package::artifact_blob_digest(&source.bytes);
        packages::mutate_json(&mut input, "wit-lock.json", |lock| {
            lock["packages"][1]["digest"] = json::json!(digest.as_str());
        });
    }
    if changed_bytes {
        let component = input
            .layers
            .iter_mut()
            .find(|layer| layer.path == "component.wasm")
            .unwrap();
        // A valid custom section changes exact component bytes while preserving
        // the real nested WIT structure and actual component validation.
        component.bytes.extend_from_slice(b"\0\x05\x04next");
    }
    let digest = latent_artifacts::package::artifact_blob_digest(
        &input
            .layers
            .iter()
            .find(|layer| layer.path == "component.wasm")
            .unwrap()
            .bytes,
    );
    packages::mutate_json(&mut input, "capsule.json", |manifest| {
        manifest["component"]["digest"] = json::json!(digest.as_str());
    });
    build_package(input, PackagingLimits::default()).unwrap()
}
fn artifact_for(bundle: &PackageBundle) -> CapsuleArtifact {
    let layer = |path: &str| {
        bundle
            .layers()
            .iter()
            .find(|layer| layer.path() == path)
            .unwrap()
            .bytes()
    };
    let component_bytes = layer("component.wasm").to_vec();
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://rollout/{}", bundle.layout().digest())),
            release_digest: latent_artifacts::content_digest(&component_bytes),
            media_type: latent_artifacts::package::COMPONENT_MEDIA_TYPE.into(),
            size_bytes: component_bytes.len() as u64,
            publisher: None,
            layers: vec![],
            annotations: Metadata::new(),
        },
        manifest: JsonManifestCodec::default()
            .decode_capsule(layer("capsule.json"))
            .unwrap(),
        contracts: decode_contract_metadata(
            layer("contracts.json"),
            ContractMetadataLimits::default(),
        )
        .unwrap(),
        component_bytes,
    }
}
fn upload(bundle: &PackageBundle) -> PackageAdmissionUpload {
    let raw = packages::raw(bundle);
    PackageAdmissionUpload {
        manifest: raw.manifest,
        configuration: raw.configuration,
        layers: raw.layers,
        signatures: vec![],
        provenance: vec![],
        sboms: vec![],
    }
}

#[test]
fn retained_package_bridge_compares_actual_nested_wit_and_binds_package_pair() {
    for changed_shape in [false, true] {
        let tenant = TenantId("tests".into());
        let old = package(false, false);
        let candidate = package(changed_shape, !changed_shape);
        let artifacts = [artifact_for(&old), artifact_for(&candidate)];
        let authority = authority::Authority::new_many(artifacts.to_vec());
        let artifacts_root = TempRoot::new();
        let root = TempRoot::new();
        // Crypto is deliberately supplied by the injected test authority; the
        // real catalog seals raw package association, then packaging parses and
        // compares both actual component/WIT graphs during rollout preparation.
        let repository = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                &artifacts_root.0,
                DirectoryArtifactRepositoryConfig::default(),
                AdmissionStorageLimits::default(),
                authority.clone(),
            )
            .unwrap(),
        );
        for bundle in [&old, &candidate] {
            run(repository.admit_package(&tenant, upload(bundle), &mut |_| Ok(()))).unwrap();
        }
        let store = run(Store::open_enforced(
            &root.0,
            repository,
            Limits::default(),
            authority,
        ))
        .unwrap();
        let mut base = deployment("base", &tenant.0, &artifacts[0].descriptor.release_digest);
        base.service
            .0
            .clone_from(&artifacts[0].manifest.metadata.name);
        run(store.apply(base)).unwrap();
        let mut proposed = deployment(
            "candidate",
            &tenant.0,
            &artifacts[1].descriptor.release_digest,
        );
        proposed
            .service
            .0
            .clone_from(&artifacts[1].manifest.metadata.name);
        proposed.route_weight = 2500;
        let mut operation = context("start", 0);
        operation.tenant = tenant.clone();
        let request = RolloutRequest::Start {
            context: operation,
            spec: StartRolloutSpec {
                id: id(),
                base: DeploymentExpectation {
                    id: DeploymentId("base".into()),
                    generation: 1,
                },
                candidate: proposed,
                candidate_weights: vec![2500, 10000],
            },
        };
        if changed_shape {
            let before = std::fs::read(root.0.join("catalog.json")).unwrap();
            assert_code(
                run(store.prepare_rollout(request)),
                Code::IncompatibleContract,
            );
            assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
            assert!(store.get_rollout(&tenant, &id()).unwrap().is_none());
        } else {
            execute(&store, request);
            let row = store.get_rollout(&tenant, &id()).unwrap().unwrap();
            assert_eq!(row.base.package.as_ref(), Some(old.layout().digest()));
            assert_eq!(
                row.candidate.package.as_ref(),
                Some(candidate.layout().digest())
            );
            assert_ne!(row.base.component, row.candidate.component);
        }
    }
}
