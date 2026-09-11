use super::*;

#[test]
fn process_name_parentheses_and_spaces_cannot_shift_start_time() {
    let record = b"91 (a strange ) process) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 18446744073709551615 20\n";
    assert_eq!(
        identity(record).unwrap(),
        ProcessIdentity {
            process_id: 91,
            start_time_ticks: u64::MAX
        }
    );
    assert_eq!(stat(record).unwrap().parent_process_id, 1);
    assert!(identity(b"91 (bad) S 1 2").is_err());
    assert!(identity(b"no pid (bad) S").is_err());
}

#[test]
fn rss_units_absence_and_overflow_are_not_zero_measurements() {
    assert_eq!(
        status(b"Name:\tnode\nVmRSS:\t12 kB\nThreads:\t3\n").unwrap(),
        (12288, 3)
    );
    for record in [
        b"Threads: 3\n".as_slice(),
        b"VmRSS: 12 B\nThreads: 3\n",
        b"VmRSS: 18446744073709551615 kB\nThreads: 3\n",
        b"VmRSS: 12 kB\nThreads: 0\n",
        b"VmRSS: 12 kB\nVmRSS: 13 kB\nThreads: 3\n",
    ] {
        assert!(status(record).is_err());
    }
}

#[test]
fn tcp_listener_counts_intersect_owned_inodes_instead_of_namespace_totals() {
    let table = b"sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n0: 0:1 0:0 0A 0:0 0:0 0 0 0 11\n1: 0:2 0:0 0A 0:0 0:0 0 0 0 22\n2: 0:3 0:0 01 0:0 0:0 0 0 0 33\n";
    assert_eq!(
        listeners(table, &BTreeSet::from([22, 33]), 3).unwrap(),
        BTreeSet::from([22])
    );
    assert!(listeners(table, &BTreeSet::new(), 2).is_err());
    assert!(listeners(b"invalid header\n", &BTreeSet::new(), 1).is_err());
    assert_eq!(socket_inode(b"socket:[33]").unwrap(), Some(33));
    assert_eq!(socket_inode(b"/tmp/unrelated").unwrap(), None);
    assert!(socket_inode(b"socket:[invalid]").is_err());
}

#[test]
fn descendant_lists_have_an_independent_count_bound() {
    assert_eq!(children(b"1 2\n", 2).unwrap(), vec![1, 2]);
    assert!(children(b"1 2 3", 2).is_err());
    assert!(children(b"not-a-pid", 2).is_err());
}
