mod fixtures;
#[path = "fixtures/host.rs"]
mod host;

use fixtures::{capsule, component, mutate_json};
use latent_artifacts::package::artifact_blob_digest;
use serde_json::json;

use latent_core::{PlatformErrorCode, PHASE3_HOST_ABI_V2};
use latent_packaging::{build_package, PackageInput, PackagingLimits};

#[test]
fn every_selected_host_contract_is_inspectable_without_a_provider_or_execution() {
    for spec in PHASE3_HOST_ABI_V2.interfaces() {
        let input = host_capsule(spec.interface, spec.wit, spec.wit, None);
        let bundle = build_package(input, PackagingLimits::default())
            .unwrap_or_else(|error| panic!("{}: {error:?}", spec.interface));
        assert_eq!(
            bundle.surface().unwrap().imports(),
            &[Box::<str>::from(spec.interface)]
        );
        assert!(bundle.blob("component.wasm").unwrap().len() < 16 * 1024);
        let binding = latent_packaging::compile_host_binding(
            &bundle,
            spec.interface,
            latent_packaging::PackageComparisonLimits::default(),
        )
        .unwrap();
        assert_eq!(binding.consumer().package(), bundle.layout().digest());
        assert_eq!(binding.interface(), spec.interface);
        assert!(!binding.operations().is_empty());
        assert!(binding.provider().is_none());
        assert_eq!(
            binding.host_abi(),
            Some(&artifact_blob_digest(spec.wit.as_bytes()))
        );
        assert!(latent_packaging::compile_host_binding(
            &bundle,
            "other:missing/api@1.0.0",
            latent_packaging::PackageComparisonLimits::default(),
        )
        .is_err());
    }
}

#[test]
fn asynchronous_imports_require_the_exact_version_kind_and_complete_pinned_shape() {
    let http = PHASE3_HOST_ABI_V2
        .interface("latent:http/client@0.2.0")
        .unwrap();
    // A matching component, manifest and lock still cannot invent a new host ABI.
    for (name, source, compiled, asynchronous) in [
        (
            http.interface.to_string(),
            http.wit.to_string(),
            http.wit.to_string(),
            Some(false),
        ),
        (
            http.interface.to_string(),
            http.wit.to_string(),
            http.wit.replace("status: u16", "status: u32"),
            None,
        ),
        (
            http.interface.to_string(),
            http.wit.replace("status: u16", "status: u32"),
            http.wit.replace("status: u16", "status: u32"),
            None,
        ),
        (
            http.interface.to_string(),
            http.wit.replace("        uncertain,", ""),
            http.wit.replace("        uncertain,", ""),
            None,
        ),
        (
            http.interface.replace("0.2.0", "0.3.0"),
            http.wit.replace("0.2.0", "0.3.0"),
            http.wit.replace("0.2.0", "0.3.0"),
            None,
        ),
    ] {
        let input = host_capsule(&name, &source, &compiled, asynchronous);
        assert_eq!(
            build_package(input, PackagingLimits::default())
                .unwrap_err()
                .code,
            PlatformErrorCode::IncompatibleContract
        );
    }
}

#[test]
fn provider_shapes_remain_subject_to_the_existing_semantic_work_ceilings() {
    let http = PHASE3_HOST_ABI_V2
        .interface("latent:http/client@0.2.0")
        .unwrap();
    for field in ["nodes", "depth", "members", "names", "tokens", "source"] {
        let mut limits = PackagingLimits::default();
        match field {
            "nodes" => limits.semantics.max_type_nodes = 1,
            "depth" => limits.semantics.max_type_depth = 1,
            "members" => limits.semantics.max_type_members = 1,
            "names" => limits.semantics.max_name_bytes = 8,
            "tokens" => limits.semantics.max_wit_tokens = 1,
            "source" => limits.semantics.max_wit_source_bytes = 1,
            _ => unreachable!(),
        }
        let error = build_package(
            host_capsule(http.interface, http.wit, http.wit, None),
            limits,
        )
        .unwrap_err();
        assert_eq!(
            error.code,
            PlatformErrorCode::ResourceExhausted,
            "{field}: {error:?}"
        );
    }
}

fn host_capsule(
    name: &str,
    source: &str,
    compiled_source: &str,
    asynchronous: Option<bool>,
) -> PackageInput {
    let bytes = component::with_host(
        component::Options::default(),
        name,
        &host::interface(compiled_source, name, asynchronous),
    );
    let mut input = capsule(component::Options::default());
    let service = String::from_utf8(component::SERVICE_WIT.to_vec())
        .unwrap()
        .replace(component::CLOCK, name)
        .into_bytes();
    let (package_interface, version) = name.rsplit_once('@').unwrap();
    let package = format!("{}@{version}", package_interface.split_once('/').unwrap().0);
    let digest = artifact_blob_digest(&bytes);
    for layer in &mut input.layers {
        match layer.path.as_str() {
            "component.wasm" => layer.bytes.clone_from(&bytes),
            "wit/clock.wit" => {
                layer.path = "wit/host.wit".into();
                layer.bytes = source.as_bytes().to_vec();
            }
            "wit/service.wit" => layer.bytes.clone_from(&service),
            _ => (),
        }
    }
    mutate_json(&mut input, "capsule.json", |manifest| {
        manifest["component"]["digest"] = json!(digest.as_str());
        manifest["imports"][0]["contract"] = json!(name);
    });
    mutate_json(&mut input, "wit-lock.json", |lock| {
        lock["packages"][0] = json!({"id": package, "sourcePath": "wit/host.wit",
            "digest": artifact_blob_digest(source.as_bytes()).as_str(), "dependencies": []});
        lock["packages"][1]["digest"] = json!(artifact_blob_digest(&service).as_str());
        lock["packages"][1]["dependencies"] = json!([package]);
    });
    input
}
