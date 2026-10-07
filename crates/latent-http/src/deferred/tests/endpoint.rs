//! A bounded reference endpoint with one durable counter/receipt transaction.
use super::super::qualification::ENDPOINT_CONTRACT;
use super::fixture::{call, WATCHDOG};
use latent_state::embedded::{AtomicBatch, ExpectedRow, Family, RowKey, RowMutation, StoreError};
use latent_state::protected_store::{ProtectedStoreConfig, ProtectedStoreOwner};
use latent_state::store_io::StoreIoKind;
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc,
    },
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::oneshot,
};

const RETENTION: u64 = 10_000;
const MAX_REQUEST: usize = 8192;
const COUNTER: &[u8] = b"reference-counter-v1";
const INCARNATION: &[u8] = b"reference-incarnation-v1";

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Record {
    format_version: u32,
    idempotency_key: String,
    body_digest: String,
    endpoint_incarnation: String,
    sequence: u64,
    created_at_millis: u64,
}

pub struct WireRequest {
    pub method: String,
    pub path: String,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

impl WireRequest {
    pub fn header(&self, name: &str) -> &str {
        let mut fields = self
            .headers
            .iter()
            .filter(|(key, _)| key.eq_ignore_ascii_case(name));
        let Some((_, value)) = fields.next() else {
            return "";
        };
        assert!(fields.next().is_none(), "duplicate fixture request header");
        value
    }
}

pub struct Endpoint {
    pub port: u16,
    pub clock: Arc<AtomicU64>,
    pub reject: Arc<AtomicBool>,
    store: Arc<ProtectedStoreOwner>,
    stop: oneshot::Sender<()>,
    task: tokio::task::JoinHandle<()>,
}

impl Endpoint {
    pub async fn open(root: PathBuf) -> Self {
        fs::create_dir(&root).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        let mut config = ProtectedStoreConfig::bounded_linux(root);
        config.create_if_missing = true;
        config.engine.maximum_rows = 65;
        config.engine.maximum_logical_bytes = 65536;
        let store = Arc::new(
            ProtectedStoreOwner::start_validated(config, 0, validate)
                .unwrap()
                .await
                .unwrap(),
        );
        call(&store, StoreIoKind::Write, |db| {
            db.apply(AtomicBatch {
                expectations: vec![ExpectedRow {
                    key: incarnation_key(),
                    value: None,
                }],
                mutations: vec![RowMutation {
                    key: incarnation_key(),
                    value: Some(vec![b'c'; 64]),
                }],
            })
            .unwrap();
        })
        .await;
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let clock = Arc::new(AtomicU64::new(100));
        let reject = Arc::new(AtomicBool::new(false));
        let (stop, mut closed) = oneshot::channel();
        let services = (store.clone(), clock.clone(), reject.clone());
        let task = tokio::spawn(async move {
            loop {
                let (mut stream, _) = tokio::select! {
                    _ = &mut closed => break,
                    accepted = listener.accept() => accepted.unwrap(),
                };
                let services = &services;
                tokio::time::timeout(WATCHDOG, async {
                    let request = read_request(&mut stream)
                        .await
                        .expect("proxy forwards a full request");
                    let reply = execute(services, request).await;
                    stream.write_all(&reply).await.unwrap();
                    stream.shutdown().await.unwrap();
                })
                .await
                .expect("bounded reference endpoint request");
            }
        });
        Self {
            port,
            clock,
            reject,
            store,
            stop,
            task,
        }
    }

    pub async fn counter(&self) -> u64 {
        call(&self.store, StoreIoKind::Read, |db| {
            let view = db.snapshot().unwrap();
            counter(view.get(&counter_key()).unwrap().as_deref())
        })
        .await
    }

    pub async fn record(&self, key: &str) -> serde_json::Value {
        let key = receipt_key(key);
        call(&self.store, StoreIoKind::Read, move |db| {
            let view = db.snapshot().unwrap();
            serde_json::from_slice(&view.get(&key).unwrap().unwrap()).unwrap()
        })
        .await
    }

    pub async fn erase_receipts(&self) {
        call(&self.store, StoreIoKind::Write, |db| {
            let view = db.snapshot().unwrap();
            let rows = view.scan(Family::Result, b"", 64, 65536).unwrap();
            let mutations = rows
                .into_iter()
                .map(|(key, _)| RowMutation { key, value: None })
                .collect();
            db.apply(AtomicBatch {
                expectations: vec![],
                mutations,
            })
            .unwrap();
        })
        .await;
    }

    pub async fn recreate(&self) {
        call(&self.store, StoreIoKind::Write, |db| {
            let view = db.snapshot().unwrap();
            db.apply(AtomicBatch {
                expectations: vec![ExpectedRow {
                    key: incarnation_key(),
                    value: view.get(&incarnation_key()).unwrap(),
                }],
                mutations: vec![RowMutation {
                    key: incarnation_key(),
                    value: Some(vec![b'd'; 64]),
                }],
            })
            .unwrap();
        })
        .await;
    }

