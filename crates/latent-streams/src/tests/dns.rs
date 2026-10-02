//! Real pending resolver ownership, observed independently through Linux socket
//! inodes. The observation is bounded and does not substitute a timeout for Drop.
use super::{config, fixture::Fixture};
use crate::{StreamErrorCode, StreamResolution};
use latent_capabilities::broker::network::{OutboundStreamInvoker, StreamConnectRequest};
use std::{
    fs,
    io::Read,
    sync::atomic::Ordering,
    time::{Duration, Instant},
};
use tokio::net::{TcpListener, UdpSocket};

fn inode_for_udp_port(port: u16) -> u64 {
    let mut table = String::new();
    fs::File::open("/proc/net/udp")
        .unwrap()
        .take(65537)
        .read_to_string(&mut table)
        .unwrap();
    assert!(table.len() <= 65536);
    let suffix = format!(":{port:04X}");
    let mut inode = None;
    for (index, row) in table.lines().skip(1).take(1025).enumerate() {
        assert!(index < 1024, "bounded network observation exceeded");
        let mut columns = row.split_whitespace();
        let local = columns.nth(1).unwrap();
        if local.ends_with(&suffix) {
            assert!(inode.is_none(), "ambiguous controlled resolver socket");
            inode = Some(columns.nth(7).unwrap().parse().unwrap());
        }
    }
    inode.expect("actual pending resolver socket")
}

fn owns_socket(inode: u64) -> bool {
    let target = format!("socket:[{inode}]");
    for (index, entry) in fs::read_dir("/proc/self/fd")
        .unwrap()
        .take(1025)
        .enumerate()
    {
        assert!(index < 1024, "bounded descriptor observation exceeded");
        match fs::read_link(entry.unwrap().path()) {
            Ok(link) if link.as_os_str() == target.as_str() => return true,
            Ok(_) => {}
            Err(failure) if failure.kind() == std::io::ErrorKind::NotFound => {}
            Err(failure) => panic!("descriptor observation failed: {failure}"),
        }
    }
    false
}

#[tokio::test]
async fn pending_dns_socket_keeps_original_native_charge_until_actual_cancelled_drop() {
    let dns = UdpSocket::bind("127.0.0.1:0").await.unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.host = "registry.test".into();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    configuration.destinations[0].resolution = StreamResolution::Dns {
        server: dns.local_addr().unwrap(),
        maximum_ttl_seconds: 1,
    };
    let fixture = Fixture::new(configuration);
    let (session, control) = fixture.session(5000);
    let mut pending = fixture
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
        .unwrap();
    let mut packet = [0; 512];
    let sender = tokio::select! {
        result = &mut pending => panic!("resolver completed before peer barrier: {}", result.is_ok()),
        received = dns.recv_from(&mut packet) => received.unwrap().1,
    };
    let inode = inode_for_udp_port(sender.port());
    assert!(owns_socket(inode));
    assert_eq!(
        fixture.provider.inner.resolvers[0]
            .as_ref()
            .unwrap()
            .usage()
            .active,
        1
    );
    assert!(control.budget.host_memory_bytes() >= 64 * 1024);
    assert!(control.budget.snapshot_at(Instant::now()).peak_memory_bytes >= 64 * 1024);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert_eq!(fixture.io.snapshot().calls, 1);

    // A cancellation acknowledgement alone refunds nothing. Only polling and
    // destroying the original owned DNS future closes its actual descriptor.
    control.probe.0.store(true, Ordering::Release);
    assert!(owns_socket(inode));
    assert!(control.budget.host_memory_bytes() >= 64 * 1024);
    assert_eq!(
        pending.await.err().unwrap().code,
        StreamErrorCode::Cancelled
    );
    assert!(!owns_socket(inode));
    assert_eq!(
        fixture.provider.inner.resolvers[0]
            .as_ref()
            .unwrap()
            .usage()
            .active,
        0
    );
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        1
    );
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
    assert!(
        tokio::time::timeout(Duration::from_millis(50), listener.accept())
            .await
            .is_err()
    );
    drop(listener);
    drop(session);
    fixture.clean().await;
}
