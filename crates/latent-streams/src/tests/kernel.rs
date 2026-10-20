//! A current-kernel counterexample, not a kernel-retirement certificate.
use super::{config, fixture::Fixture};
use latent_capabilities::broker::network::{OutboundStreamInvoker, StreamConnectRequest};
use std::{
    collections::BTreeSet,
    path::Path,
    process::Command,
    time::{Duration, Instant},
};
use tokio::{io::AsyncReadExt, net::TcpListener};

fn identity(fixture: &Fixture) -> [u64; 3] {
    let connections: Vec<_> = fixture
        .provider
        .inner
        .connections
        .lock()
        .unwrap()
        .iter()
        .filter_map(std::sync::Weak::upgrade)
        .collect();
    assert_eq!(connections.len(), 1);
    connections[0].kernel_reference_identity()
}

fn observe(key: [u64; 3]) -> serde_json::Value {
    let helper =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/host_stream_kernel_observer.py");
    let result = Command::new("python3")
        .arg(helper)
        .args([
            "--local-port",
            &key[0].to_string(),
            "--peer-port",
            &key[1].to_string(),
            "--inode",
            &key[2].to_string(),
        ])
        .output()
        .unwrap();
    assert!(result.status.success(), "bounded socket observer failed");
    assert!(result.stderr.is_empty() && result.stdout.len() <= 4096);
    let value: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    let object = value.as_object().unwrap();
    let fields: BTreeSet<_> = object.keys().map(String::as_str).collect();
    assert_eq!(
        fields,
        BTreeSet::from([
            "matchingRows",
            "state",
            "inodeMatched",
            "memory",
            "retirementProven",
            "toolSha256"
        ])
    );
    assert!(value["matchingRows"].as_u64().is_some_and(|n| n <= 1));
    assert_eq!(value["retirementProven"], false);
    assert!(value["inodeMatched"].is_boolean());
    assert!(matches!(
        value["state"].as_str(),
        Some(
            "absent"
                | "ESTAB"
                | "FIN-WAIT-1"
                | "FIN-WAIT-2"
                | "TIME-WAIT"
                | "CLOSE-WAIT"
                | "LAST-ACK"
                | "CLOSING"
                | "CLOSE"
                | "SYN-SENT"
                | "SYN-RECV"
        )
    ));
    let digest = value["toolSha256"].as_str().unwrap();
    assert!(digest.len() == 64 && digest.bytes().all(|b| b.is_ascii_hexdigit()));
    if let Some(memory) = value["memory"].as_object() {
        assert_eq!(
            memory.keys().map(String::as_str).collect::<BTreeSet<_>>(),
            BTreeSet::from([
                "receiveAllocatedBytes",
                "receiveLimitBytes",
                "transmitAllocatedBytes",
                "transmitLimitBytes",
                "forwardAllocatedBytes",
                "queuedWriteBytes",
                "optionBytes",
                "backlogBytes",
                "drops"
            ])
        );
        assert!(memory
            .values()
            .all(|n| n.as_u64().is_some_and(|v| u32::try_from(v).is_ok())));
    } else {
        assert!(value["memory"].is_null());
    }
    value
}

fn record(stage: &str, observation: serde_json::Value, host: u64, connections: usize) {
    println!(
        "KERNEL_OWNER_OBSERVATION {}",
        serde_json::json!({
            "stage": stage, "observation": observation,
            "hostMemoryBytes": host, "poolConnections": connections
        })
    );
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "one original owner across controlled pressure and both physical close barriers"
)]
async fn current_linux_pressure_and_active_close_distinguish_kernel_tail_from_fd_refund() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = config();
    config.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let fixture = Fixture::new(config);
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(
            &session,
            StreamConnectRequest {
                endpoint: fixture.provider.inner.config.destinations[0]
                    .endpoint
                    .clone(),
                timeout_millis: None,
            },
        )
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    socket2::SockRef::from(&peer)
        .set_recv_buffer_size(16 * 1024)
        .unwrap();
    let key = identity(&fixture);
    let connected = observe(key);
    assert_eq!(connected["matchingRows"], 1);
    assert_eq!(connected["inodeMatched"], true);
    assert_eq!(
        connected["memory"]["receiveLimitBytes"].as_u64().unwrap()
            + connected["memory"]["transmitLimitBytes"].as_u64().unwrap(),
        96 * 1024
    );
    record(
        "connected",
        connected,
        control.budget.host_memory_bytes(),
        fixture.pools.snapshot().unwrap().connections,
    );

    let mut accepted = 0usize;
    let mut blocked = None;
    for _ in 0..24 {
        let mut write = stream.write(vec![0x5a; 16 * 1024], None).unwrap();
        match tokio::time::timeout(Duration::from_millis(20), &mut write).await {
            Ok(Ok(count)) => {
                assert!(count > 0);
                accepted += usize::try_from(count).unwrap();
            }
            Ok(Err(_)) => panic!("original bounded write failed before pressure barrier"),
            Err(_) => {
                blocked = Some(write);
                break;
            }
        }
    }
    let mut blocked = blocked.expect("the controlled peer must apply actual send backpressure");
    assert!(fixture.provider.usage().unwrap().pending_operations > 0);
    assert!(control.budget.host_memory_bytes() >= 96 * 1024);
    let pressure = observe(key);
    assert_eq!(pressure["matchingRows"], 1);
    assert_eq!(pressure["inodeMatched"], true);
    record(
        "send-pressure",
        pressure,
        control.budget.host_memory_bytes(),
        fixture.pools.snapshot().unwrap().connections,
    );
    let mut received = 0;
    let mut bytes = [0u8; 16 * 1024];
    loop {
        tokio::select! {
            value = &mut blocked => { accepted += usize::try_from(value.unwrap()).unwrap(); break; }
            value = peer.read(&mut bytes) => { let count = value.unwrap(); assert!(count > 0); received += count; }
        }
    }
    drop(blocked);
    while received < accepted {
        let maximum = bytes.len().min(accepted - received);
        let count = peer.read(&mut bytes[..maximum]).await.unwrap();
        assert!(count > 0);
        received += count;
    }
    assert_eq!(received, accepted);
    assert_eq!(
        stream.close().await.unwrap().state,
        latent_capabilities::broker::network::StreamState::Closed
    );
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    let closed = observe(key);
    assert_eq!(
        closed["matchingRows"], 1,
        "an open passive peer must retain an actual kernel close tail"
    );
    assert!(matches!(
        closed["state"].as_str(),
        Some("FIN-WAIT-1" | "FIN-WAIT-2" | "TIME-WAIT")
    ));
    record(
        "after-fd-drop",
        closed,
        control.budget.host_memory_bytes(),
        fixture.pools.snapshot().unwrap().connections,
    );
    drop(peer);
    record(
        "after-peer-drop",
        observe(key),
        control.budget.host_memory_bytes(),
        fixture.pools.snapshot().unwrap().connections,
    );
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        1
    );
    drop(session);
    fixture.clean().await;
}
