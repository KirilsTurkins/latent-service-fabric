//! Finite real RPC checks against an already signed, installed aggregate.
//! This owns no namespace, policy grant, publication or compiler. Failure is
//! retained by the enclosing campaign; no uncertain mutation is retried.
use clap::Parser;
use latent_wire::{
    invocation::proto as i,
    management::proto as c,
    phase4::{contract, transaction as t},
};
use std::{net::SocketAddr, path::PathBuf, time::Duration};
use t::transaction_service_client::TransactionServiceClient;
use tonic::{transport::Endpoint, Request};

#[path = "transaction_rpc_probe/observation.rs"]
mod observation;
use observation::{aggregate, check_command, input, precondition, same_original};

#[derive(Parser)]
struct Arguments {
    #[arg(long)]
    endpoint: SocketAddr,
    #[arg(long)]
    credential_file: PathBuf,
    #[arg(long)]
    foreign_credential_file: PathBuf,
    #[arg(long)]
    operator_credential_file: PathBuf,
    #[arg(long)]
    component_digest: String,
    #[arg(long)]
    publication: String,
    #[arg(long)]
    client_key: String,
}

const TENANT: &str = "examples";
const SERVICE: &str = "examples/transaction-java-aggregate";
const CONTRACT: &str = "examples:transactional-aggregate/api@1.0.0";
const ROUTE: &str = "transaction-java-aggregate";
const MEDIA: &str = "application/vnd.latent.wit-values.v1+json";
const DEADLINE: Duration = Duration::from_mins(2);

