use std::future::poll_fn;
use std::sync::atomic::AtomicUsize;
use std::task::{Context, Poll, Waker};

use latent_artifacts::{ArtifactDescriptor, ArtifactPage, ArtifactQuery};
use latent_core::{ContractId, PublicationId};

use super::*;

struct NeverWait;
impl PreparationReadWait for NeverWait {
    fn now(&self) -> Instant {
        panic!("the bridge cannot consult the caller's clock");
    }
    fn wait_until(&self, _: Instant) -> BoxFuture<'_, ()> {
        panic!("the bridge cannot arm a timer");
    }
}

struct UnusedRepository;
impl ArtifactRepository for UnusedRepository {
    fn resolve<'a>(
        &'a self,
        _: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        panic!("bridge cannot resolve");
    }
    fn fetch<'a>(
        &'a self,
        _: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        panic!("bridge cannot fetch");
    }
    fn publish(
        &self,
        _: CapsuleArtifact,
    ) -> BoxFuture<'_, Result<ArtifactDescriptor, PlatformError>> {
        panic!("bridge cannot publish");
    }
    fn list<'a>(
        &'a self,
        _: Option<&'a ReleaseDigest>,
        _: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        panic!("bridge cannot list");
    }
}

#[derive(Debug)]
struct Owner(Arc<AtomicUsize>);
impl Drop for Owner {
    fn drop(&mut self) {
        self.0.fetch_add(1, Ordering::Relaxed);
    }
}

struct WaitAware {
    source: Arc<dyn ArtifactRepository>,
    wait: Arc<NeverWait>,
    descriptor: PreparedComponent,
    calls: AtomicUsize,
    polls: AtomicUsize,
    drops: Arc<AtomicUsize>,
}
impl WaitAware {
    fn new() -> Self {
        let mut descriptor = request().prepared;
        descriptor.key.publication = Some(
            format!("publication:sha256:{}", "7".repeat(64))
                .parse::<PublicationId>()
                .unwrap(),
        );
        Self {
            source: Arc::new(UnusedRepository),
            wait: Arc::new(NeverWait),
            descriptor,
            calls: AtomicUsize::new(0),
            polls: AtomicUsize::new(0),
            drops: Arc::new(AtomicUsize::new(0)),
        }
    }
}
impl ExecutionBackend for WaitAware {
    fn backend_id(&self) -> &'static str {
        "wait-aware"
    }
    fn prepare_ready_from_repository(
        &self,
        _: Arc<dyn ArtifactRepository>,
        _: PreparationKey,
    ) -> BoxFuture<'_, Result<PreparedReadiness, PlatformError>> {
        panic!("bridge must preserve explicit wait opt-in");
    }
    fn prepare_ready_from_repository_with_wait<'a>(
        &'a self,
        source: Arc<dyn ArtifactRepository>,
        key: PreparationKey,
        wait: &'a dyn PreparationReadWait,
    ) -> BoxFuture<'a, Result<PreparedReadiness, PlatformError>> {
        assert!(Arc::ptr_eq(&source, &self.source));
        assert_eq!(key, self.descriptor.key);
        assert!(std::ptr::addr_eq(
            wait,
            self.wait.as_ref() as &dyn PreparationReadWait
        ));
        self.calls.fetch_add(1, Ordering::Relaxed);
        let owner = Owner(self.drops.clone());
        Box::pin(async move {
            poll_fn(|_| {
                if self.polls.fetch_add(1, Ordering::Relaxed) == 0 {
                    Poll::Pending
                } else {
                    Poll::Ready(())
                }
            })
            .await;
            Ok(PreparedReadiness::new(
                self.descriptor.clone(),
                vec![ContractId("exact-import".into())],
                owner,
            ))
        })
    }
    fn prepare<'a>(
        &'a self,
        _: &'a CapsuleArtifact,
        _: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        panic!("bridge must not change preparation API");
    }
    fn invoke<'a>(
        &'a self,
        _: ExecutionRequest,
        _: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        panic!("bridge must not invoke during readiness");
    }
    fn release(&self, _: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
        panic!("bridge must not release a foreign owner");
    }
}

#[test]
fn wait_aware_readiness_forwards_exact_inputs_without_eager_poll_or_replay() {
    let inner = Arc::new(WaitAware::new());
    let backend = BudgetedExecutionBackend::new(inner.clone(), ActivationBudgetRegistry::default());
    let mut future = backend.prepare_ready_from_repository_with_wait(
        inner.source.clone(),
        inner.descriptor.key.clone(),
        inner.wait.as_ref(),
    );
    assert_eq!(inner.calls.load(Ordering::Relaxed), 1);
    assert_eq!(inner.polls.load(Ordering::Relaxed), 0);
    let mut context = Context::from_waker(Waker::noop());
    assert!(future.as_mut().poll(&mut context).is_pending());
    let Poll::Ready(result) = future.as_mut().poll(&mut context) else {
        panic!("the same owned future must complete");
    };
    let (descriptor, imports, owner) = result.unwrap().into_parts::<Owner>().unwrap();
    assert_eq!(descriptor, inner.descriptor);
    assert_eq!(imports, [ContractId("exact-import".into())]);
    assert!(Arc::ptr_eq(&owner.0, &inner.drops));
    drop(future);
    assert_eq!(inner.calls.load(Ordering::Relaxed), 1);
    assert_eq!(inner.polls.load(Ordering::Relaxed), 2);
    assert_eq!(inner.drops.load(Ordering::Relaxed), 0);
    drop(owner);
    assert_eq!(inner.drops.load(Ordering::Relaxed), 1);
}

#[test]
fn dropping_wait_aware_readiness_reclaims_unpolled_and_pending_owners_once() {
    for poll_once in [false, true] {
        let inner = Arc::new(WaitAware::new());
        let backend =
            BudgetedExecutionBackend::new(inner.clone(), ActivationBudgetRegistry::default());
        let mut future = backend.prepare_ready_from_repository_with_wait(
            inner.source.clone(),
            inner.descriptor.key.clone(),
            inner.wait.as_ref(),
        );
        if poll_once {
            assert!(future
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending());
        }
        assert_eq!(inner.drops.load(Ordering::Relaxed), 0);
        drop(future);
        assert_eq!(inner.calls.load(Ordering::Relaxed), 1);
        assert_eq!(inner.polls.load(Ordering::Relaxed), usize::from(poll_once));
        assert_eq!(inner.drops.load(Ordering::Relaxed), 1);
    }
}
