use latent_core::TenantId;
use latent_protected_files::ProtectedFilePolicy;
use latent_sdk::{
    management::{
        CallOptions, CancelRequest, ClientFailure, ClientProfile, GetActivationRequest,
        InvocationTarget, InvokeRequest, InvokeResponse, OutcomeKnowledge, ResourceBudget,
    },
    network::{ClientConfig, ClientLimits, RpcClient},
};
use serde_json::{json, Value};
use std::{net::SocketAddr, path::PathBuf, process::ExitCode, time::Duration};
use tokio::time::Instant;
use zeroize::Zeroizing;

struct Arguments {
    endpoint: SocketAddr,
    tenant: TenantId,
    credential_file: PathBuf,
    activation: String,
    mode: String,
    service: Option<String>,
    route: Option<String>,
    http_url: Option<String>,
}

impl Arguments {
    fn parse() -> Result<Self, &'static str> {
        let values: Vec<_> = std::env::args_os().skip(1).take(10).collect();
        if !(5..=8).contains(&values.len()) {
            return Err("usage: provider_client ENDPOINT TENANT CREDENTIAL_FILE ACTIVATION_ID http|blob|status|cancel [SERVICE ROUTE [HTTP_URL]]");
        }
        let text = |index: usize| {
            values[index]
                .to_str()
                .filter(|value| !value.is_empty() && value.len() <= 256)
                .ok_or("invalid-argument")
        };
        let mode = text(4)?;
        let expected = match mode {
            "http" => 8,
            "blob" => 7,
            "status" | "cancel" => 5,
            _ => return Err("invalid-argument"),
        };
        if values.len() != expected || values[2].len() > 4096 {
            return Err("invalid-argument");
        }
        Ok(Self {
            endpoint: text(0)?.parse().map_err(|_| "invalid-endpoint")?,
            tenant: TenantId(text(1)?.into()),
            credential_file: PathBuf::from(&values[2]),
            activation: text(3)?.into(),
            mode: mode.into(),
            service: (values.len() >= 7)
                .then(|| text(5).map(str::to_owned))
                .transpose()?,
            route: (values.len() >= 7)
                .then(|| text(6).map(str::to_owned))
                .transpose()?,
            http_url: (values.len() == 8)
                .then(|| text(7).map(str::to_owned))
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
    if !cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        return Err("example-requires-protected-linux-profile");
    }
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
            rpc_timeout: Duration::from_secs(5),
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
    let options = CallOptions {
        timeout_millis: Some(5000),
    };
    if arguments.mode == "status" {
        return Ok(
            match client
                .get_activation(
                    GetActivationRequest {
                        activation_id: arguments.activation,
                    },
                    options,
                )
                .await
            {
                Ok(reply) => json!({"outcome":"status", "phase":reply.value.phase,
                "terminalState":reply.value.terminal_state}),
                Err(error) => failure(&error),
            },
        );
    }
    if arguments.mode == "cancel" {
        return Ok(
            match client
                .cancel(
                    CancelRequest {
                        activation_id: arguments.activation,
                        reason: "explicit example request".into(),
                    },
                    options,
                )
                .await
            {
                Ok(reply) => {
                    json!({"outcome":"cancel", "disposition":reply.value.disposition.0,
                        "terminalState":reply.value.terminal_state})
                }
                Err(error) => failure(&error),
            },
        );
    }
    let (contract, payload) = if arguments.mode == "http" {
        (
            "tests:http/api@1.0.0",
            serde_json::to_vec(&json!([
                0,
                arguments.http_url.ok_or("missing-http-url")?,
                "0"
            ]))
            .map_err(|_| "guest-request-encoding")?,
        )
    } else {
        ("tests:local-blobs/api@1.0.0", b"[0,\"\",\"0\"]".to_vec())
    };
    let request = InvokeRequest {
        activation_id: Some(arguments.activation),
        root_activation_id: None,
        parent_activation_id: None,
        target: Some(InvocationTarget {
            tenant: arguments.tenant.0,
            service: arguments.service.ok_or("missing-service")?,
            contract: contract.into(),
            function: "run".into(),
            route: arguments.route,
        }),
        payload,
        media_type: "application/vnd.latent.wit-values.v1+json".into(),
        budget: Some(ResourceBudget {
            cpu_fuel: 10_000_000_000,
            memory_bytes: 16 * 1024 * 1024,
            wall_time_limit_millis: Some(5000),
            child_calls: 0,
            outbound_requests: 8,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: if arguments.mode == "blob" { 65536 } else { 0 },
            blob_write_bytes: if arguments.mode == "blob" { 65536 } else { 0 },
            log_bytes: 0,
            effect_count: 0,
        }),
        ..Default::default()
    };
    let reply = match client.invoke(request, options).await {
        Ok(reply) => reply,
        Err(error) => return Ok(failure(&error)),
    };
    outcome(reply.value)
}

fn outcome(value: InvokeResponse) -> Result<Value, &'static str> {
    Ok(
        match (value.success, value.declared_error, value.platform_failure) {
            (Some(success), None, None) => {
                if success.payload.len() > 256 {
                    return Err("unexpected-guest-result");
                }
                let result: Value = serde_json::from_slice(&success.payload)
                    .map_err(|_| "unexpected-guest-result")?;
                let values = result
                    .as_array()
                    .filter(|values| values.len() == 1)
                    .ok_or("unexpected-guest-result")?;
                let number = values[0]
                    .as_str()
                    .and_then(|value| value.parse::<u64>().ok())
                    .ok_or("unexpected-guest-result")?;
                let consumption = value.consumption.ok_or("missing-consumption")?;
                json!({"outcome":"succeeded", "guestResult":number.to_string(),
                "activationId":value.activation_id,
                "outboundRequests":consumption.outbound_requests,
                "blobReadBytes":consumption.blob_read_bytes.to_string(),
                "blobWriteBytes":consumption.blob_write_bytes.to_string()})
            }
            (None, Some(_), None) => json!({"outcome":"declared-error"}),
            (None, None, Some(error)) => {
                json!({"outcome":"platform-failure", "code":error.code})
            }
            _ => return Err("invalid-invocation-outcome"),
        },
    )
}

fn failure(value: &ClientFailure) -> Value {
    json!({"outcome":"rpc-failure", "category":value.category.0,
        "dispatched":value.dispatched, "outcomeKnown":value.outcome == OutcomeKnowledge::OBSERVED,
        "activationId":value.identity.activation_id, "grpcCode":value.grpc_status})
}
