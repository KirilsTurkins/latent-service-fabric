use super::*;
use latent_contracts::ComparisonLimits;
use wit_parser::Resolve;

const ID: &str = "example:binding/api@1.0.0";
const SOURCE: &str = "package example:binding@1.0.0; interface api { record item { count: u32 } run: func(value: item) -> result<u32, string>; }";
fn resolve(source: &str) -> (Resolve, wit_parser::InterfaceId) {
    let mut resolve = Resolve::default();
    resolve.push_source("binding.wit", source).unwrap();
    let id = resolve
        .interfaces
        .iter()
        .find_map(|(id, _)| {
            resolve
                .id_of(id)
                .is_some_and(|name| name.contains("/api@"))
                .then_some(id)
        })
        .unwrap();
    (resolve, id)
}
fn matches(left: &str, right: &str, limits: ComparisonLimits) -> bool {
    let (left, a) = resolve(left);
    let (right, b) = resolve(right);
    let mut analysis = Analysis::new(limits).unwrap();
    if exact_interface(&left, a, &right, b, ID, &mut analysis).is_err() {
        return false;
    }
    let report = analysis.finish();
    report.analysis_complete && report.level == Level::Identical
}
#[test]
fn named_definitions_versions_and_exact_function_sets_are_checked() {
    assert!(matches(SOURCE, SOURCE, ComparisonLimits::default()));
    for changed in [
        SOURCE.replace("count: u32", "count: u64"),
        SOURCE.replace("1.0.0", "1.0.1"),
        SOURCE.replace("run: func", "added: func(); run: func"),
        SOURCE.replace("result<u32, string>", "result<string, u32>"),
        SOURCE.replace("value: item", "different: item"),
        SOURCE
            .replace("record item { count: u32 }", "resource item;")
            .replace("value: item", "value: borrow<item>"),
        SOURCE.replace("run: func", "run: async func"),
    ] {
        assert!(!matches(SOURCE, &changed, ComparisonLimits::default()));
    }
    assert!(!matches(
        SOURCE,
        SOURCE,
        ComparisonLimits {
            max_nodes: 1,
            ..Default::default()
        }
    ));
}
#[test]
fn dependency_versions_cannot_alias_same_shaped_types() {
    fn dependent(version: &str) -> (Resolve, wit_parser::InterfaceId) {
        let mut r = Resolve::default();
        r.push_source(
            "dep.wit",
            &format!(
                "package dep:types@{version}; interface types {{ record item {{ count: u32 }} }}"
            ),
        )
        .unwrap();
        r.push_source("api.wit", &format!("package example:binding@1.0.0; interface api {{ use dep:types/types@{version}.{{item}}; run: func(value: item); }}")).unwrap();
        let id = r
            .interfaces
            .iter()
            .find_map(|(id, _)| (r.id_of(id).as_deref() == Some(ID)).then_some(id))
            .unwrap();
        (r, id)
    }
    let (a, ai) = dependent("1.0.0");
    let (b, bi) = dependent("2.0.0");
    assert!(exact_interface(
        &a,
        ai,
        &b,
        bi,
        ID,
        &mut Analysis::new(ComparisonLimits::default()).unwrap()
    )
    .is_err());
}
