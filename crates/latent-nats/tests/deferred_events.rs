//! Committed state-to-broker delivery through a real protected engine and NATS.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

#[path = "deferred_events/campaign.rs"]
mod campaign;
#[path = "deferred_events/locks.rs"]
mod locks;
#[path = "deferred_events/proxy.rs"]
mod proxy;
#[path = "deferred_events/redrive.rs"]
mod redrive;
#[path = "deferred_events/support.rs"]
mod support;
