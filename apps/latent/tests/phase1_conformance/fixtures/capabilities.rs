use latent_artifacts::ValueType;
use serde_json::json;

use super::generic::{contract, encode_contracts, field, function, manifest};
use super::{Package, IMPORTS};

pub(super) fn package(bytes: Vec<u8>) -> Package {
    let mut manifest = manifest(
        "capabilities",
        "tests:capabilities/service@0.1.0",
        &["tests:capabilities/api@0.1.0"],
    );
    manifest["imports"] = json!(IMPORTS
        .iter()
        .map(|name| json!({"contract":name,"optional":false}))
        .collect::<Vec<_>>());
    let record = |name: &str| ValueType::Record(name.to_owned());
    let fields = || ValueType::List(Box::new(record("field")));
    let functions = vec![
        function("snapshot", Vec::new(), Some(record("context-snapshot"))),
        function(
            "log-probe",
            vec![
                field("message", ValueType::String),
                field("fields", fields()),
            ],
            Some(record("log-observation")),
        ),
        function(
            "log-twice",
            vec![
                field("message", ValueType::String),
                field("fields", fields()),
            ],
            Some(ValueType::List(Box::new(record("log-observation")))),
        ),
        function(
            "clocks",
            Vec::new(),
            Some(ValueType::List(Box::new(record("clock-reading")))),
        ),
        function("work-observe", Vec::new(), Some(record("work-observation"))),
    ];
    Package::create(
        bytes,
        manifest,
        encode_contracts(&[contract("tests:capabilities", "api", functions)]),
        "capabilities",
        "tests:capabilities/api@0.1.0",
        "tests",
    )
}
