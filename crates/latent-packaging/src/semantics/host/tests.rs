use super::*;
use crate::semantics::compare::Comparison;
use latent_core::PHASE3_HOST_ABI_V3;

const STREAMING: &str = "latent:http/streaming@0.3.0";

#[test]
fn blob_v2_rejects_resource_ownership_and_async_substitutions() {
    let name = "latent:blob/blob@0.2.0";
    let wit = latent_core::PHASE3_HOST_ABI_CURRENT
        .interface(name)
        .unwrap()
        .wit;
    let (resolve, imports) = source(wit);
    validate(&resolve, &imports, SemanticLimits::default()).unwrap();
    for altered in [
        wit.replace("value: borrow<chunk>", "value: chunk"),
        wit.replace("read: async func", "read: func"),
        wit.replace("result<chunk, blob-error>", "result<u64, blob-error>"),
    ] {
        assert_ne!(altered, wit);
        let (resolve, imports) = source(&altered);
        assert!(validate(&resolve, &imports, SemanticLimits::default()).is_err());
    }
    let mut application = Comparison::new(&resolve, &resolve, SemanticLimits::default());
    assert!(application.interface(imports[name], imports[name]).is_err());
}
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

fn transaction_sources(state: &str, intents: &str) -> (Resolve, BTreeMap<String, InterfaceId>) {
    let mut resolve = Resolve::default();
    resolve.push_source("state.wit", state).unwrap();
    resolve.push_source("intents.wit", intents).unwrap();
    let imports = resolve
        .interfaces
        .iter()
        .map(|(id, _)| (resolve.id_of(id).unwrap(), id))
        .collect();
    (resolve, imports)
}

#[test]
fn phase4_state_and_intents_require_exact_shared_resource_ownership_and_async_shapes() {
    let state = PHASE4_HOST_ABI_V1
        .interface("latent:state/key-value@0.2.0")
        .unwrap()
        .wit;
    let intents = PHASE4_HOST_ABI_V1
        .interface("latent:intents/staging@0.1.0")
        .unwrap()
        .wit;
    let (resolve, imports) = transaction_sources(state, intents);
    validate(&resolve, &imports, SemanticLimits::default()).unwrap();
    // The staging import alone still resolves its nominal state dependency.
    validate(
        &resolve,
        &BTreeMap::from([(
            "latent:intents/staging@0.1.0".into(),
            imports["latent:intents/staging@0.1.0"],
        )]),
        SemanticLimits::default(),
    )
    .unwrap();
    for changed in [
        intents.replace(
            "transaction: borrow<transaction>",
            "transaction: transaction",
        ),
        intents.replace("stage: async func", "stage: func"),
    ] {
        assert_ne!(changed, intents);
        let (resolve, imports) = transaction_sources(state, &changed);
        assert!(validate(&resolve, &imports, SemanticLimits::default()).is_err());
    }
    let changed = state.replace("get: async func", "get: func");
    assert_ne!(changed, state);
    let (resolve, imports) = transaction_sources(&changed, intents);
    assert!(validate(&resolve, &imports, SemanticLimits::default()).is_err());
}

#[test]
fn phase4_resources_are_never_accepted_as_application_export_authority() {
    let state = PHASE4_HOST_ABI_V1
        .interface("latent:state/key-value@0.2.0")
        .unwrap()
        .wit;
    let intents = PHASE4_HOST_ABI_V1
        .interface("latent:intents/staging@0.1.0")
        .unwrap()
        .wit;
    let (resolve, imports) = transaction_sources(state, intents);
    let mut application = Comparison::new(&resolve, &resolve, SemanticLimits::default());
    let interface = imports["latent:state/key-value@0.2.0"];
    assert!(application.interface(interface, interface).is_err());
}
