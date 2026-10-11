use super::*;
use latent_contracts::ComparisonLimits;
use latent_core::PHASE3_HOST_ABI_V3;
const INTERFACE: &str = "latent:http/streaming@0.3.0";
fn parse(source: &str) -> (Resolve, InterfaceId) {
    let mut resolve = Resolve::default();
    resolve.push_source("fixture.wit", source).unwrap();
    let id = resolve
        .interfaces
        .iter()
        .find_map(|(id, _)| (resolve.id_of(id).as_deref() == Some(INTERFACE)).then_some(id))
        .unwrap();
    (resolve, id)
}
fn inspect(host: bool, replacement: &str) -> latent_contracts::StructuralReport {
    let (left, old) = parse(PHASE3_HOST_ABI_V3.interface(INTERFACE).unwrap().wit);
    let (right, new) = parse(replacement);
    let mut analysis = Analysis::new(ComparisonLimits::default()).unwrap();
    for (resolve, id) in [(&left, old), (&right, new)] {
        if host {
            inspect_host_interface(resolve, id, &mut analysis).unwrap();
        } else {
            inspect_interface(resolve, id, &mut analysis).unwrap();
        }
    }
    Walker {
        left: &left,
        right: &right,
        analysis: &mut analysis,
        resources: host,
    }
    .interface(old, new, INTERFACE, false)
    .unwrap();
    analysis.finish()
}
#[test]
fn only_explicit_host_comparisons_recognize_http_resource_ownership() {
    let source = PHASE3_HOST_ABI_V3.interface(INTERFACE).unwrap().wit;
    let exact = inspect(true, source);
    assert_eq!(exact.level, Level::Identical);
    assert!(exact.analysis_complete);
    let application = inspect(false, source);
    assert!(matches!(
        application.level,
        Level::Unsupported | Level::Unknown
    ));
    assert!(application
        .issues
        .iter()
        .any(|issue| issue.code == Code::UnsupportedType));
    for changed in [
        source.replace("target: borrow<upload>", "target: upload"),
        source.replace("target: borrow<upload>", "target: borrow<body>"),
    ] {
        assert_ne!(inspect(true, &changed).level, Level::Identical);
    }
}
