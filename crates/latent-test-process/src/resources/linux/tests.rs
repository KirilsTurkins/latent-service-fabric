use super::*;

fn process(root: &Path, pid: u32, parent_id: u32, task_ids: &[u32], start: u64) -> PathBuf {
    let path = root.join(pid.to_string());
    std::fs::create_dir_all(path.join("fd")).unwrap();
    std::fs::create_dir_all(path.join("net")).unwrap();
    for task in task_ids {
        let task = path.join("task").join(task.to_string());
        std::fs::create_dir_all(&task).unwrap();
        std::fs::write(task.join("children"), b"").unwrap();
    }
    std::fs::write(
        path.join("stat"),
        format!(
            "{pid} (fixture) S {parent_id} 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 {start}\n"
        ),
    )
    .unwrap();
    std::fs::write(
        path.join("status"),
        format!("VmRSS: 12 kB\nThreads: {}\n", task_ids.len()),
    )
    .unwrap();
    let header = b"sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n";
    for name in ["tcp", "tcp6"] {
        std::fs::write(path.join("net").join(name), header).unwrap();
    }
    path
}

#[test]
fn descendants_created_by_other_tasks_are_included_and_bounded() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path();
    let parent = process(root, 11, 1, &[11, 12], 100);
    process(root, 21, 11, &[21], 200);
    std::fs::write(parent.join("task/12/children"), b"21").unwrap();
    let expected = ProcessIdentity {
        process_id: 11,
        start_time_ticks: 100,
    };
    let observed = capture_at(root, expected, ProbeLimits::default(), 1).unwrap();
    assert_eq!(
        observed.descendants,
        vec![ProcessIdentity {
            process_id: 21,
            start_time_ticks: 200
        }]
    );
    assert!(capture_at(
        root,
        expected,
        ProbeLimits {
            maximum_descendants: 0,
            ..ProbeLimits::default()
        },
        1
    )
    .is_err());
    assert!(capture_at(
        root,
        ProcessIdentity {
            start_time_ticks: 101,
            ..expected
        },
        ProbeLimits::default(),
        1
    )
    .is_err());
}

#[test]
fn disappearing_fd_and_missing_or_oversized_proc_files_are_unavailable() {
    let directory = tempfile::tempdir().unwrap();
    let expected = ProcessIdentity {
        process_id: 11,
        start_time_ticks: 100,
    };
    let path = process(directory.path(), 11, 1, &[11], 100);
    assert!(capture_at(
        directory.path(),
        expected,
        ProbeLimits {
            maximum_file_bytes: 1,
            ..ProbeLimits::default()
        },
        1
    )
    .is_err());
    assert!(capture_at(
        directory.path(),
        expected,
        ProbeLimits {
            maximum_total_bytes: 1,
            ..ProbeLimits::default()
        },
        1
    )
    .is_err());
    std::fs::write(path.join("fd/1"), b"not a symlink").unwrap();
    assert!(capture_at(directory.path(), expected, ProbeLimits::default(), 1).is_err());
    std::fs::remove_file(path.join("fd/1")).unwrap();
    std::fs::remove_file(path.join("net/tcp6")).unwrap();
    assert!(capture_at(directory.path(), expected, ProbeLimits::default(), 1).is_err());
}

#[test]
fn reused_foreign_pid_is_not_reported_as_an_owned_descendant() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path();
    let parent = process(root, 11, 1, &[11, 12], 100);
    // Simulate a stale children-file PID now owned by an unrelated process.
    process(root, 21, 99, &[21], 200);
    std::fs::write(parent.join("task/12/children"), b"21").unwrap();
    let error = capture_at(
        root,
        ProcessIdentity {
            process_id: 11,
            start_time_ticks: 100,
        },
        ProbeLimits::default(),
        1,
    )
    .unwrap_err();
    assert_eq!(error.kind(), io::ErrorKind::Interrupted);
    assert_eq!(error.to_string(), "child process parent relation changed");
}
