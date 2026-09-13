use super::{compare, host, sources, SemanticLimits};
use latent_artifacts::package::{artifact_blob_digest, WitLock, WitLockedPackage};
use latent_core::PlatformErrorCode;
use std::collections::BTreeMap;
use wit_parser::Resolve;

const SOURCE: &str = "package example:shape@1.0.0; interface api { record item { count: u32, enabled: bool } variant outcome { empty, found(item) } run: func(value: result<outcome, u32>) -> u32; } world service { export api; }";

fn resolve(source: &str) -> (Resolve, wit_parser::WorldId) {
    let mut resolve = Resolve::default();
    let package = resolve.push_source("fixture.wit", source).unwrap();
    let world = resolve.select_world(&[package], Some("service")).unwrap();
    (resolve, world)
}

fn compares(
    left: &str,
    right: &str,
    limits: SemanticLimits,
) -> Result<usize, latent_core::PlatformError> {
    let (left, world) = resolve(left);
    let (right, other) = resolve(right);
    let a = compare::surface(&left, world, limits)?;
    let b = compare::surface(&right, other, limits)?;
    compare::worlds(&left, &a, &right, &b, limits)
}

#[test]
fn compares_complete_nested_record_variant_and_result_structure() {
    compares(SOURCE, SOURCE, SemanticLimits::default()).unwrap();
    for modified in [
        SOURCE.replace("count: u32", "count: u64"),
        SOURCE.replace("enabled: bool", "renamed: bool"),
        SOURCE.replace("empty, found", "missing, found"),
        SOURCE.replace("found(item)", "found(u32)"),
        SOURCE.replace("result<outcome, u32>", "result<outcome, u64>"),
        SOURCE.replace("value:", "renamed:"),
    ] {
        assert_eq!(
            compares(SOURCE, &modified, SemanticLimits::default())
                .unwrap_err()
                .code,
            PlatformErrorCode::IncompatibleContract
        );
    }
}

#[test]
fn aliases_are_transparent_but_exported_names_and_enum_cases_are_checked() {
    let original = "package example:shape@1.0.0; interface api { enum state { one, two } type count = u32; run: func(value: state) -> count; } world service { export api; }";
    compares(original, original, SemanticLimits::default()).unwrap();
    assert!(compares(
        original,
        &original.replace("one, two", "two, one"),
        SemanticLimits::default()
    )
    .is_err());
    assert!(compares(
        original,
        &original.replace("api", "other"),
        SemanticLimits::default()
    )
    .is_err());
}

fn context_world(context: &str, imported: bool) -> (Resolve, wit_parser::WorldId) {
    let mut resolve = Resolve::default();
    resolve.push_source("context.wit", context).unwrap();
    let source = if imported {
        SOURCE.replace(
            "world service {",
            "world service { import latent:context/context@0.1.0;",
        )
    } else {
        SOURCE.to_owned()
    };
    let package = resolve.push_source("fixture.wit", &source).unwrap();
    let world = resolve.select_world(&[package], Some("service")).unwrap();
    (resolve, world)
}

#[test]
fn compiled_host_imports_can_prune_members_or_the_entire_interface() {
    let context = include_str!("../../../../wit/platform/context/package.wit");
    let pruned =
        "package latent:context@0.1.0; interface context { activation-id: func() -> string; }";
    let limits = SemanticLimits::default();
    let (source, world) = context_world(context, true);
    let declared = compare::surface(&source, world, limits).unwrap();
    host::validate(&source, &declared.imports, limits).unwrap();
    for imported in [true, false] {
        let (actual, world) = context_world(pruned, imported);
        let compiled = compare::surface(&actual, world, limits).unwrap();
        compare::worlds(&source, &declared, &actual, &compiled, limits).unwrap();
        if imported {
            // The exact-interface path used by exports and pinned host-source
            // checks must continue rejecting this intentionally reduced shape.
            let id = "latent:context/context@0.1.0";
            assert!(compare::Comparison::new(&source, &actual, limits)
                .interface(declared.imports[id], compiled.imports[id])
                .is_err());
        }
    }
    let (actual, world) = context_world(pruned, false);
    let empty = compare::surface(&actual, world, limits).unwrap();
    assert!(compare::worlds(&actual, &empty, &source, &declared, limits).is_err());
}

#[test]
fn retained_host_imports_reject_changed_or_unknown_functions_and_types() {
    let context = include_str!("../../../../wit/platform/context/package.wit");
    let pruned =
        "package latent:context@0.1.0; interface context { activation-id: func() -> string; }";
    let limits = SemanticLimits::default();
    let (source, world) = context_world(context, true);
    let declared = compare::surface(&source, world, limits).unwrap();
    for modified in [
        pruned.replace("-> string", "-> u32"),
        pruned.replace("activation-id", "unknown-call"),
        pruned.replace(
            "interface context {",
            "interface context { type unknown-type = u32;",
        ),
        context.replace(
            "wall-time-limit-millis: option<u64>",
            "wall-time-limit-millis: option<u32>",
        ),
        context.replace(
            "claims: list<tuple<string, string>>",
            "claims: list<tuple<string, u32>>",
        ),
    ] {
        let (actual, world) = context_world(&modified, true);
        let compiled = compare::surface(&actual, world, limits).unwrap();
        assert_eq!(
            compare::worlds(&source, &declared, &actual, &compiled, limits)
                .unwrap_err()
                .code,
            PlatformErrorCode::IncompatibleContract
        );
    }
}

