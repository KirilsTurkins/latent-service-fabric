use super::*;
use crate::semantics::compare::Comparison;
use latent_core::PHASE3_HOST_ABI_V3;

const STREAMING: &str = "latent:http/streaming@0.3.0";
fn source(text: &str) -> (Resolve, BTreeMap<String, InterfaceId>) {
    let mut resolve = Resolve::default();
    resolve.push_source("fixture.wit", text).unwrap();
    let imports = resolve
        .interfaces
        .iter()
        .map(|(id, _)| (resolve.id_of(id).unwrap(), id))
        .collect();
    (resolve, imports)
}
#[test]
fn buffered_and_streaming_package_versions_coexist_without_aliasing() {
    let mut resolve = Resolve::default();
    for name in ["latent:http/client@0.2.0", STREAMING] {
        resolve
            .push_source(name, PHASE3_HOST_ABI_V3.interface(name).unwrap().wit)
            .unwrap();
    }
    let imports = resolve
        .interfaces
        .iter()
        .map(|(id, _)| (resolve.id_of(id).unwrap(), id))
        .collect();
    validate(&resolve, &imports, SemanticLimits::default()).unwrap();
}
#[test]
fn exact_resource_identity_ownership_and_async_shapes_are_required() {
    let trusted = PHASE3_HOST_ABI_V3.interface(STREAMING).unwrap().wit;
    for altered in [
        trusted.replace("target: borrow<upload>", "target: borrow<body>"),
        trusted.replace("target: borrow<upload>", "target: upload"),
        trusted.replace("read: async func", "read: func"),
        trusted.replace(
            "result<option<chunk>, http-error>",
            "result<option<stream<u8>>, http-error>",
        ),
    ] {
        assert_ne!(altered, trusted);
        let (resolve, imports) = source(&altered);
        assert!(validate(&resolve, &imports, SemanticLimits::default()).is_err());
    }
}
#[test]
fn resource_permission_is_not_a_general_application_value_profile() {
    let (resolve, imports) = source(PHASE3_HOST_ABI_V3.interface(STREAMING).unwrap().wit);
    validate(&resolve, &imports, SemanticLimits::default()).unwrap();
    let id = imports[STREAMING];
    let mut application = Comparison::new(&resolve, &resolve, SemanticLimits::default());
    assert!(application.interface(id, id).is_err());
}
