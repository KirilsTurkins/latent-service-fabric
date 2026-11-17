//! Standalone observer of the actual stream-scope Arc allocation and original
//! activation charge. Unsafe code is confined to this allocator witness, which
//! is compiled separately from the production workspace crates.
#![allow(dead_code)]
use latent_capabilities::broker::network::StreamScope;
use latent_capabilities::broker::*;
use latent_core::{ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget};
use latent_policy::capability::ResourceTarget;
use std::alloc::{GlobalAlloc, Layout, System};
use std::ptr::null_mut;
use std::sync::atomic::{AtomicBool, AtomicPtr, AtomicUsize, Ordering::SeqCst};
use std::sync::{Arc, Barrier};
use std::time::{Duration, Instant};

#[path = "../crates/latent-streams/src/strong_owner.rs"]
mod strong_owner;

// The runner owns and cleans the private temporary root. This small shim lets
// the unchanged authenticated fixture use its existing TempDir interface
// without compiling the entire library test graph.
mod tempfile {
    use std::{
        env, fs, io,
        path::{Path, PathBuf},
    };
    pub struct TempDir(PathBuf);
    impl TempDir {
        pub fn new() -> io::Result<Self> {
            let root = env::var_os("LSF_SCOPE_WITNESS_ROOT")
                .ok_or_else(|| io::Error::other("missing private fixture root"))?;
            let path = PathBuf::from(root).join("fixture");
            fs::create_dir(&path)?;
            Ok(Self(path))
        }
        pub fn path(&self) -> &Path {
            &self.0
        }
    }
}

// Reuse the actual authenticated production-session fixture rather than
// constructing a synthetic scope or exporting any production test hook.
mod fixture {
    include!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/src/broker/tests/fixture.rs"
    ));
}

const CAPTURE_LIMIT: usize = 64;
static CAPTURING: AtomicBool = AtomicBool::new(false);
static CAPTURE_COUNT: AtomicUsize = AtomicUsize::new(0);
static CAPTURE_SIZE: [AtomicUsize; CAPTURE_LIMIT] = [const { AtomicUsize::new(0) }; CAPTURE_LIMIT];
static CAPTURE_PTR: [AtomicPtr<u8>; CAPTURE_LIMIT] =
    [const { AtomicPtr::new(null_mut()) }; CAPTURE_LIMIT];
static WATCH: AtomicPtr<u8> = AtomicPtr::new(null_mut());
static ARMED: AtomicBool = AtomicBool::new(false);
static ENTERED: AtomicBool = AtomicBool::new(false);
static RELEASE: AtomicBool = AtomicBool::new(false);
static FREED: AtomicBool = AtomicBool::new(false);

struct Allocator;
#[global_allocator]
static ALLOCATOR: Allocator = Allocator;
unsafe impl GlobalAlloc for Allocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let ptr = unsafe { System.alloc(layout) };
        if CAPTURING.load(SeqCst) {
            let index = CAPTURE_COUNT.fetch_add(1, SeqCst);
            if index < CAPTURE_LIMIT {
                CAPTURE_SIZE[index].store(layout.size(), SeqCst);
                CAPTURE_PTR[index].store(ptr, SeqCst);
            }
        }
        ptr
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        if ptr == WATCH.load(SeqCst) && ARMED.swap(false, SeqCst) {
            ENTERED.store(true, SeqCst);
            while !RELEASE.load(SeqCst) {
                std::thread::yield_now();
            }
            unsafe { System.dealloc(ptr, layout) };
            FREED.store(true, SeqCst);
        } else {
            unsafe { System.dealloc(ptr, layout) };
        }
    }
}
fn start_capture() {
    CAPTURE_COUNT.store(0, SeqCst);
    CAPTURING.store(true, SeqCst);
}
fn stop_capture() {
    CAPTURING.store(false, SeqCst);
    assert!(
        CAPTURE_COUNT.load(SeqCst) < CAPTURE_LIMIT,
        "allocation trace overflow"
    );
}
fn allocation_of_size(size: usize) -> *mut u8 {
    let count = CAPTURE_COUNT.load(SeqCst);
    let mut found: *mut u8 = null_mut();
    for index in 0..count {
        if CAPTURE_SIZE[index].load(SeqCst) == size {
            assert!(found.is_null(), "ambiguous scope allocation size {size}");
            found = CAPTURE_PTR[index].load(SeqCst);
        }
    }
    assert!(
        !found.is_null(),
        "scope allocation of size {size} not observed"
    );
    found
}
fn watch(ptr: *mut u8) {
    WATCH.store(ptr, SeqCst);
    ENTERED.store(false, SeqCst);
    RELEASE.store(false, SeqCst);
    FREED.store(false, SeqCst);
    ARMED.store(true, SeqCst);
}
fn wait_for_deallocator() {
    let deadline = Instant::now() + Duration::from_secs(5);
    while !ENTERED.load(SeqCst) && Instant::now() < deadline {
        std::thread::yield_now();
    }
    if !ENTERED.load(SeqCst) {
        RELEASE.store(true, SeqCst);
        panic!("scope Arc deallocator not reached");
    }
}

// Exercise the exact private wrapper used by TLS configuration and the
// maintenance stop state. The marker stands for the value's trailing charge;
// this does not measure rustls allocations or qualify the host TLS profile.
struct StrongChargeMarker(Arc<AtomicBool>);
impl Drop for StrongChargeMarker {
    fn drop(&mut self) {
        self.0.store(false, SeqCst);
    }
}

