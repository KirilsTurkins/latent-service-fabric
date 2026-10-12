use super::{fixture::*, proxy::Fault, Disposition};
use crate::deferred::DeferredHttpAuthorization;
use latent_capabilities::broker::http::HttpError;
use latent_effects::authority::DispatchGrant;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

struct RefusePost(Arc<AtomicUsize>);
impl DeferredHttpAuthorization for RefusePost {
    fn check_current(
        &self,
        _grant: &DispatchGrant,
        method: &str,
        _path: &str,
    ) -> Result<(), HttpError> {
        self.0.fetch_add(1, Ordering::SeqCst);
        if method == "POST" {
            Err(HttpError::PermissionDenied)
        } else {
            Ok(())
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_protocol_dispatch_policy_can_refuse_post_after_qualification_without_remote_mutation(
) {
    let observations = Arc::new(AtomicUsize::new(0));
    let fixture = Fixture::with_authorization(
        Fault::Normal,
        Some(Arc::new(RefusePost(observations.clone()))),
    )
    .await;
    let effect = fixture.commit("dispatch-policy-refusal").await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    fixture.settled(&effect, Disposition::PolicyBlocked).await;
    assert!(observations.load(Ordering::SeqCst) >= 2);
    assert_eq!(fixture.endpoint.counter().await, 0);
    assert_eq!(fixture.pool_snapshot().await.running_requests, 0);
    fixture.finish().await;
}
