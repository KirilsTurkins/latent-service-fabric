use crate::{observation, support};
use latent_executor::{ExecutionBackend, ExecutionCleanup, GuestInterruptionKind, GuestOutcome};
use serde_json::{json, Value};
use std::{
    sync::atomic::Ordering,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::oneshot,
};

#[path = "../http/component.rs"]
mod component;
#[path = "../http/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
#[path = "../http/packages.rs"]
#[allow(dead_code)]
mod packages;

async fn request(stream: &mut TcpStream) {
    let mut header = Vec::new();
    let mut byte = [0];
    while !header.ends_with(b"\r\n\r\n") {
        assert!(header.len() < 8192);
        assert_eq!(stream.read(&mut byte).await.unwrap(), 1);
        header.push(byte[0]);
    }
    let header = std::str::from_utf8(&header).unwrap().to_ascii_lowercase();
    let length = header
        .lines()
        .find_map(|line| line.strip_prefix("content-length: "))
        .unwrap_or("0")
        .parse::<usize>()
        .unwrap();
    assert!(length <= 4096);
    stream.read_exact(&mut vec![0; length]).await.unwrap();
}

pub async fn measure(rows: &mut Vec<Value>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let began = Instant::now();
    let fixture = fixture::Fixture::new(listener.local_addr().unwrap().port(), "/allowed").await;
    let mut fixed = capture(&fixture, "fixed");
    fixed["setupPreparationNanos"] = json!(began.elapsed().as_nanos().to_string());
    fixed["componentSha256"] = json!(fixture.revision.release.0);
    rows.push(fixed);
    for ordinal in 0..2 {
        for phase in ["success", "failure", "cancel", "recovery"] {
            let (started, observed) = oneshot::channel();
            let (release, released) = oneshot::channel();
            let (request_data, control) =
                fixture.request(&format!("resource-http-{ordinal}-{phase}"), 0);
            let began = Instant::now();
            let peer = async {
                let (mut stream, _) = listener.accept().await.unwrap();
                request(&mut stream).await;
                started.send(()).unwrap();
                released.await.unwrap();
                if phase == "cancel" {
                    let mut byte = [0];
                    assert_eq!(stream.read(&mut byte).await.unwrap(), 0);
                } else if phase != "failure" {
                    stream.write_all(b"HTTP/1.1 201 Created\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
                        .await.unwrap();
                }
            };
            let controller = async {
                observed.await.unwrap();
                let active = capture(&fixture, "active");
                assert_eq!(active["runtime"]["live_stores"], 1);
                assert_eq!(active["broker"]["calls"], 1);
                assert!(observation::pool_snapshot(&fixture.pools).0.connections > 0);
                rows.push(active);
                if phase == "cancel" {
                    control.probe.0.store(true, Ordering::Release);
                }
                release.send(()).unwrap();
            };
            let (report, (), ()) = tokio::time::timeout(Duration::from_secs(3), async {
                tokio::join!(
                    fixture.backend.invoke_contained(request_data, &control),
                    controller,
                    peer
                )
            })
            .await
            .unwrap();
            assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
            match report.outcome.unwrap() {
                GuestOutcome::Returned { output, .. } => {
                    let value: Value = serde_json::from_slice(&output).unwrap();
                    if phase == "failure" {
                        assert_ne!(value, json!([2201]));
                    } else {
                        assert_ne!(phase, "cancel");
                        assert_eq!(value, json!([2201]));
                    }
                }
                GuestOutcome::Interrupted { kind, .. } => {
                    assert_eq!(phase, "cancel");
                    assert_eq!(kind, GuestInterruptionKind::Cancelled);
                }
                other => panic!("unexpected resource HTTP outcome: {other:?}"),
            }
            fixture.idle();
            assert_eq!(observation::pool_snapshot(&fixture.pools).0.connections, 0);
            let mut retired = capture(&fixture, "recovery");
            retired["after"] = json!(phase);
            retired["invocationNanos"] = json!(began.elapsed().as_nanos().to_string());
            rows.push(retired);
        }
    }
    assert!(fixture
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
    rows.push(capture(&fixture, "shutdown"));
}

fn capture(fixture: &fixture::Fixture, phase: &str) -> Value {
    observation::snapshot(
        "http",
        phase,
        &fixture.backend,
        &fixture.broker,
        Some(&fixture.pools),
        Some(&fixture.io),
    )
}
