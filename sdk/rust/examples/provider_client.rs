use latent_core::{ActivationId, ContractId, FunctionId, ResourceBudget, ServiceId, TenantId};
use latent_protected_files::ProtectedFilePolicy;
use latent_sdk::{
    network::{ClientConfig, ClientLimits, RpcClient, RpcFailure},
    InvocationOutcome, InvocationTarget, InvokeOptions, InvokeRequest,
};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap, net::SocketAddr, path::PathBuf, process::ExitCode, time::Duration,
};
use tokio::time::Instant;
use zeroize::Zeroizing;

struct Arguments {
    endpoint: SocketAddr,
    tenant: TenantId,
    credential_file: PathBuf,
    activation: ActivationId,
    mode: String,
    service: Option<ServiceId>,
}

impl Arguments {
    fn parse() -> Result<Self, &'static str> {
        let values: Vec<_> = std::env::args_os().skip(1).take(8).collect();
        if !(5..=6).contains(&values.len()) {
            return Err("usage: provider_client ENDPOINT TENANT CREDENTIAL_FILE ACTIVATION_ID http|blob|status|cancel [SERVICE]");
        }
        let text = |index: usize| {
            values[index]
                .to_str()
                .filter(|value| !value.is_empty() && value.len() <= 256)
                .ok_or("invalid-argument")
        };
        let mode = text(4)?;
        if !matches!(mode, "http" | "blob" | "status" | "cancel")
            || matches!(mode, "http" | "blob") != (values.len() == 6)
            || values[2].len() > 4096
        {
            return Err("invalid-argument");
        }
        Ok(Self {
            endpoint: text(0)?.parse().map_err(|_| "invalid-endpoint")?,
            tenant: TenantId(text(1)?.into()),
            credential_file: PathBuf::from(&values[2]),
            activation: ActivationId(text(3)?.into()),
            mode: mode.into(),
            service: (values.len() == 6)
                .then(|| text(5).map(|value| ServiceId(value.into())))
                .transpose()?,
        })
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> ExitCode {
    match run().await {
        Ok(value) => {
            println!("{value}");
            ExitCode::SUCCESS
        }
        Err(reason) => {
            eprintln!("{reason}");
            ExitCode::FAILURE
        }
    }
}

async fn run() -> Result<Value, &'static str> {
    let arguments = Arguments::parse()?;
    let bytes = Zeroizing::new(
        latent_protected_files::read(
            &arguments.credential_file,
            256,
            ProtectedFilePolicy::Secret,
            "client.credential",
        )
        .map_err(|_| "protected-credential-file")?,
    );
    let credential = Zeroizing::new(
        std::str::from_utf8(&bytes)
            .map_err(|_| "credential-encoding")?
            .to_owned(),
    );
    let client = RpcClient::new(ClientConfig {
        endpoint: arguments.endpoint,
        tenant: arguments.tenant.clone(),
        credential,
        limits: ClientLimits {
            maximum_calls: 2,
            maximum_response_bytes: 16384,
            ..ClientLimits::default()
        },
    })
    .map_err(|_| "invalid-client-configuration")?;
    let result = execute(&client, arguments).await;
    client
        .shutdown(Instant::now() + Duration::from_secs(5))
        .await
        .map_err(|_| "client-shutdown-incomplete")?;
    let mut result = result?;
    result["clientOwnersReaped"] = json!(true);
    result["schemaVersion"] = json!("latent.rust.provider-client.v1");
    Ok(result)
}

async fn execute(client: &RpcClient, arguments: Arguments) -> Result<Value, &'static str> {
    let deadline = Instant::now() + Duration::from_secs(10);
    if arguments.mode == "status" {
        return Ok(
            match client
                .get_activation_until(&arguments.activation, deadline)
                .await
            {
                Ok(reply) => json!({"outcome":"status", "phase":format!("{:?}", reply.value.phase),
                "terminalState":reply.value.terminal_state.map(|state| format!("{state:?}"))}),
                Err(error) => failure(&error),
            },
        );
    }
    if arguments.mode == "cancel" {
        return Ok(
            match client
                .cancel_until(&arguments.activation, "explicit example request", deadline)
                .await
            {
                Ok(reply) => {
                    json!({"outcome":"cancel", "disposition":format!("{:?}", reply.value)})
                }
                Err(error) => failure(&error),
            },
        );
    }
    let (contract, payload) = if arguments.mode == "http" {
        ("tests:http/api@1.0.0", b"[0]".to_vec())
    } else {
        ("tests:local-blobs/api@1.0.0", b"[0,\"0\"]".to_vec())
    };
    let request = InvokeRequest {
        activation_id: Some(arguments.activation),
        root_activation_id: None,
        parent_activation_id: None,
        target: InvocationTarget {
            tenant: arguments.tenant,
            service: arguments.service.ok_or("missing-service")?,
            contract: ContractId(contract.into()),
            function: FunctionId("run".into()),
            route: None,
        },
        payload,
        media_type: "application/json".into(),
        options: InvokeOptions {
            deadline_unix_millis: None,
            priority: 0,
            idempotency_key: None,
            metadata: BTreeMap::new(),
            budget: ResourceBudget {
                cpu_fuel: 1_000_000,
                memory_bytes: 4 * 1024 * 1024,
                wall_time_limit_millis: Some(5000),
                child_calls: 0,
                outbound_requests: 1,
                state_read_bytes: 0,
                state_write_bytes: 0,
                blob_read_bytes: 64,
                blob_write_bytes: 64,
                log_bytes: 0,
                effect_count: 0,
            },
        },
    };
    let reply = match client.invoke_until(request, deadline).await {
        Ok(reply) => reply,
        Err(error) => return Ok(failure(&error)),
    };
    Ok(match reply.value {
        InvocationOutcome::Succeeded(value) => {
            if value.payload.len() > 256 {
                return Err("unexpected-guest-result");
            }
            let result: Value =
                serde_json::from_slice(&value.payload).map_err(|_| "unexpected-guest-result")?;
            let values = result
                .as_array()
                .filter(|values| values.len() == 1)
                .ok_or("unexpected-guest-result")?;
            let number = if arguments.mode == "http" {
                values[0].as_u64()
            } else {
                values[0]
                    .as_str()
                    .and_then(|value| value.parse::<u64>().ok())
            }
            .ok_or("unexpected-guest-result")?;
            json!({"outcome":"succeeded", "guestResult":number.to_string(),
                "activationId":value.activation_id.0,
                "outboundRequests":value.consumption.outbound_requests,
                "blobReadBytes":value.consumption.blob_read_bytes.to_string(),
                "blobWriteBytes":value.consumption.blob_write_bytes.to_string()})
        }
        InvocationOutcome::DeclaredError(_) => json!({"outcome":"declared-error"}),
        InvocationOutcome::PlatformFailure(value) => {
            json!({"outcome":"platform-failure", "code":value.error.code.wire_code()})
        }
    })
}

fn failure(value: &RpcFailure) -> Value {
    json!({"outcome":"rpc-failure", "kind":format!("{:?}", value.kind),
        "dispatched":value.dispatched, "outcomeKnown":value.outcome_known,
        "activationId":value.recovery.activation_id, "grpcCode":value.grpc_code})
}
