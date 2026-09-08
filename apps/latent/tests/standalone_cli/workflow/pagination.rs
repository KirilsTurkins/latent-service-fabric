use super::{path, Harness, Package};

pub(super) fn deployment_pages(
    harness: &Harness,
    package: &Package,
) -> (std::path::PathBuf, String) {
    let first = package.deployment("echo-a");
    let second = package.deployment("echo-b");
    let applied = harness.call(
        "operator",
        &[
            "deployment",
            "apply",
            path(&first),
            "--expected-generation",
            "0",
        ],
        0,
        "success",
    );
    let original = applied["data"]["deployment"]["generation"]
        .as_str()
        .expect("decimal object version");
    harness.call(
        "operator",
        &[
            "deployment",
            "apply",
            path(&second),
            "--expected-generation",
            "0",
        ],
        0,
        "success",
    );
    let token = scoped_pages(harness);
    let updated = harness.call(
        "operator",
        &[
            "deployment",
            "apply",
            path(&first),
            "--expected-generation",
            original,
        ],
        0,
        "success",
    );
    let generation = updated["data"]["deployment"]["generation"]
        .as_str()
        .expect("updated object version")
        .to_owned();
    assert_ne!(
        generation, original,
        "unrelated write preserved the caller's old object precondition"
    );
    harness.call(
        "operator",
        &["deployment", "list", "--page-token", &token],
        4,
        "platform-failure",
    );
    let conflict = harness.call(
        "operator",
        &[
            "deployment",
            "apply",
            path(&first),
            "--expected-generation",
            original,
        ],
        4,
        "platform-failure",
    );
    assert_eq!(conflict["error"]["code"], "state-conflict");
    (first, generation)
}

fn scoped_pages(harness: &Harness) -> String {
    let page = harness.call(
        "operator",
        &["deployment", "list", "--page-size", "1"],
        0,
        "success",
    );
    let rows = page["data"]["deployments"].as_array().expect("one page");
    assert_eq!(rows.len(), 1);
    let token = page["data"]["nextPageToken"]
        .as_str()
        .expect("continuation");
    let next = harness.call(
        "operator",
        &[
            "deployment",
            "list",
            "--page-size",
            "1",
            "--page-token",
            token,
        ],
        0,
        "success",
    );
    let next_rows = next["data"]["deployments"].as_array().expect("final page");
    assert_eq!(next_rows.len(), 1);
    assert_ne!(
        rows[0]["manifest"]["metadata"]["name"],
        next_rows[0]["manifest"]["metadata"]["name"]
    );
    assert!(next["data"]["nextPageToken"].is_null());
    harness.call(
        "foreign",
        &["deployment", "list", "--page-token", token],
        4,
        "platform-failure",
    );
    token.to_owned()
}
