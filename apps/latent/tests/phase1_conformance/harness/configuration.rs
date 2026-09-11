use serde_json::{json, Value};
use std::path::Path;

pub const NODE_ID: &str = "phase1-conformance";
pub const TOKENS: [&str; 2] = [
    "phase1-tests-private-0000000000000000000001",
    "phase1-examples-private-000000000000000001",
];

pub(super) fn node() -> (Value, Value) {
    let public = json!({
        "formatVersion":1,"dataDirectory":"data","nodeId":NODE_ID,"bind":"127.0.0.1:0",
        "workers":{"runtime":1,"control":1},
        "cells":[{"class":"standard","capacity":2,"queueCapacity":3,"maximumMemoryBytes":67_108_864}],
        "execution":{"maximumCpuFuel":10_000_000_000_u64,"maximumWallTimeMillis":5000,"maximumLogBytes":16384},
        "cache":{"entries":4,"preparations":1},"catalogs":{"releaseEntries":8,"deployments":8},
        "retention":{"terminalEntries":32,"terminalTtlMillis":30_000},"shutdownGraceMillis":200
    });
    let mut private = public.clone();
    private["credentials"] = json!([
        {"token":TOKENS[0],"subject":"tests-operator","tenant":"tests","role":"operator"},
        {"token":TOKENS[1],"subject":"examples-operator","tenant":"examples","role":"operator"}
    ]);
    (private, public)
}

pub(super) fn profiles(path: &Path, endpoint: &str) {
    let profiles = [("tests", TOKENS[0]), ("examples", TOKENS[1])]
        .into_iter()
        .map(|(tenant, token)| {
            json!({"name":tenant,"tenant":tenant,"token":token,
            "endpoint":endpoint,"connectTimeoutMillis":2000,"rpcTimeoutMillis":5000})
        })
        .collect::<Vec<_>>();
    std::fs::write(
        path,
        serde_json::to_vec(&json!({"formatVersion":1,
        "defaultProfile":"tests","profiles":profiles}))
        .expect("profiles JSON"),
    )
    .expect("separate client profile");
}
