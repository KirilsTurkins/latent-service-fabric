use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_core::RouteGeneration;
use latent_manifest::DeploymentManifest;
use latent_routing::RouteResolver;

use super::fixtures::*;
use crate::DeploymentStore;

mod during_open;

const CHILD_ROOT: &str = "LSF_DEPLOYMENT_ROOT_IDENTITY_CHILD";
const VERIFIED: &str = "root-identity-verified";

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
            std::thread::sleep(Duration::from_millis(10));
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

fn supervise(test_name: &str, scenario: fn(&Path)) {
    if let Some(root) = std::env::var_os(CHILD_ROOT) {
        let root = Path::new(&root);
        scenario(root);
        fs::write(root.join(VERIFIED), test_name.as_bytes())
            .expect("record completed child assertions");
        return;
    }

    let scratch = TempRoot::new();
    let root = fs::canonicalize(&scratch.0).expect("absolute child root");
    let log_path = root.join("child.log");
    let log = fs::File::create(&log_path).expect("child output log");
    let mut child = SupervisedChild(
        Command::new(std::env::current_exe().expect("current test executable"))
            .args(["--exact", test_name, "--nocapture", "--test-threads=1"])
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
        test_name.as_bytes()
    );
}

fn open_at(root: &Path, releases: &Arc<Releases>) -> Store {
    run(Store::open(root, releases.clone(), Limits::default())).expect("open catalog")
}

fn assert_owned(root: &Path, releases: &Arc<Releases>) {
    let failure = run(Store::open(root, releases.clone(), Limits::default()))
        .err()
        .expect("catalog must retain exclusive ownership");
    assert_eq!(failure.code, Code::Unavailable);
    assert_eq!(failure.message, "catalog-root-already-owned");
}

fn assert_deployment(store: &Store, expected: &DeploymentManifest, generation: u64) {
    assert_eq!(store.generation(), RouteGeneration(generation));
    assert_eq!(
        run(store.list()).expect("list deployment"),
        vec![expected.clone()]
    );
    assert_eq!(
        run(DeploymentStore::get(store, &expected.id)).expect("get deployment"),
        Some(expected.clone())
    );
    let tenant = expected.metadata.tenant.as_ref().expect("fixture tenant");
    assert_eq!(
        store
            .resolve(&target(&tenant.0, None), None)
            .expect("resolve route")
            .release,
        expected.release
    );
}

fn assert_files_unchanged(saved: &[(PathBuf, Vec<u8>)]) {
    for (path, bytes) in saved {
        assert_eq!(&fs::read(path).expect("preserved catalog file"), bytes);
    }
}

#[test]
fn mutations_stay_in_the_owned_root_after_working_directory_changes() {
    supervise(
        "deployments::tests::root_identity::mutations_stay_in_the_owned_root_after_working_directory_changes",
        exercise_after_open,
    );
}

fn exercise_after_open(root: &Path) {
    let directory_a = root.join("a");
    let directory_b = root.join("b");
    fs::create_dir(&directory_a).expect("working directory A");
    fs::create_dir(&directory_b).expect("working directory B");
    let releases = Arc::new(Releases::default());
    let first_release = releases.add("first");
    let second_release = releases.add("second");

    // Only the exact isolated child changes cwd; the parent runner stays untouched.
    std::env::set_current_dir(&directory_a).expect("enter directory A");
    let catalog_a = open_at(Path::new("catalog"), &releases);
    let root_a = directory_a.join("catalog");
    let original = deployment("a-blue", "alice", &first_release);
    run(catalog_a.apply(original.clone())).expect("seed catalog A");

    std::env::set_current_dir(&directory_b).expect("enter directory B");
    let catalog_b = open_at(Path::new("catalog"), &releases);
    let root_b = directory_b.join("catalog");
    let preserved = deployment("b-blue", "bob", &first_release);
    run(catalog_b.apply(preserved.clone())).expect("seed catalog B");
    // Model B's private in-progress staging while its owner remains alive.
    fs::write(root_b.join(".catalog.pending"), b"catalog B private stage")
        .expect("catalog B staging fixture");
    let saved = [
        "catalog.json",
        "INITIALIZED",
        ".catalog.lock",
        ".catalog.pending",
    ]
    .map(|name| {
        let path = root_b.join(name);
        let bytes = fs::read(&path).expect("catalog B original bytes");
        (path, bytes)
    });
    let preserved_snapshot = snapshot(&catalog_b);

    let replacement = deployment("a-green", "alice", &second_release);
    run(catalog_a.apply(replacement.clone())).expect("apply A while cwd is B");
    run(catalog_a.delete(&original.id)).expect("delete A while cwd is B");
    assert_deployment(&catalog_a, &replacement, 3);
    assert_deployment(&catalog_b, &preserved, 1);
    assert_eq!(snapshot(&catalog_b), preserved_snapshot);
    assert_files_unchanged(&saved);
    assert_eq!(catalog_a.root, root_a);
    assert_eq!(catalog_b.root, root_b);
    assert_owned(&root_a, &releases);
    assert_owned(&root_b, &releases);
    assert_files_unchanged(&saved);

    drop(catalog_a);
    let reopened_a = open_at(&root_a, &releases);
    assert_deployment(&reopened_a, &replacement, 3);
    assert_files_unchanged(&saved);
    drop(catalog_b);
    let reopened_b = open_at(&root_b, &releases);
    assert_deployment(&reopened_b, &preserved, 1);
    assert_eq!(snapshot(&reopened_b), preserved_snapshot);
    assert!(
        !root_b.join(".catalog.pending").exists(),
        "B's new owner cleans its stage"
    );
}
