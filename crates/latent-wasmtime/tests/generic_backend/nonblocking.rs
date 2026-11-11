//! Type and default-denial controls for an uninstalled research interface.
//! No provider, physical socket or ordinary-library execution is claimed.

use super::{artifact_bytes, config, fixture, host_fixture, idle};
use latent_core::{ContractId, PlatformErrorCode, PHASE3_HOST_ABI_V2};
use latent_executor::ExecutionBackend;
use latent_manifest::ContractImport;
use latent_wasmtime::WasmtimeComponentEngineFactory;
use wit_parser::{Function, FunctionKind, Handle, Resolve, Type, TypeDefKind, TypeId};

const V1: &str = "latent:network/streams@0.1.0";
const V2: &str = "latent:network-nonblocking/streams@0.2.0";
const SOURCES: &[(&str, &str)] = &[
    (
        "network.wit",
        include_str!("../../../../wit/platform/network/package.wit"),
    ),
    (
        "nonblocking.wit",
        include_str!("../../../../research/standard-outbound/nonblocking-v2/package.wit"),
    ),
];

fn resolve() -> Resolve {
    let mut resolve = Resolve::default();
    for (path, source) in SOURCES {
        resolve.push_source(path, source).unwrap();
    }
    resolve
}

fn interface<'a>(resolve: &'a Resolve, name: &str) -> &'a wit_parser::Interface {
    resolve
        .interfaces
        .iter()
        .find(|(id, _)| resolve.id_of(*id).as_deref() == Some(name))
        .map(|(_, interface)| interface)
        .unwrap()
}

fn original(resolve: &Resolve, mut ty: Type) -> Type {
    while let Type::Id(id) = ty {
        let TypeDefKind::Type(target) = &resolve.types[id].kind else {
            break;
        };
        ty = *target;
    }
    ty
}

fn kind(resolve: &Resolve, ty: Type) -> &TypeDefKind {
    let Type::Id(id) = original(resolve, ty) else {
        panic!("expected a defined type")
    };
    &resolve.types[id].kind
}

fn result(resolve: &Resolve, function: &Function) -> (Option<Type>, Type) {
    let TypeDefKind::Result(result) = kind(resolve, function.result.unwrap()) else {
        panic!("every companion operation returns a guarded result")
    };
    (result.ok, result.err.unwrap())
}

fn handle(resolve: &Resolve, ty: Type, owner: TypeId, owned: bool) {
    let actual = match kind(resolve, ty) {
        TypeDefKind::Handle(Handle::Own(id)) if owned => *id,
        TypeDefKind::Handle(Handle::Borrow(id)) if !owned => *id,
        other => panic!("wrong ownership: {other:?}"),
    };
    assert_eq!(original(resolve, Type::Id(actual)), Type::Id(owner));
}

fn case(resolve: &Resolve, ty: Type, name: &str) -> Option<Type> {
    let TypeDefKind::Variant(variant) = kind(resolve, ty) else {
        panic!("expected an outcome variant")
    };
    variant
        .cases
        .iter()
        .find(|case| case.name == name)
        .unwrap()
        .ty
}

#[test]
fn companion_aliases_keep_the_original_resources_and_error_evidence() {
    let resolve = resolve();
    let v1 = interface(&resolve, V1);
    let v2 = interface(&resolve, V2);
    for name in ["connection", "chunk", "connect-request", "stream-error"] {
        assert_eq!(
            original(&resolve, Type::Id(v2.types[name])),
            Type::Id(v1.types[name]),
            "{name} must reuse the original v1 type"
        );
    }
    assert!(matches!(
        resolve.types[v2.types["connect-attempt"]].kind,
        TypeDefKind::Resource
    ));
    for function in v2.functions.values() {
        assert_eq!(function.kind, FunctionKind::AsyncFreestanding);
        assert_eq!(
            original(&resolve, result(&resolve, function).1),
            Type::Id(v1.types["stream-error"])
        );
    }
    assert_eq!(
        original(&resolve, v2.functions["begin-connect"].params[0].ty),
        Type::Id(v1.types["connect-request"])
    );
    assert_eq!(
        original(
            &resolve,
            case(&resolve, Type::Id(v2.types["connect-status"]), "failed").unwrap()
        ),
        Type::Id(v1.types["stream-error"])
    );
}

