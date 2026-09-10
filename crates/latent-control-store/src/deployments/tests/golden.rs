use super::super::{compiler, persistence};
use super::fixtures::*;
use latent_core::RouteGeneration;
use latent_manifest::__serde_json as json;

#[test]
fn catalog_preserves_original_bytes_and_weighted_assignments() {
    let releases = Releases::default();
    let one = releases.add("golden-one");
    let two = releases.add("golden-two");
    let mut blue = deployment("blue", "alice", &one);
    blue.metadata.annotations.insert(
        "unicode-and-escape".to_owned(),
        "\"\\ caf\u{e9} \u{96ea}".to_owned(),
    );
    let mut green = deployment("green", "alice", &two);
    green.route_weight = 3;
    let bob = deployment("bob-blue", "bob", &one);
    let desired = [blue, green, bob]
        .into_iter()
        .map(|d| (d.id.clone(), d))
        .collect();
    let catalog = run(compiler::compile(
        desired,
        RouteGeneration(9),
        1_234_567_890_000,
        &releases,
        Limits::default(),
    ))
    .unwrap();
    let bytes = persistence::encode(&catalog, Limits::default()).unwrap();
    let mut choices = Vec::new();
    for tenant in ["alice", "bob"] {
        for route in [
            None,
            Some("default"),
            Some(if tenant == "alice" {
                "blue"
            } else {
                "bob-blue"
            }),
        ] {
            for key in [
                None,
                Some(""),
                Some("key-0"),
                Some("key-1"),
                Some("a:b/c|d"),
                Some("caf\u{e9} \u{96ea}"),
            ] {
                let target = target(tenant, route);
                let resolved = catalog.resolve(&target, key, Limits::default()).unwrap();
                choices.push(json::json!({"tenant": tenant, "route": route, "key": key, "revision": resolved.revision.0, "release": resolved.release.0, "attributes": resolved.attributes}));
            }
        }
    }
    let mut failures = Vec::new();
    for (tenant, route, function) in [
        ("missing", None, "echo"),
        ("alice", Some("bob-blue"), "echo"),
        ("alice", None, "missing"),
    ] {
        let mut request = target(tenant, route);
        request.function.0 = function.to_owned();
        let failed = catalog
            .resolve(&request, None, Limits::default())
            .unwrap_err();
        failures.push(json::json!({"code": format!("{:?}", failed.code), "message": failed.message, "retryable": failed.retryable}));
    }
    assert_eq!(bytes.as_slice(), include_bytes!("golden/catalog-v2.json"));
    let snapshot = json::to_vec(&persistence::catalog_snapshot_value(&catalog)).unwrap();
    assert_eq!(snapshot.as_slice(), include_bytes!("golden/snapshot.json"));
    let expected_choices: json::Value =
        json::from_slice(include_bytes!("golden/choices.json")).unwrap();
    assert_eq!(json::Value::Array(choices), expected_choices);
    let expected_failures: json::Value =
        json::from_slice(include_bytes!("golden/failures.json")).unwrap();
    assert_eq!(json::Value::Array(failures), expected_failures);
}
