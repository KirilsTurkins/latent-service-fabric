use serde_json::Value;

use super::{Harness, Package};

/// The second component is published only: its deliberate post-return trap never runs.
pub(super) fn two_scoped_pages(harness: &Harness, generic: &Package) {
    let dormant = Package::dormant_adversarial();
    assert_ne!(generic.digest, dormant.digest);
    let published = dormant.publish(harness, "generic");
    assert_eq!(published["data"]["release"]["digest"], dormant.digest);
    assert_eq!(published["data"]["release"]["tenant"], "tests");

    let first = harness.call(
        "generic",
        &["release", "list", "--page-size", "1"],
        0,
        "success",
    );
    let token = first["data"]["nextPageToken"]
        .as_str()
        .expect("real release continuation");
    let second_args = ["release", "list", "--page-size", "1", "--page-token", token];
    let second = harness.call("generic", &second_args, 0, "success");
    let mut expected = [&generic.digest, &dormant.digest];
    expected.sort();
    assert_eq!(single_digest(&first), expected[0]);
    assert_eq!(single_digest(&second), expected[1]);
    assert!(second["data"]["nextPageToken"].is_null());

    let repeated = harness.call(
        "generic",
        &["release", "list", "--page-size", "1"],
        0,
        "success",
    );
    assert_eq!(
        repeated["data"], first["data"],
        "unchanged snapshot returns the same cursor"
    );
    let repeated = harness.call("generic", &second_args, 0, "success");
    assert_eq!(
        repeated["data"], second["data"],
        "continuation is repeatable without implicit paging"
    );

    filters(harness, generic, &dormant, token);
    let inventory = harness.call(
        "operator",
        &["node", "get", super::super::support::NODE_ID],
        0,
        "success",
    );
    assert_eq!(
        inventory["data"]["inventory"]["cacheSummary"]["entries"], "0",
        "publication and paging do not prepare either component"
    );
}

fn filters(harness: &Harness, generic: &Package, dormant: &Package, token: &str) {
    for package in [generic, dormant] {
        let page = harness.call(
            "generic",
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
        assert_eq!(single_digest(&page), package.digest);
        assert!(page["data"]["nextPageToken"].is_null());
    }
    let missing = harness.call(
        "generic",
        &["release", "list", "--service", "tests/missing"],
        0,
        "success",
    );
    assert!(missing["data"]["releases"]
        .as_array()
        .expect("empty service page")
        .is_empty());
    assert!(missing["data"]["nextPageToken"].is_null());
    let foreign = harness.call(
        "foreign",
        &["release", "list", "--page-size", "1"],
        0,
        "success",
    );
    assert!(foreign["data"]["releases"]
        .as_array()
        .expect("empty tenant page")
        .is_empty());
    assert!(foreign["data"]["nextPageToken"].is_null());

    let wrong_tenant = harness.call(
        "foreign",
        &["release", "list", "--page-token", token],
        4,
        "platform-failure",
    );
    assert_eq!(wrong_tenant["error"]["code"], "invalid-argument");
    let wrong_service = harness.call(
        "generic",
        &[
            "release",
            "list",
            "--service",
            generic.service,
            "--page-token",
            token,
        ],
        4,
        "platform-failure",
    );
    assert_eq!(wrong_service["error"]["code"], "invalid-argument");
}

fn single_digest(page: &Value) -> &str {
    let rows = page["data"]["releases"]
        .as_array()
        .expect("one release page");
    assert_eq!(rows.len(), 1, "CLI returns exactly one requested page");
    assert_eq!(rows[0]["tenant"], "tests");
    rows[0]["digest"].as_str().expect("exact release digest")
}
