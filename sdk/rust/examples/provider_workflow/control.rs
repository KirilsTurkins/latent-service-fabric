use super::{
    config::{options, Configuration},
    require, shutdown, Assertions, ClientProfile, Result, RpcClient,
};
use latent_sdk::management::{
    CallOptions, CancelDisposition, CancelRequest, FailureCategory, GetActivationRequest,
};
use std::{fs, io::Write, path::Path, time::Duration};
use tokio::time::{sleep, Instant};

fn mode(config: &Configuration, value: &str) -> Result<()> {
    let root = Path::new(config.field("controlDirectory")?);
    let temporary = root.join("mode.tmp");
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|_| "rendezvous-write")?;
    file.write_all(value.as_bytes())
        .map_err(|_| "rendezvous-write")?;
    drop(file);
    fs::rename(&temporary, root.join("mode")).map_err(|_| "rendezvous-rename")
}

async fn rendezvous(config: &Configuration, prefix: &str, token: &str) -> Result<()> {
    let path = Path::new(config.field("controlDirectory")?).join(format!("{prefix}-{token}"));
    let deadline = Instant::now() + Duration::from_secs(4);
    while Instant::now() < deadline {
        match fs::symlink_metadata(&path) {
            Ok(metadata) => return require(metadata.is_file(), "rendezvous-type"),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => (),
            Err(_) => return Err("rendezvous-read"),
        }
        sleep(Duration::from_millis(2)).await;
    }
    Err("provider-rendezvous-expired")
}

pub async fn terminal(client: &RpcClient, identity: &str) -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(4);
    while Instant::now() < deadline {
        let response = client
            .get_activation(
                GetActivationRequest {
                    activation_id: identity.into(),
                },
                options(),
            )
            .await
            .map_err(|_| "retained-status-rpc")?;
        require(
            response.value.activation_id == identity,
            "retained-identity",
        )?;
        if response.value.terminal_state.is_some() {
            return Ok(());
        }
        sleep(Duration::from_millis(2)).await;
    }
    Err("retained-terminal-expired")
}

async fn require_running(client: &RpcClient, identity: &str) -> Result<()> {
    let running = client
        .get_activation(
            GetActivationRequest {
                activation_id: identity.into(),
            },
            options(),
        )
        .await
        .map_err(|_| "running-status-rpc")?;
    require(
        running.value.terminal_state.is_none(),
        "held-activation-not-running",
    )
}

pub async fn held(
    config: &Configuration,
    client: &RpcClient,
    kind: &'static str,
    assertions: &mut Assertions,
    activations: &mut Vec<String>,
) -> Result<()> {
    let identity = format!("rust-{kind}");
    let token = format!("hold-{identity}");
    mode(config, &token)?;
    let mut pending = client.invoke(
        config.request("http", kind, None)?,
        CallOptions {
            timeout_millis: Some(if kind == "deadline" { 500 } else { 3000 }),
        },
    );
    tokio::select! {
        started = rendezvous(config, "started", &token) => started?,
        _result = &mut pending => return Err("held-call-completed-before-start"),
    }
    activations.push(identity.clone());
    require_running(client, &identity).await?;
    match kind {
        "local-cancel" => {
            // lsf-example-begin: cancel
            drop(pending);
            let response = client
                .cancel(
                    CancelRequest {
                        activation_id: identity.clone(),
                        reason: "explicit recovery".into(),
                    },
                    options(),
                )
                .await
                .map_err(|_| "recovery-cancel-rpc")?;
            require(
                matches!(
                    response.value.disposition,
                    CancelDisposition::ACCEPTED | CancelDisposition::ALREADY_TERMINAL
                ),
                "recovery-cancel-disposition",
            )?;
            // lsf-example-end: cancel
            assertions.insert("localCancellation", true);
            assertions.insert("lostResponseStatus", true);
        }
        "explicit-cancel" => {
            let response = client
                .cancel(
                    CancelRequest {
                        activation_id: identity.clone(),
                        reason: "explicit request".into(),
                    },
                    options(),
                )
                .await
                .map_err(|_| "explicit-cancel-rpc")?;
            require(
                response.value.disposition == CancelDisposition::ACCEPTED,
                "explicit-cancel-not-accepted",
            )?;
            let response = pending.await;
            require(
                match response {
                    Ok(response) => response
                        .value
                        .platform_failure
                        .is_some_and(|error| error.code == "cancelled"),
                    Err(error) => matches!(error.grpc_status, Some(1 | 4)),
                },
                "explicit-cancel-result",
            )?;
            assertions.insert("explicitCancellation", true);
        }
        "deadline" => {
            let failure = pending.await.err().ok_or("deadline-not-enforced")?;
            require(
                failure.category == FailureCategory::DEADLINE
                    && failure.identity.activation_id.as_deref() == Some(identity.as_str()),
                "deadline-facts",
            )?;
            assertions.insert("absoluteDeadline", true);
        }
        "shutdown" => {
            let shutting_down = client.shutdown(Instant::now() + Duration::from_secs(5));
            let (response, closed) = tokio::join!(pending, shutting_down);
            closed.map_err(|_| "outstanding-shutdown-incomplete")?;
            require(
                response
                    .err()
                    .is_some_and(|failure| failure.category == FailureCategory::LOCAL_CANCELLED),
                "outstanding-shutdown-result",
            )?;
            shutdown(client).await?;
            assertions.insert("shutdownOutstanding", true);
        }
        _ => return Err("unknown-hold-case"),
    }
    rendezvous(config, "closed", &token).await?;
    mode(config, "reply")?;
    if kind != "shutdown" {
        terminal(client, &identity).await?;
    }
    Ok(())
}
