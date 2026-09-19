use latent_capabilities::broker::{
    io::IoRuntime,
    pools::{ProviderPoolSnapshot, ProviderPools},
    ActivationCapabilityBroker,
};
use latent_core::PlatformErrorCode;
use latent_wasmtime::WasmtimeBackend;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    fs,
    io::Read,
    io::Write,
    path::Path,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

macro_rules! fields {
    ($value:expr, $($field:ident),+ $(,)?) => {
        serde_json::json!({$(stringify!($field): $value.$field),+})
    };
}
pub(crate) use fields;

pub fn pool_snapshot(owner: &ProviderPools) -> (ProviderPoolSnapshot, Value) {
    let began = Instant::now();
    for attempt in 1..=32 {
        match owner.snapshot() {
            Ok(current) => {
                assert!(began.elapsed() < Duration::from_millis(50));
                return (
                    current,
                    json!({"attempts": attempt,
                    "elapsedNanos": began.elapsed().as_nanos().to_string(),
                    "maximumAttempts": 32, "deadlineMillis": 50,
                    "retryScope": "only-diagnostic-capability-busy-no-workload-retry"}),
                );
            }
            Err(error) => {
                assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
                assert_eq!(error.message, "capability-busy");
                assert!(began.elapsed() < Duration::from_millis(50));
                std::thread::sleep(Duration::from_micros(200));
            }
        }
    }
    panic!("bounded provider pool observation remained unavailable");
}

pub fn snapshot(
    provider: &str,
    phase: &str,
    backend: &WasmtimeBackend,
    broker: &ActivationCapabilityBroker,
    pools: Option<&ProviderPools>,
    io: Option<&IoRuntime>,
) -> Value {
    let began = Instant::now();
    let started = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
    let runtime = backend.resource_snapshot();
    let broker = broker.snapshot();
    let mut pool_observation = Value::Null;
    let pools = pools.map(|owner| {
        let (current, observation) = pool_snapshot(owner);
        pool_observation = observation;
        fields!(
            current,
            configurations,
            retained_configurations,
            clients,
            connections,
            active_connections,
            connecting_connections,
            retired_connections,
            idle_connections,
            pending_requests,
            running_requests,
            workers,
            cleanup_jobs,
            failed_cleanup,
            metadata_bytes,
            control_owners,
            control_failed,
            closed
        )
    });
    let io = io.map(|owner| {
        let current = owner.snapshot();
        fields!(
            current,
            calls,
            occupied_running_slots,
            queued_calls,
            staged_bytes,
            result_bytes,
            buffers,
            streams,
            metadata_bytes
        )
    });
    json!({
        "provider": provider, "phase": phase, "os": process(),
        "runtime": fields!(runtime, active_invocations, live_stores, live_host_states,
            live_component_instances, live_temporary_buffers, live_cancellation_probes, stores_created),
        "broker": fields!(broker, providers, plans, sessions, handles, calls, results, metadata_bytes, buffer_bytes),
        "providerPools": pools, "providerPoolObservation": pool_observation, "providerIo": io,
        "backendInstanceReservations": backend.active_instance_reservations(),
        "cache": backend.cache_accounting_snapshot(), "compiler": backend.compiler_snapshot(),
        "rendererHeapBytes": null, "rendererHeapAvailability": "not-an-SSR-population",
        "schedulerCellLeases": null, "schedulerCellAvailability": "separate-node-inventory-required",
        "allocatorRetainedBytes": null, "allocatorAvailability": "RSS-and-accounted-bytes-are-different",
        "consistency": "sequential-non-atomic-owner-snapshots",
        "startedUnixNanos": started.as_nanos().to_string(),
        "elapsedNanos": began.elapsed().as_nanos().to_string()
    })
}

fn read_text(path: &str, maximum: u64) -> String {
    let mut contents = String::new();
    fs::File::open(path)
        .unwrap()
        .take(maximum + 1)
        .read_to_string(&mut contents)
        .unwrap();
    assert!(contents.len() as u64 <= maximum);
    contents
}

