//! Bounded Linux observation of this one manual test process, including its peers.
//! Keep the low-level OCI crate independent of testkit's node/provider graph.
use serde_json::{json, Value};
use std::{fs, io::Read};

pub(super) fn capture() -> Value {
    let mut status = String::new();
    fs::File::open("/proc/self/status")
        .unwrap()
        .take(65537)
        .read_to_string(&mut status)
        .unwrap();
    assert!(status.len() <= 65536);
    let number = |key: &str| -> u64 {
        status
            .lines()
            .find_map(|line| line.strip_prefix(key))
            .unwrap()
            .split_whitespace()
            .next()
            .unwrap()
            .parse()
            .unwrap()
    };
    let rss = number("VmRSS:").checked_mul(1024).unwrap();
    let threads = number("Threads:");
    assert!(rss > 0 && threads > 0);
    let mut descriptors = 0_u64;
    let mut sockets = 0_u64;
    for entry in fs::read_dir("/proc/self/fd").unwrap().take(1025) {
        descriptors += 1;
        assert!(descriptors <= 1024);
        let target = fs::read_link(entry.unwrap().path()).unwrap();
        if target.to_string_lossy().starts_with("socket:[") {
            sockets += 1;
        }
    }
    json!({"processId": std::process::id(), "residentMemoryBytes": rss.to_string(),
        "threadCount": threads.to_string(), "openFileDescriptors": descriptors.to_string(),
        "socketCount": sockets.to_string()})
}
