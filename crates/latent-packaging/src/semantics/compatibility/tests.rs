use super::*;
use latent_contracts::{ComparisonLimits, StructuralReport};
const SOURCE:&str="package example:shape@1.0.0; interface api { record item { count: u32, enabled: bool } variant outcome { empty, found(item) } run: func(value: result<outcome, u32>) -> u32; } world service { export api; }";
fn resolved(source: &str) -> (Resolve, compare::WorldSurface) {
    let mut resolve = Resolve::default();
    let package = resolve.push_source("test.wit", source).unwrap();
    let world = resolve.select_world(&[package], Some("service")).unwrap();
    let surface = compare::surface(&resolve, world, SemanticLimits::default()).unwrap();
    (resolve, surface)
}
fn compare(old: &str, new: &str, limits: ComparisonLimits) -> StructuralReport {
    let (left, old) = resolved(old);
    let (right, new) = resolved(new);
    let mut analysis = Analysis::new(limits).unwrap();
    match surfaces(&left, &old, &right, &new, &mut analysis) {
        Ok(()) => (),
        Err(error) if error.code == PlatformErrorCode::ResourceExhausted => analysis.exhausted(),
        Err(error) => panic!("unexpected error: {error:?}"),
    }
    analysis.finish()
}
#[test]
fn complete_named_nested_record_variant_and_result_changes_are_breaking() {
    assert_eq!(
        compare(SOURCE, SOURCE, ComparisonLimits::default()).level,
        Level::Identical
    );
    for changed in [
        SOURCE.replace("count: u32", "count: u64"),
        SOURCE.replace("enabled: bool", "renamed: bool"),
        SOURCE.replace("empty, found", "absent, found"),
        SOURCE.replace("found(item)", "found(u32)"),
        SOURCE.replace("result<outcome, u32>", "result<outcome, u64>"),
        SOURCE.replace("value:", "renamed:"),
    ] {
        let report = compare(SOURCE, &changed, ComparisonLimits::default());
        assert_eq!(report.level, Level::Breaking);
        assert!(report.analysis_complete);
    }
}
#[test]
fn compatible_additions_and_versioned_removals_preserve_dispatch_identity() {
    let added = SOURCE.replace("run: func", "added: func(); run: func");
    assert_eq!(
        compare(SOURCE, &added, ComparisonLimits::default()).level,
        Level::BackwardCompatible
    );
    assert_eq!(
        compare(&added, SOURCE, ComparisonLimits::default()).level,
        Level::Breaking
    );
    let version = SOURCE.replace("@1.0.0", "@2.0.0");
    assert_eq!(
        compare(SOURCE, &version, ComparisonLimits::default()).level,
        Level::Breaking
    );
    let renamed = SOURCE
        .replace("export api", "export other")
        .replace("interface api", "interface other");
    assert_eq!(
        compare(SOURCE, &renamed, ComparisonLimits::default()).level,
        Level::Breaking
    );
}
#[test]
fn aliases_and_named_type_additions_are_supported_but_enum_order_is_exact() {
    let source="package example:shape@1.0.0; interface api { enum state { one, two } type count = u32; run: func(value: state) -> count; } world service { export api; }";
    let alias = source.replace("type count = u32;", "type extra = u32; type count = extra;");
    assert_eq!(
        compare(source, &alias, ComparisonLimits::default()).level,
        Level::BackwardCompatible
    );
    assert_eq!(
        compare(
            source,
            &source.replace("one, two", "two, one"),
            ComparisonLimits::default()
        )
        .level,
        Level::Breaking
    );
    let comment = format!("// independent package source bytes\n{source}");
    assert_eq!(
        compare(source, &comment, ComparisonLimits::default()).level,
        Level::Identical
    );
    let containers = "package example:shape@1.0.0; interface api { type values = list<u32>; run: func(value: values); } world service { export api; }";
    let aliased = containers.replace(
        "type values = list<u32>;",
        "type inner = list<u32>; type values = inner;",
    );
    assert_eq!(
        compare(containers, &aliased, ComparisonLimits::default()).level,
        Level::BackwardCompatible
    );
}
#[test]
fn unsupported_shapes_even_on_added_functions_cannot_hide_behind_a_break() {
    for source in ["package example:shape@1.0.0; interface api { flags options { one, two } run: func(value: options); } world service { export api; }",
        "package example:shape@1.0.0; interface api { resource item; run: func(value: borrow<item>); } world service { export api; }"] {
        let report=compare(SOURCE,source,ComparisonLimits::default());
        assert_eq!(report.level,Level::Unsupported);
        assert!(!report.analysis_complete);
    }
}
#[test]
fn lower_work_depth_string_and_report_budgets_do_not_produce_positive_results() {
    for limits in [
        ComparisonLimits {
            max_nodes: 1,
            ..Default::default()
        },
        ComparisonLimits {
            max_edges: 1,
            ..Default::default()
        },
        ComparisonLimits {
            max_depth: 1,
            ..Default::default()
        },
        ComparisonLimits {
            max_string_bytes: 1,
            ..Default::default()
        },
    ] {
        let report = compare(SOURCE, SOURCE, limits);
        assert_eq!(report.level, Level::Unknown);
        assert!(!report.analysis_complete);
    }
    let report = compare(
        SOURCE,
        &SOURCE.replace("u32", "u64"),
        ComparisonLimits {
            max_issues: 1,
            max_path_bytes: 8,
            max_report_bytes: 128,
            ..Default::default()
        },
    );
    assert_eq!(report.level, Level::Breaking);
    assert!(report.analysis_complete);
    assert!(report.issues.len() <= 1);
    assert!(report.issues.iter().all(|issue| issue.path.len() <= 8));
}

