//! Explicit caller-scope refusal on a separately provisioned node.
#![cfg(feature = "transport")]
use latent_core::TenantId;
use latent_sdk::{
    management::{CallOptions, PublicationRef},
    network::{ClientConfig, ClientLimits, RpcClient},
    transaction::{
        self, CommandSelector, LookupCommandRequest, NamespaceSelector, TransactionClient,
    },
};
use std::{env, time::Duration};
use tokio::time::Instant;
fn required(name: &str) -> String {
    env::var(name).unwrap_or_else(|_| panic!("missing fixture field {name}"))
}
#[tokio::test]
#[ignore = "requires an original command and a different authenticated caller"]
async fn foreign_caller_cannot_recover_original() {
    let tenant = required("LSF_401_TENANT");
    let client = RpcClient::new(ClientConfig {
        endpoint: required("LSF_401_ENDPOINT").parse().expect("endpoint"),
        tenant: TenantId(tenant.clone()),
        credential: required("LSF_401_SCOPE_TOKEN").into(),
        limits: ClientLimits::default(),
    })
    .expect("client");
    let request = LookupCommandRequest {
        profile: Some(transaction::current_profile()),
        command: Some(CommandSelector {
            namespace: Some(NamespaceSelector {
                tenant: tenant.clone(),
                namespace: required("LSF_401_NAMESPACE"),
                incarnation: required("LSF_401_INCARNATION"),
            }),
            operation: "update".into(),
            entity: None,
            client_key: required("LSF_401_COMMAND_KEY"),
            shared_recovery_scope: None,
        }),
        attempt_id: None,
        authorization_publication: Some(PublicationRef {
            tenant,
            id: required("LSF_401_PUBLICATION"),
        }),
    };
    let failure = client
        .lookup_command(request, CallOptions::default())
        .await
        .expect_err("foreign caller must not recover");
    assert_eq!(failure.transport.grpc_status, Some(7));
    assert!(failure.observed.is_none());
    assert!(client
        .shutdown(Instant::now() + Duration::from_secs(5))
        .await
        .is_ok());
    let usage = client.usage();
    assert_eq!(
        (
            usage.active_calls,
            usage.reserved_message_bytes,
            usage.sockets,
            usage.executor_tasks
        ),
        (0, 0, 0, 0)
    );
    println!("SCOPE_REFUSED grpc=7");
}