#[test]
fn unsupported_shapes_are_rejected_even_when_both_inputs_match() {
    for source in [
        "package example:shape@1.0.0; interface api { flags options { one, two } record item { access: options } run: func(value: item); } world service { export api; }",
        "package example:shape@1.0.0; interface api { resource item; run: func(value: borrow<item>); } world service { export api; }",
        "package example:shape@1.0.0; world service { export run: func() -> u32; }",
        "package example:shape@1.0.0; interface api { type count = u32; } world service { export api; }",
    ] {
        assert!(compares(source, source, SemanticLimits::default()).is_err());
    }
}

#[test]
fn repeated_type_visits_cannot_bypass_depth_or_work_limits() {
    let limits = SemanticLimits {
        max_type_depth: 2,
        ..SemanticLimits::default()
    };
    assert_eq!(
        compares(SOURCE, SOURCE, limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(
        compares(
            SOURCE,
            SOURCE,
            SemanticLimits {
                max_type_nodes: 3,
                ..SemanticLimits::default()
            }
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::ResourceExhausted
    );
}

fn inputs(source: &str) -> (WitLock, BTreeMap<String, &[u8]>) {
    let entry = WitLockedPackage {
        id: "example:shape@1.0.0".to_owned(),
        source_path: "wit/shape.wit".to_owned(),
        digest: artifact_blob_digest(source.as_bytes()),
        dependencies: vec![],
    };
    (
        WitLock {
            format_version: 1,
            world: "example:shape/service@1.0.0".to_owned(),
            contracts_digest: artifact_blob_digest(b"contracts"),
            packages: vec![entry],
        },
        BTreeMap::from([("wit/shape.wit".to_owned(), source.as_bytes())]),
    )
}

#[test]
fn source_package_identity_digest_and_exact_set_are_independent_checks() {
    let (lock, mut files) = inputs(SOURCE);
    sources::resolve(&lock, &files, SemanticLimits::default()).unwrap();
    files.insert("wit/extra.wit".to_owned(), SOURCE.as_bytes());
    assert!(sources::resolve(&lock, &files, SemanticLimits::default()).is_err());
    let changed = SOURCE.replace("example:shape", "example:other");
    let (mut lock, files) = inputs(&changed);
    assert!(sources::resolve(&lock, &files, SemanticLimits::default()).is_err());
    lock.packages[0].digest = artifact_blob_digest(b"wrong");
    assert!(sources::resolve(&lock, &files, SemanticLimits::default()).is_err());
}

#[test]
fn unused_world_functions_still_consume_parameter_and_function_budgets() {
    let source = format!("{SOURCE} world unused {{ export other: func(a: u32, b: u32); }}");
    let (lock, files) = inputs(&source);
    let limits = SemanticLimits {
        max_parameters: 1,
        ..SemanticLimits::default()
    };
    assert_eq!(
        sources::resolve(&lock, &files, limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    let limits = SemanticLimits {
        max_functions: 1,
        ..SemanticLimits::default()
    };
    assert_eq!(
        sources::resolve(&lock, &files, limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
}

#[test]
fn parsed_dependencies_must_equal_the_pinned_lock() {
    let source = SOURCE.replace(
        "world service {",
        "world service { import latent:clock/monotonic@0.1.0;",
    );
    let (mut lock, mut files) = inputs(&source);
    assert!(sources::resolve(&lock, &files, SemanticLimits::default()).is_err());
    let clock = include_bytes!("../../../../wit/platform/clock/package.wit");
    lock.packages[0]
        .dependencies
        .push("latent:clock@0.1.0".to_owned());
    lock.packages.push(WitLockedPackage {
        id: "latent:clock@0.1.0".to_owned(),
        source_path: "wit/clock.wit".to_owned(),
        digest: artifact_blob_digest(clock),
        dependencies: vec![],
    });
    files.insert("wit/clock.wit".to_owned(), clock);
    let (resolve, world) = sources::resolve(&lock, &files, SemanticLimits::default()).unwrap();
    let surface = compare::surface(&resolve, world, SemanticLimits::default()).unwrap();
    host::validate(&resolve, &surface.imports, SemanticLimits::default()).unwrap();
    let forged = std::str::from_utf8(clock)
        .unwrap()
        .replace("now-nanos: func() -> u64", "now-nanos: func() -> u32");
    lock.packages[1].digest = artifact_blob_digest(forged.as_bytes());
    files.insert("wit/clock.wit".to_owned(), forged.as_bytes());
    let (resolve, world) = sources::resolve(&lock, &files, SemanticLimits::default()).unwrap();
    let surface = compare::surface(&resolve, world, SemanticLimits::default()).unwrap();
    assert!(host::validate(&resolve, &surface.imports, SemanticLimits::default()).is_err());
}
