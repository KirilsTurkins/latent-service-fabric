//! Thread-local filesystem failpoints. No hooks or state are included in production builds.

use std::cell::RefCell;
use std::fs;
use std::future::Future;
use std::marker::PhantomData;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll, Waker};

use latent_artifacts::{
    ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode, ReleaseDigest};

use super::super::{DirectoryDeploymentRepository as Store, DirectoryDeploymentRepositoryConfig};
use super::{IoStep, INITIALIZED_CONTENT, INITIALIZED_FILE, INITIALIZED_PENDING_FILE, STATE_FILE};

type Event = (IoStep, PathBuf);

struct Trace {
    fail: Option<Event>,
    events: Vec<Event>,
}

thread_local! {
    static TRACE: RefCell<Option<Trace>> = const { RefCell::new(None) };
}

// A guard cannot move to another thread, where its failpoint would not be installed.
struct Guard(PhantomData<Rc<()>>);

impl Guard {
    fn new(fail: Option<Event>) -> Self {
        TRACE.with(|trace| {
            let mut trace = trace.borrow_mut();
            assert!(trace.is_none(), "nested filesystem fault guard");
            *trace = Some(Trace {
                fail,
                events: Vec::new(),
            });
        });
        Self(PhantomData)
    }

    fn events(&self) -> Vec<Event> {
        TRACE.with(|trace| trace.borrow().as_ref().unwrap().events.clone())
    }
}

impl Drop for Guard {
    fn drop(&mut self) {
        TRACE.with(|trace| *trace.borrow_mut() = None);
    }
}

pub(super) fn checkpoint(step: IoStep, path: &Path) -> std::io::Result<()> {
    TRACE.with(|trace| {
        let mut trace = trace.borrow_mut();
        if let Some(trace) = trace.as_mut() {
            let event = (step, path.to_owned());
            trace.events.push(event.clone());
            if trace.fail.as_ref() == Some(&event) {
                trace.fail = None;
                return Err(std::io::Error::other("injected catalog filesystem failure"));
            }
        }
        Ok(())
    })
}

struct Scratch(PathBuf);

impl Scratch {
    fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "lsf-catalog-fault-{}-{nonce}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(fs::canonicalize(path).unwrap())
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

struct NoReleases;

impl ArtifactRepository for NoReleases {
    fn resolve<'a>(
        &'a self,
        _query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        panic!("empty initialization must not access releases")
    }

    fn fetch<'a>(
        &'a self,
        _digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        panic!("empty initialization must not access releases")
    }

    fn publish<'a>(
        &'a self,
        _artifact: CapsuleArtifact,
    ) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>> {
        panic!("deployment initialization must not publish releases")
    }

    fn list<'a>(
        &'a self,
        _after: Option<&'a ReleaseDigest>,
        _limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        panic!("empty initialization must not enumerate releases")
    }
}

fn open(path: &Path) -> Result<Store, PlatformError> {
    let mut future = std::pin::pin!(Store::open(
        path.to_owned(),
        Arc::new(NoReleases),
        DirectoryDeploymentRepositoryConfig::default(),
    ));
    match future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    {
        Poll::Ready(result) => result,
        Poll::Pending => panic!("empty initialization has no asynchronous release work"),
    }
}

#[test]
fn marker_creation_and_partial_writes_are_recoverable_at_every_boundary() {
    for step in [
        IoStep::MarkerCreated,
        IoStep::MarkerPartialWrite,
        IoStep::MarkerFileSync,
        IoStep::MarkerRename,
        IoStep::MarkerDirectorySync,
    ] {
        let scratch = Scratch::new();
        let root = scratch.0.join("catalog");
        let pending = root.join(INITIALIZED_PENDING_FILE);
        let marker = root.join(INITIALIZED_FILE);
        let fault_path = if step == IoStep::MarkerDirectorySync {
            root.clone()
        } else {
            pending.clone()
        };
        let guard = Guard::new(Some((step, fault_path.clone())));
        let failure = open(&root).err().expect("failpoint must interrupt open");
        assert_eq!(failure.code, PlatformErrorCode::Unavailable);
        assert_eq!(guard.events().last(), Some(&(step, fault_path)));
        drop(guard);

        let complete = fs::read(root.join(STATE_FILE)).unwrap();
        if step == IoStep::MarkerDirectorySync {
            assert_eq!(fs::read(&marker).unwrap(), INITIALIZED_CONTENT);
            assert!(!pending.exists());
        } else {
            assert!(!marker.exists(), "partial marker must not be authoritative");
            let contents = fs::read(&pending).unwrap();
            let expected = match step {
                IoStep::MarkerCreated => &INITIALIZED_CONTENT[..0],
                IoStep::MarkerPartialWrite => &INITIALIZED_CONTENT[..INITIALIZED_CONTENT.len() / 2],
                _ => INITIALIZED_CONTENT,
            };
            assert_eq!(contents, expected);
        }
        drop(open(&root).unwrap());
        assert_eq!(fs::read(root.join(STATE_FILE)).unwrap(), complete);
        assert_eq!(fs::read(&marker).unwrap(), INITIALIZED_CONTENT);
        assert!(!pending.exists());
        assert_eq!(fs::read_dir(&root).unwrap().count(), 3);
        // Completed initialization still makes loss of the state file a hard error.
        fs::remove_file(root.join(STATE_FILE)).unwrap();
        let failure = open(&root).err().unwrap();
        assert_eq!(failure.code, PlatformErrorCode::CorruptArtifact);
        assert_eq!(failure.message, "initialized-catalog-state-missing");
    }
}

