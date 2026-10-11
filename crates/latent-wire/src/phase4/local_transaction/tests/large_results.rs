//! Actual boundary-sized authored output, with real state and intent staging.
use super::*;
use latent_core::transaction_contract::VALUE_BYTES;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust result-boundary transaction variant"]
async fn actual_guest_exact_maximum_result_body_commits_once_and_replays_exactly() {
    let f = Fixture::with_large_result_guest().await;
    let size = u32::try_from(VALUE_BYTES).unwrap();
    let original = invoke(&f, "maximum-body", size, false).await;
    let body = success(&original);
    assert_eq!(body.payload.len(), VALUE_BYTES);
    assert_eq!(
        f.backend.imports.returned_bytes.load(Ordering::SeqCst),
        VALUE_BYTES as u64
    );
    let value: serde_json::Value = serde_json::from_slice(&body.payload).unwrap();
    let parts = value[0].as_array().unwrap();
    assert_eq!(parts.len(), 4);
    assert_eq!(
        parts
            .iter()
            .map(|part| part.as_str().unwrap().len())
            .sum::<usize>(),
        VALUE_BYTES - 15
    );
    for part in parts {
        let part = part.as_str().unwrap();
        assert!(part.len() <= 256 * 1024);
        assert!(part.bytes().all(|byte| byte == b'a'));
    }
    let receipt = original.command.as_ref().unwrap().commit.clone().unwrap();
    assert_eq!(receipt.effect_ids.len(), 1);
    assert_eq!(receipt.effect_ids, body.effect_ids);
    assert_eq!(f.executions(), 1);
    assert_eq!(f.backend.real.resource_snapshot().stores_created, 1);
    assert_eq!(f.rows(Family::State).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    assert_eq!(large_result_counts(&f).await, (1, 0));
    drop(original);
    let replay = invoke(&f, "maximum-body", size, false).await;
    assert!(replay.replayed);
    assert_eq!(success(&replay), body);
    assert_eq!(
        replay.command.as_ref().unwrap().commit.as_ref(),
        Some(&receipt)
    );
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Attempt).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    drop(replay);
    f.shutdown().await;
}

async fn large_result_counts(f: &Fixture) -> (usize, usize) {
    // This new diagnostic envelope fits the actual maximum body and its closed
    // record metadata. Original runtime, guest and parent-case budgets stay fixed.
    f.store
        .with_store(
            latent_state::store_io::StoreIoKind::Read,
            2 * 1024 * 1024,
            |store| {
                let view = store.snapshot()?;
                let mut terminal = 0;
                let mut pending = 0;
                for (key, bytes) in view.scan(Family::Result, b"", 4, 2 * 1024 * 1024)? {
                    latent_commit::atomic::validate_linked_row(&view, &key, &bytes)?;
                    let (format, _) = latent_commit::atomic::durable_row_format(&key, &bytes)
                        .map_err(|_| latent_state::embedded::StoreError::Corrupt)?;
                    if format == "latent.result-pending.v1" {
                        pending += 1;
                    } else {
                        terminal += 1;
                    }
                }
                Ok((terminal, pending))
            },
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust result-boundary transaction variant"]
async fn actual_guest_one_byte_oversized_result_preserves_identity_without_partial_commit() {
    let f = Fixture::with_large_result_guest().await;
    let size = u32::try_from(VALUE_BYTES + 1).unwrap();
    let rejected = invoke(&f, "oversized-body", size, false).await;
    assert_eq!(f.backend.imports.staged_intents.load(Ordering::SeqCst), 1);
    assert_eq!(f.backend.imports.returned_bytes.load(Ordering::SeqCst), 0);
    assert!(f.backend.imports.result_limit_trap.load(Ordering::SeqCst));
    assert_eq!(
        *f.backend.imports.platform_failure.lock().unwrap(),
        Some(latent_core::PlatformErrorCode::ResourceExhausted),
        "the unchanged encoded-output ceiling rejects the authored one-byte oversized body"
    );
    assert_eq!(
        rejected.command.as_ref().unwrap().outcome,
        t::CommandOutcome::RecoveryRequired as i32
    );
    assert!(
        !rejected
            .command
            .as_ref()
            .unwrap()
            .application_state_committed
    );
    assert!(rejected.command.as_ref().unwrap().commit.is_none());
    assert!(rejected.command.as_ref().unwrap().retained_result.is_none());
    assert_eq!(f.executions(), 1);
    assert_eq!(f.backend.real.resource_snapshot().stores_created, 1);
    assert_eq!(f.rows(Family::Command).await, 1);
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    assert_eq!(f.terminal_result_rows().await, 0);
    assert_eq!(f.pending_result_rows().await, 1);
    drop(rejected);
    let replay = invoke(&f, "oversized-body", size, false).await;
    assert!(replay.replayed);
    assert_eq!(
        replay.command.as_ref().unwrap().outcome,
        t::CommandOutcome::InProgress as i32
    );
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Attempt).await, 1);
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    drop(replay);
    f.shutdown().await;
}
