#[path = "provider_workflow/config.rs"]
mod config;
#[path = "provider_workflow/control.rs"]
mod control;
#[path = "provider_workflow/invocation.rs"]
mod invocation;
#[path = "provider_workflow/management.rs"]
mod management;

use config::Configuration;
use latent_sdk::{management::ClientProfile, network::RpcClient};
use serde_json::{json, Value};
use std::{collections::BTreeMap, process::ExitCode, time::Duration};
use tokio::time::Instant;

type Result<Value> = std::result::Result<Value, &'static str>;
type Assertions = BTreeMap<&'static str, bool>;

fn require(condition: bool, reason: &'static str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(reason)
    }
}

async fn shutdown(client: &RpcClient) -> Result<()> {
    client
        .shutdown(Instant::now() + Duration::from_secs(5))
        .await
        .map_err(|_| "client-shutdown-incomplete")?;
    let usage = client.usage();
    require(
        usage.active_calls == 0
            && usage.reserved_message_bytes == 0
            && usage.executor_tasks == 0
            && usage.sockets == 0
            && usage.closed,
        "client-physical-owners-remain",
    )
}

async fn execute(config: &Configuration, clients: &[RpcClient]) -> Result<Value> {
    let client = &clients[0];
    let mut assertions = Assertions::new();
    let mut activations = Vec::new();
    invocation::run(config, clients, &mut assertions, &mut activations).await?;
    let (operation, attempt) = management::run(config, client, &mut assertions).await?;
    for kind in ["local-cancel", "explicit-cancel", "deadline", "shutdown"] {
        control::held(config, client, kind, &mut assertions, &mut activations).await?;
    }
    control::terminal(&clients[1], "rust-shutdown").await?;
    for owner in clients {
        shutdown(owner).await?;
    }
    assertions.insert("clientOwnersReaped", true);
    Ok(
        json!({"schemaVersion":"latent.sdk.provider.workflow.result.v1",
        "language":"rust", "assertions":assertions, "activationIds":activations,
        "operationId":operation, "auditAttempt":attempt.map(|value| value.to_string()),
        "transport":"numeric-loopback-http2-protobuf-v1"}),
    )
}

async fn run() -> Result<Value> {
    let config = Configuration::load()?;
    let clients = [
        config.client("tests", false, false)?,
        config.client("tests", false, false)?,
        config.client("foreign", false, false)?,
        config.client("tests", true, false)?,
        config.client("tests", false, true)?,
    ];
    let result = execute(&config, &clients).await;
    for owner in &clients {
        shutdown(owner).await?;
    }
    result
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> ExitCode {
    match run().await {
        Ok(value) => {
            println!("{value}");
            ExitCode::SUCCESS
        }
        Err(reason) => {
            eprintln!("{{\"stage\":\"rust-participant\",\"reason\":\"{reason}\"}}");
            ExitCode::FAILURE
        }
    }
}
