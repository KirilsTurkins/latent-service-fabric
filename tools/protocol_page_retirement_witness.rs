//! Standalone allocator witness. The unsafe code is confined to observing the
//! actual GlobalAlloc calls; production crates retain their unsafe-code ban.
use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
    ActivationCapabilityBroker, CapabilityBrokerLimits,
};
use latent_core::SystemActivationClock;
use latent_http::protocol::{ProtocolPage, SharedProtocolPage};
use latent_policy::capability::{PolicyStore, PolicyStoreLimits};
use std::alloc::{GlobalAlloc, Layout, System};
use std::ptr::null_mut;
use std::sync::atomic::{AtomicBool, AtomicPtr, AtomicUsize, Ordering::SeqCst};
use std::sync::{Arc, Barrier};
use std::time::{Duration, Instant};

struct Allocator;
#[global_allocator]
static ALLOCATOR: Allocator = Allocator;
static ALLOC_ARMED: AtomicBool = AtomicBool::new(false);
static SIZE: AtomicUsize = AtomicUsize::new(0);
static HEADER: AtomicPtr<u8> = AtomicPtr::new(null_mut());
static DATA: AtomicPtr<u8> = AtomicPtr::new(null_mut());
static DEALLOC_ARMED: AtomicBool = AtomicBool::new(false);
static ENTERED: AtomicBool = AtomicBool::new(false);
static RELEASE: AtomicBool = AtomicBool::new(false);
static FREED: AtomicBool = AtomicBool::new(false);
static DATA_FREED: AtomicBool = AtomicBool::new(false);

unsafe impl GlobalAlloc for Allocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let ptr = unsafe { System.alloc(layout) };
        if layout.size() == SIZE.load(SeqCst) && ALLOC_ARMED.swap(false, SeqCst) {
            HEADER.store(ptr, SeqCst);
        }
        ptr
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        if ptr == HEADER.load(SeqCst) && DEALLOC_ARMED.swap(false, SeqCst) {
            ENTERED.store(true, SeqCst);
            while !RELEASE.load(SeqCst) {
                std::thread::yield_now();
            }
            unsafe { System.dealloc(ptr, layout) };
            FREED.store(true, SeqCst);
        } else {
            unsafe { System.dealloc(ptr, layout) };
        }
        if ptr == DATA.load(SeqCst) {
            DATA_FREED.store(true, SeqCst);
        }
    }
}

fn prepare(arc_size: usize) {
    HEADER.store(null_mut(), SeqCst);
    DATA.store(null_mut(), SeqCst);
    SIZE.store(arc_size, SeqCst);
    ENTERED.store(false, SeqCst);
    RELEASE.store(false, SeqCst);
    FREED.store(false, SeqCst);
    DATA_FREED.store(false, SeqCst);
    DEALLOC_ARMED.store(true, SeqCst);
    ALLOC_ARMED.store(true, SeqCst);
}
fn wait_for_deallocator() {
    let deadline = Instant::now() + Duration::from_secs(5);
    while !ENTERED.load(SeqCst) && Instant::now() < deadline {
        std::thread::yield_now();
    }
    if !ENTERED.load(SeqCst) {
        RELEASE.store(true, SeqCst);
        panic!("actual page Arc deallocator not reached");
    }
}
fn main() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let _entered = runtime.enter();
    let tmp = std::path::PathBuf::from(
        std::env::var_os("LSF_PROTOCOL_WITNESS_ROOT").expect("private fixture root"),
    );
    let repo = DirectoryArtifactRepository::open(
        tmp.join("artifacts"),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    let policies = Arc::new(
        PolicyStore::open(
            &tmp.join("policies"),
            PolicyStoreLimits::default(),
            repo.lifecycle_authority(),
        )
        .unwrap(),
    );
    let broker = Arc::new(
        ActivationCapabilityBroker::new(
            repo.lifecycle_authority(),
            policies,
            Arc::new(SystemActivationClock),
            CapabilityBrokerLimits::default(),
        )
        .unwrap(),
    );
    let pools = Arc::new(
        ProviderPools::new(
            broker,
            Arc::new(IoRuntime::new(IoLimits::default()).unwrap()),
            tokio::runtime::Handle::current(),
            ProviderPoolLimits::default(),
        )
        .unwrap(),
    );
    let base = pools.snapshot().unwrap().metadata_bytes;
    let arc_size = Layout::new::<[AtomicUsize; 2]>()
        .extend(Layout::new::<ProtocolPage>())
        .unwrap()
        .0
        .pad_to_align()
        .size();
    let capacity = 257usize;
    assert!(arc_size + 128 <= 512);
    for mode in 0..3 {
        prepare(arc_size);
        let mut page = SharedProtocolPage::allocate(&pools, capacity).unwrap();
        assert!(!HEADER.load(SeqCst).is_null());
        page.try_append(b"payload").unwrap().unwrap();
        DATA.store(page.bytes().as_ptr() as *mut u8, SeqCst);
        assert_eq!(
            pools.snapshot().unwrap().metadata_bytes,
            base + capacity + 512
        );
        let mut workers = Vec::new();
        if mode == 2 {
            let barrier = Arc::new(Barrier::new(9));
            for _ in 0..8 {
                let clone = page.clone();
                let barrier = barrier.clone();
                workers.push(std::thread::spawn(move || {
                    barrier.wait();
                    drop(clone);
                }));
            }
            drop(page);
            barrier.wait();
        } else {
            workers.push(std::thread::spawn(move || {
                let result = std::panic::catch_unwind(|| {
                    if mode == 1 {
                        let _page = page;
                        panic!("controlled caller unwind");
                    }
                    drop(page);
                });
                assert_eq!(result.is_err(), mode == 1);
            }));
        }
        wait_for_deallocator();
        assert!(!FREED.load(SeqCst));
        assert!(!DATA_FREED.load(SeqCst));
        assert_eq!(
            pools.snapshot().unwrap().metadata_bytes,
            base + capacity + 512
        );
        RELEASE.store(true, SeqCst);
        for worker in workers {
            worker.join().unwrap();
        }
        assert!(FREED.load(SeqCst));
        assert!(DATA_FREED.load(SeqCst));
        assert_eq!(pools.snapshot().unwrap().metadata_bytes, base);
        println!("managed mode={mode} actual Arc={arc_size} charged through deallocation=true");
    }
    let mut legacy = ProtocolPage::allocate(&pools, capacity).unwrap();
    legacy.append(b"payload").unwrap();
    let data = legacy.bytes().as_ptr() as *mut u8;
    prepare(arc_size);
    let legacy = Arc::new(legacy);
    DATA.store(data, SeqCst);
    let weak = Arc::downgrade(&legacy);
    drop(legacy);
    assert_eq!(pools.snapshot().unwrap().metadata_bytes, base);
    assert!(!FREED.load(SeqCst));
    assert!(DATA_FREED.load(SeqCst));
    RELEASE.store(true, SeqCst);
    drop(weak);
    assert!(FREED.load(SeqCst));
    println!("legacy Weak held actual Arc header after original charge refund=true");
}
