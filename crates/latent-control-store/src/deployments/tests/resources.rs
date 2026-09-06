use std::fs;
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use latent_routing::RouteResolver;

use super::fixtures::*;
use crate::DeploymentStore;

const CHILD_ENV: &str = "LSF_DEPLOYMENT_DORMANCY_CHILD";
const TEST_NAME: &str =
    "deployments::tests::resources::dormant_deployments_allocate_no_runtime_resources";

struct ReapedChild(Child);

impl Drop for ReapedChild {
    fn drop(&mut self) {
        if !matches!(self.0.try_wait(), Ok(Some(_))) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

#[test]
fn dormant_deployments_allocate_no_runtime_resources() {
    if std::env::var(CHILD_ENV).ok().as_deref() == Some("1") {
        child_probe();
        return;
    }
    // Isolate resource accounting from parallel tests and supervise every child exit path.
    let logs = TempRoot::new();
    let path = logs.0.join("dormancy.log");
    let output = fs::File::create(&path).unwrap();
    let mut child = ReapedChild(
        Command::new(std::env::current_exe().unwrap())
            .args(["--exact", TEST_NAME, "--nocapture", "--test-threads=1"])
            .env(CHILD_ENV, "1")
            .stdin(Stdio::null())
            .stdout(output.try_clone().unwrap())
            .stderr(output)
            .spawn()
            .unwrap(),
    );
    let deadline = Instant::now() + Duration::from_secs(120);
    loop {
        if let Some(status) = child.0.try_wait().unwrap() {
            let evidence = fs::read_to_string(&path).unwrap();
            assert!(status.success(), "dormancy child failed: {evidence}");
            assert!(evidence.contains("deployments=1000"), "{evidence}");
            println!("{evidence}");
            break;
        }
        assert!(Instant::now() < deadline, "dormancy child exceeded its deadline");
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[derive(Debug, PartialEq, Eq)]
struct Resources {
    threads: usize,
    descriptors: usize,
    sockets: usize,
    children: usize,
}

fn measure() -> Resources {
    let mut descriptors = 0;
    let mut sockets = 0;
    for entry in fs::read_dir("/proc/self/fd").unwrap() {
        let destination = fs::read_link(entry.unwrap().path()).unwrap();
        descriptors += 1;
        sockets += usize::from(destination.to_string_lossy().starts_with("socket:"));
    }
    let mut threads = 0;
    let mut children = 0;
    for entry in fs::read_dir("/proc/self/task").unwrap() {
        threads += 1;
        let path = entry.unwrap().path().join("children");
        children += fs::read_to_string(path).unwrap().split_whitespace().count();
    }
    Resources {
        threads,
        descriptors,
        sockets,
        children,
    }
}

fn child_probe() {
    let root = TempRoot::new();
    let releases = Arc::new(
        DirectoryArtifactRepository::open(
            root.0.join("releases"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap(),
    );
    let descriptor = run(releases.publish(artifact("dormant"))).unwrap();
    let deployments_root = root.0.join("deployments");
    let store = run(Store::open(
        deployments_root.clone(),
        releases,
        Limits::default(),
    ))
    .unwrap();
    let before = measure();
    let before_files = fs::read_dir(&deployments_root).unwrap().count();
    let deployments = (0..1000)
        .map(|index| deployment(&format!("blue-{index}"), "alice", &descriptor.release_digest))
        .collect();
    run(store.apply_many(deployments)).unwrap();
    assert_eq!(run(store.list()).unwrap().len(), 1000);
    for index in 0..1000 {
        let route = format!("blue-{index}");
        let resolved = store.resolve(&target("alice", Some(&route)), Some("key")).unwrap();
        assert_eq!(resolved.release, descriptor.release_digest);
    }
    let after = measure();
    assert_eq!(before, after, "dormant routes must not allocate runtime resources");
    assert_eq!(fs::read_dir(&deployments_root).unwrap().count(), before_files);
    assert_eq!(before_files, 3, "only state, initialization marker, and node lock persist");
    println!("deployments=1000 before={before:?} after={after:?} catalog_files={before_files}");
}