    pub async fn finish(self) {
        let _ = self.stop.send(());
        tokio::time::timeout(WATCHDOG, self.task)
            .await
            .unwrap()
            .unwrap();
        let deadline = std::time::Instant::now() + WATCHDOG;
        let report = self
            .store
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await;
        assert!(report.clean, "{report:?}");
        self.store.reap_retired_threads().unwrap();
    }
}

type Services = (Arc<ProtectedStoreOwner>, Arc<AtomicU64>, Arc<AtomicBool>);

async fn execute(services: &Services, request: WireRequest) -> Vec<u8> {
    let incarnation = call(&services.0, StoreIoKind::Read, |db| {
        String::from_utf8(
            db.snapshot()
                .unwrap()
                .get(&incarnation_key())
                .unwrap()
                .unwrap(),
        )
        .unwrap()
    })
    .await;
    if request.header("authorization") != "Bearer synthetic-http-reference" {
        return response(403, &incarnation, b"{}");
    }
    if request.header("lsf-endpoint-contract") != ENDPOINT_CONTRACT
        || request.header("lsf-endpoint-incarnation") != incarnation
        || request.header("lsf-idempotency-retention-millis") != RETENTION.to_string()
    {
        return response(421, &incarnation, b"{}");
    }
    if request.method == "GET" && request.path == "/effect" {
        return response(
            200,
            &incarnation,
            &serde_json::to_vec(&json!({
                "formatVersion":1, "contract":ENDPOINT_CONTRACT, "endpointIncarnation":incarnation,
                "retentionMillis":RETENTION, "maximumPayloadBytes":8192,
            }))
            .unwrap(),
        );
    }
    let key = request.header("idempotency-key").to_owned();
    let digest = request.header("lsf-body-sha256").to_owned();
    if !key
        .strip_prefix("lsf-effect-")
        .is_some_and(super::super::qualification::digest)
        || !super::super::qualification::digest(&digest)
    {
        return response(400, &incarnation, b"{}");
    }
    let now = services.1.load(Ordering::Acquire);
    if request.method == "GET" && request.path == format!("/receipts/{key}") {
        let row = receipt_key(&key);
        let existing = call(&services.0, StoreIoKind::Read, move |db| {
            db.snapshot().unwrap().get(&row).unwrap()
        })
        .await;
        let (status, body) = receipt(existing.as_deref(), &key, &digest, &incarnation, now);
        return response(status, &incarnation, &body);
    }
    if request.method != "POST"
        || request.path != "/effect"
        || request.body.len() > MAX_REQUEST
        || request.header("content-type") != "text/plain"
        || format!(
            "{:x}",
            latent_core::digest::HexDigest(Sha256::digest(&request.body))
        ) != digest
    {
        return response(400, &incarnation, b"{}");
    }
    if services.2.load(Ordering::Acquire) {
        return response(422, &incarnation, &serde_json::to_vec(&json!({"formatVersion":1,"endpointIncarnation":incarnation,"idempotencyKey":key,"bodyDigest":digest,"outcome":"rejected","sequence":0,"duplicate":false})).unwrap());
    }
    let (status, body) = commit(&services.0, key, digest, incarnation.clone(), now).await;
    response(status, &incarnation, &body)
}

async fn commit(
    store: &ProtectedStoreOwner,
    key: String,
    digest: String,
    scope: String,
    now: u64,
) -> (u16, Vec<u8>) {
    call(store, StoreIoKind::Write, move |db| {
        let view = db.snapshot().unwrap();
        let current_incarnation = view.get(&incarnation_key()).unwrap().unwrap();
        if current_incarnation != scope.as_bytes() {
            return (421, b"{}".to_vec());
        }
        let row = receipt_key(&key);
        let prior = view.get(&row).unwrap();
        if prior.is_some() {
            return receipt(prior.as_deref(), &key, &digest, &scope, now);
        }
        let previous = view.get(&counter_key()).unwrap();
        let sequence = counter(previous.as_deref()).checked_add(1).unwrap();
        let record = Record {
            format_version: 1,
            idempotency_key: key,
            body_digest: digest,
            endpoint_incarnation: scope.clone(),
            sequence,
            created_at_millis: now,
        };
        let bytes = serde_json::to_vec(&record).unwrap();
        db.apply(AtomicBatch {
            expectations: vec![
                ExpectedRow {
                    key: row.clone(),
                    value: None,
                },
                ExpectedRow {
                    key: counter_key(),
                    value: previous,
                },
                ExpectedRow {
                    key: incarnation_key(),
                    value: Some(current_incarnation),
                },
            ],
            mutations: vec![
                RowMutation {
                    key: row,
                    value: Some(bytes.clone()),
                },
                RowMutation {
                    key: counter_key(),
                    value: Some(sequence.to_le_bytes().to_vec()),
                },
            ],
        })
        .unwrap();
        let (_, body) = receipt(
            Some(&bytes),
            &record.idempotency_key,
            &record.body_digest,
            &scope,
            now,
        );
        let mut answer: serde_json::Value = serde_json::from_slice(&body).unwrap();
        answer["duplicate"] = false.into();
        (201, serde_json::to_vec(&answer).unwrap())
    })
    .await
}

fn receipt(
    bytes: Option<&[u8]>,
    key: &str,
    digest: &str,
    incarnation: &str,
    now: u64,
) -> (u16, Vec<u8>) {
    let record: Option<Record> = bytes.map(|bytes| serde_json::from_slice(bytes).unwrap());
    let (status, outcome, sequence, duplicate, body_digest) = match &record {
        None => (404, "absent", 0, false, digest),
        Some(record) if record.body_digest != digest => {
            (409, "conflict", 0, false, record.body_digest.as_str())
        }
        Some(record)
            if record.endpoint_incarnation != incarnation
                || now >= record.created_at_millis + RETENTION =>
        {
            (410, "expired", 0, false, digest)
        }
        Some(record) => (200, "accepted", record.sequence, true, digest),
    };
    (status, serde_json::to_vec(&json!({"formatVersion":1,"endpointIncarnation":incarnation,"idempotencyKey":key,"bodyDigest":body_digest,"outcome":outcome,"sequence":sequence,"duplicate":duplicate})).unwrap())
}

pub fn response(status: u16, incarnation: &str, body: &[u8]) -> Vec<u8> {
    let mut response = format!("HTTP/1.1 {status} Fixture\r\nContent-Length: {}\r\nContent-Type: application/json\r\nLsf-Endpoint-Contract: {ENDPOINT_CONTRACT}\r\nLsf-Endpoint-Incarnation: {incarnation}\r\nLsf-Idempotency-Retention-Millis: {RETENTION}\r\nConnection: close\r\n\r\n", body.len()).into_bytes();
    response.extend_from_slice(body);
    response
}

fn counter_key() -> RowKey {
    RowKey {
        family: Family::State,
        key: COUNTER.into(),
    }
}
fn incarnation_key() -> RowKey {
    RowKey {
        family: Family::Maintenance,
        key: INCARNATION.into(),
    }
}
fn receipt_key(key: &str) -> RowKey {
    RowKey {
        family: Family::Result,
        key: key.as_bytes().to_vec(),
    }
}
fn counter(bytes: Option<&[u8]>) -> u64 {
    bytes.map_or(0, |bytes| u64::from_le_bytes(bytes.try_into().unwrap()))
}
fn validate(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    if *key == counter_key() && bytes.len() == 8 {
        return Ok(());
    }
    if *key == incarnation_key()
        && std::str::from_utf8(bytes)
            .ok()
            .is_some_and(super::super::qualification::digest)
    {
        return Ok(());
    }
    if key.family != Family::Result || bytes.len() > 2048 {
        return Err(StoreError::Corrupt);
    }
    let record: Record = serde_json::from_slice(bytes).map_err(|_| StoreError::Corrupt)?;
    if record.format_version != 1
        || record.sequence == 0
        || record.idempotency_key.as_bytes() != key.key
        || !record
            .idempotency_key
            .strip_prefix("lsf-effect-")
            .is_some_and(super::super::qualification::digest)
        || !super::super::qualification::digest(&record.body_digest)
        || !super::super::qualification::digest(&record.endpoint_incarnation)
    {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}

pub async fn read_request(stream: &mut (impl AsyncRead + Unpin)) -> Option<WireRequest> {
    let mut bytes = Vec::with_capacity(16384);
    while !bytes.ends_with(b"\r\n\r\n") {
        assert!(bytes.len() < 16384);
        let mut byte = [0];
        if stream.read(&mut byte).await.unwrap_or(0) == 0 {
            return None;
        }
        bytes.push(byte[0]);
    }
    let text = std::str::from_utf8(&bytes).unwrap();
    let mut lines = text.split("\r\n");
    let mut first = lines.next().unwrap().split(' ');
    let method = first.next().unwrap().into();
    let path = first.next().unwrap().into();
    assert_eq!(first.next(), Some("HTTP/1.1"));
    let headers: Vec<_> = lines
        .filter(|line| !line.is_empty())
        .map(|line| {
            let (name, value) = line.split_once(':').unwrap();
            (name.to_ascii_lowercase(), value.trim().to_owned())
        })
        .collect();
    assert!(headers.len() <= 32);
    let length = headers
        .iter()
        .find_map(|(name, value)| {
            (name == "content-length").then(|| value.parse::<usize>().unwrap())
        })
        .unwrap_or(0);
    assert!(length <= MAX_REQUEST);
    let mut body = vec![0; length];
    stream.read_exact(&mut body).await.unwrap();
    Some(WireRequest {
        method,
        path,
        headers,
        body,
    })
}