#[test]
fn same_id_import_signature_or_named_type_change_is_unknown() {
    let source = "package example:shape@1.0.0; interface helper { type count = u32; tick: func() -> count; } interface api { run: func(); } world service { import helper; export api; }";
    for modified in [
        source.replace("type count = u32", "type count = u64"),
        source.replace("tick: func() -> count", "tick: func(value: count) -> count"),
        source.replace(
            "tick: func() -> count;",
            "tick: func() -> count; extra: func();",
        ),
    ] {
        let report = compare(source, &modified, ComparisonLimits::default());
        assert_eq!(report.level, Level::Unknown);
        assert!(!report.analysis_complete);
        super::report::assert_unknown_rejects_allowance(report);
    }
}
#[test]
fn exact_dependency_ids_and_referenced_type_names_are_compared() {
    fn source(version: &str) -> (Resolve, compare::WorldSurface) {
        let mut resolve = Resolve::default();
        resolve.push_source("types.wit",&format!("package dep:types@{version}; interface values {{ record item {{ value: u32 }} }}")).unwrap();
        let package=resolve.push_source("api.wit",&format!("package example:shape@1.0.0; interface api {{ use dep:types/values@{version}.{{item}}; run: func(value: item); }} world service {{ export api; }}")).unwrap();
        let world = resolve.select_world(&[package], Some("service")).unwrap();
        let surface = compare::surface(&resolve, world, SemanticLimits::default()).unwrap();
        (resolve, surface)
    }
    let (left, old) = source("1.0.0");
    let (right, new) = source("2.0.0");
    let mut analysis = Analysis::new(ComparisonLimits::default()).unwrap();
    surfaces(&left, &old, &right, &new, &mut analysis).unwrap();
    let report = analysis.finish();
    // WIT also exposes the changed dependency as a type import requirement.
    assert_eq!(report.level, Level::Unknown);
    assert!(!report.analysis_complete);
    super::report::assert_unknown_rejects_allowance(report.clone());
    assert!(report
        .issues
        .iter()
        .any(|issue| issue.code == Code::DependencyChanged));
}

#[test]
fn diamond_alias_reuse_is_charged_and_cannot_hide_deeper_visits() {
    let source = "package example:shape@1.0.0; interface api { type a = tuple<u32, u32>; type b = tuple<a, a>; type c = tuple<b, b>; type d = tuple<c, c>; run: func(value: d); } world service { export api; }";
    let complete = compare(source, source, ComparisonLimits::default());
    assert_eq!(complete.level, Level::Identical);
    let bounded = compare(
        source,
        source,
        ComparisonLimits {
            max_nodes: 32,
            ..Default::default()
        },
    );
    assert_eq!(bounded.level, Level::Unknown);
    assert!(!bounded.analysis_complete);
}
