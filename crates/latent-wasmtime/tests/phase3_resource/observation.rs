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

// Native all-features debug harnesses include the runtime/compiler and can
// exceed 512 MiB. This bounds identity input, not guest memory or provider use.
const MAX_EXECUTABLE_BYTES: u64 = 2 * 1024 * 1024 * 1024;

pub fn file_digest(path: &Path) -> String {
    file_digest_with_limit(path, MAX_EXECUTABLE_BYTES)
}

fn file_digest_with_limit(path: &Path, maximum: u64) -> String {
    let mut file = fs::File::open(path).unwrap();
    let metadata = file.metadata().unwrap();
    assert!(metadata.is_file());
    assert!(metadata.len() <= maximum);
    let (digest, observed) = read_digest(&mut file, metadata.len());
    assert_eq!(observed, metadata.len(), "identity input was truncated");
    assert_eq!(file.metadata().unwrap().len(), observed);
    digest
}

fn read_digest(reader: impl Read, maximum: u64) -> (String, u64) {
    let began = Instant::now();
    // Read at most one byte past the bound so growing inputs cannot extend work.
    let mut reader = reader.take(maximum.checked_add(1).unwrap());
    let mut hasher = Sha256::new();
    let mut bytes = vec![0; 65_536];
    let mut observed_bytes = 0_u64;
    loop {
        let length = reader.read(&mut bytes).unwrap();
        assert!(began.elapsed() < Duration::from_secs(30));
        if length == 0 {
            break;
        }
        observed_bytes += length as u64;
        assert!(
            observed_bytes <= maximum,
            "identity input exceeds byte limit"
        );
        hasher.update(&bytes[..length]);
    }
    (
        format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(hasher.finalize())
        ),
        observed_bytes,
    )
}

// Run within the existing registered checkpoint so every ordinary invocation
// checks exact-boundary hashing and both independent overflow guards.
pub fn check_file_digest_bounds() {
    use std::{io::Cursor, panic::catch_unwind};

    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("digest-boundary");
    let payload = b"artifact";
    fs::write(&path, payload).unwrap();
    let expected = format!(
        "sha256:{:x}",
        latent_core::digest::HexDigest(Sha256::digest(payload))
    );
    assert_eq!(file_digest_with_limit(&path, 8), expected);
    assert_eq!(read_digest(Cursor::new(payload), 8).0, expected);
    assert_eq!(
        read_digest(Cursor::new([]), 0).0,
        format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(Sha256::digest([]))
        )
    );
    // Reject a known oversized file before reading and reject a reader
    // that grows beyond the allowed length independently of metadata.
    assert!(catch_unwind(|| file_digest_with_limit(&path, 7)).is_err());
    assert!(catch_unwind(|| read_digest(Cursor::new(payload), 7)).is_err());
}

pub fn publish(observations: &[Value]) {
    assert!(!observations.is_empty() && observations.len() <= 128);
    for provider in ["http", "blob", "secret", "event", "child"] {
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
        "runtimePopulations":{"http-blob-secret-event":"current-thread-maintained-direct-provider-fixtures",
            "child":"separate-fixed-two-worker-local-activation-runtime"},
        "externalServices":"HTTP-and-NATS-controlled-TCP-TLS-peers-in-test-process; local-protected-secret-and-blob-stores",
        "pending":["real-Angular-SSR","OCI-network-campaign","longer-churn"]});
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn executable_identity_hashes_all_bytes_with_a_fixed_buffer() {
        let input = vec![42; 2 * 65536 + 7];
        let expected = format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(Sha256::digest(&input))
        );
        assert_eq!(
            read_digest(Cursor::new(&input), input.len() as u64),
            (expected.clone(), input.len() as u64)
        );
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("harness");
        fs::write(&path, &input).unwrap();
        assert_eq!(file_digest(&path), expected);
        assert_eq!(
            read_digest(Cursor::new([]), 0),
            (
                "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855".into(),
                0
            )
        );
    }

    #[test]
    fn executable_identity_rejects_overflow_without_unbounded_reading() {
        let mut input = Cursor::new([42; 64]);
        let result =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| read_digest(&mut input, 7)));
        assert!(result.is_err());
        assert_eq!(input.position(), 8);
        // A sparse oversized file must be rejected before any payload is read.
        let file = tempfile::NamedTempFile::new().unwrap();
        file.as_file().set_len(MAX_EXECUTABLE_BYTES + 1).unwrap();
        assert!(std::panic::catch_unwind(|| file_digest(file.path())).is_err());
    }
}
