use std::fs::File;
use std::io::Read;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

const CHILD_ENV: &str = "LSF_SHUTDOWN_TEST_CHILD";
const COMPLETE: &str = "standalone-shutdown-assertions-completed";
const MAXIMUM_OUTPUT_BYTES: u64 = 64 * 1024;

struct OwnedChild(Child);
impl Drop for OwnedChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

pub fn supervise(name: &str, scenario: fn()) {
    if std::env::var(CHILD_ENV).as_deref() == Ok(name) {
        scenario();
        println!("{COMPLETE}");
        return;
    }
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("child.log");
    let log = File::create(&path).unwrap();
    let mut child = OwnedChild(
        Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                name,
                "--include-ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(CHILD_ENV, name)
            .stdin(Stdio::null())
            .stdout(log.try_clone().unwrap())
            .stderr(log)
            .spawn()
            .unwrap(),
    );
    let deadline = Instant::now() + Duration::from_secs(20);
    let status = loop {
        if std::fs::metadata(&path).unwrap().len() > MAXIMUM_OUTPUT_BYTES
            || Instant::now() >= deadline
        {
            child.0.kill().unwrap();
            child.0.wait().unwrap();
            break None;
        }
        if let Some(status) = child.0.try_wait().unwrap() {
            break Some(status);
        }
        std::thread::sleep(Duration::from_millis(5));
    };
    let mut output = String::new();
    File::open(path)
        .unwrap()
        .take(MAXIMUM_OUTPUT_BYTES + 1)
        .read_to_string(&mut output)
        .unwrap();
    assert!(
        status.is_some_and(|status| status.success())
            && output.len() as u64 <= MAXIMUM_OUTPUT_BYTES
            && output.contains(COMPLETE),
        "bounded shutdown scenario failed: {status:?}\n{output}"
    );
}