#[test]
fn consuming_handoffs_and_borrowed_observations_have_distinct_ownership() {
    let resolve = resolve();
    let v1 = interface(&resolve, V1);
    let v2 = interface(&resolve, V2);
    let attempt = v2.types["connect-attempt"];
    handle(
        &resolve,
        result(&resolve, &v2.functions["begin-connect"]).0.unwrap(),
        attempt,
        true,
    );
    for name in ["finish-connect", "cancel-connect", "get-connect-status"] {
        handle(
            &resolve,
            v2.functions[name].params[0].ty,
            attempt,
            name != "get-connect-status",
        );
    }
    handle(
        &resolve,
        result(&resolve, &v2.functions["finish-connect"]).0.unwrap(),
        v1.types["connection"],
        true,
    );
    assert!(result(&resolve, &v2.functions["cancel-connect"]).0.is_none());
    for name in ["try-read", "try-write"] {
        handle(
            &resolve,
            v2.functions[name].params[0].ty,
            v1.types["connection"],
            false,
        );
    }
    handle(
        &resolve,
        case(&resolve, Type::Id(v2.types["read-result"]), "bytes").unwrap(),
        v1.types["chunk"],
        true,
    );
    for (name, owner) in [
        ("established", v1.types["connection"]),
        ("connecting", attempt),
    ] {
        handle(
            &resolve,
            case(&resolve, Type::Id(v2.types["watch-target"]), name).unwrap(),
            owner,
            false,
        );
    }
}

#[test]
fn readiness_and_immediate_results_cannot_collapse_to_timeout_or_zero_bytes() {
    let resolve = resolve();
    let v2 = interface(&resolve, V2);
    for (name, expected) in [
        ("interest", &["readable", "writable", "priority"][..]),
        (
            "events",
            &[
                "readable",
                "writable",
                "priority",
                "hangup",
                "error",
                "connect-complete",
            ][..],
        ),
    ] {
        let TypeDefKind::Flags(flags) = kind(&resolve, Type::Id(v2.types[name])) else {
            panic!("independent event bits, not a mutually exclusive enum")
        };
        assert_eq!(
            flags
                .flags
                .iter()
                .map(|flag| flag.name.as_str())
                .collect::<Vec<_>>(),
            expected
        );
    }
    for (name, empty) in [
        ("read-result", "would-block"),
        ("read-result", "eof"),
        ("write-result", "would-block"),
        ("observation", "elapsed"),
    ] {
        assert!(case(&resolve, Type::Id(v2.types[name]), empty).is_none());
    }
    assert_eq!(
        case(&resolve, Type::Id(v2.types["write-result"]), "written"),
        Some(Type::U32)
    );
    let ready = case(&resolve, Type::Id(v2.types["observation"]), "ready").unwrap();
    let TypeDefKind::List(events) = kind(&resolve, ready) else {
        panic!("one ordered event mask per input watch")
    };
    assert_eq!(original(&resolve, *events), Type::Id(v2.types["events"]));
}

#[tokio::test(flavor = "current_thread")]
async fn typed_companion_import_is_denied_even_when_optional_or_described_as_v1() {
    assert!(PHASE3_HOST_ABI_V2.interface(V2).is_none());
    // This single-interface rejection fixture encodes the full type closure.
    // The separate parser tests above check its cross-package alias identities.
    let import = host_fixture::interface_with_dependencies(SOURCES, V2, None);
    let bytes = fixture::with_host(fixture::Options::default(), V2, &import);
    wasmparser::Validator::new_with_features(wasmparser::WasmFeatures::all())
        .validate_all(&bytes)
        .expect("rejection must not be explained by a malformed component");
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    for (name, optional) in [(V2, false), (V2, true), (V1, false)] {
        let mut artifact = artifact_bytes(bytes.clone(), &[fixture::CONTRACT]);
        artifact.manifest.imports = vec![ContractImport {
            contract: ContractId(name.into()),
            optional,
        }];
        let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
        let error = backend.prepare(&artifact, &key).await.unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
        assert_eq!(backend.resource_snapshot().stores_created, 0);
        assert_eq!(backend.cache_snapshot().entries, 0);
        idle(&backend);
    }
}