fn strong_owner_backing() {
    for mode in 0..3 {
        let charged = Arc::new(AtomicBool::new(true));
        start_capture();
        let owner = strong_owner::StrongOwner::new(StrongChargeMarker(Arc::clone(&charged)));
        stop_capture();
        assert_eq!(CAPTURE_COUNT.load(SeqCst), 1);
        let pointer = CAPTURE_PTR[0].load(SeqCst);
        assert!(!pointer.is_null());
        watch(pointer);
        let mut workers = Vec::new();
        if mode == 2 {
            let barrier = Arc::new(Barrier::new(9));
            for _ in 0..8 {
                let clone = owner.clone();
                let barrier = Arc::clone(&barrier);
                workers.push(std::thread::spawn(move || {
                    barrier.wait();
                    drop(clone);
                }));
            }
            drop(owner);
            barrier.wait();
        } else {
            workers.push(std::thread::spawn(move || {
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    if mode == 1 {
                        let _owner = owner;
                        panic!("controlled TLS owner unwind");
                    }
                    drop(owner);
                }));
                assert_eq!(result.is_err(), mode == 1);
            }));
        }
        wait_for_deallocator();
        let held = charged.load(SeqCst);
        RELEASE.store(true, SeqCst);
        for worker in workers {
            worker.join().unwrap();
        }
        assert!(FREED.load(SeqCst) && held && !charged.load(SeqCst));
        println!("Strong owner backing mode={mode} marker held through deallocation");
    }
}

fn main() {
    strong_owner_backing();
    let fixture = fixture::Fixture::new(CapabilityBrokerLimits::default());
    let (request, mut control) = fixture.request("scope-allocation-witness");
    let deadline = control.budget.deadline();
    let sample = ClockSample::new(
        deadline.admitted_at_unix_millis(),
        deadline.admitted_at_monotonic(),
    );
    control.budget = ActivationBudget::with_profile(
        EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &request.budget,
            &request.budget,
            &request.budget,
            request.activation.deadline_unix_millis,
            sample,
        )
        .unwrap(),
        BudgetProfile::Phase3,
    )
    .unwrap();
    let session = fixture.session(&request, &control);
    let budget = &control.budget;
    let baseline = budget.host_memory_bytes();
    let mut measured = None;
    for mode in 0..3 {
        let scope = session.reserve_stream().unwrap();
        let original = budget.host_memory_bytes();
        start_capture();
        let shared = scope.share().unwrap();
        stop_capture();
        let charge = budget.host_memory_bytes() - original;
        let size = usize::try_from(charge - 64).unwrap();
        assert!(size > 0);
        if let Some(previous) = measured {
            assert_eq!(previous, charge);
        }
        measured = Some(charge);
        let ptr = allocation_of_size(size);
        watch(ptr);
        let mut workers = Vec::new();
        if mode == 2 {
            let barrier = Arc::new(Barrier::new(9));
            for _ in 0..8 {
                let clone = shared.clone();
                let barrier = barrier.clone();
                workers.push(std::thread::spawn(move || {
                    barrier.wait();
                    drop(clone);
                }));
            }
            drop(shared);
            barrier.wait();
        } else {
            workers.push(std::thread::spawn(move || {
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    if mode == 1 {
                        let _scope = shared;
                        panic!("controlled caller unwind");
                    }
                    drop(shared);
                }));
                assert_eq!(result.is_err(), mode == 1);
            }));
        }
        wait_for_deallocator();
        assert!(!FREED.load(SeqCst));
        assert_eq!(budget.host_memory_bytes(), original + charge);
        RELEASE.store(true, SeqCst);
        for worker in workers {
            worker.join().unwrap();
        }
        assert!(FREED.load(SeqCst));
        assert_eq!(budget.host_memory_bytes(), baseline);
        println!("managed mode={mode} actual Arc={size} original activation charged through deallocation=true");
    }

    let scope = session.reserve_stream().unwrap();
    let original = budget.host_memory_bytes();
    let charge = measured.unwrap();
    let padding = budget
        .reserve_host_memory(request.budget.memory_bytes - original - charge + 1)
        .unwrap();
    start_capture();
    let refused = scope.share();
    stop_capture();
    assert!(refused.is_err());
    let size = usize::try_from(charge - 64).unwrap();
    assert!(
        (0..CAPTURE_COUNT.load(SeqCst)).all(|index| CAPTURE_SIZE[index].load(SeqCst) != size),
        "scope Arc allocated before refused admission"
    );
    assert_eq!(budget.host_memory_bytes(), baseline + padding.bytes());
    drop(padding);
    assert_eq!(budget.host_memory_bytes(), baseline);
    println!("one-byte-short original activation refused before scope Arc allocation=true");

    // Legacy raw Arc/Weak is intentionally supported without the new prepaid
    // Arc guarantee; show the header remains after the scope credit returns.
    let scope = session.reserve_stream().unwrap();
    let raw_size = Layout::new::<[AtomicUsize; 2]>()
        .extend(Layout::new::<StreamScope>())
        .unwrap()
        .0
        .pad_to_align()
        .size();
    start_capture();
    let legacy = Arc::new(scope);
    stop_capture();
    watch(allocation_of_size(raw_size));
    let weak = Arc::downgrade(&legacy);
    drop(legacy);
    assert_eq!(budget.host_memory_bytes(), baseline);
    assert!(!FREED.load(SeqCst));
    RELEASE.store(true, SeqCst);
    drop(weak);
    assert!(FREED.load(SeqCst));
    println!("legacy raw Weak retains its Arc header after scope refund=true");
}
