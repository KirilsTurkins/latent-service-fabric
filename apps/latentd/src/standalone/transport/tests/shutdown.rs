use super::*;
use std::sync::atomic::{AtomicBool, Ordering};

struct Dropped(Arc<AtomicBool>);
impl Drop for Dropped {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

#[tokio::test(start_paused = true)]
async fn timed_out_server_is_aborted_and_joined_before_returning_failure() {
    let dropped = Arc::new(AtomicBool::new(false));
    let guard = Dropped(Arc::clone(&dropped));
    let serving = tokio::spawn(async move {
        let _guard = guard;
        std::future::pending::<Result<(), tonic::transport::Error>>().await
    });
    let shared = ready_shared();
    let transport = Transport {
        address: "127.0.0.1:1".parse().unwrap(),
        handle: TransportHandle { shared },
        serving: Some(serving),
    };
    let began = tokio::time::Instant::now();
    assert!(transport.shutdown().await.is_err());
    assert!(
        dropped.load(Ordering::Acquire),
        "abort must be acknowledged before return"
    );
    assert!(tokio::time::Instant::now().duration_since(began) <= configuration().shutdown_timeout);
}

#[tokio::test(start_paused = true)]
async fn already_panicked_server_is_joined_without_repolling_its_handle() {
    let serving = tokio::spawn(async {
        panic!("server fixture panic");
        #[allow(unreachable_code)]
        Ok::<(), tonic::transport::Error>(())
    });
    tokio::task::yield_now().await;
    let transport = Transport {
        address: "127.0.0.1:1".parse().unwrap(),
        handle: TransportHandle {
            shared: ready_shared(),
        },
        serving: Some(serving),
    };
    assert!(transport.shutdown().await.is_err());
}
