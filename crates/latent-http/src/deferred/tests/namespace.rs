use super::{fixture::*, proxy::Fault};
use latent_effects::{authority::AuthorityError, dispatch::Disposition};

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn namespace_close_acceptance_invalidates_held_tls_grant_without_refunding_physical_work() {
    for accepted in [false, true] {
        let fixture = Fixture::new(Fault::HoldSecondTls).await;
        let effect = fixture.commit("namespace-original-grant").await;
        fixture.owner.as_ref().unwrap().resume().unwrap();
        fixture.proxy.wait_gate().await;
        assert_eq!(fixture.pool_snapshot().await.running_requests, 1);
        assert_eq!(fixture.authority.owners().unwrap().physical, 1);
        assert_eq!(fixture.endpoint.counter().await, 0);
        let result = fixture
            .authority
            .prepare_namespace_close("tests", "aggregate", 1)
            .unwrap()
            .accept(|| {
                // This tests the reviewed metadata bridge, not a fabricated
                // management permission. Authenticated Wire closure has its
                // separate real Policy/Namespace/Native acceptance schedules.
                if accepted {
                    Ok(())
                } else {
                    Err("original-management-request-closed")
                }
            });
        assert_eq!(result.is_ok(), accepted);
        assert_eq!(fixture.pool_snapshot().await.running_requests, 1);
        assert_eq!(fixture.authority.owners().unwrap().physical, 1);
        if accepted {
            let mut new_publication = fixture.rule.clone();
            new_publication.scope.publication = "replacement-publication".into();
            new_publication.policy_revision = 2;
            assert_eq!(
                fixture.authority.publish(new_publication),
                Err(AuthorityError::PolicyBlocked)
            );
        }
        fixture.proxy.release();
        let expected = if accepted {
            Disposition::PolicyBlocked
        } else {
            Disposition::ProviderAcknowledged
        };
        let record = fixture.settled(&effect, expected).await;
        assert_eq!(record.attempts(), 1);
        assert_eq!(record.latest().unwrap().disposition, expected);
        assert_eq!(fixture.endpoint.counter().await, u64::from(!accepted));
        assert_eq!(
            fixture
                .proxy
                .posts
                .load(std::sync::atomic::Ordering::Acquire),
            u64::from(!accepted)
        );
        tokio::time::timeout(WATCHDOG, async {
            loop {
                if fixture.authority.owners().unwrap().physical == 0
                    && fixture.pool_snapshot().await.running_requests == 0
                {
                    break;
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("actual retained grant/socket/request did not retire");
        fixture.finish().await;
    }
}
