//! Accepted queued roots keep their original reservation and ingress deadline.
use super::admission::{queued_fixture, request};
use super::*;

fn observed(case: &str, tenant: &str, index: u32, outcome: &str) {
    println!(
        "GO_QUEUED_CASE {}",
        serde_json::json!({"case":case,"tenant":tenant,"index":index,"outcome":outcome})
    );
}

async fn queued(
    mut invocation: Pin<&mut impl Future<Output = latent_node::ActivationReceipt>>,
    f: &Fixture,
    count: u32,
) {
    tokio::time::timeout(
        Duration::from_secs(5),
        std::future::poll_fn(|context| match invocation.as_mut().poll(context) {
            Poll::Ready(receipt) => panic!(
                "queued root executed or failed early: {:?}",
                receipt.outcome
            ),
            Poll::Pending if f.queued_cell_requests() == count => {
                f.assert_one_occupied_cell_with_queued(count);
                Poll::Ready(())
            }
            Poll::Pending => Poll::Pending,
        }),
    )
    .await
    .expect("observe an actual scheduler queue, not an unpolled request");
}

async fn no_store_before_next_queued_root(f: &Fixture) {
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let resources = f.backend.resource_snapshot();
            if resources.live_stores == 0
                && resources.live_host_states == 0
                && resources.live_component_instances == 0
                && resources.active_invocations == 0
                && f.backend.active_instance_reservations() == 0
            {
                assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("the previous real Store retires while accepted queued roots remain charged");
}

#[tokio::test]
#[ignore = "requires the exact maintained Go v5 component and signed tenant publications"]
#[expect(
    clippy::too_many_lines,
    reason = "one real pending Store and its seven accepted root handles retain one lexical ownership scope"
)]
async fn signed_ordinary_queue_keeps_original_budgets_deadlines_and_tenant_ownership() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    let f = queued_fixture(root.path()).await;
    for tenant in ["tenant-a", "tenant-b"] {
        assert_eq!(
            value(
                f.manager
                    .start(request(&f, tenant, &format!("queue-warm-{tenant}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
        observed("warm", tenant, 0, "success");
    }
    for (owner, peer, mode) in [("tenant-a", "tenant-b", 3), ("tenant-b", "tenant-a", 4)] {
        let original_id = ActivationId(format!("queue-original-{owner}"));
        let mut original = Box::pin(
            f.manager
                .start(request(&f, owner, &original_id.0, mode))
                .unwrap(),
        );
        pending_timer(original.as_mut(), &f).await;
        let created = f.backend.resource_snapshot().stores_created;
        let mut waiting = Vec::new();
        let mut deadline = None;
        for index in 0..7 {
            let id = ActivationId(format!("queue-accepted-{peer}-{index}"));
            let mut call = request(&f, peer, &id.0, 0);
            if index == 0 {
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap();
                call.deadline_unix_millis = Some(u64::try_from(now.as_millis()).unwrap() + 10_000);
            }
            let mut handle = Box::pin(f.manager.start(call).unwrap());
            queued(handle.as_mut(), &f, index + 1).await;
            assert_eq!(f.backend.resource_snapshot().stores_created, created);
            if index == 0 {
                deadline = Some(handle);
            } else {
                waiting.push((id, handle));
            }
        }
        observed("queued-full", peer, 0, "pending");
        let refused = match f
            .manager
            .start(request(&f, owner, &format!("queue-ninth-{owner}"), 0))
        {
            Ok(handle) => failure(
                tokio::time::timeout(Duration::from_secs(2), handle)
                    .await
                    .expect("full admission must not create another queue or retry"),
            ),
            Err(error) => error,
        };
        assert_eq!(refused.code, PlatformErrorCode::ResourceExhausted);
        assert!(refused.retryable);
        assert!(refused
            .details
            .iter()
            .any(|detail| detail.kind == "admission.limit"
                && detail.fields
                    == std::collections::BTreeMap::from([
                        ("scope".into(), "node".into()),
                        ("dimension".into(), "concurrency".into()),
                        ("reason".into(), "capacity-exhausted".into())
                    ])));
        f.assert_one_occupied_cell_with_queued(7);
        assert_eq!(f.backend.resource_snapshot().stores_created, created);
        observed("saturated", owner, 0, "resource-exhausted");
        let (victim_id, victim) = waiting.pop().unwrap();
        assert_eq!(
            f.manager
                .cancel_for(&TenantId(owner.into()), &victim_id, "foreign-queued-cancel")
                .unwrap(),
            latent_core::CancelDisposition::NotFound
        );
        f.assert_one_occupied_cell_with_queued(7);
        observed("foreign-cancel", owner, 0, "not-found");
        assert_eq!(
            f.manager
                .cancel_for(&TenantId(peer.into()), &victim_id, "owned-queued-cancel")
                .unwrap(),
            latent_core::CancelDisposition::Accepted
        );
        assert_eq!(
            failure(
                tokio::time::timeout(Duration::from_secs(2), victim)
                    .await
                    .unwrap()
            )
            .code,
            PlatformErrorCode::Cancelled
        );
        f.assert_one_occupied_cell_with_queued(6);
        assert_eq!(f.backend.resource_snapshot().stores_created, created);
        observed("queued-cancel", peer, 0, "cancelled");
        let replacement_id = ActivationId(format!("queue-replacement-{peer}"));
        let mut replacement = Box::pin(
            f.manager
                .start(request(&f, peer, &replacement_id.0, 0))
                .unwrap(),
        );
        queued(replacement.as_mut(), &f, 7).await;
        waiting.push((replacement_id, replacement));
        observed("replacement-queued", peer, 0, "pending");
        assert_eq!(
            failure(
                tokio::time::timeout(Duration::from_secs(12), deadline.take().unwrap())
                    .await
                    .expect("original ingress deadline must include scheduler waiting")
            )
            .code,
            PlatformErrorCode::DeadlineExceeded
        );
        f.assert_one_occupied_cell_with_queued(6);
        assert_eq!(f.backend.resource_snapshot().stores_created, created);
        observed("queued-deadline", peer, 0, "deadline-exceeded");
        let final_id = ActivationId(format!("queue-after-deadline-{peer}"));
        let mut final_queued =
            Box::pin(f.manager.start(request(&f, peer, &final_id.0, 0)).unwrap());
        queued(final_queued.as_mut(), &f, 7).await;
        waiting.push((final_id, final_queued));
        observed("deadline-replacement", peer, 0, "pending");
        let expected = if mode == 3 {
            assert_eq!(
                f.manager
                    .cancel_for(
                        &TenantId(owner.into()),
                        &original_id,
                        "owned-original-cancel"
                    )
                    .unwrap(),
                latent_core::CancelDisposition::Accepted
            );
            PlatformErrorCode::Cancelled
        } else {
            PlatformErrorCode::GuestTrap
        };
        assert_eq!(failure(original.await).code, expected);
        no_store_before_next_queued_root(&f).await;
        let usage = f.quotas.usage().unwrap();
        assert_eq!(usage.active_activations, 7);
        assert_eq!(usage.reserved_cpu_fuel, packages::budget().cpu_fuel * 7);
        assert_eq!(
            usage.reserved_memory_bytes,
            packages::budget().memory_bytes * 7
        );
        observed(
            "original",
            owner,
            0,
            if mode == 3 { "cancelled" } else { "guest-trap" },
        );
        for (index, (_, handle)) in waiting.into_iter().enumerate() {
            assert_eq!(value(handle.await), 42);
            no_store_before_next_queued_root(&f).await;
            let remaining = 6 - u32::try_from(index).unwrap();
            let quota = f.quotas.usage().unwrap();
            assert_eq!(quota.active_activations, remaining);
            assert_eq!(
                quota.reserved_cpu_fuel,
                packages::budget().cpu_fuel * u64::from(remaining)
            );
            assert_eq!(
                quota.reserved_memory_bytes,
                packages::budget().memory_bytes * u64::from(remaining)
            );
            assert_eq!(
                f.backend.resource_snapshot().stores_created,
                created + u64::try_from(index).unwrap() + 1
            );
            observed(
                "queued-fresh",
                peer,
                u32::try_from(index).unwrap(),
                "success",
            );
        }
        f.idle().await;
    }
    for tenant in ["tenant-a", "tenant-b"] {
        assert_eq!(
            value(
                f.manager
                    .start(request(&f, tenant, &format!("queue-final-{tenant}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
        observed("final-fresh", tenant, 0, "success");
    }
}
