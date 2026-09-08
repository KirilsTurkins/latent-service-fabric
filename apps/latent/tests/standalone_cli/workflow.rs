#[path = "workflow/pagination.rs"]
mod pagination;
#[path = "workflow/payload.rs"]
mod payload;

use pagination::deployment_pages;
use payload::{assert_receipt_pin, output_failure, quiet_echo};

use std::fs;

use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::{json, Value};

use super::support::{
    package::{path, Package, MEDIA},
    Harness, NODE_ID,
};

#[test]
#[ignore = "requires prebuilt latentd and the generated echo publication package"]
fn cli_publishes_deploys_pages_invokes_and_recovers_without_client_artifact_files() {
    let package = Package::echo();
    let mut harness = Harness::start();
    let release = publish(&harness, &package);
    let (deployment, generation) = deployment_pages(&harness, &package);
    let route = inspect_management(&harness);
    harness.ready();
    let payload = package.payload("input.json", &json!(["hello\n\u{1b}[31m"]));
    let raw_output = package.directory.path().join("raw-output.bin");
    let first = invoke_echo(
        &harness,
        &package,
        &payload,
        "cli-before-restart",
        Some(&raw_output),
    );
    assert_payload(&first, &json!([{"ok":"hello\n\u{1b}[31m"}]));
    assert_receipt_pin(&first, &route, &package.digest);
    assert_eq!(
        fs::read(&raw_output).expect("explicit raw payload file"),
        STANDARD
            .decode(
                first["data"]["payload"]["data"]
                    .as_str()
                    .expect("base64 payload")
            )
            .expect("payload decode")
    );
    let status = harness.call(
        "caller",
        &["activation", "get", "cli-before-restart"],
        0,
        "success",
    );
    assert_eq!(status["data"]["terminalState"], "completed");
    harness.call(
        "foreign",
        &["activation", "get", "cli-before-restart"],
        6,
        "not-found",
    );
    for file in [&package.component, &package.manifest, &package.contracts] {
        fs::remove_file(file).expect("remove client-side artifact source after byte publication");
    }
    harness.stop();
    harness.restart();
    let recovered = harness.call(
        "operator",
        &["release", "get", &package.digest],
        0,
        "success",
    );
    assert_eq!(recovered["data"]["release"], release["data"]["release"]);
    let recovered = harness.call("operator", &["deployment", "get", "echo-a"], 0, "success");
    assert_eq!(recovered["data"]["deployment"]["generation"], generation);
    let restored = harness.call("operator", &["route", "get"], 0, "success");
    assert_eq!(restored["data"]["snapshot"], route["data"]["snapshot"]);
    harness.ready();
    let second = quiet_echo(&harness, &package, &payload);
    assert_payload(&second, &json!([{"ok":"hello\n\u{1b}[31m"}]));
    assert_receipt_pin(&second, &restored, &package.digest);
    output_failure(&harness, &package, &payload, &raw_output);
    harness.call(
        "operator",
        &[
            "deployment",
            "delete",
            "echo-a",
            "--expected-generation",
            &generation,
        ],
        0,
        "success",
    );
    harness.call("operator", &["deployment", "get", "echo-a"], 6, "not-found");
    assert!(
        deployment.is_file(),
        "client deployment input stays outside node data"
    );
    harness.stop();
}

fn publish(harness: &Harness, package: &Package) -> Value {
    for (kind, file) in [
        ("capsule", &package.manifest),
        ("deployment", &package.deployment("echo-a")),
    ] {
        harness.call("operator", &["validate", kind, path(file)], 0, "success");
    }
    let release = package.publish(harness, "operator");
    assert_eq!(release["data"]["release"]["digest"], package.digest);
    assert_eq!(release["data"]["release"]["service"], package.service);
    let duplicate = package.publish(harness, "operator");
    assert_eq!(duplicate["data"]["release"], release["data"]["release"]);
    let got = harness.call(
        "operator",
        &["release", "get", &package.digest],
        0,
        "success",
    );
    assert_eq!(got["data"]["release"], release["data"]["release"]);
    let listed = harness.call(
        "operator",
        &[
            "release",
            "list",
            "--service",
            package.service,
            "--page-size",
            "1",
        ],
        0,
        "success",
    );
    assert_eq!(
        listed["data"]["releases"]
            .as_array()
            .expect("release page")
            .len(),
        1
    );
    assert!(listed["data"]["nextPageToken"].is_null());
    harness.call(
        "foreign",
        &["release", "get", &package.digest],
        6,
        "not-found",
    );
    let denied = harness.call("caller", &["release", "list"], 4, "platform-failure");
    assert_eq!(denied["error"]["code"], "permission-denied");

    release
}

fn inspect_management(harness: &Harness) -> Value {
    let route = harness.call("operator", &["route", "get"], 0, "success");
    assert_eq!(route["data"]["snapshot"]["tenant"], "examples");
    assert!(route["data"]["snapshot"]["services"]
        .as_array()
        .expect("route rows")
        .iter()
        .all(|row| row["tenant"] == "examples"));
    let inventory = harness.call("operator", &["node", "get", NODE_ID], 0, "success");
    assert_eq!(
        inventory["data"]["inventory"]["cacheSummary"]["entries"], "0",
        "management did not prepare a guest"
    );
    harness.call(
        "operator",
        &[
            "node",
            "list",
            "--trust-class",
            "internal",
            "--page-size",
            "1",
        ],
        0,
        "success",
    );
    route
}

fn invoke_echo(
    harness: &Harness,
    package: &Package,
    input: &std::path::Path,
    id: &str,
    output: Option<&std::path::Path>,
) -> Value {
    let mut args = vec![
        "invoke",
        "--service",
        package.service,
        "--contract",
        package.contract,
        "--function",
        "echo",
        "--input",
        path(input),
        "--activation-id",
        id,
    ];
    if let Some(output) = output {
        args.extend_from_slice(&["--payload-output", path(output)]);
    }
    harness.call("caller", &args, 0, "success")
}

pub(super) fn assert_payload(value: &Value, expected: &Value) {
    assert_eq!(value["data"]["payload"]["mediaType"], MEDIA);
    let encoded = value["data"]["payload"]["data"]
        .as_str()
        .expect("visible successful payload");
    let bytes = STANDARD.decode(encoded).expect("base64 response");
    assert_eq!(
        value["data"]["payload"]["byteLength"],
        bytes.len().to_string()
    );
    assert_eq!(
        serde_json::from_slice::<Value>(&bytes).expect("WIT result array"),
        *expected
    );
}
