//! Synthetic conformance endpoint v1. The existing atomic engine is fixture
//! storage only: reservation, mutation counter and receipt share one flush.
use super::*;
use latent_state::embedded::{
    AtomicBatch, EmbeddedStore, Family, RowKey, RowMutation, StoreLimits,
};
use serde::{Deserialize, Serialize};
use std::{fs::OpenOptions, sync::Mutex};
use tokio::net::TcpListener;

mod wire;
pub(super) use wire::{read_wire, Request};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Fault {
    Normal,
    ReserveOnce,
    Status(u16),
    Malformed,
    Oversized,
    Redirect,
    ExpireLookup,
    WrongIncarnation,
    UnknownField,
    Encoded,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Record {
    contract: String,
    effect: String,
    body_sha256: String,
    provider_incarnation: String,
    retain_until_unix_millis: String,
    state: String,
    receipt: Option<String>,
}

struct Identity<'a> {
    effect: &'a str,
    body_sha256: &'a str,
    retain_until: u64,
}

pub(super) struct Shared {
    store: Mutex<EmbeddedStore>,
    clock: Arc<Clock>,
    pub fault: Mutex<Fault>,
    pub token: Mutex<String>,
    pub puts: AtomicU64,
    pub gets: AtomicU64,
}

pub(super) struct Endpoint {
    pub port: u16,
    pub root_certificate: Vec<u8>,
    pub shared: Arc<Shared>,
    stop: tokio::sync::oneshot::Sender<()>,
    task: tokio::task::JoinHandle<()>,
    root: tempfile::TempDir,
}

impl Endpoint {
    pub async fn new(clock: Arc<Clock>, fault: Fault) -> Self {
        let root = tempfile::tempdir().unwrap();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(root.path().join("remote.redb"))
            .unwrap();
        let store = EmbeddedStore::open_file(file, StoreLimits::default()).unwrap();
        store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: counter_key(),
                    value: Some(0_u64.to_le_bytes().to_vec()),
                }],
            })
            .unwrap();
        let shared = Arc::new(Shared {
            store: Mutex::new(store),
            clock,
            fault: Mutex::new(fault),
            token: Mutex::new("synthetic-alpha".into()),
            puts: AtomicU64::new(0),
            gets: AtomicU64::new(0),
        });
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let (root_certificate, acceptor) = certificate();
        let state = shared.clone();
        let (stop, mut stopped) = tokio::sync::oneshot::channel();
        let task = tokio::spawn(async move {
            loop {
                let socket = tokio::select! {
                    result = listener.accept() => result.unwrap().0,
                    _ = &mut stopped => break,
                };
                let Ok(mut socket) = watched(acceptor.accept(socket)).await else {
                    continue;
                };
                let Some(request) = read_wire(&mut socket).await else {
                    continue;
                };
                let current = state.clone();
                let reply = tokio::task::spawn_blocking(move || current.handle(request))
                    .await
                    .unwrap();
                let _ = socket.write_all(&reply).await;
                let _ = socket.shutdown().await;
            }
        });
        Self {
            port,
            root_certificate,
            shared,
            stop,
            task,
            root,
        }
    }

    pub fn counter(&self) -> u64 {
        self.shared.counter()
    }
    pub fn attempts(&self) -> (u64, u64) {
        (
            self.shared.puts.load(Ordering::SeqCst),
            self.shared.gets.load(Ordering::SeqCst),
        )
    }
    pub fn token(&self, token: &str) {
        *self.shared.token.lock().unwrap() = token.into();
    }

    pub fn assert_applied(&self, effect: u64, body: &[u8], receipt: &str, until: u64) {
        let store = self.shared.store.lock().unwrap();
        let bytes = store
            .snapshot()
            .unwrap()
            .get(&record_key(&format!("{effect:064x}")))
            .unwrap()
            .unwrap();
        let record: Record = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(record.contract, "latent.http-effect.put-once.v1");
        assert_eq!(record.effect, format!("{effect:064x}"));
        assert_eq!(record.body_sha256, wire::sha256(body));
        assert_eq!(record.provider_incarnation, "a".repeat(64));
        assert_eq!(record.retain_until_unix_millis, until.to_string());
        assert_eq!(record.state, "applied");
        assert_eq!(record.receipt.as_deref(), Some(receipt));
    }

    pub fn forget_expired(&self, effect: u64) {
        let store = self.shared.store.lock().unwrap();
        let key = record_key(&format!("{effect:064x}"));
        let record: Record =
            serde_json::from_slice(&store.snapshot().unwrap().get(&key).unwrap().unwrap()).unwrap();
        assert!(
            self.shared.clock.observe().unix_millis
                >= record.retain_until_unix_millis.parse::<u64>().unwrap()
        );
        store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation { key, value: None }],
            })
            .unwrap();
    }

    pub async fn finish(self, expected_counter: u64) {
        assert_eq!(self.counter(), expected_counter);
        let _ = self.stop.send(());
        watched(self.task).await.unwrap();
        let expected_records = records(&self.shared.store.lock().unwrap());
        drop(self.shared);
        // Reopening the actual database distinguishes a durable mutation from
        // an in-memory network-attempt count. No fixture reset/truncate occurs.
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.path().join("remote.redb"))
            .unwrap();
        let reopened = EmbeddedStore::open_file(file, StoreLimits::default()).unwrap();
        let bytes = reopened
            .snapshot()
            .unwrap()
            .get(&counter_key())
            .unwrap()
            .unwrap();
        assert_eq!(
            u64::from_le_bytes(bytes.try_into().unwrap()),
            expected_counter
        );
        assert_eq!(records(&reopened), expected_records);
    }
}

