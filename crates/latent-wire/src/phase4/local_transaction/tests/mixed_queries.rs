//! Bounded command/query traffic through one authored native fixture.
use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn mixed_queries_keep_fresh_views_without_growing_durable_history() {
    const SAMPLES: u64 = 24;
    let fixture = Fixture::with_concurrent_commands(true).await;
    let writer = fixture.adapter();
    let pending = tokio::spawn(async move {
        writer
            .invoke_command(context("alice").request(command("first-write", 1, false)))
            .await
    });
    tokio::time::timeout(
        Duration::from_secs(5),
        fixture.backend.imports.entered.notified(),
    )
    .await
    .unwrap();
    let (before, _) = query(&fixture, None).await;
    assert_eq!(
        before, 0,
        "an in-flight write must leave the original view readable"
    );
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    fixture.backend.imports.release.notify_one();
    let first = tokio::time::timeout(Duration::from_secs(5), pending)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    assert_eq!(aggregate(&success(&first).payload), 1);

    let mut commit_nanos = Vec::new();
    let mut query_nanos = Vec::new();
    let mut replay_nanos = Vec::new();
    for sample in 1..=SAMPLES {
        let key = format!("mixed-{sample}");
        let started = Instant::now();
        let commit = invoke(&fixture, &key, 1, false).await;
        commit_nanos.push(started.elapsed().as_nanos());
        assert_eq!(aggregate(&success(&commit).payload), sample + 1);
        let receipt = commit.command.as_ref().unwrap().commit.as_ref().unwrap();
        let started = Instant::now();
        let (observed, view) = query(&fixture, Some(receipt.committed_version.clone())).await;
        query_nanos.push(started.elapsed().as_nanos());
        assert_eq!(observed, sample + 1);
        assert!(!view.is_empty());
        let started = Instant::now();
        let replay = invoke(&fixture, &key, 1, false).await;
        replay_nanos.push(started.elapsed().as_nanos());
        assert!(replay.replayed);
        assert_eq!(
            replay.command.as_ref().unwrap().commit.as_ref(),
            Some(receipt)
        );
    }
    let committed = usize::try_from(SAMPLES + 1).unwrap();
    assert_eq!(fixture.rows(Family::Command).await, committed);
    assert_eq!(fixture.rows(Family::Result).await, committed);
    assert_eq!(fixture.rows(Family::Outbox).await, committed);
    assert_eq!(fixture.rows(Family::Inbox).await, 0);
    assert_eq!(fixture.rows(Family::State).await, 1);
    assert_eq!(fixture.executions(), SAMPLES + 1);
    fixture.shutdown().await;
    println!(
        "{}",
        serde_json::json!({
            "schemaVersion": "latent.mixed-transaction-sample.v1",
            "profile": "rust-trusted-local-native",
            "samplesPerOperation": SAMPLES,
            "commandNanos": percentiles(&mut commit_nanos),
            "queryNanos": percentiles(&mut query_nanos),
            "replayNanos": percentiles(&mut replay_nanos),
            "durableCommands": committed,
            "pendingEffects": committed,
        })
    );
}

async fn query(fixture: &Fixture, minimum_view_version: Option<Vec<u8>>) -> (u64, Vec<u8>) {
    let request = t::QueryRequest {
        profile: Some(latent_rpc::phase4::current_profile()),
        invocation: Some(invocation("query", b"[]".to_vec(), true)),
        namespace: Some(selector()),
        entity: None,
        minimum_view_version,
    };
    let response = tokio::time::timeout(
        Duration::from_secs(5),
        fixture.adapter().query(context("alice").request(request)),
    )
    .await
    .unwrap()
    .unwrap()
    .into_inner();
    let result = response.invocation.unwrap().result.unwrap();
    let i::invoke_response::Result::Success(body) = result else {
        panic!("expected a read-only aggregate, got {result:?}");
    };
    assert!(body.effect_ids.is_empty());
    (aggregate(&body.payload), response.view.unwrap().version)
}

fn percentiles(samples: &mut [u128]) -> serde_json::Value {
    samples.sort_unstable();
    serde_json::json!({
        "p50": samples[(samples.len() * 50).div_ceil(100) - 1].to_string(),
        "p99": samples[(samples.len() * 99).div_ceil(100) - 1].to_string(),
    })
}
