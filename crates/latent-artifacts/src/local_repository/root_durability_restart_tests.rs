use std::io::Read;
use std::process::{Child, Command, ExitStatus, Stdio};

use super::*;

const CHILD_ROOT: &str = "LSF_ARTIFACT_RELATIVE_ROOT_CHILD";
const CHILD_TEST: &str = "local_repository::tests::root_durability::restart::relative_root_identity_survives_working_directory_change";
const VERIFIED: &str = "cwd-shift-verified";

struct SupervisedChild(Child);

impl SupervisedChild {
    fn wait(&mut self) -> Option<ExitStatus> {
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            if let Some(status) = self.0.try_wait().expect("poll isolated child") {
                return Some(status);
            }
            if Instant::now() >= deadline {
                self.0.kill().expect("kill timed-out child");
                self.0.wait().expect("reap timed-out child");
                return None;
            }
            thread::sleep(Duration::from_millis(10));
        }
    }
}

impl Drop for SupervisedChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn child_output(path: &Path) -> String {
    let mut output = String::new();
    fs::File::open(path)
        .expect("child log")
        .take(64 * 1024)
        .read_to_string(&mut output)
        .expect("bounded child output");
    output
}

#[test]
fn relative_root_identity_survives_working_directory_change() {
    if let Some(root) = std::env::var_os(CHILD_ROOT) {
        exercise_working_directory_change(Path::new(&root));
        return;
    }

    let scratch = TempRoot::new();
    let root = fs::canonicalize(scratch.path()).expect("absolute child root");
    let log_path = root.join("child.log");
    let log = fs::File::create(&log_path).expect("child output log");
    let mut child = SupervisedChild(
        Command::new(std::env::current_exe().expect("current test executable"))
            .args(["--exact", CHILD_TEST, "--nocapture", "--test-threads=1"])
            .env(CHILD_ROOT, &root)
            .current_dir(&root)
            .stdin(Stdio::null())
            .stdout(log.try_clone().expect("clone child log"))
            .stderr(log)
            .spawn()
            .expect("spawn isolated working-directory regression"),
    );
    let status = child.wait();
    assert!(
        status.is_some_and(|status| status.success()),
        "working-directory child must succeed within five seconds: {status:?}\n{}",
        child_output(&log_path)
    );
    assert_eq!(
        fs::read(root.join(VERIFIED)).expect("child executed every assertion"),
        b"relative catalog identity preserved\n"
    );
}

fn exercise_working_directory_change(root: &Path) {
    let directory_a = root.join("a");
    let directory_b = root.join("b");
    fs::create_dir(&directory_a).expect("working directory A");
    fs::create_dir(&directory_b).expect("working directory B");

    // This process runs exactly this test. Its cwd changes cannot affect any
    // parallel tests in the parent process or redirect their temporary cleanup.
    std::env::set_current_dir(&directory_a).expect("enter directory A");
    let catalog_a = open(Path::new("catalog")).expect("relative catalog A");
    let root_a = directory_a.join("catalog");
    assert_eq!(catalog_a.root(), root_a);
    std::env::set_current_dir(&directory_b).expect("enter directory B");
    let catalog_b = open(Path::new("catalog")).expect("relative catalog B");
    let root_b = directory_b.join("catalog");
    assert_eq!(catalog_b.root(), root_b);

    let expected = artifact("cwd-owned-release", b"one tiny release belongs to A");
    block_on(catalog_a.publish(expected.clone())).expect("publish A while cwd is B");
    assert_release(&catalog_a, &expected);
    assert!(block_on(catalog_b.list(None, 1))
        .expect("B stays empty")
        .entries
        .is_empty());
    assert_eq!(
        fs::read_dir(root_a.join("releases"))
            .expect("A releases")
            .count(),
        1
    );
    assert_eq!(
        fs::read_dir(root_b.join("releases"))
            .expect("B releases")
            .count(),
        0
    );
    for owned_root in [&root_a, &root_b] {
        assert_eq!(
            open(owned_root)
                .expect_err("each original lock stays owned")
                .code,
            PlatformErrorCode::Unavailable
        );
    }

    drop(catalog_a);
    assert_release(
        &open(&root_a).expect("restart original catalog A"),
        &expected,
    );
    drop(catalog_b);
    assert!(
        block_on(open(&root_b).expect("restart catalog B").list(None, 1))
            .expect("B remains empty after restart")
            .entries
            .is_empty()
    );
    fs::write(
        root.join(VERIFIED),
        b"relative catalog identity preserved\n",
    )
    .expect("record completed child assertions");
}
