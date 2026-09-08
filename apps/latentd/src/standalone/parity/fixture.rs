mod contracts;
mod package;

use std::io::Read;
use std::path::Path;

pub use package::{capabilities, echo, Package};

pub const SHARED: &str = "shared";
pub const CELL: &str = "phase1-adapter-parity:phase0:standard:00000000";
pub const TOKEN: &str = "parity-00000000000000000000000000000";
pub const TESTS_TOKEN: &str = "parity-tests-00000000000000000000000";
pub const IMPORTS: [&str; 4] = [
    "latent:context/context@0.1.0",
    "latent:log/log@0.1.0",
    "latent:clock/monotonic@0.1.0",
    "latent:clock/wall@0.1.0",
];

pub fn read(path: &Path, maximum: u64) -> Vec<u8> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)
        .expect("required prebuilt fixture")
        .take(maximum + 1)
        .read_to_end(&mut bytes)
        .expect("bounded fixture read");
    assert!(!bytes.is_empty() && u64::try_from(bytes.len()).unwrap() <= maximum);
    bytes
}

pub fn configuration(directory: &Path) -> (crate::config::NodeConfig, serde_json::Value) {
    let path = directory.join("node.json");
    let value = serde_json::json!({
        "formatVersion":1,"dataDirectory":directory.join("data"),
        "nodeId":"phase1-adapter-parity","bind":"127.0.0.1:0",
        "workers":{"runtime":1,"control":1},
        "cells":[{"class":"standard","capacity":1,"queueCapacity":2,
            "maximumMemoryBytes":64*1024*1024}],
        "execution":{"maximumCpuFuel":100_000_000,"maximumWallTimeMillis":5000,
            "maximumLogBytes":16384},
        "shutdownGraceMillis":500,
        "credentials":[
            {"token":TOKEN,"subject":"parity","tenant":"examples","role":"operator"},
            {"token":TESTS_TOKEN,"subject":"parity-tests","tenant":"tests","role":"operator"}
        ]
    });
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    let mut public = value;
    public.as_object_mut().unwrap().remove("credentials");
    public["dataDirectory"] = "data".into();
    (crate::config::NodeConfig::load(&path).unwrap(), public)
}

pub fn request<T>(message: T) -> tonic::Request<T> {
    authenticated(message, TOKEN)
}

pub fn authenticated<T>(message: T, token: &str) -> tonic::Request<T> {
    let mut request = tonic::Request::new(message);
    request
        .metadata_mut()
        .insert("authorization", format!("Bearer {token}").parse().unwrap());
    request.set_timeout(std::time::Duration::from_secs(5));
    request
}
