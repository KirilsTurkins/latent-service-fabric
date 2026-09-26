use super::super::{
    destination,
    dns::DnsPeer,
    named,
    peer::{wait_until, Peer},
    policy, HttpOciRegistry, RegistryActions, RegistryResolution,
};
use super::observe::{cancel, sample, settled, spawn, warm};
use serde_json::Value;
use std::sync::atomic::Ordering;

pub(super) async fn tokens(ceiling: usize, rows: &mut Vec<Value>) {
    let peer = Peer::new().await;
    peer.state.hold.store(true, Ordering::Release);
    let mut config = peer.config(RegistryActions::Pull);
    config.limits.max_in_flight = ceiling;
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, policy(&peer)).unwrap();
    sample(rows, "token", ceiling, "fixed", &client, None);
    let mut calls = vec![spawn(&client, &origin)];
    peer.wait_tokens(1).await;
    for _ in 1..ceiling {
        calls.push(spawn(&client, &origin));
    }
    wait_until(|| client.usage().bearer.unwrap().waiting_acquisitions == ceiling - 1).await;
    assert_eq!(client.usage().bearer.unwrap().active_acquisitions, 1);
    sample(rows, "token", ceiling, "active", &client, None);
    cancel(calls).await;
    wait_until(|| peer.state.disconnected.load(Ordering::Acquire) == 1).await;
    settled(&client);
    sample(rows, "token", ceiling, "recovery", &client, None);
    peer.state.hold.store(false, Ordering::Release);
    warm(rows, "token", ceiling, &client, &origin).await;
    assert_eq!(peer.state.tokens.load(Ordering::Acquire), 2);
    peer.close().await;
}

pub(super) async fn dns(ceiling: usize, rows: &mut Vec<Value>) {
    let dns = DnsPeer::new().await;
    dns.hold.store(true, Ordering::Release);
    let peer = Peer::with_names(vec!["registry.test".into()]).await;
    let (mut config, mut network) = named(&peer, "registry.test");
    config.limits.max_in_flight = ceiling;
    network.destinations[0].resolution = RegistryResolution::Dns {
        server: dns.address,
        maximum_ttl_seconds: 60,
    };
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, network).unwrap();
    sample(rows, "dns", ceiling, "fixed", &client, None);
    let mut calls = vec![spawn(&client, &origin)];
    wait_until(|| dns.count.load(Ordering::Acquire) > 0).await;
    for _ in 1..ceiling {
        calls.push(spawn(&client, &origin));
    }
    wait_until(|| client.usage().network.unwrap().waiting_resolvers == ceiling - 1).await;
    assert_eq!(client.usage().network.unwrap().active_resolvers, 1);
    sample(rows, "dns", ceiling, "active", &client, None);
    cancel(calls).await;
    settled(&client);
    sample(rows, "dns", ceiling, "recovery", &client, None);
    dns.hold.store(false, Ordering::Release);
    dns.release.add_permits(4);
    warm(rows, "dns", ceiling, &client, &origin).await;
    peer.close().await;
    dns.close().await;
}

pub(super) async fn redirects(ceiling: usize, rows: &mut Vec<Value>) {
    let registry = Peer::new().await;
    let storage = Peer::new().await;
    storage.state.storage.store(true, Ordering::Release);
    storage.state.hold_headers.store(true, Ordering::Release);
    *registry.state.redirect.lock().unwrap() =
        Some(format!("https://{}/objects/blob", storage.address));
    let mut network = policy(&registry);
    network.destinations.push(destination(&storage, true));
    let mut config = registry.config(RegistryActions::Pull);
    config.limits.max_in_flight = ceiling;
    config.additional_root_certificates.extend(
        storage
            .config(RegistryActions::Pull)
            .additional_root_certificates,
    );
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, network).unwrap();
    sample(rows, "redirect", ceiling, "fixed", &client, None);
    let calls = (0..ceiling).map(|_| spawn(&client, &origin)).collect();
    wait_until(|| storage.state.reads.load(Ordering::Acquire) == ceiling).await;
    assert_eq!(
        client.usage().network.unwrap().reserved_redirect_bytes,
        ceiling * 16384
    );
    sample(rows, "redirect", ceiling, "active", &client, None);
    cancel(calls).await;
    wait_until(|| storage.state.disconnected.load(Ordering::Acquire) == ceiling).await;
    settled(&client);
    sample(rows, "redirect", ceiling, "recovery", &client, None);
    storage.state.hold_headers.store(false, Ordering::Release);
    warm(rows, "redirect", ceiling, &client, &origin).await;
    registry.close().await;
    storage.close().await;
}
