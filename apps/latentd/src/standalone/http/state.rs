use super::HttpSettings;
use crate::config::http::CONNECTION_BYTES;
use latent_ingress::http::{HttpPool, EXCHANGE_RESERVATION_BYTES};
use serde::Serialize;
use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Arc,
};
use tokio::sync::watch;

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(super) enum Signal {
    Starting,
    Accepting,
    Draining,
    Forced,
}
pub(super) struct State {
    pub signal: watch::Sender<Signal>,
    pub pool: HttpPool,
    pub connections: AtomicUsize,
    pub maximum_connections: usize,
    pub maximum_bytes: usize,
    pub listener_alive: AtomicBool,
    pub owner_alive: AtomicBool,
    pub joined: AtomicBool,
    pub failed: AtomicBool,
}

#[derive(Clone)]
pub(crate) struct HttpHandle(pub(super) Arc<State>);

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
#[expect(
    clippy::struct_excessive_bools,
    reason = "independent observed owners, join, failure and admission facts may coexist"
)]
pub struct HttpSnapshot {
    pub listener_alive: bool,
    pub owner_alive: bool,
    pub joined: bool,
    pub failed: bool,
    pub accepting: bool,
    pub maximum_connections: usize,
    pub connections: usize,
    pub maximum_exchanges: usize,
    pub exchanges: usize,
    pub maximum_buffer_bytes: usize,
    pub reserved_buffer_bytes: usize,
}
impl HttpSnapshot {
    #[must_use]
    pub fn clean(self) -> bool {
        !self.listener_alive
            && !self.owner_alive
            && !self.accepting
            && self.joined
            && !self.failed
            && self.connections == 0
            && self.exchanges == 0
            && self.reserved_buffer_bytes == 0
    }
}
impl HttpHandle {
    pub(super) fn new(settings: &HttpSettings) -> Result<Self, latent_core::PlatformError> {
        let limits = settings.limits;
        Ok(Self(Arc::new(State {
            signal: watch::channel(Signal::Starting).0,
            pool: HttpPool::new(
                limits.maximum_exchanges,
                limits.maximum_exchanges * EXCHANGE_RESERVATION_BYTES,
            )
            .map_err(|_| super::failure())?,
            connections: AtomicUsize::new(0),
            maximum_connections: limits.maximum_connections,
            maximum_bytes: limits.maximum_buffer_bytes,
            listener_alive: AtomicBool::new(true),
            owner_alive: AtomicBool::new(true),
            joined: AtomicBool::new(false),
            failed: AtomicBool::new(false),
        })))
    }
    pub(crate) fn snapshot(&self) -> HttpSnapshot {
        let pool = self.0.pool.snapshot();
        let connections = self.0.connections.load(Ordering::Acquire);
        HttpSnapshot {
            listener_alive: self.0.listener_alive.load(Ordering::Acquire),
            owner_alive: self.0.owner_alive.load(Ordering::Acquire),
            joined: self.0.joined.load(Ordering::Acquire),
            failed: self.0.failed.load(Ordering::Acquire),
            accepting: self.accepting(),
            maximum_connections: self.0.maximum_connections,
            connections,
            maximum_exchanges: pool.maximum_exchanges,
            exchanges: pool.active_exchanges,
            maximum_buffer_bytes: self.0.maximum_bytes,
            reserved_buffer_bytes: connections * CONNECTION_BYTES + pool.reserved_bytes,
        }
    }
    pub(super) fn accepting(&self) -> bool {
        *self.0.signal.borrow() == Signal::Accepting
    }
    pub(crate) fn start_accepting(&self) -> Result<(), latent_core::PlatformError> {
        if !self.0.owner_alive.load(Ordering::Acquire)
            || *self.0.signal.borrow() != Signal::Starting
        {
            return Err(super::failure());
        }
        self.0.signal.send_replace(Signal::Accepting);
        Ok(())
    }
    pub(crate) fn stop_accepting(&self) {
        self.signal(Signal::Draining);
    }
    pub(super) fn signal(&self, signal: Signal) {
        self.0.signal.send_if_modified(|old| {
            if *old < signal {
                *old = signal;
                true
            } else {
                false
            }
        });
    }
    pub(super) async fn stopped(&self, at: Signal) {
        let mut signal = self.0.signal.subscribe();
        let _ = signal.wait_for(|value| *value >= at).await;
    }
    pub(super) fn reserve(&self) -> Option<ConnectionPermit> {
        if !self.accepting() {
            return None;
        }
        self.0
            .connections
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
                (n < self.0.maximum_connections).then_some(n + 1)
            })
            .ok()?;
        Some(ConnectionPermit(self.clone()))
    }
}
pub(super) struct ConnectionPermit(HttpHandle);
impl Drop for ConnectionPermit {
    fn drop(&mut self) {
        self.0 .0.connections.fetch_sub(1, Ordering::AcqRel);
    }
}