#[test]
fn initialization_orders_state_marker_file_rename_and_directory_sync() {
    let scratch = Scratch::new();
    let root = scratch.0.join("one/two/catalog");
    let guard = Guard::new(None);
    drop(open(&root).unwrap());
    let mut expected = root
        .ancestors()
        .map(|path| (IoStep::PathDirectorySync, path.to_owned()))
        .collect::<Vec<_>>();
    let pending = root.join(INITIALIZED_PENDING_FILE);
    expected.extend([
        (IoStep::StateDirectorySync, root.clone()),
        (IoStep::MarkerCreated, pending.clone()),
        (IoStep::MarkerPartialWrite, pending.clone()),
        (IoStep::MarkerFileSync, pending.clone()),
        (IoStep::MarkerRename, pending),
        (IoStep::MarkerDirectorySync, root),
    ]);
    assert_eq!(guard.events(), expected);
}

#[test]
fn nested_path_sync_failures_propagate_and_existing_path_retries_resync_all_links() {
    // Include both newly created ancestors and the pre-existing filesystem root.
    let scratch = Scratch::new();
    let depth = scratch.0.join("one/two/catalog").ancestors().count();
    for failed_index in 0..depth {
        let root = scratch.0.join(format!("case-{failed_index}/two/catalog"));
        let expected = root
            .ancestors()
            .map(|path| (IoStep::PathDirectorySync, path.to_owned()))
            .collect::<Vec<_>>();
        let guard = Guard::new(Some(expected[failed_index].clone()));
        let failure = open(&root).err().expect("path sync must fail open");
        assert_eq!(failure.code, PlatformErrorCode::Unavailable);
        assert_eq!(failure.message, "catalog-path-durability-uncertain");
        assert!(failure.retryable);
        assert_eq!(guard.events(), expected[..=failed_index]);
        assert!(!root.join(STATE_FILE).exists());
        assert!(!root.join(INITIALIZED_FILE).exists());
        drop(guard);

        // All path components now exist, but the failed fsync is still required.
        let guard = Guard::new(None);
        drop(open(&root).unwrap());
        let events = guard.events();
        assert_eq!(&events[..expected.len()], expected.as_slice());
        assert_eq!(
            fs::read(root.join(INITIALIZED_FILE)).unwrap(),
            INITIALIZED_CONTENT
        );
        drop(guard);

        // A subsequent failure on an existing catalog must not replace its state.
        let complete = fs::read(root.join(STATE_FILE)).unwrap();
        let guard = Guard::new(Some(expected[failed_index].clone()));
        assert_eq!(
            open(&root).err().unwrap().code,
            PlatformErrorCode::Unavailable
        );
        assert_eq!(fs::read(root.join(STATE_FILE)).unwrap(), complete);
        drop(guard);
        drop(open(&root).unwrap());
        assert_eq!(fs::read(root.join(STATE_FILE)).unwrap(), complete);
    }
}

#[test]
fn staging_marker_cleanup_never_repairs_corrupt_completed_state() {
    let scratch = Scratch::new();
    let root = scratch.0.join("catalog");
    drop(open(&root).unwrap());
    let complete = fs::read(root.join(STATE_FILE)).unwrap();
    for bad_marker in [b"".as_slice(), b"lsf-deployment", b"wrong-version\n"] {
        fs::write(root.join(INITIALIZED_FILE), bad_marker).unwrap();
        fs::write(root.join(INITIALIZED_PENDING_FILE), INITIALIZED_CONTENT).unwrap();
        assert_eq!(
            open(&root).err().unwrap().code,
            PlatformErrorCode::CorruptArtifact
        );
        assert_eq!(fs::read(root.join(INITIALIZED_FILE)).unwrap(), bad_marker);
        assert_eq!(fs::read(root.join(STATE_FILE)).unwrap(), complete);
    }
    fs::remove_file(root.join(INITIALIZED_FILE)).unwrap();
    fs::write(root.join(STATE_FILE), b"corrupt completed record").unwrap();
    assert_eq!(
        open(&root).err().unwrap().code,
        PlatformErrorCode::CorruptArtifact
    );
    assert!(!root.join(INITIALIZED_FILE).exists());
    assert_eq!(
        fs::read(root.join(STATE_FILE)).unwrap(),
        b"corrupt completed record"
    );
}
