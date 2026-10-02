//! Actual SDK participant. The fixture owner supplies already admitted node inputs.
#[cfg(target_os = "linux")]
mod fixture {
    use latent_core::TenantId;
    use latent_protected_files::ProtectedFilePolicy;
    use latent_rpc::{control::v1 as c, transaction::v1 as t};
    use latent_sdk::{
        network::{ClientConfig, ClientLimits, RpcClient},
        transaction::{self as tx, TransactionClient},
    };
    use prost::Message;
    use serde_json::{json, Value};
    use std::{
        collections::HashSet,
        fs::OpenOptions,
        io::{BufRead, Write},
        path::{Path, PathBuf},
        time::Duration,
    };
    use tokio::time::{sleep_until, Instant};
    use zeroize::Zeroizing;

    type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
    const MAXIMUM: usize = 2 * 1024 * 1024;

    fn write(path: &Path, bytes: &[u8]) -> Result<()> {
        use std::os::unix::fs::OpenOptionsExt;
        if bytes.len() > MAXIMUM {
            return Err("fixture-output-bound".into());
        }
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)?;
        output.write_all(bytes)?;
        output.sync_all()?;
        Ok(())
    }

    fn observations(
        directory: &Path,
        id: &str,
        observed: &Option<tx::ObservedOutcome>,
    ) -> Result<()> {
        macro_rules! save {
            ($kind:literal, $wire:ty, $value:expr) => {{
                let value: $wire = (*$value.clone())
                    .try_into()
                    .map_err(|_| "fixture-observation-conversion")?;
                write(
                    &directory.join(format!("{id}.{}.pb", $kind)),
                    &value.encode_to_vec(),
                )?;
            }};
        }
        match observed {
            Some(tx::ObservedOutcome::Command(value)) => {
                let value = tx::CommandInspection {
                    command_id: value.command_id.clone(),
                    attempt_id: value.attempt_id.clone(),
                    outcome: value.outcome,
                    metadata_durable: value.metadata_durable,
                    application_state_committed: value.application_state_committed,
                    fingerprint_sha256: value.fingerprint_sha256.clone(),
                    commit: value.commit.clone(),
                    proven_abort: value.proven_abort.clone(),
                    source: value.source.clone(),
                    retention: value.retention.clone(),
                    ..Default::default()
                };
                let wire: t::CommandInspection = value
                    .try_into()
                    .map_err(|_| "fixture-observation-conversion")?;
                write(
                    &directory.join(format!("{id}.command.pb")),
                    &wire.encode_to_vec(),
                )?;
            }
            Some(tx::ObservedOutcome::State(value)) => {
                save!("state", c::StateOperationReceipt, value)
            }
            Some(tx::ObservedOutcome::Namespace(value)) => {
                save!("namespace", c::NamespaceOperationReceipt, value)
            }
            Some(tx::ObservedOutcome::Effect(value)) => save!("effect", t::EffectReceipt, value),
            Some(tx::ObservedOutcome::Dispatcher(value)) => {
                save!("dispatcher", c::DispatcherOperationReceipt, value)
            }
            Some(tx::ObservedOutcome::EffectPlan(value)) => {
                save!("effectPlan", c::EffectManagementPlan, value)
            }
            None => {}
        }
        Ok(())
    }

    async fn dispatch(
        client: &RpcClient,
        method: &str,
        bytes: &[u8],
        options: tx::CallOptions,
        cancel: Option<Instant>,
        directory: &Path,
        id: &str,
    ) -> Result<Value> {
        macro_rules! call { ($method:ident, $module:ident, $request:ident, $response:ident) => {{
        let request = $module::$request::decode(bytes)?;
        let future = client.$method(request.into(), options);
        let cancellation = sleep_until(cancel.unwrap_or_else(|| Instant::now() + Duration::from_secs(120)));
        tokio::pin!(future, cancellation);
        let result = tokio::select! {
            value = &mut future => Some(value),
            _ = &mut cancellation, if cancel.is_some() => None,
        };
        match result {
            Some(Ok(value)) => {
                let response: $module::$response = value.value.try_into().map_err(|_| "fixture-response-conversion")?;
                write(&directory.join(format!("{id}.response.pb")), &response.encode_to_vec())?;
                json!({"status":"response"})
            }
            Some(Err(failure)) => {
                observations(directory, id, &failure.observed)?;
                json!({"status":"failure", "failureCategory":failure.transport.category.0,
                    "grpcStatus":failure.transport.grpc_status, "dispatched":failure.transport.dispatched})
            }
            None => json!({"status":"local-cancelled"}),
        }
    }} }
        let value = match method {
            "invoke_command" => call!(
                invoke_command,
                t,
                InvokeCommandRequest,
                InvokeCommandResponse
            ),
            "query" => call!(query, t, QueryRequest, QueryResponse),
            "lookup_command" => call!(
                lookup_command,
                t,
                LookupCommandRequest,
                LookupCommandResponse
            ),
            "lookup_commit" => call!(lookup_commit, t, LookupCommitRequest, LookupCommitResponse),
            "get_effect" => call!(get_effect, t, GetEffectRequest, GetEffectResponse),
            "list_effect_history" => call!(
                list_effect_history,
                t,
                ListEffectHistoryRequest,
                ListEffectHistoryResponse
            ),
            "cancel_command" => call!(
                cancel_command,
                t,
                CancelCommandRequest,
                CancelCommandResponse
            ),
            "mutate_namespace" => call!(
                mutate_namespace,
                c,
                MutateNamespaceRequest,
                MutateNamespaceResponse
            ),
            "inspect_namespace" => call!(
                inspect_namespace,
                c,
                InspectNamespaceRequest,
                InspectNamespaceResponse
            ),
            "select_entity" => call!(select_entity, c, SelectEntityRequest, SelectEntityResponse),
            "mutate_state" => call!(mutate_state, c, MutateStateRequest, MutateStateResponse),
            "plan_effect_mutation" => call!(
                plan_effect_mutation,
                c,
                PlanEffectMutationRequest,
                PlanEffectMutationResponse
            ),
            "get_state_operation_receipt" => call!(
                get_state_operation_receipt,
                c,
                GetStateOperationReceiptRequest,
                GetStateOperationReceiptResponse
            ),
            "inspect_dispatcher" => call!(
                inspect_dispatcher,
                c,
                InspectDispatcherRequest,
                InspectDispatcherResponse
            ),
            "control_dispatcher" => call!(
                control_dispatcher,
                c,
                ControlDispatcherRequest,
                ControlDispatcherResponse
            ),
            "get_dispatcher_operation" => call!(
                get_dispatcher_operation,
                c,
                GetDispatcherOperationRequest,
                GetDispatcherOperationResponse
            ),
            _ => return Err("fixture-method".into()),
        };
        Ok(value)
    }

    async fn run() -> Result<()> {
        use std::os::unix::fs::MetadataExt;
        let args: Vec<_> = std::env::args().skip(1).collect();
        if args.len() != 5 || args[0] != "--node-fixture" || !cfg!(target_os = "linux") {
            return Err("fixture-arguments".into());
        }
        let directory = PathBuf::from(&args[4]);
        let metadata = std::fs::symlink_metadata(&directory)?;
        let token_metadata = std::fs::symlink_metadata(&args[3])?;
        if !metadata.is_dir()
            || metadata.mode() & 0o077 != 0
            || metadata.uid() != token_metadata.uid()
        {
            return Err("fixture-directory".into());
        }
        let bytes = Zeroizing::new(
            latent_protected_files::read(
                Path::new(&args[3]),
                256,
                ProtectedFilePolicy::Secret,
                "transaction.fixture.credential",
            )
            .map_err(|_| "fixture-credential-file")?,
        );
        let credential = Zeroizing::new(std::str::from_utf8(&bytes)?.to_owned());
        let client = RpcClient::new(ClientConfig {
            endpoint: args[1]
                .strip_prefix("http://")
                .ok_or("fixture-endpoint")?
                .parse()?,
            tenant: TenantId(args[2].clone()),
            credential,
            limits: ClientLimits {
                maximum_calls: 4,
                maximum_request_bytes: MAXIMUM,
                maximum_response_bytes: MAXIMUM,
                rpc_timeout: Duration::from_secs(5),
                ..Default::default()
            },
        })?;
        let deadline = Instant::now() + Duration::from_secs(120);
        let mut used = HashSet::new();
        let result: Result<()> = async {
            println!("ready");
            for line in std::io::stdin().lock().lines() {
                let line = line?;
                if line == "close" {
                    break;
                }
                let values: Vec<_> = line.split(' ').collect();
                if line.len() > 192
                    || values.len() != 4
                    || values[1].is_empty()
                    || values[1].len() > 64
                    || !values[1].bytes().all(|value| {
                        value.is_ascii_alphanumeric() || value == b'-' || value == b'_'
                    })
                    || used.len() >= 32
                    || !used.insert(values[1].to_owned())
                {
                    return Err("fixture-command".into());
                }
                let timeout: u64 = values[2].parse()?;
                let cancel: i64 = values[3].parse()?;
                if !(1..=5000).contains(&timeout)
                    || !(-1..=5000).contains(&cancel)
                    || Instant::now() >= deadline
                {
                    return Err("fixture-deadline".into());
                }
                let remaining = deadline
                    .saturating_duration_since(Instant::now())
                    .as_millis();
                let options = tx::CallOptions {
                    timeout_millis: Some(timeout.min(u64::try_from(remaining)?)),
                };
                let bytes = latent_protected_files::read(
                    &directory.join(format!("{}.request.pb", values[1])),
                    MAXIMUM,
                    ProtectedFilePolicy::Integrity,
                    "transaction.fixture.request",
                )
                .map_err(|_| "fixture-request-file")?;
                let cancel =
                    (cancel >= 0).then(|| Instant::now() + Duration::from_millis(cancel as u64));
                let value = dispatch(
                    &client, values[0], &bytes, options, cancel, &directory, values[1],
                )
                .await?;
                write(
                    &directory.join(format!("{}.result.json", values[1])),
                    &serde_json::to_vec(&value)?,
                )?;
                println!("done {}", values[1]);
            }
            Ok(())
        }
        .await;
        let shutdown = client
            .shutdown(Instant::now() + Duration::from_secs(5))
            .await;
        let usage = client.usage();
        let clean = shutdown.is_ok()
            && usage.closed
            && usage.active_calls == 0
            && usage.executor_tasks == 0
            && usage.sockets == 0
            && usage.reserved_message_bytes == 0;
        write(
            &directory.join("cleanup.json"),
            &serde_json::to_vec(
                &json!({"schemaVersion":"latent.sdk.transaction.node.cleanup.v1",
        "clean":clean,"activeCalls":usage.active_calls,"executorTasks":usage.executor_tasks,"sockets":usage.sockets,
        "reservedMessageBytes":usage.reserved_message_bytes}),
            )?,
        )?;
        if !clean {
            return Err("fixture-client-cleanup".into());
        }
        result
    }

    #[tokio::main(flavor = "current_thread")]
    pub async fn main() {
        if run().await.is_err() {
            eprintln!("transaction-node-workflow-failed");
            std::process::exit(1);
        }
    }
}

#[cfg(target_os = "linux")]
fn main() {
    fixture::main();
}

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("transaction-node-workflow-requires-linux");
    std::process::exit(1);
}
