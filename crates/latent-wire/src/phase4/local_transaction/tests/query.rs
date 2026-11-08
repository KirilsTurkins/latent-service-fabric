//! Fresh queries through the real compiled guest and production RPC owners.
use super::*;

fn request(minimum: Option<Vec<u8>>) -> t::QueryRequest {
    t::QueryRequest {
        profile: Some(latent_rpc::phase4::current_profile()),
        invocation: Some(invocation("query", b"[]".to_vec(), true)),
        namespace: Some(selector()),
        entity: None,
        minimum_view_version: minimum,
    }
}

async fn query(f: &Fixture, minimum: Option<Vec<u8>>) -> t::QueryResponse {
    tokio::time::timeout(
        Duration::from_secs(10),
        f.adapter()
            .query(context("alice").request(request(minimum))),
    )
    .await
    .unwrap()
    .unwrap()
    .into_inner()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_query_denies_other_caller_and_tenant_before_guest_execution() {
    let f = Fixture::new(false).await;
    let denied = f
        .adapter()
        .query(context("bob").request(request(None)))
        .await
        .unwrap_err();
    assert_eq!(denied.code(), tonic::Code::PermissionDenied);
    let mut foreign = principal("alice");
    foreign.tenant = Some(latent_core::TenantId("foreign".into()));
    let denied = f
        .adapter()
        .query(context_for(foreign).request(request(None)))
        .await
        .unwrap_err();
    assert_eq!(denied.code(), tonic::Code::PermissionDenied);
    assert_eq!(f.backend.imports.queries.load(Ordering::SeqCst), 0);
    assert_eq!(f.rows(Family::Command).await, 0);
    let authorized = query(&f, None).await;
    assert_eq!(value(&authorized), 0);
    let mut foreign_view = authorized.view.as_ref().unwrap().version.clone();
    foreign_view[3] ^= 1; // The original scope digest is part of this view token.
    let mut future_view = authorized.view.as_ref().unwrap().version.clone();
    // The last three u64 fields are generation, schema epoch and recovery epoch.
    let offset = future_view.len() - 24;
    let generation = u64::from_le_bytes(future_view[offset..offset + 8].try_into().unwrap());
    future_view[offset..offset + 8]
        .copy_from_slice(&generation.checked_add(1).unwrap().to_le_bytes());
    drop(authorized);
    assert!(f
        .adapter()
        .query(context("alice").request(request(Some(foreign_view))))
        .await
        .is_err());
    let future = f
        .adapter()
        .query(context("alice").request(request(Some(future_view))))
        .await
        .unwrap_err();
    assert_eq!(future.code(), tonic::Code::Aborted);
    assert_eq!(f.backend.imports.queries.load(Ordering::SeqCst), 1);
    assert_eq!(f.rows(Family::Command).await, 0);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_cannot_acquire_command_under_a_query_binding() {
    let f = Fixture::with_query_update_mismatch().await;
    let mut selected = request(None);
    selected.invocation = Some(invocation(
        "update",
        serde_json::to_vec(&serde_json::json!([{"delta": 1, "reject": false}])).unwrap(),
        true,
    ));
    let result = f.adapter().query(context("alice").request(selected)).await;
    if let Ok(response) = result {
        assert!(matches!(
            response.into_inner().invocation.unwrap().result,
            Some(i::invoke_response::Result::PlatformFailure(_))
        ));
    }
    assert_eq!(
        f.backend
            .imports
            .wrong_mode_command_acquisitions
            .load(Ordering::SeqCst),
        1
    );
    assert_eq!(f.executions(), 0);
    for family in [
        Family::Command,
        Family::Attempt,
        Family::Result,
        Family::Outbox,
        Family::State,
    ] {
        assert_eq!(f.rows(family).await, 0);
    }
    f.shutdown_after_wrong_mode().await;
}

fn value(response: &t::QueryResponse) -> u64 {
    let Some(i::invoke_response::Result::Success(body)) =
        response.invocation.as_ref().unwrap().result.as_ref()
    else {
        panic!("fresh guest query must succeed: {response:?}")
    };
    assert!(body.effect_ids.is_empty());
    assert!(body.committed_state_version.is_none());
    aggregate(&body.payload)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_queries_after_commit_and_restart_keep_fresh_view_without_command_rows() {
    let mut f = Fixture::new(false).await;
    let original = invoke(&f, "query-freshness", 1, false).await;
    let committed = success(&original);
    assert_eq!(aggregate(&committed.payload), 1);
    let token = committed.committed_state_version.as_deref().unwrap();
    assert_eq!(
        token.len(),
        latent_state::session::version::VIEW_TOKEN_BYTES * 2
    );
    let minimum = token
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap())
        .collect::<Vec<_>>();
    drop(original);
    let first = query(&f, Some(minimum.clone())).await;
    assert_eq!(value(&first), 1);
    assert!(!first.view.as_ref().unwrap().version.is_empty());
    drop(first);
    let families = [
        Family::Command,
        Family::Attempt,
        Family::Result,
        Family::Outbox,
    ];
    let mut before = Vec::new();
    for family in families {
        before.push(f.rows(family).await);
    }
    for _ in 0..3 {
        assert_eq!(value(&query(&f, Some(minimum.clone())).await), 1);
    }
    for (index, family) in families.into_iter().enumerate() {
        assert_eq!(f.rows(family).await, before[index]);
    }
    assert_eq!(f.executions(), 1);
    f.restart().await;
    for _ in 0..3 {
        assert_eq!(value(&query(&f, Some(minimum.clone())).await), 1);
    }
    for (index, family) in families.into_iter().enumerate() {
        assert_eq!(f.rows(family).await, before[index]);
    }
    assert_eq!(f.executions(), 1);
    f.shutdown().await;
}
