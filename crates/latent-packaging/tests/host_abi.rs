mod fixtures;

use latent_core::{PlatformErrorCode, PHASE3_HOST_ABI_V2};
use latent_packaging::{build_package, PackagingLimits};

#[test]
fn every_selected_host_contract_is_inspectable_without_a_provider_or_execution() {
    for spec in PHASE3_HOST_ABI_V2.interfaces() {
        let input = fixtures::host_capsule(spec.interface, spec.wit, spec.wit, None);
        let bundle = build_package(input, PackagingLimits::default())
            .unwrap_or_else(|error| panic!("{}: {error:?}", spec.interface));
        assert_eq!(
            bundle.surface().unwrap().imports(),
            &[Box::<str>::from(spec.interface)]
        );
        assert!(bundle.blob("component.wasm").unwrap().len() < 16 * 1024);
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
        let input = fixtures::host_capsule(&name, &source, &compiled, asynchronous);
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
            fixtures::host_capsule(http.interface, http.wit, http.wit, None),
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
