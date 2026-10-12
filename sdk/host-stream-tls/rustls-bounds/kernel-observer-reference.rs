static PRIVATE_SOCKET_INODES: Mutex<Vec<String>> = Mutex::new(Vec::new());

fn private_observe_socket(tcp: &TcpStream, stage: &str) {
    use std::os::fd::AsRawFd;
    let inode = std::fs::read_link(format!("/proc/self/fd/{}", tcp.as_raw_fd())).unwrap()
        .to_string_lossy().into_owned();
    let port = tcp.local_addr().unwrap().port();
    let socket = socket2::SockRef::from(tcp);
    let send = socket.send_buffer_size().unwrap();
    let receive = socket.recv_buffer_size().unwrap();
    assert!(send + receive <= 96 * 1024);
    let result = std::process::Command::new("ss")
        .args(["-tanm", "--extended", "--no-header", &format!("sport = :{port}")])
        .output().unwrap();
    assert!(result.status.success());
    let mut tracked = PRIVATE_SOCKET_INODES.lock().unwrap();
    if !tracked.contains(&inode) { tracked.push(inode.clone()); }
    println!("LSF_SOCKET_OBSERVATION {}", serde_json::json!({
        "stage": stage, "socketInode": inode, "sendBufferBytes": send,
        "receiveBufferBytes": receive, "logicalKernelAllowanceBytes": 96 * 1024,
        "ss": String::from_utf8(result.stdout).unwrap()}));
}

impl Drop for Transport {
    fn drop(&mut self) {
        private_observe_socket(&self.tcp, "before-physical-drop");
    }
}

pub(crate) fn private_observe_retired_sockets() {
    let tracked = PRIVATE_SOCKET_INODES.lock().unwrap();
    let descriptors: Vec<_> = std::fs::read_dir("/proc/self/fd").unwrap().filter_map(|entry| {
        std::fs::read_link(entry.unwrap().path()).ok()
            .map(|link| link.to_string_lossy().into_owned())
    }).collect();
    assert!(tracked.iter().all(|inode| !descriptors.contains(inode)));
    println!("LSF_SOCKET_RETIREMENT {}", serde_json::json!({
        "trackedSocketCount": tracked.len(), "remainingDescriptors": 0}));
}
