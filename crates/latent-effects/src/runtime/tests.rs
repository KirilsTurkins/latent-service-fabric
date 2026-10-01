use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_core::test_support::coordination::{
    with_watchdog, PauseTicket, PollProbe, Registration, Rendezvous, Stage, WATCHDOG,
};
use latent_core::transaction_contract::Value;
use latent_core::BoxFuture;
use latent_state::embedded::{AtomicBatch, RowMutation};
use latent_state::protected_store::{
    ProtectedStoreConfig, ProtectedStoreError, ProtectedStoreOwner,
};
use latent_state::store_io::StoreIoKind;

use crate::authority::{
    AuthorityError, CommitLink, DispatchCeiling, DispatchGrant, DispatchProfile,
    DurableEffectAuthority, EffectAuthorityOwner, EffectRule, EffectScope, EffectTime,
};
use crate::dispatch::{AttemptIdentity, AttemptReceipt, Disposition, EffectRecord};
use crate::dispatch_store::{
    effect_payload_key, effect_row_key, initial_due_mutation, DispatchCatalog,
};
use crate::payload::{payload_digest, PayloadRecord};

use super::*;

mod admission;
mod control;
mod ownership;
mod pressure;
mod recovery;
mod scheduling;

#[derive(Default)]
struct Clock {
    millis: AtomicU64,
    continuous: AtomicBool,
}

impl EffectTimeSource for Clock {
    fn observe(&self) -> EffectTime {
        EffectTime {
            unix_millis: self.millis.load(Ordering::SeqCst),
            continuity_proven: self.continuous.load(Ordering::SeqCst),
        }
    }
}

struct Fixture {
    _root: tempfile::TempDir,
    config: ProtectedStoreConfig,
    store: Arc<ProtectedStoreOwner>,
    authority: EffectAuthorityOwner,
    clock: Arc<Clock>,
}

impl Fixture {
    async fn new() -> Self {
        let base = std::env::var_os("LATENT_STATE_TEST_ROOT")
            .map_or_else(std::env::temp_dir, PathBuf::from);
        let root = tempfile::tempdir_in(base).unwrap();
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let mut config = ProtectedStoreConfig::bounded_linux(root.path().to_path_buf());
        config.create_if_missing = true;
        let store = Arc::new(Self::open(config.clone()).await);
        Self {
            _root: root,
            config,
            store,
            authority: EffectAuthorityOwner::new(128, 16, 100).unwrap(),
            clock: Arc::new(Clock {
                millis: AtomicU64::new(100),
                continuous: AtomicBool::new(true),
            }),
        }
    }

    async fn open(config: ProtectedStoreConfig) -> ProtectedStoreOwner {
        ProtectedStoreOwner::start_validated_view(config, 0, DispatchCatalog::validate_view)
            .unwrap()
            .await
            .unwrap()
    }

    async fn seed(
        &self,
        index: u64,
        tenant: &str,
        publication: &str,
        profile: DispatchProfile,
    ) -> DurableEffectAuthority {
        let value = Value {
            bytes: format!("committed payload {index}").into_bytes(),
            media_type: "application/octet-stream".into(),
            metadata: vec![("command".into(), format!("command-{index}"))],
        };
        let rule = rule(tenant, publication, profile);
        self.authority.publish(rule.clone()).unwrap();
        let authority = self
            .authority
            .capture(
                &rule.scope,
                CommitLink {
                    command: format!("command-{index}"),
                    caller_scope: "caller-a".into(),
                    attempt: 1,
                    commit: format!("commit-{index}"),
                    effect: format!("{index:064x}"),
                    sequence: u32::try_from(index).unwrap(),
                },
                value.bytes.len() as u64,
                payload_digest(&value).unwrap(),
                self.clock.observe(),
            )
            .unwrap();
        let payload = PayloadRecord::new(&authority, value).unwrap();
        let record = EffectRecord::committed(&authority).unwrap();
        self.store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![
                    RowMutation {
                        key: effect_row_key(payload.effect()).unwrap(),
                        value: Some(record.encode().unwrap()),
                    },
                    RowMutation {
                        key: effect_payload_key(payload.effect()).unwrap(),
                        value: Some(payload.encode().unwrap()),
                    },
                    initial_due_mutation(&authority).unwrap(),
                ],
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        authority
    }

    async fn start(
        &self,
        config: DispatcherConfig,
        adapters: Vec<Arc<dyn DeferredEffectAdapter>>,
        checkpoint: Option<(u64, u64)>,
    ) -> Result<DispatcherOwner, DispatcherError> {
        DispatcherOwner::start(
            config,
            Arc::clone(&self.store),
            self.authority.clone(),
            adapters,
            self.clock.clone(),
            checkpoint,
        )
        .await
    }

    async fn record(&self, authority: &DurableEffectAuthority) -> EffectRecord {
        with_watchdog(WATCHDOG, async {
            loop {
                match self.try_record(authority).await {
                    Ok(record) => return record,
                    Err(ProtectedStoreError::Io(
                        latent_state::store_io::StoreIoError::QueueFull
                        | latent_state::store_io::StoreIoError::AcceptedFull
                        | latent_state::store_io::StoreIoError::ByteBudget,
                    )) => tokio::task::yield_now().await,
                    Err(error) => panic!("read observation failed {error:?}"),
                }
            }
        })
        .await
    }

