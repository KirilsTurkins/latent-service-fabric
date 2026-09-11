mod prepare;
mod response;

use std::path::PathBuf;
use std::time::Duration;

use crate::{
    args::InvokeArgs,
    config::{InputLimits, ResolvedConfig},
};

fn config() -> ResolvedConfig {
    ResolvedConfig {
        endpoint: "http://127.0.0.1:1".to_owned(),
        tenant: "tests".to_owned(),
        token: "not-used-by-local-tests".to_owned(),
        connect_timeout: Duration::from_secs(1),
        rpc_timeout: Duration::from_secs(1),
        limits: InputLimits::default(),
    }
}

fn invoke(input: PathBuf) -> InvokeArgs {
    InvokeArgs {
        service: "tests/service".to_owned(),
        contract: "tests:example/api@0.1.0".to_owned(),
        function: "call".to_owned(),
        input,
        route: None,
        activation_id: None,
        root_activation_id: None,
        parent_activation_id: None,
        media_type: "application/vnd.latent.wit-values.v1+json".to_owned(),
        deadline_unix_millis: None,
        priority: 0,
        idempotency_key: None,
        metadata: Vec::new(),
        budget: None,
        cpu_fuel: None,
        memory_bytes: None,
        wall_time_ms: None,
        log_bytes: None,
        payload_output: None,
    }
}
