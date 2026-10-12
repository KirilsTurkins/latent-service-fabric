use super::*;
use std::sync::atomic::AtomicUsize;
use tokio::{
    net::{TcpListener, TcpStream},
    sync::Notify,
};

/// One finite test relay controls actual TLS to the pinned Vault, without
/// terminating TLS or receiving decoded credentials/secret responses.
struct Relay {
    port: u16,
    mode: Arc<AtomicUsize>,
    accepted: Arc<Notify>,
    resume: Arc<Notify>,
    stopped: Arc<Notify>,
    task: tokio::task::JoinHandle<()>,
}
impl Relay {
    async fn new(destination: u16) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let mode = Arc::new(AtomicUsize::new(0));
        let accepted = Arc::new(Notify::new());
        let resume = Arc::new(Notify::new());
        let stopped = Arc::new(Notify::new());
        let (state, event, release, stop) = (
            mode.clone(),
            accepted.clone(),
            resume.clone(),
            stopped.clone(),
        );
        let task = tokio::spawn(async move {
            for _ in 0..16 {
                let (mut client, _) = tokio::select! {
                    _ = stop.notified() => return,
                    value = listener.accept() => value.unwrap(),
                };
                let selected = state.load(Ordering::Acquire);
                event.notify_one();
                if selected == 2 {
                    continue;
                }
                if selected == 1 {
                    tokio::select! {
                        _ = stop.notified() => return,
                        _ = tokio::time::sleep(Duration::from_secs(6)) => continue,
                        _ = release.notified() => (),
                    }
                }
                let exchange = async {
                    use tokio::io::{AsyncReadExt, AsyncWriteExt};
                    let mut backend = TcpStream::connect(("127.0.0.1", destination))
                        .await
                        .unwrap();
                    let (read_a, mut write_a) = client.split();
                    let (read_b, mut write_b) = backend.split();
                    let (mut read_a, mut read_b) =
                        (read_a.take(1024 * 1024), read_b.take(1024 * 1024));
                    let forward = async {
                        tokio::io::copy(&mut read_a, &mut write_b).await?;
                        write_b.shutdown().await
                    };
                    let backward = async {
                        tokio::io::copy(&mut read_b, &mut write_a).await?;
                        write_a.shutdown().await
                    };
                    let _ = tokio::try_join!(forward, backward);
                };
                tokio::select! {
                    _ = stop.notified() => return,
                    _ = tokio::time::timeout(Duration::from_secs(6), exchange) => (),
                }
            }
            panic!("finite Vault relay connection bound exceeded");
        });
        Self {
            port,
            mode,
            accepted,
            resume,
            stopped,
            task,
        }
    }
    async fn close(mut self) {
        self.stopped.notify_one();
        tokio::time::timeout(Duration::from_secs(1), &mut self.task)
            .await
            .unwrap()
            .unwrap();
    }
}
impl Drop for Relay {
    fn drop(&mut self) {
        self.task.abort();
    }
}

#[tokio::test]
#[ignore = "requires tools/run_vault_secret_tests.py owned pinned TLS Vault"]
async fn real_vault_transport_cancellation_outage_tls_and_healthy_reuse() {
    setup::control("reset-fixture");
    let real = setup::configured();
    let mut wrong = real.clone();
    wrong.transport.destinations[0].origin.host = "wrong-vault.example".into();
    let f = setup::fixture(wrong, None).await;
    assert_eq!(invoke(&f, 0).await, 1003); // Certificate identity mismatch.
    shutdown(&f).await;

    let relay = Relay::new(real.transport.destinations[0].origin.port).await;
    let mut config = real;
    config.transport.destinations[0].origin.port = relay.port;
    config.limits.cache_ttl_millis = 0;
    let f = setup::fixture(config, None).await;
    relay.mode.store(1, Ordering::Release);
    let (session, control) = f.session("cancelled-vault-network");
    let future = f.provider.read(&session, "allowed".into()).unwrap();
    tokio::pin!(future);
    tokio::select! {
        _ = tokio::time::sleep(Duration::from_secs(2)) => panic!("relay accept deadline"),
        _ = relay.accepted.notified() => (),
        _ = &mut future => panic!("blocked TLS unexpectedly completed"),
    }
    assert!(f.provider.snapshot().unwrap().retained_plaintext_bytes > 0);
    control.probe.0.store(true, Ordering::Release);
    assert!(matches!(
        tokio::time::timeout(Duration::from_secs(1), &mut future)
            .await
            .unwrap(),
        Err(SecretError::Unavailable)
    ));
    drop(session);
    relay.mode.store(0, Ordering::Release);
    relay.resume.notify_one();
    setup::idle(&f).await;
    assert_eq!(f.provider.snapshot().unwrap().retained_plaintext_bytes, 0);
    // Failed connection attempts preserve the shared pool's finite backoff.
    tokio::time::sleep(Duration::from_millis(120)).await;
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
    relay.mode.store(2, Ordering::Release);
    assert_eq!(invoke(&f, 0).await, 1003); // Real backend path is unavailable.
    relay.mode.store(0, Ordering::Release);
    tokio::time::sleep(Duration::from_millis(120)).await;
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
    assert_eq!(f.provider.snapshot().unwrap().remote_read_attempts, 4);
    shutdown(&f).await;
    relay.close().await;
}
