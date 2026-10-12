//! The Linux kernel denies native growth of the selected engine's original
//! file, after durable admission and before one complete envelope publication.
//! The bounded engine backend also denies growth with its storage-full error.
//! Neither schedule claims device ENOSPC or power-loss evidence.
use super::*;
use latent_test_process::process::{OwnedProcess, ProcessLimits};
use rustix::process::{getrlimit, setrlimit, Resource, Rlimit};
use std::{io::Write, os::unix::process::ExitStatusExt, path::Path, process::Command};

const READY: &[u8] = b"ORIGINAL_ENGINE_KERNEL_FILE_LIMIT";
const CHILD: &str = "atomic::tests::io_faults::owned_kernel_file_limit_child";

fn request() -> AdmissionInput {
    let mut request = input("kernel-file-limit");
    request.inbox = Some(InboxIdentity {
        provider: "input".into(),
        binding: "source".into(),
        message: "kernel-file-limit-message".into(),
        payload_digest: Identity::derive(b"input", &[b"kernel-file-limit-message"]),
    });
    request
}

fn pressured_state(view: &latent_state::embedded::ReadView) -> latent_state::session::StatePlan {
    let scope = StateScope {
        tenant: TenantId("tenant".into()),
        namespace: StateNamespaceId("aggregate".into()),
        incarnation: 1,
        state_schema: schema(),
        entity: None,
        mode: StateMode::Command,
    };
    let mut session =
        StateSession::open(view, scope, SessionLimits::default(), state_permission).unwrap();
    // The original source profile permits 8 MiB staging. This closed 2 MiB
    // attempt stays inside it while exceeding the seeded engine's file size.
    let payload = vec![0x5a; 64 * 1024];
    for index in 0..32 {
        session
            .put(
                view,
                format!("pressure/{index:02}").into_bytes(),
                value(&payload),
                state_permission,
            )
            .unwrap();
    }
    session.seal(view, state_permission).unwrap()
}

#[test]
fn original_backend_storage_full_retains_pending_identity_without_partial_envelope() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("state.redb");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)
        .unwrap();
    let (store, status) = EmbeddedStore::open_bounded_file(
        file,
        StoreLimits {
            maximum_key_bytes: 4096,
            maximum_value_bytes: 2 * 1024 * 1024,
            maximum_batch_rows: 1024,
            ..StoreLimits::default()
        },
        2 * 1024 * 1024,
    )
    .unwrap();
    let effects = seed(&store);
    let input = request();
    let owner = claim(&store, request());
    let view = store.snapshot().unwrap();
    let original = inspect(&view, &input.key, time(100), permission).unwrap().0;
    let complete = CompleteEnvelope::success(
        &view,
        owner,
        Some(pressured_state(&view)),
        vec![intent()],
        value(b"must not partially persist"),
        &effects,
        time(101),
    )
    .unwrap();
    // This plan passes logical byte/count preflight. The selected engine's
    // original physical backend must refuse the larger native allocation.
    match complete.publish(&store, |_| Ok(())) {
        PreparedDisposition::RecoveryRequired { identity } => {
            assert_eq!(identity.id, original.id);
            assert_eq!(identity.attempt(), original.attempt());
            assert_eq!(identity.outcome(), Outcome::Pending);
        }
        _ => panic!("physical storage failure cannot prove commit or safe retry"),
    }
    drop(view);
    drop(store);
    assert!(status.close_observed());
    let store = open(&path);
    let view = store.snapshot().unwrap();
    let (command, result) = inspect(&view, &input.key, time(103), permission).unwrap();
    assert_eq!(command.encode().unwrap(), original.encode().unwrap());
    assert!(result.is_none());
    for family in [
        Family::State,
        Family::Outbox,
        Family::Inbox,
        Family::PayloadReference,
    ] {
        assert!(view
            .scan_after(family, b"", None, 128, 1024 * 1024)
            .unwrap()
            .rows
            .is_empty());
    }
    assert!(matches!(
        PreparedAdmission::prepare(&view, request(), time(104), permission).unwrap(),
        AdmissionDecision::Existing(existing) if existing.outcome() == Outcome::Pending
    ));
}

#[test]
fn owned_kernel_file_limit_child() {
    let Ok(root) = std::env::var("LSF_ENVELOPE_IO_CHILD_ROOT") else {
        // Only the owned parent provides this test protocol. The entry point
        // alone establishes no kernel-failure or durability qualification.
        return;
    };
    let path = Path::new(&root).join("state.redb");
    let store = open(&path);
    let effects = seed(&store);
    let owner = claim(&store, request());
    let view = store.snapshot().unwrap();
    let complete = CompleteEnvelope::success(
        &view,
        owner,
        Some(pressured_state(&view)),
        vec![intent()],
        value(b"must not partially persist"),
        &effects,
        time(101),
    )
    .unwrap();
    let original_bytes = std::fs::metadata(&path).unwrap().len();
    assert!(original_bytes < 2 * 1024 * 1024);
    setrlimit(
        Resource::Core,
        Rlimit {
            current: Some(0),
            maximum: Some(0),
        },
    )
    .unwrap();
    setrlimit(
        Resource::Fsize,
        Rlimit {
            current: Some(original_bytes),
            maximum: Some(original_bytes),
        },
    )
    .unwrap();
    assert_eq!(getrlimit(Resource::Fsize).current, Some(original_bytes));
    println!("{}", std::str::from_utf8(READY).unwrap());
    std::io::stdout().flush().unwrap();
    let _ = complete.publish(&store, |authorities| {
        let guard = effects.commit_fence(
            authorities,
            EffectTime {
                unix_millis: 101,
                continuity_proven: true,
            },
        )?;
        permission(CommandAccess::FinalDisposition, None)?;
        drop(guard);
        Ok(())
    });
    panic!("the original engine growth must encounter the kernel file-size limit");
}

#[tokio::test]
async fn original_kernel_io_failure_reopens_without_any_partial_business_envelope() {
    let root = tempfile::tempdir().unwrap();
    let mut command = Command::new(std::env::current_exe().unwrap());
    command
        .args(["--exact", CHILD, "--nocapture"])
        .env("LSF_ENVELOPE_IO_CHILD_ROOT", root.path());
    let retired = OwnedProcess::spawn(command, ProcessLimits::default())
        .unwrap()
        .wait()
        .await
        .unwrap();
    // wait has reaped the exact child and joined both bounded output owners.
    // The positively observed marker excludes startup/fixture failures.
    assert!(retired
        .stdout
        .windows(READY.len())
        .any(|bytes| bytes == READY));
    assert_eq!(retired.status.signal(), Some(25), "expected Linux SIGXFSZ");
    let store = open(&root.path().join("state.redb"));
    let view = store.snapshot().unwrap();
    let input = request();
    let (command, result) = inspect(&view, &input.key, time(103), permission).unwrap();
    assert_eq!(command.outcome(), Outcome::Pending);
    assert!(result.is_none());
    assert!(command.effect_ids().is_empty());
    for family in [
        Family::State,
        Family::Outbox,
        Family::Inbox,
        Family::PayloadReference,
    ] {
        assert!(view
            .scan_after(family, b"", None, 128, 1024 * 1024)
            .unwrap()
            .rows
            .is_empty());
    }
    assert_eq!(command.key(), &input.key);
    assert_eq!(command.source(), &input.source);
    assert_eq!(command.result_read_policy(), input.result_read_policy);
}
