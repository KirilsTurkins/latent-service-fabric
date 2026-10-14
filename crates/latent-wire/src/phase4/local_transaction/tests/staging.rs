use super::*;
use crate::management::proto;
use latent_core::TenantId;
use latent_rpc::control::v1::node_service_server::NodeService;

fn inspection_request(
    identity: &str,
    administrator: bool,
) -> tonic::Request<proto::InspectActivationTreeRequest> {
    let mut caller = principal("alice");
    if administrator {
        caller.kind = latent_core::PrincipalKind::Administrator;
    }
    context_for(caller).request(proto::InspectActivationTreeRequest {
        activation_id: identity.into(),
        page: Some(proto::PageRequest {
            page_size: 8,
            page_token: None,
        }),
        ..Default::default()
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_post_insertion_staging_reaches_original_manager_and_privileged_wire() {
    let f = Fixture::new(false).await;
    f.backend
        .imports
        .pause_after_stage
        .store(true, Ordering::SeqCst);
    let adapter = f.adapter();
    let owner = tokio::spawn(async move {
        adapter
            .invoke_command(context("alice").request(command("original-staging", 1, false)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.staged.notified())
        .await
        .unwrap();
    assert_eq!(f.backend.imports.staged_intents.load(Ordering::SeqCst), 1);
    let roots = f
        .manager
        .journal()
        .inspect_roots(
            &TenantId(publication::TENANT.into()),
            &latent_core::ServiceId(publication::SERVICE.into()),
            None,
            8,
            None,
        )
        .unwrap();
    assert_eq!(roots.nodes.len(), 1);
    let identity = roots.nodes[0].activation_id.0.clone();
    let inspection = f.inspection_adapter();
    let denied = inspection
        .inspect_activation_tree(inspection_request(&identity, false))
        .await
        .unwrap_err();
    let live = inspection
        .inspect_activation_tree(inspection_request(&identity, true))
        .await
        .unwrap()
        .into_inner();
    let witness = live.nodes[0].transaction_staging.clone();
    f.backend.imports.continue_after_stage.notify_one();
    let result = tokio::time::timeout(Duration::from_secs(5), owner)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    let terminal = inspection
        .inspect_activation_tree(inspection_request(&identity, true))
        .await
        .unwrap()
        .into_inner();
    let command = result.command.as_ref().unwrap();
    let expected_command = command.command_id.clone();
    let expected_attempt = command.attempt_id.clone();
    let expected_transaction = command.commit.as_ref().unwrap().transaction_id.clone();
    let expected_publication = command.source.as_ref().unwrap().publication_id.clone();
    drop((result, inspection));
    f.shutdown().await;
    let witness = witness.expect("actual original host post-insertion witness missing");
    assert_eq!(denied.code(), tonic::Code::PermissionDenied);
    assert_eq!(witness.schema_version, 1);
    assert!(witness.activation_serial > 0);
    assert_eq!(witness.command_id, expected_command);
    assert_eq!(witness.attempt_id, expected_attempt);
    assert_eq!(witness.transaction_id, expected_transaction);
    assert_eq!(witness.publication_id, expected_publication);
    assert_eq!((witness.staged_mutations, witness.captured_intents), (1, 1));
    assert!(witness.state_write_bytes > 16_384);
    assert_eq!(
        terminal.nodes[0].transaction_staging.as_ref(),
        Some(&witness)
    );
    assert_eq!(live.nodes[0].phase, "running");
    assert!(live.nodes[0].terminal_state.is_none());
    assert_eq!(
        terminal.nodes[0].terminal_state.as_deref(),
        Some("completed")
    );
}
