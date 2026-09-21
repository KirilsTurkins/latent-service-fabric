use super::super::{pull, HttpOciRegistry};
use latent_core::PlatformError;
use serde_json::{json, Value};
use std::time::Duration;
use tokio::{task::JoinHandle, time::Instant};

pub(super) fn sample(
    rows: &mut Vec<Value>,
    kind: &str,
    ceiling: usize,
    phase: &str,
    client: &HttpOciRegistry,
    elapsed: Option<u128>,
) {
    let u = client.usage();
    let b = u.bearer.unwrap();
    let n = u.network.unwrap();
    assert!(u.in_flight <= ceiling && n.connections <= n.maximum_connections);
    assert!(
        n.reserved_connection_bytes <= n.maximum_connection_bytes
            && b.retained_token_bytes <= b.maximum_token_bytes
    );
    rows.push(json!({"kind": kind, "ceiling": ceiling, "phase": phase, "elapsedNanos": elapsed.map(|x| x.to_string()),
        "os": super::probe::capture(),
        "usage": {"inFlight": u.in_flight, "retainedPackages": u.retained_packages, "retainedBytes": u.retained_bytes, "closed": u.closed},
        "bearer": {"cachedTokens": b.cached_tokens, "activeAcquisitions": b.active_acquisitions,
            "waitingAcquisitions": b.waiting_acquisitions, "retainedTokenBytes": b.retained_token_bytes,
            "maximumTokenBytes": b.maximum_token_bytes, "reservedAcquisitionBytes": b.reserved_acquisition_bytes, "closed": b.closed},
        "network": {"connections": n.connections, "reservedConnectionBytes": n.reserved_connection_bytes,
            "maximumConnections": n.maximum_connections, "maximumConnectionBytes": n.maximum_connection_bytes,
            "activeResolvers": n.active_resolvers, "waitingResolvers": n.waiting_resolvers,
            "retainedDnsAnswers": n.retained_dns_answers, "reservedResolverBytes": n.reserved_resolver_bytes,
            "reservedRedirectBytes": n.reserved_redirect_bytes, "destinations": n.destinations, "closed": n.closed}}));
}

pub(super) fn settled(client: &HttpOciRegistry) {
    let u = client.usage();
    let b = u.bearer.unwrap();
    let n = u.network.unwrap();
    assert_eq!(
        (u.in_flight, u.retained_packages, u.retained_bytes),
        (0, 0, 0)
    );
    assert_eq!(
        (
            b.active_acquisitions,
            b.waiting_acquisitions,
            b.reserved_acquisition_bytes
        ),
        (0, 0, 0)
    );
    assert_eq!(
        (n.connections, n.active_resolvers, n.waiting_resolvers),
        (0, 0, 0)
    );
    assert_eq!(
        (n.reserved_connection_bytes, n.reserved_redirect_bytes),
        (0, 0)
    );
    // Configured resolver names and cache capacity are fixed/shared metadata;
    // their measured retained bytes are separate from active resolver ownership.
}

pub(super) fn spawn(
    client: &HttpOciRegistry,
    origin: &str,
) -> JoinHandle<Result<Vec<u8>, PlatformError>> {
    let client = client.clone();
    let origin = origin.to_owned();
    tokio::spawn(async move { pull(&client, &origin).await })
}

pub(super) async fn cancel(calls: Vec<JoinHandle<Result<Vec<u8>, PlatformError>>>) {
    for call in &calls {
        call.abort();
    }
    for call in calls {
        assert!(call.await.unwrap_err().is_cancelled());
    }
}

pub(super) async fn warm(
    rows: &mut Vec<Value>,
    kind: &str,
    ceiling: usize,
    client: &HttpOciRegistry,
    origin: &str,
) {
    let mut plateau = None;
    for cycle in 0..4 {
        let start = Instant::now();
        assert_eq!(pull(client, origin).await.unwrap(), b"abc");
        settled(client);
        let usage = client.usage();
        let retained = (
            usage.bearer.unwrap().retained_token_bytes,
            usage.network.unwrap().reserved_resolver_bytes,
        );
        if let Some(expected) = plateau {
            assert_eq!(retained, expected);
        }
        plateau = Some(retained);
        sample(
            rows,
            kind,
            ceiling,
            if cycle == 0 { "cold" } else { "warm" },
            client,
            Some(start.elapsed().as_nanos()),
        );
    }
    client
        .shutdown(Instant::now() + Duration::from_secs(3))
        .await
        .unwrap();
    settled(client);
    assert_eq!(client.usage().bearer.unwrap().cached_tokens, 0);
    assert_eq!(client.usage().network.unwrap().retained_dns_answers, 0);
    sample(rows, kind, ceiling, "shutdown", client, None);
}