fn records(store: &EmbeddedStore) -> Vec<(RowKey, Vec<u8>)> {
    let page = store
        .snapshot()
        .unwrap()
        .scan_after(Family::State, b"put-once-v1/", None, 64, 65_536)
        .unwrap();
    assert!(
        page.resume.is_none(),
        "fixture record inspection must be complete"
    );
    page.rows
}

impl Shared {
    pub fn counter(&self) -> u64 {
        let store = self.store.lock().unwrap();
        let bytes = store
            .snapshot()
            .unwrap()
            .get(&counter_key())
            .unwrap()
            .unwrap();
        u64::from_le_bytes(bytes.try_into().unwrap())
    }

    fn handle(&self, request: Request) -> Vec<u8> {
        if request.method == "PUT" {
            self.puts.fetch_add(1, Ordering::SeqCst);
        } else if request.method == "GET" {
            self.gets.fetch_add(1, Ordering::SeqCst);
        } else {
            return wire::reply(405, b"", "");
        }
        let identity = match self.identify(&request) {
            Ok(identity) => identity,
            Err(status) => return wire::reply(status, b"", ""),
        };
        let mut fault = self.fault.lock().unwrap();
        if let Fault::Status(status) = *fault {
            return wire::reply(status, b"synthetic private reply", "");
        }
        if request.method == "PUT" {
            match *fault {
                Fault::Malformed => {
                    return wire::reply(200, b"{synthetic malformed private reply", "")
                }
                Fault::Oversized => return wire::reply(200, &[b'x'; 1025], ""),
                Fault::Redirect => {
                    return wire::reply(307, b"", "Location: https://unsafe.invalid/other\r\n")
                }
                _ => {}
            }
        }
        match self.commit(&request.method, identity, &mut fault) {
            Ok((status, record)) => reply_record(status, record, *fault),
            Err(status) => wire::reply(status, b"", ""),
        }
    }

