use super::*;

#[test]
fn observed_u64_values_and_unavailable_fields_roundtrip_losslessly() {
    let value = ChildProcessResources {
        identity: ProcessIdentity {
            process_id: 1,
            start_time_ticks: u64::MAX,
        },
        process: ProcessResources {
            process_id: 1,
            resident_memory_bytes: Some(u64::MAX),
            thread_count: Some(2),
            open_file_descriptors: None,
            socket_count: Some(0),
        },
        task_count: 2,
        unique_socket_count: 0,
        listening_tcp_socket_count: 0,
        descendants: Vec::new(),
        sample_attempts: 1,
    };
    let json = serde_json::to_value(&value).unwrap();
    assert_eq!(json["identity"]["startTimeTicks"], u64::MAX.to_string());
    assert!(json["process"]["openFileDescriptors"].is_null());
    assert_eq!(json["process"]["socketCount"], "0");
    assert_eq!(
        serde_json::from_value::<ChildProcessResources>(json.clone()).unwrap(),
        value
    );
    for malformed in [
        serde_json::json!(1),
        serde_json::json!("01"),
        serde_json::json!("+1"),
    ] {
        let mut json = json.clone();
        json["taskCount"] = malformed;
        assert!(serde_json::from_value::<ChildProcessResources>(json).is_err());
    }
}

#[cfg(target_os = "linux")]
#[test]
fn resource_child_fixture() {
    use std::io::Write;
    let Some(marker) = std::env::var_os("LSF_RESOURCE_PROBE_CHILD") else {
        return;
    };
    assert_eq!(marker, "listener");
    let _listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    println!("RESOURCE_PROBE_READY");
    std::io::stdout().flush().unwrap();
    // The parent kills/reaps this leaf process immediately after sampling.
    std::thread::park_timeout(std::time::Duration::from_secs(30));
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn captures_the_live_child_listener_and_rejects_foreign_or_exited_owners() {
    use crate::process::ProcessLimits;
    use std::process::Command;
    use std::time::Duration;

    let mut command = Command::new(std::env::current_exe().unwrap());
    command
        .args([
            "--exact",
            "resources::child::tests::resource_child_fixture",
            "--nocapture",
            "--test-threads=1",
        ])
        .env("LSF_RESOURCE_PROBE_CHILD", "listener");
    let mut child = OwnedProcess::spawn(command, ProcessLimits::default()).unwrap();
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            if String::from_utf8(child.stdout_snapshot().unwrap())
                .unwrap()
                .contains("RESOURCE_PROBE_READY")
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    let probe = ChildProcessProbe::bind(&mut child, ProbeLimits::default()).unwrap();
    let observed = probe.capture(&mut child).unwrap();
    assert_ne!(observed.identity.process_id, std::process::id());
    assert_eq!(observed.identity.process_id, child.id());
    assert!(observed.process.resident_memory_bytes.unwrap() > 0);
    assert_eq!(observed.process.thread_count, Some(observed.task_count));
    assert_eq!(observed.unique_socket_count, 1);
    assert_eq!(observed.listening_tcp_socket_count, 1);
    assert!(observed.descendants.is_empty());

    let mut command = Command::new("/bin/sh");
    command.args(["-c", "exec sleep 30"]);
    let mut foreign = OwnedProcess::spawn(command, ProcessLimits::default()).unwrap();
    assert_eq!(
        probe.capture(&mut foreign).unwrap_err().kind(),
        io::ErrorKind::InvalidInput
    );
    foreign.terminate().await.unwrap();
    let limited = ChildProcessProbe::bind(
        &mut child,
        ProbeLimits {
            maximum_file_descriptors: 1,
            ..ProbeLimits::default()
        },
    )
    .unwrap();
    assert!(limited.capture(&mut child).is_err());
    child.terminate().await.unwrap();

    let mut command = Command::new("/bin/sh");
    command.args(["-c", "exit 0"]);
    let mut exited = OwnedProcess::spawn(command, ProcessLimits::default()).unwrap();
    tokio::time::timeout(Duration::from_secs(2), async {
        while exited.try_status().unwrap().is_none() {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        ChildProcessProbe::bind(&mut exited, ProbeLimits::default())
            .err()
            .unwrap()
            .kind(),
        io::ErrorKind::NotFound
    );
    exited.wait().await.unwrap();
}
