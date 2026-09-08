use super::{cancel, phase, spin};
use crate::{
    cases::{payload, unsigned},
    evidence::Evidence,
    fixtures::{path, Package},
    harness::Harness,
};
use serde_json::{json, Value};

pub async fn route_update(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("route-update");
    let original = harness
        .call("tests", &["deployment", "get", "generic"], 0, "success")
        .await;
    let original_manifest = &original["data"]["deployment"]["manifest"];
    let expected = original["data"]["deployment"]["generation"]
        .as_str()
        .expect("object generation");
    let input = package.input("route-empty.json", &json!([]));
    let pending = spin(harness, package, "route-old-owner", &input);
    let running = phase(harness, "tests", "route-old-owner", "running").await;
    let old_pin = pin_from_status(&running);
    assert_eq!(old_pin["releaseDigest"], package.digest);
    let mut candidate = original_manifest.clone();
    candidate["spec"]["resources"]["cpuFuel"] = json!(2_000_000_000_u64);
    let update = package.input("generic-policy-update.json", &candidate);
    let applied = apply(harness, &update, expected).await;
    let current = harness
        .invoke(
            package,
            "identify",
            "route-new-owner",
            &input,
            &["--cpu-fuel", "100000000"],
            (0, "success"),
        )
        .await;
    assert_eq!(payload(&current), json!([11]));
    let new_pin = &current["data"]["resolvedRevision"];
    assert_eq!(new_pin["releaseDigest"], old_pin["releaseDigest"]);
    assert_ne!(
        new_pin["revisionId"], old_pin["revisionId"],
        "policy changes revision identity"
    );
    assert!(unsigned(&new_pin["routeGeneration"]) > unsigned(&old_pin["routeGeneration"]));
    let accepted = cancel(harness, "route-old-owner").await;
    let old_result = harness.finish_cli(pending, 4, "platform-failure").await;
    assert_eq!(old_result["error"]["code"], "cancelled");
    assert_eq!(
        old_result["data"]["resolvedRevision"], old_pin,
        "accepted owner retains its original policy revision and catalog generation"
    );
    let old_status = harness
        .call(
            "tests",
            &["activation", "get", "route-old-owner"],
            0,
            "success",
        )
        .await;
    assert_eq!(pin_from_status(&old_status), old_pin);
    let restore = package.input("generic-policy-original.json", original_manifest);
    let changed_generation = applied["data"]["deployment"]["generation"]
        .as_str()
        .expect("updated version");
    let restored = apply(harness, &restore, changed_generation).await;
    let restored_routes = harness.call("tests", &["route", "get"], 0, "success").await;
    let matching = restored_routes["data"]["snapshot"]["services"]
        .as_array()
        .expect("scoped route rows")
        .iter()
        .filter(|row| row["service"] == package.service)
        .collect::<Vec<_>>();
    assert!(
        !matching.is_empty(),
        "restored service must remain routable"
    );
    for service in matching {
        let revisions = service["revisions"].as_array().expect("revision rows");
        assert!(!revisions.is_empty(), "restored service has a revision");
        assert!(revisions
            .iter()
            .all(|revision| revision["revisionId"] == old_pin["revisionId"]));
    }
    assert_eq!(
        old_status["data"]["finalConsumption"],
        old_result["data"]["consumption"]
    );

    evidence.passed(
        harness,
        json!({"original":original,"running":running,"applied":applied,
        "newResponse":current,"cancel":accepted,"oldResponse":old_result,"oldStatus":old_status,
        "restored":restored,"restoredRoutes":restored_routes,
        "revisionChange":"same-immutable-component-with-changed-budget-policy"}),
    );
}

async fn apply(harness: &mut Harness, file: &std::path::Path, expected: &str) -> Value {
    harness
        .call(
            "tests",
            &[
                "deployment",
                "apply",
                path(file),
                "--expected-generation",
                expected,
            ],
            0,
            "success",
        )
        .await
}

fn pin_from_status(status: &Value) -> Value {
    let metadata = &status["data"]["metadata"];
    for field in ["revision", "release", "route-generation"] {
        assert!(
            metadata[field]
                .as_str()
                .is_some_and(|value| !value.is_empty()),
            "trusted resolved status metadata"
        );
    }
    json!({"revisionId":metadata["revision"],"releaseDigest":metadata["release"],
        "routeGeneration":metadata["route-generation"]})
}
