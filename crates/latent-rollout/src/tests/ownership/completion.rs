use super::super::{expires, runtime, support, Fixture};
use crate::{invalid, CoordinatorLimits, CoordinatorSnapshot, RolloutHandle};
use std::{
    future::Future,
    sync::{mpsc, Arc},
    task::{Context, Wake, Waker},
    time::Duration,
};

struct CompletionWake {
    handle: RolloutHandle,
    observed: mpsc::SyncSender<CoordinatorSnapshot>,
}

impl Wake for CompletionWake {
    fn wake(self: Arc<Self>) {
        self.wake_by_ref();
    }

    fn wake_by_ref(self: &Arc<Self>) {
        // oneshot wakes synchronously inside send, before the worker can do
        // later cleanup. Capture that exact ordering without scheduler luck.
        let _ = self.observed.try_send(self.handle.snapshot());
    }
}

#[test]
fn completion_retires_request_before_waking_client_and_keeps_success_response_owned() {
    runtime().block_on(async {
        for succeed in [false, true] {
            let mut fixture = Fixture::new(CoordinatorLimits::default()).await;
            let (entered, ready) = mpsc::sync_channel(1);
            let (release, proceed) = mpsc::sync_channel(1);
            let ticket = fixture
                .handle
                .submit(support::start(), expires(), move |_| {
                    entered.send(()).unwrap();
                    proceed.recv_timeout(Duration::from_secs(5)).unwrap();
                    if succeed {
                        Ok(())
                    } else {
                        Err(invalid("completion-fixture-rejection"))
                    }
                })
                .unwrap();
            ready.recv_timeout(Duration::from_secs(5)).unwrap();
            let (observed, wake) = mpsc::sync_channel(1);
            let waker = Waker::from(Arc::new(CompletionWake {
                handle: fixture.handle.clone(),
                observed,
            }));
            let mut completion = std::pin::pin!(ticket.wait());
            assert!(completion
                .as_mut()
                .poll(&mut Context::from_waker(&waker))
                .is_pending());
            assert_eq!(fixture.handle.snapshot().active_commands, 1);
            release.send(()).unwrap();
            let snapshot = wake.recv_timeout(Duration::from_secs(5)).unwrap();
            let response = completion.await;
            assert_eq!(response.is_ok(), succeed);
            assert_eq!(
                (
                    snapshot.active_commands,
                    snapshot.queued_commands,
                    snapshot.retained_request_bytes,
                    snapshot.completed_commands,
                ),
                (0, 0, 0, 1),
                "completion woke the client before request cleanup"
            );
            assert_eq!(snapshot.response_owners, usize::from(succeed));
            assert_eq!(snapshot.response_bytes > 0, succeed);
            // Holding a successful response must not keep request admission
            // busy, but must retain its distinct allowance across shutdown.
            drop(
                fixture
                    .handle
                    .get(
                        latent_core::TenantId("alice".into()),
                        latent_control_store::rollouts::RolloutId("rollout".into()),
                        expires(),
                    )
                    .unwrap()
                    .wait()
                    .await
                    .unwrap(),
            );
            fixture.shutdown().await;
            assert_eq!(
                fixture.handle.snapshot().response_owners,
                usize::from(succeed)
            );
            drop(response);
            assert_eq!(fixture.handle.snapshot().response_bytes, 0);
        }
    });
}