    fn identify<'a>(&self, request: &'a Request) -> Result<Identity<'a>, u16> {
        if request.header("authorization")
            != Some(format!("Bearer {}", self.token.lock().unwrap()).as_str())
        {
            return Err(401);
        }
        let Some(effect) = request.path.strip_prefix("/latent-effects/v1/") else {
            return Err(404);
        };
        if !is_hex(effect)
            || request.header("idempotency-key") != Some(effect)
            || request.header("x-lsf-effect-contract") != Some("latent.http-effect.put-once.v1")
            || request.header("x-lsf-effect-provider-incarnation")
                != Some("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        {
            return Err(409);
        }
        let Some(until) = request
            .header("x-lsf-effect-retain-until")
            .and_then(|value| {
                value
                    .parse::<u64>()
                    .ok()
                    .filter(|number| number.to_string() == value)
            })
        else {
            return Err(400);
        };
        let now = self.clock.observe().unix_millis;
        if until <= now || until > now.saturating_add(10_000) {
            return Err(410);
        }
        let Some(hash) = request
            .header("x-lsf-effect-body-sha256")
            .filter(|hash| is_hex(hash))
        else {
            return Err(400);
        };
        if request.method == "PUT" {
            if request.body.len() > 65_536
                || request.header("content-type") != Some("application/octet-stream")
                || hash != wire::sha256(&request.body)
            {
                return Err(409);
            }
        } else if !request.body.is_empty() {
            return Err(400);
        }
        Ok(Identity {
            effect,
            body_sha256: hash,
            retain_until: until,
        })
    }

    fn commit(
        &self,
        method: &str,
        identity: Identity<'_>,
        fault: &mut Fault,
    ) -> Result<(u16, Record), u16> {
        let Identity {
            effect,
            body_sha256: hash,
            retain_until: until,
        } = identity;
        let store = self.store.lock().unwrap();
        let key = record_key(effect);
        let view = store.snapshot().unwrap();
        let existing = view.get(&key).unwrap();
        let mut record: Option<Record> = existing
            .as_deref()
            .map(|bytes| serde_json::from_slice(bytes).unwrap());
        let counter = u64::from_le_bytes(
            view.get(&counter_key())
                .unwrap()
                .unwrap()
                .try_into()
                .unwrap(),
        );
        drop(view);
        if method == "GET" && *fault == Fault::ExpireLookup {
            store
                .apply(AtomicBatch {
                    expectations: vec![],
                    mutations: vec![RowMutation { key, value: None }],
                })
                .unwrap();
            return Err(410);
        }
        if let Some(old) = &record {
            if old.body_sha256 != hash || old.retain_until_unix_millis != until.to_string() {
                return Err(409);
            }
        } else if method == "GET" {
            return Err(404);
        }
        let mut status = 200;
        if method == "PUT"
            && record
                .as_ref()
                .is_none_or(|record| record.state == "reserved")
        {
            let reserve = *fault == Fault::ReserveOnce;
            if reserve {
                *fault = Fault::Normal;
            }
            let receipt = (!reserve)
                .then(|| wire::sha256(format!("put-once-v1:{effect}:{hash}:{until}").as_bytes()));
            record = Some(Record {
                contract: "latent.http-effect.put-once.v1".into(),
                effect: effect.into(),
                body_sha256: hash.into(),
                provider_incarnation: "a".repeat(64),
                retain_until_unix_millis: until.to_string(),
                state: if reserve { "reserved" } else { "applied" }.into(),
                receipt,
            });
            let mut mutations = vec![RowMutation {
                key,
                value: Some(serde_json::to_vec(record.as_ref().unwrap()).unwrap()),
            }];
            if !reserve {
                mutations.push(RowMutation {
                    key: counter_key(),
                    value: Some((counter + 1).to_le_bytes().to_vec()),
                });
            }
            store
                .apply(AtomicBatch {
                    expectations: vec![],
                    mutations,
                })
                .unwrap();
            status = if reserve { 202 } else { 201 };
        }
        Ok((status, record.unwrap()))
    }
}

fn reply_record(status: u16, record: Record, fault: Fault) -> Vec<u8> {
    let mut record = serde_json::to_value(record).unwrap();
    if fault == Fault::WrongIncarnation {
        record["providerIncarnation"] = "b".repeat(64).into();
    }
    if fault == Fault::UnknownField {
        record["privateDebug"] = "synthetic private reply".into();
    }
    let headers = if fault == Fault::Encoded {
        "Content-Encoding: identity\r\n"
    } else {
        ""
    };
    wire::reply(status, &serde_json::to_vec(&record).unwrap(), headers)
}

fn counter_key() -> RowKey {
    RowKey {
        family: Family::Maintenance,
        key: b"qualified-http-fixture-counter-v1".to_vec(),
    }
}
fn record_key(effect: &str) -> RowKey {
    RowKey {
        family: Family::State,
        key: format!("put-once-v1/{effect}").into_bytes(),
    }
}
fn is_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