pub fn process() -> Value {
    let began = Instant::now();
    let status = read_text("/proc/self/status", 131_072);
    let field = |name: &str| {
        status
            .lines()
            .find_map(|line| line.strip_prefix(name))
            .unwrap()
            .split_whitespace()
            .next()
            .unwrap()
            .parse::<u64>()
            .unwrap()
    };
    let mut sockets = BTreeSet::new();
    let mut descriptors = 0;
    for entry in fs::read_dir("/proc/self/fd").unwrap() {
        descriptors += 1;
        assert!(descriptors <= 4096);
        assert!(began.elapsed() < Duration::from_secs(2));
        if let Ok(target) = fs::read_link(entry.unwrap().path()) {
            let target = target.to_string_lossy();
            if let Some(inode) = target
                .strip_prefix("socket:[")
                .and_then(|text| text.strip_suffix(']'))
            {
                sockets.insert(inode.to_owned());
            }
        }
    }
    let mut listeners = BTreeSet::new();
    for table in ["/proc/self/net/tcp", "/proc/self/net/tcp6"] {
        let contents = read_text(table, 1024 * 1024);
        for (ordinal, line) in contents.lines().skip(1).enumerate() {
            assert!(ordinal < 8192);
            assert!(began.elapsed() < Duration::from_secs(2));
            let fields: Vec<_> = line.split_whitespace().collect();
            assert!(fields.len() >= 10);
            if fields[3] == "0A" && sockets.contains(fields[9]) {
                listeners.insert(fields[9].to_owned());
            }
        }
    }
    json!({"processId": std::process::id(), "processes": 1,
        "scope": "test-process-including-in-process-peer",
        "rssBytes": field("VmRSS:") * 1024, "threads": field("Threads:"),
        "handles": descriptors, "sockets": sockets.len(), "listeners": listeners.len(),
        "consistency": "non-atomic-proc-scan",
        "elapsedNanos": began.elapsed().as_nanos().to_string()})
}

pub fn file_digest(path: &Path) -> String {
    let mut file = fs::File::open(path).unwrap();
    assert!(file.metadata().unwrap().len() <= 512 * 1024 * 1024);
    let mut hasher = Sha256::new();
    let mut bytes = vec![0; 65536];
    let mut observed_bytes = 0_u64;
    loop {
        let length = file.read(&mut bytes).unwrap();
        if length == 0 {
            break;
        }
        observed_bytes += length as u64;
        assert!(observed_bytes <= 512 * 1024 * 1024);
        hasher.update(&bytes[..length]);
    }
    format!("sha256:{:x}", hasher.finalize())
}

pub fn publish(observations: &[Value]) {
    assert!(!observations.is_empty() && observations.len() <= 128);
    for provider in ["http", "blob", "secret", "child"] {
        assert!(observations
            .iter()
            .any(|entry| entry["provider"] == provider && entry["phase"] == "active"));
        assert!(observations
            .iter()
            .any(|entry| entry["provider"] == provider && entry["phase"] == "recovery"));
    }
    let value = json!({"schemaVersion":"latent.phase3.resource-regression.v1",
        "status":"checkpoint-passed", "ticketAcceptance":"pending", "observations":observations,
        "binarySha256":file_digest(&std::env::current_exe().unwrap()),
        "fixtureScope":"maintained-component-fixtures-with-real-providers-and-local-manager",
        "runtimePopulations":{"http-blob-secret":"current-thread-maintained-direct-provider-fixtures",
            "child":"separate-fixed-two-worker-local-activation-runtime"},
        "externalServices":"HTTP-controlled-TCP-peer-in-test-process; local-protected-secret-and-blob-stores",
        "pending":["real-Angular-SSR","NATS-event-campaign","OCI-network-campaign","longer-churn"]});
    let encoded = serde_json::to_vec(&value).unwrap();
    assert!(encoded.len() <= 2 * 1024 * 1024);
    if let Some(path) = std::env::var_os("LSF_PHASE3_RESOURCE_REPORT") {
        let path = Path::new(&path);
        assert!(path.is_absolute());
        let mut output = fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(path)
            .unwrap();
        output.write_all(&encoded).unwrap();
        output.sync_all().unwrap();
    }
    println!(
        "resource checkpoint: {} observed ownership snapshots; full ticket pending",
        observations.len()
    );
}
