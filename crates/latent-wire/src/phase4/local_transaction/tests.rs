//! Real compiled aggregate executions through the authenticated production RPC,
//! native admission/commit, manager and Wasmtime backend. Trusted-local source
//! publication is explicit; these cases do not qualify publisher signatures.
mod backend;
mod fixture;
mod policy;
mod publication;
mod recovery;
mod requests;

use super::*;
use crate::phase4::{Phase4Call, Phase4Runtime};
use fixture::Fixture;
use latent_rpc::transaction::v1::transaction_service_server::TransactionService;
use latent_rpc::{invocation::v1 as i, transaction::v1 as t};
use latent_state::embedded::Family;
use requests::*;
use std::{
    sync::atomic::Ordering,
    time::{Duration, Instant},
};

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_duplicate_conflict_and_dropped_waiter_have_one_execution_commit_and_effect() {
    let f = Fixture::new(true).await;
    let adapter = f.adapter();
    let owner = tokio::spawn(async move {
        adapter
            .invoke_command(context("alice").request(command("same", 1, false)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    // These counters are incremented by the compiled guest's acquire-command
    // host import. The real guest Store is live at its first actual state read.
    assert_eq!(f.executions(), 1);
    assert_eq!(f.backend.real.resource_snapshot().stores_created, 1);
    assert_eq!(f.rows(Family::Command).await, 1);
    assert_eq!(f.rows(Family::Result).await, 0);
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    f.drop_duplicate_during_native_lookup().await;
    let duplicate_adapter = f.adapter();
    let conflict_adapter = f.adapter();
    let (duplicate, conflict) = tokio::join!(
        duplicate_adapter.invoke_command(context("alice").request(command("same", 1, false))),
        conflict_adapter.invoke_command(context("alice").request(command("same", 2, false))),
    );
    let duplicate = duplicate.unwrap().into_inner();
    assert_eq!(
        duplicate.command.as_ref().unwrap().outcome,
        t::CommandOutcome::InProgress as i32
    );
    assert!(duplicate.replayed);
    assert_eq!(
        duplicate
            .invocation
            .as_ref()
            .unwrap()
            .consumption
            .as_ref()
            .unwrap()
            .cpu_fuel,
        0
    );
    assert_eq!(conflict.unwrap_err().code(), tonic::Code::Aborted);
    drop(duplicate); // one lost duplicate reply cannot cancel the shared owner
    assert_eq!(f.quotas.usage().unwrap().active_activations, 1);
    assert_eq!(f.executions(), 1);
    f.backend.imports.release.notify_one();
    let original = tokio::time::timeout(Duration::from_secs(5), owner)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    let body = success(&original);
    assert!(
        original
            .invocation
            .as_ref()
            .unwrap()
            .consumption
            .as_ref()
            .unwrap()
            .cpu_fuel
            > 0
    );
    assert_eq!(aggregate(&body.payload), 1);
    assert_eq!(body.effect_ids.len(), 1);
    assert_eq!(f.rows(Family::State).await, 1);
    assert_eq!(f.rows(Family::Result).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    assert_eq!(f.rows(Family::Attempt).await, 1);
    let receipt = original.command.as_ref().unwrap().commit.clone().unwrap();
    assert_eq!(receipt.effect_ids, body.effect_ids);
    drop(original); // lost terminal RPC response after the durable commit
    let replay = invoke(&f, "same", 1, false).await;
    assert!(replay.replayed);
    assert_eq!(
        replay.command.as_ref().unwrap().commit.as_ref(),
        Some(&receipt)
    );
    assert_eq!(success(&replay), body);
    drop(replay);
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_retained_rejection_survives_later_business_mutation_and_owner_restart() {
    let mut f = Fixture::new(false).await;
    let rejected = invoke(&f, "rejected", 5, true).await;
    let Some(i::invoke_response::Result::DeclaredError(body)) =
        rejected.invocation.as_ref().unwrap().result.as_ref()
    else {
        panic!("expected admitted business rejection: {rejected:?}")
    };
    let body = body.clone();
    assert_eq!(
        rejected.command.as_ref().unwrap().outcome,
        t::CommandOutcome::Rejected as i32
    );
    assert!(rejected.command.as_ref().unwrap().metadata_durable);
    assert!(
        !rejected
            .command
            .as_ref()
            .unwrap()
            .application_state_committed
    );
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    drop(rejected);
    let later = invoke(&f, "new-evaluation", 2, false).await;
    assert_eq!(aggregate(&success(&later).payload), 2);
    assert_eq!(f.executions(), 2);
    drop(later);
    f.restart().await; // stop/drain, reopen the actual persisted protected store
    let replay = invoke(&f, "rejected", 5, true).await;
    assert!(replay.replayed);
    assert_eq!(
        replay.invocation.as_ref().unwrap().result,
        Some(i::invoke_response::Result::DeclaredError(body))
    );
    assert_eq!(
        f.executions(),
        2,
        "historical rejection never calls the original mutation body"
    );
    assert_eq!(f.rows(Family::State).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    assert_eq!(f.rows(Family::Result).await, 2);
    drop(replay);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_replay_rechecks_tenant_subject_token_rotation_and_revoked_permission() {
    let f = Fixture::new(false).await;
    let original = invoke(&f, "authorized", 1, false).await;
    let original = success(&original);
    let mut rotated = principal("alice");
    rotated
        .claims
        .insert("credential-epoch".into(), "rotated".into());
    let replay = f
        .adapter()
        .invoke_command(context_for(rotated).request(command("authorized", 1, false)))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(success(&replay), original);
    drop(replay);
    let mut foreign = principal("alice");
    foreign.tenant = Some(latent_core::TenantId("foreign".into()));
    assert_eq!(
        f.adapter()
            .invoke_command(context_for(foreign).request(command("authorized", 1, false)))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::PermissionDenied
    );
    assert_eq!(
        f.adapter()
            .invoke_command(context("bob").request(command("authorized", 1, false)))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::PermissionDenied
    );
    policy::revoke(&f.policy);
    assert_eq!(
        f.adapter()
            .invoke_command(context("alice").request(command("authorized", 1, false)))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::PermissionDenied
    );
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Command).await, 1);
    assert_eq!(f.rows(Family::Result).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    f.shutdown().await;
}