    async fn try_record(
        &self,
        authority: &DurableEffectAuthority,
    ) -> Result<EffectRecord, ProtectedStoreError> {
        let key = effect_row_key(&authority.link().effect).unwrap();
        self.store
            .with_store(StoreIoKind::Read, 128 * 1024, move |store| {
                let bytes = store.snapshot()?.get(&key)?.unwrap();
                Ok(EffectRecord::decode(&bytes).unwrap())
            })?
            .await
            .map_err(ProtectedStoreError::Io)?
    }

    async fn finish(&self) {
        let deadline = Instant::now() + WATCHDOG;
        let report = self
            .store
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await;
        assert!(report.clean, "{report:?}");
        assert!(report.snapshot.physically_retired());
        self.store.reap_retired_threads().unwrap();
    }
}

fn profile(adapter: &str) -> DispatchProfile {
    DispatchProfile {
        provider: "provider-a".into(),
        destination: "orders.events".into(),
        adapter: adapter.into(),
        intent_format: 1,
        payload_format: "value.v1".into(),
        idempotency_profile: "none.v1".into(),
    }
}

fn rule(tenant: &str, publication: &str, profile: DispatchProfile) -> EffectRule {
    EffectRule {
        scope: EffectScope {
            tenant: tenant.into(),
            namespace: "orders".into(),
            incarnation: 7,
            publication: publication.into(),
            binding: "events".into(),
            operation: "publish".into(),
        },
        profile,
        policy_revision: 1,
        credential_epoch: 1,
        protected_credential_reference: "provider-a-secret".into(),
        ceiling: DispatchCeiling {
            maximum_payload_bytes: 1024 * 1024,
            maximum_response_bytes: 1024,
            maximum_attempts: 3,
            maximum_age_millis: 60_000,
            attempt_timeout_millis: 10_000,
        },
        enabled: true,
    }
}

struct Event {
    effect: String,
    registration: Registration,
    ticket: Option<PauseTicket>,
}

struct Adapter {
    profile: DispatchProfile,
    gate_tenant: Option<String>,
    gates: Rendezvous,
    entered: tokio::sync::mpsc::Sender<Event>,
    physical: Arc<AtomicUsize>,
    sent: Arc<AtomicUsize>,
}

impl Adapter {
    fn new(
        adapter: &str,
        gate_tenant: Option<&str>,
    ) -> (Arc<Self>, tokio::sync::mpsc::Receiver<Event>) {
        let (entered, receiver) = tokio::sync::mpsc::channel(32);
        (
            Arc::new(Self {
                profile: profile(adapter),
                gate_tenant: gate_tenant.map(str::to_owned),
                gates: Rendezvous::new(32),
                entered,
                physical: Arc::new(AtomicUsize::new(0)),
                sent: Arc::new(AtomicUsize::new(0)),
            }),
            receiver,
        )
    }
}

impl DeferredEffectAdapter for Adapter {
    fn profile(&self) -> &DispatchProfile {
        &self.profile
    }

    fn accept(
        &self,
        grant: DispatchGrant,
        payload: PayloadRecord,
        attempt: AttemptIdentity,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
        assert_eq!(grant.profile(), &self.profile);
        assert_eq!(grant.effect(), payload.effect());
        assert_eq!(grant.attempt(), attempt.attempt());
        let requires_pause = self.gate_tenant.as_deref() == Some(&grant.scope().tenant);
        let effect = payload.effect().to_owned();
        let (registration, mut tracked) = self.gates.track(payload).unwrap();
        let gates = self.gates.clone();
        let entered = self.entered.clone();
        let physical = Arc::clone(&self.physical);
        let sent = Arc::clone(&self.sent);
        Ok(Box::pin(async move {
            physical.fetch_add(1, Ordering::SeqCst);
            sent.fetch_add(1, Ordering::SeqCst);
            tracked.commit(Stage::Entered).unwrap();
            if requires_pause {
                let mut pause = Box::pin(tracked.pause());
                PollProbe::default().pending(pause.as_mut());
                let ticket = gates.blocked(registration, Stage::Entered).unwrap();
                entered
                    .send(Event {
                        effect,
                        registration,
                        ticket: Some(ticket),
                    })
                    .await
                    .unwrap();
                pause.await;
            } else {
                entered
                    .send(Event {
                        effect,
                        registration,
                        ticket: None,
                    })
                    .await
                    .unwrap();
            }
            drop(tracked); // Payload/provider buffers retire before the receipt.
            physical.fetch_sub(1, Ordering::SeqCst);
            AdapterOutcome {
                receipt: AttemptReceipt {
                    disposition: Disposition::ProviderAcknowledged,
                    reason: "adapter-acknowledged".into(),
                    provider_receipt: Some("provider-receipt".into()),
                    observed_at_millis: 100,
                },
                retry: None,
            }
        }))
    }
}

async fn event(receiver: &mut tokio::sync::mpsc::Receiver<Event>) -> Event {
    with_watchdog(WATCHDOG, receiver.recv()).await.unwrap()
}

async fn wait_disposition(
    fixture: &Fixture,
    authority: &DurableEffectAuthority,
    expected: Disposition,
) {
    with_watchdog(WATCHDOG, async {
        loop {
            if fixture.record(authority).await.disposition() == expected {
                return;
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
}

fn config() -> DispatcherConfig {
    DispatcherConfig {
        page_rows: 2,
        scan_pages_per_tick: 2,
        poll_interval: Duration::from_millis(2),
        ..DispatcherConfig::default()
    }
}