fn credential(path: &std::path::Path) -> String {
    let bytes = latent_protected_files::read(
        path,
        512,
        latent_protected_files::ProtectedFilePolicy::Secret,
        "transactionRpcProbeCredential",
    )
    .expect("protected actual transport credential");
    let value = std::str::from_utf8(&bytes).expect("credential encoding");
    assert!(!value.is_empty() && !value.chars().any(char::is_control));
    value.to_owned()
}
fn request<T>(token: Option<&str>, message: T) -> Request<T> {
    let mut request = Request::new(message);
    request.set_timeout(DEADLINE);
    if let Some(token) = token {
        request
            .metadata_mut()
            .insert("authorization", format!("Bearer {token}").parse().unwrap());
    }
    request
}
fn namespace() -> t::NamespaceSelector {
    t::NamespaceSelector {
        tenant: TENANT.into(),
        namespace: "transactional-aggregate".into(),
        incarnation: "1".into(),
    }
}
fn invocation(function: &str, payload: Vec<u8>, query: bool) -> i::InvokeRequest {
    i::InvokeRequest {
        target: Some(i::InvocationTarget {
            tenant: TENANT.into(),
            service: SERVICE.into(),
            contract: CONTRACT.into(),
            function: function.into(),
            route: Some(ROUTE.into()),
        }),
        payload,
        media_type: MEDIA.into(),
        budget: Some(i::ResourceBudget {
            cpu_fuel: 1_000_000_000,
            memory_bytes: 67_108_864,
            wall_time_limit_millis: Some(120_000),
            state_read_bytes: 4_194_304,
            state_write_bytes: if query { 0 } else { 2_097_152 },
            effect_count: u32::from(!query),
            ..Default::default()
        }),
        ..Default::default()
    }
}
fn query(minimum: Option<Vec<u8>>) -> t::QueryRequest {
    t::QueryRequest {
        profile: Some(contract::current_profile()),
        namespace: Some(namespace()),
        invocation: Some(invocation("query", b"[]".to_vec(), true)),
        entity: None,
        minimum_view_version: minimum,
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args = Arguments::parse();
    assert!(args.endpoint.ip().is_loopback() && args.endpoint.port() != 0);
    assert!(args.component_digest.starts_with("sha256:") && args.component_digest.len() == 71);
    args.publication
        .parse::<latent_core::PublicationId>()
        .unwrap();
    let token = credential(&args.credential_file);
    let foreign = credential(&args.foreign_credential_file);
    let operator = credential(&args.operator_credential_file);
    let channel = Endpoint::from_shared(format!("http://{}", args.endpoint))
        .unwrap()
        .connect_timeout(Duration::from_secs(2))
        .timeout(DEADLINE)
        .connect()
        .await
        .unwrap();
    let mut states = c::state_service_client::StateServiceClient::new(channel.clone());
    let mut client = TransactionServiceClient::new(channel)
        .max_encoding_message_size(1_048_576)
        .max_decoding_message_size(1_048_576);
    assert_eq!(command_count(&mut states, &operator, &args).await, 0);
    let initial = initial_query(&mut client, &token, &foreign, &args).await;
    assert_eq!(command_count(&mut states, &operator, &args).await, 0);
    let record =
        command_and_replay(&mut client, &token, &foreign, &args, initial.key_version).await;
    let acknowledged = record.commit.as_ref().unwrap().committed_version.clone();
    let observed = final_query(&mut client, &token, acknowledged).await;
    assert_eq!(command_count(&mut states, &operator, &args).await, 1);
    println!(
        "{}",
        serde_json::json!({"schemaVersion":"latent.transaction-rpc-probe.v1", "passed":true,
        "cases":12, "ordinaryQueries":2, "explicitCommandRequests":2, "unauthorizedRefusals":5, "resultLookups":2, "wrongOriginalAssociationRefusals":2, "automaticRetries":0,
        "commandId":record.command_id, "attemptId":record.attempt_id, "clientKey":args.client_key,
        "componentDigest":args.component_digest, "publication":args.publication,
        "finalAggregate":observed.count, "compilerExecuted":false, "authorityInstalledByProbe":false,
        "finalCommandCount":1,
        "completeCI":false, "packagedDistributionQualified":false})
    );
}

async fn command_count(
    client: &mut c::state_service_client::StateServiceClient<tonic::transport::Channel>,
    operator: &str,
    args: &Arguments,
) -> u64 {
    let input = c::InspectNamespaceRequest {
        profile: Some(contract::current_profile()),
        namespace: Some(namespace()),
        authorization_publication: Some(c::PublicationRef {
            tenant: TENANT.into(),
            id: args.publication.clone(),
        }),
    };
    let expected = contract::Request::from(input.clone());
    let response = client
        .inspect_namespace(request(Some(operator), input))
        .await
        .unwrap()
        .into_inner();
    contract::Response::from(response.clone())
        .validate_for(&expected)
        .unwrap();
    response.namespace.unwrap().command_count
}

async fn initial_query(
    client: &mut TransactionServiceClient<tonic::transport::Channel>,
    token: &str,
    foreign: &str,
    args: &Arguments,
) -> observation::Aggregate {
    let before_request = query(None);
    let before_contract = contract::Request::from(before_request.clone());
    before_contract.validate().unwrap();
    for (credential, expected) in [
        (None, tonic::Code::Unauthenticated),
        (Some(foreign), tonic::Code::PermissionDenied),
    ] {
        let error = client
            .query(request(credential, before_request.clone()))
            .await
            .unwrap_err();
        assert_eq!(
            error.code(),
            expected,
            "private listener refusal precedes the application"
        );
    }
    let before = client
        .query(request(Some(token), before_request))
        .await
        .unwrap()
        .into_inner();
    contract::Response::from(before.clone())
        .validate_for(&before_contract)
        .unwrap();
    let initial = aggregate(before.invocation.as_ref().unwrap());
    assert_eq!(
        initial.count, 0,
        "requires an actual fresh disposable namespace"
    );
    assert!(initial.key_version.is_none());
    assert_eq!(before.view.as_ref().unwrap().version, initial.view_version);
    assert_eq!(
        before.source.as_ref().unwrap().component_digest,
        args.component_digest
    );
    assert_eq!(
        before.source.as_ref().unwrap().publication_id,
        args.publication
    );
    initial
}

async fn command_and_replay(
    client: &mut TransactionServiceClient<tonic::transport::Channel>,
    token: &str,
    foreign: &str,
    args: &Arguments,
    version: Option<Vec<u8>>,
) -> t::CommandInspection {
    let original = t::CommandSelector {
        namespace: Some(namespace()),
        operation: "update".into(),
        client_key: args.client_key.clone(),
        entity: None,
        shared_recovery_scope: None,
    };
    let command = t::InvokeCommandRequest {
        profile: Some(contract::current_profile()),
        invocation: Some(invocation("update", input(1, false), false)),
        command: Some(original),
        input_format: "lsf-wit-values-v1".into(),
        expected_versions: vec![precondition(version)],
        retry_attempt: None,
    };
    let command_contract = contract::Request::from(command.clone());
    command_contract.validate().unwrap();
    for (credential, expected) in [
        (None, tonic::Code::Unauthenticated),
        (Some(foreign), tonic::Code::PermissionDenied),
    ] {
        let error = client
            .invoke_command(request(credential, command.clone()))
            .await
            .unwrap_err();
        assert_eq!(
            error.code(),
            expected,
            "unauthorized commands cannot create an original result"
        );
    }
    let first = client
        .invoke_command(request(Some(token), command.clone()))
        .await
        .unwrap()
        .into_inner();
    contract::Response::from(first.clone())
        .validate_for(&command_contract)
        .unwrap();
    assert!(!first.replayed);
    let record = check_command(&first, &args.publication, &args.component_digest);
    assert_eq!(aggregate(first.invocation.as_ref().unwrap()).count, 1);
    let replay = client
        .invoke_command(request(Some(token), command))
        .await
        .unwrap()
        .into_inner();
    contract::Response::from(replay.clone())
        .validate_for(&command_contract)
        .unwrap();
    assert!(
        replay.replayed,
        "the server reports original durable result recovery"
    );
    same_original(record, replay.command.as_ref().unwrap());
    assert_eq!(aggregate(replay.invocation.as_ref().unwrap()).count, 1);
    lookup_original(client, token, foreign, record).await;
    record.clone()
}

async fn final_query(
    client: &mut TransactionServiceClient<tonic::transport::Channel>,
    token: &str,
    acknowledged: Vec<u8>,
) -> observation::Aggregate {
    let final_request = query(Some(acknowledged));
    let final_contract = contract::Request::from(final_request.clone());
    let after = client
        .query(request(Some(token), final_request))
        .await
        .unwrap()
        .into_inner();
    contract::Response::from(after.clone())
        .validate_for(&final_contract)
        .unwrap();
    let observed = aggregate(after.invocation.as_ref().unwrap());
    assert_eq!(
        observed.count, 1,
        "duplicate replay cannot run the business mutation twice"
    );
    assert_eq!(after.view.as_ref().unwrap().version, observed.view_version);
    assert!(after.invocation.as_ref().unwrap().result.as_ref().is_some_and(|value|
        matches!(value, i::invoke_response::Result::Success(success) if success.effect_ids.is_empty())));
    observed
}

async fn lookup_original(
    client: &mut TransactionServiceClient<tonic::transport::Channel>,
    token: &str,
    foreign: &str,
    original: &t::CommandInspection,
) {
    let key = original.key.as_ref().unwrap();
    let command = t::CommandSelector {
        namespace: key.namespace.clone(),
        operation: key.operation.clone(),
        entity: key.entity.clone(),
        client_key: key.client_key.clone(),
        shared_recovery_scope: None,
    };
    let publication = c::PublicationRef {
        tenant: key.namespace.as_ref().unwrap().tenant.clone(),
        id: original.source.as_ref().unwrap().publication_id.clone(),
    };
    let lookup = t::LookupCommandRequest {
        profile: Some(contract::current_profile()),
        command: Some(command.clone()),
        attempt_id: Some(original.attempt_id.clone()),
        authorization_publication: Some(publication.clone()),
    };
    let response = client
        .lookup_command(request(Some(token), lookup.clone()))
        .await
        .unwrap()
        .into_inner();
    contract::Response::from(response.clone())
        .validate_for(&contract::Request::from(lookup.clone()))
        .unwrap();
    same_original(original, response.command.as_ref().unwrap());
    let foreign_error = client
        .lookup_command(request(Some(foreign), lookup.clone()))
        .await
        .unwrap_err();
    assert_eq!(foreign_error.code(), tonic::Code::PermissionDenied);
    let mut wrong_attempt = lookup;
    wrong_attempt.attempt_id = Some(format!("command-attempt:sha256:{}", "f".repeat(64)));
    assert!(client
        .lookup_command(request(Some(token), wrong_attempt))
        .await
        .is_err());
    let commit = t::LookupCommitRequest {
        profile: Some(contract::current_profile()),
        command: Some(command),
        receipt_id: original.commit.as_ref().unwrap().receipt_id.clone(),
        authorization_publication: Some(publication),
    };
    let response = client
        .lookup_commit(request(Some(token), commit.clone()))
        .await
        .unwrap()
        .into_inner();
    contract::Response::from(response.clone())
        .validate_for(&contract::Request::from(commit.clone()))
        .unwrap();
    same_original(original, response.command.as_ref().unwrap());
    let mut wrong_commit = commit;
    wrong_commit.receipt_id = format!("command-disposition:sha256:{}", "f".repeat(64));
    assert!(client
        .lookup_commit(request(Some(token), wrong_commit))
        .await
        .is_err());
}
