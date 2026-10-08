#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

use super::{config as http_config, fixture::Fixture as HttpFixture, tls::certificate};
use crate::effects::{PutOnceContract, QualifiedHttpEffectAdapter, HTTP_EFFECT_OPERATION};
use latent_core::{transaction_contract::Value, TenantId};
use latent_effects::{
    authority::{
        AuthorityError, CommitLink, DispatchCeiling, DispatchContext, DurableEffectAuthority,
        EffectAuthorityOwner, EffectRule, EffectScope, EffectTime,
    },
    dispatch::{AttemptIdentity, Disposition, EffectRecord},
    payload::{payload_digest, PayloadRecord},
    runtime::{AdapterOutcome, DeferredEffectAdapter, EffectTimeSource},
};
use std::{
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

mod dispatcher;
mod endpoint;
mod fixture;
mod ownership;
mod proxy;
mod reconciliation;

use endpoint::{Endpoint, Fault};
use fixture::Fixture;

#[derive(Default)]
struct Clock(AtomicU64);
impl EffectTimeSource for Clock {
    fn observe(&self) -> EffectTime {
        EffectTime {
            unix_millis: self.0.load(Ordering::SeqCst),
            continuity_proven: true,
        }
    }
}

/// Failure watchdog only: readiness is a socket, durable row or explicit event.
async fn watched<T>(future: impl std::future::Future<Output = T>) -> T {
    tokio::time::timeout(Duration::from_secs(10), future)
        .await
        .expect("effect test watchdog")
}
