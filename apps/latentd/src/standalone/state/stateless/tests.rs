use super::*;
use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
use latent_core::test_support::coordination::{PollProbe, Rendezvous, Stage, WATCHDOG};
use latent_core::test_support::{block_on, TestClock};
use std::fs;
use std::os::unix::fs::symlink;
use std::sync::mpsc;

fn clock() -> TestClock {
    TestClock::new(1000, Instant::now(), 1)
}

fn catalog(path: &Path) -> Arc<DirectoryArtifactRepository> {
    Arc::new(
        DirectoryArtifactRepository::open(
            path.join("releases"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap(),
    )
}

async fn observe_retirement(
    jobs: &StoreIoOwner<PhysicalProbe>,
    native: &NativeCapacityOwner,
) -> usize {
    // Observation only: this watchdog never renews the original probe grant.
    tokio::time::timeout(WATCHDOG, async {
        let mut joined = 0;
        loop {
            joined += jobs.reap_retired_threads().unwrap();
            if joined == 1
                && jobs.snapshot().unwrap().physically_retired()
                && native.snapshot().unwrap().physically_retired()
            {
                break joined;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap()
}

#[tokio::test]
async fn genuine_stateless_absence_retires_its_one_worker_and_original_capacity_before_return() {
    let root = tempfile::tempdir().unwrap();
    let data = root.path().join("existing-data");
    fs::create_dir(&data).unwrap();
    let (mut owner, job) =
        ProbeOwner::start(&data, Arc::new(clock()), Arc::new(()), || {}).unwrap();
    assert!(!job.await.unwrap().unwrap());
    owner.finish().await.unwrap();
    assert_eq!(owner.joined, 1);
    assert!(owner.jobs.snapshot().unwrap().physically_retired());
    assert!(owner.native.snapshot().unwrap().physically_retired());
    assert!(!data.join(STATE_DIRECTORY).exists());
    assert!(!data.join("transaction-checkpoint").exists());
    require_stateless_mode(&data, Arc::new(clock()), catalog(&data))
        .await
        .unwrap();
}

#[tokio::test]
async fn missing_intermediate_data_directory_is_observed_without_creating_any_parent() {
    let root = tempfile::tempdir().unwrap();
    let missing = root.path().join("missing");
    let data = missing.join("nested-data");
    let (mut owner, job) =
        ProbeOwner::start(&data, Arc::new(clock()), Arc::new(()), || {}).unwrap();
    assert!(!job.await.unwrap().unwrap());
    owner.finish().await.unwrap();
    assert!(!missing.exists());
    assert!(!data.exists());
}

#[tokio::test]
async fn persisted_state_entries_require_configuration_without_reading_or_modifying_mode_bytes() {
    for shape in 0..3 {
        let root = tempfile::tempdir().unwrap();
        let state = root.path().join(STATE_DIRECTORY);
        let mode = root.path().join("original-mode");
        let bytes = b"opaque failed LSM marker; never a stateless grant";
        fs::write(&mode, bytes).unwrap();
        match shape {
            0 => fs::create_dir(&state).unwrap(),
            1 => fs::write(&state, bytes).unwrap(),
            2 => symlink(&mode, &state).unwrap(),
            _ => unreachable!(),
        }
        let refusal = require_stateless_mode(root.path(), Arc::new(clock()), catalog(root.path()))
            .await
            .unwrap_err();
        assert_eq!(refusal.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(fs::read(&mode).unwrap(), bytes);
        assert!(fs::symlink_metadata(&state).is_ok());
    }
}

#[test]
fn unbounded_relative_and_parent_paths_refuse_before_starting_a_native_owner() {
    let root = tempfile::tempdir().unwrap();
    let too_deep = (0..=MAXIMUM_COMPONENTS).fold(root.path().to_path_buf(), |path, _| {
        path.join("bounded-component")
    });
    let too_long = root.path().join("x".repeat(MAXIMUM_PATH_BYTES));
    for path in [
        Path::new("relative").to_path_buf(),
        root.path().join(".."),
        too_deep,
        too_long,
    ] {
        let entered = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let observed = Arc::clone(&entered);
        assert!(
            ProbeOwner::start(&path, Arc::new(clock()), Arc::new(()), move || {
                observed.store(true, std::sync::atomic::Ordering::Release);
            })
            .is_err()
        );
        assert!(!entered.load(std::sync::atomic::Ordering::Acquire));
    }
    assert!(fs::read_dir(root.path()).unwrap().next().is_none());
}

#[tokio::test]
async fn a_linked_ancestor_is_not_negative_evidence_for_stateless_downgrade() {
    let root = tempfile::tempdir().unwrap();
    let actual = root.path().join("actual-data");
    fs::create_dir(&actual).unwrap();
    fs::create_dir(actual.join(STATE_DIRECTORY)).unwrap();
    let alias = root.path().join("alias");
    symlink(&actual, &alias).unwrap();
    let (mut owner, job) =
        ProbeOwner::start(&alias, Arc::new(clock()), Arc::new(()), || {}).unwrap();
    assert!(job.await.unwrap().is_err());
    owner.finish().await.unwrap();
    assert!(actual.join(STATE_DIRECTORY).is_dir());
    assert!(fs::symlink_metadata(&alias).unwrap().is_symlink());
}

#[tokio::test]
async fn replacing_an_ancestor_while_real_anchors_are_held_refuses_readiness() {
    let root = tempfile::tempdir().unwrap();
    let data = root.path().join("data");
    let original = root.path().join("original");
    fs::create_dir(&data).unwrap();
    let gates = Rendezvous::new(1);
    let worker = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let (mut owner, job) = ProbeOwner::start(&data, Arc::new(clock()), Arc::new(()), move || {
        let (registration, mut physical) = worker.track(()).unwrap();
        physical.commit(Stage::Entered).unwrap();
        let mut paused = Box::pin(physical.pause());
        PollProbe::default().pending(paused.as_mut());
        notice
            .send(worker.blocked(registration, Stage::Entered).unwrap())
            .unwrap();
        block_on(paused);
    })
    .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    fs::rename(&data, &original).unwrap();
    fs::create_dir(&data).unwrap();
    assert_eq!(owner.native.snapshot().unwrap().recovery.slots, 1);
    gates.release(ticket).unwrap();
    assert!(job.await.unwrap().is_err());
    owner.finish().await.unwrap();
    assert!(original.is_dir() && data.is_dir());
    assert!(!data.join(STATE_DIRECTORY).exists());
}

#[tokio::test]
async fn expired_original_probe_refuses_readiness_and_never_renews_accepted_native_work() {
    let root = tempfile::tempdir().unwrap();
    let clock = clock();
    let gates = Rendezvous::new(1);
    let worker = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let (mut owner, job) = ProbeOwner::start(
        root.path(),
        Arc::new(clock.clone()),
        Arc::new(()),
        move || {
            let (registration, mut physical) = worker.track(()).unwrap();
            physical.commit(Stage::Entered).unwrap();
            let mut paused = Box::pin(physical.pause());
            PollProbe::default().pending(paused.as_mut());
            notice
                .send(worker.blocked(registration, Stage::Entered).unwrap())
                .unwrap();
            block_on(paused);
        },
    )
    .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    let original_deadline = owner.deadline;
    let jobs = owner.jobs.clone();
    let native = owner.native.clone();
    clock.advance(ORIGINAL_WINDOW + Duration::from_secs(1));
    gates.release(ticket).unwrap();
    assert!(job.await.unwrap().is_err());
    assert!(owner.finish().await.is_err());
    assert_eq!(owner.deadline, original_deadline);
    drop(owner);
    assert_eq!(observe_retirement(&jobs, &native).await, 1);
    assert!(native.snapshot().unwrap().quarantined);
    assert!(!root.path().join(STATE_DIRECTORY).exists());
}

#[tokio::test]
async fn detached_probe_waiter_retains_original_capacity_until_actual_anchor_destruction() {
    let root = tempfile::tempdir().unwrap();
    let catalog_owner = catalog(root.path());
    let weak_catalog = Arc::downgrade(&catalog_owner);
    let gates = Rendezvous::new(1);
    let worker = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let (owner, job) = ProbeOwner::start(
        root.path(),
        Arc::new(clock()),
        catalog_owner.clone(),
        move || {
            let (registration, mut physical) = worker.track(()).unwrap();
            physical.commit(Stage::Entered).unwrap();
            let mut paused = Box::pin(physical.pause());
            PollProbe::default().pending(paused.as_mut());
            notice
                .send((
                    std::thread::current().id(),
                    worker.blocked(registration, Stage::Entered).unwrap(),
                ))
                .unwrap();
            block_on(paused);
        },
    )
    .unwrap();
    let (worker_id, ticket) = receiver.recv_timeout(WATCHDOG).unwrap();
    assert_ne!(worker_id, std::thread::current().id());
    let weak = Arc::downgrade(&owner.keeper.as_ref().unwrap().original);
    let jobs = owner.jobs.clone();
    let native = owner.native.clone();
    drop(job);
    drop(owner);
    drop(catalog_owner);
    assert!(weak.upgrade().is_some());
    assert!(weak_catalog.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(jobs.snapshot().unwrap().live_workers, 1);
    assert_eq!(
        DirectoryArtifactRepository::open(
            root.path().join("releases"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::Unavailable,
    );
    gates.release(ticket).unwrap();
    assert_eq!(observe_retirement(&jobs, &native).await, 1);
    assert!(weak.upgrade().is_none());
    assert!(weak_catalog.upgrade().is_none());
    let reopened = DirectoryArtifactRepository::open(
        root.path().join("releases"),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    drop(reopened);
    assert!(native.snapshot().unwrap().quarantined);
    assert!(!root.path().join(STATE_DIRECTORY).exists());
}
