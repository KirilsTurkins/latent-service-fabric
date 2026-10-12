//! Outside-production allocator witness using genuine pinned rustls parsers.
use rustls::internal::msgs::message::MessagePayload;
use rustls::{ContentType, ProtocolVersion};
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

struct Witness;
static TRACK: AtomicBool = AtomicBool::new(false);
static LIVE: AtomicUsize = AtomicUsize::new(0);
static PEAK: AtomicUsize = AtomicUsize::new(0);
static ALLOCATED: AtomicUsize = AtomicUsize::new(0);
unsafe impl GlobalAlloc for Witness {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let value = unsafe { System.alloc(layout) };
        if !value.is_null() && TRACK.load(Ordering::Relaxed) {
            let live = LIVE.fetch_add(layout.size(), Ordering::Relaxed) + layout.size();
            PEAK.fetch_max(live, Ordering::Relaxed);
            ALLOCATED.fetch_add(layout.size(), Ordering::Relaxed);
        }
        value
    }
    unsafe fn dealloc(&self, value: *mut u8, layout: Layout) {
        if TRACK.load(Ordering::Relaxed) {
            LIVE.fetch_sub(layout.size(), Ordering::Relaxed);
        }
        unsafe { System.dealloc(value, layout) }
    }
    unsafe fn realloc(&self, value: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        let result = unsafe { System.realloc(value, layout, size) };
        if !result.is_null() && TRACK.load(Ordering::Relaxed) {
            let live = if size >= layout.size() {
                LIVE.fetch_add(size - layout.size(), Ordering::Relaxed) + size - layout.size()
            } else {
                LIVE.fetch_sub(layout.size() - size, Ordering::Relaxed) - layout.size() + size
            };
            PEAK.fetch_max(live, Ordering::Relaxed);
            ALLOCATED.fetch_add(size, Ordering::Relaxed);
        }
        result
    }
}
#[global_allocator]
static ALLOCATOR: Witness = Witness;

fn u24(size: usize) -> [u8; 3] {
    [(size >> 16) as u8, (size >> 8) as u8, size as u8]
}
fn handshake(kind: u8, body: Vec<u8>) -> Vec<u8> {
    let mut value = vec![kind];
    value.extend(u24(body.len()));
    value.extend(body);
    value
}
fn certificates(count: usize, bytes: usize, extensions: usize, tls13: bool) -> Vec<u8> {
    let mut items = Vec::new();
    for _ in 0..count {
        items.extend(u24(bytes));
        items.extend(std::iter::repeat_n(0, bytes));
        if tls13 {
            if extensions == 0 {
                items.extend([0, 0]);
            } else {
                // Genuine TLS13 status_request Certificate extension, including
                // typed OCSP status and the explicit three-byte payload length.
                items.extend(((extensions + 8) as u16).to_be_bytes());
                items.extend([0, 5]);
                items.extend(((extensions + 4) as u16).to_be_bytes());
                items.push(1);
                items.extend(u24(extensions));
                items.extend(std::iter::repeat_n(0, extensions));
            }
        }
    }
    let mut body = if tls13 { vec![0] } else { vec![] };
    body.extend(u24(items.len()));
    body.extend(items);
    handshake(11, body)
}
fn authorities(count: usize) -> Vec<u8> {
    let mut names = Vec::new();
    for _ in 0..count {
        names.extend([0, 1, 0]);
    }
    let mut body = vec![1, 1, 0, 2, 4, 3];
    body.extend((names.len() as u16).to_be_bytes());
    body.extend(names);
    handshake(13, body)
}
fn inspect(name: &str, version: ProtocolVersion, input: &[u8], accepted: bool) {
    LIVE.store(0, Ordering::Relaxed);
    PEAK.store(0, Ordering::Relaxed);
    ALLOCATED.store(0, Ordering::Relaxed);
    TRACK.store(true, Ordering::Relaxed);
    let parsed = MessagePayload::new(ContentType::Handshake, version, input);
    let outcome = parsed.is_ok();
    drop(parsed);
    TRACK.store(false, Ordering::Relaxed);
    let live = LIVE.load(Ordering::Relaxed);
    let peak = PEAK.load(Ordering::Relaxed);
    let allocated = ALLOCATED.load(Ordering::Relaxed);
    println!(
        "{{\"case\":\"{name}\",\"inputBytes\":{},\"accepted\":{outcome},\"expectedAccepted\":{accepted},\"peakAllocationBytes\":{peak},\"cumulativeAllocationBytes\":{allocated},\"liveAfterDropBytes\":{live}}}",
        input.len()
    );
    assert_eq!(live, 0, "actual parser allocations must retire");
    assert_eq!(outcome, accepted, "exact parser admission");
    assert!(
        peak <= 64 * 1024,
        "original TLS parser suballocation witness exceeded"
    );
}
fn main() {
    let mode = std::env::args().nth(1).expect("old or new");
    assert!(mode == "old" || mode == "new");
    if mode == "old" {
        let hostile = certificates(5000, 1, 0, true);
        inspect(
            "tls13-five-thousand-tiny-certificates-old",
            ProtocolVersion::TLSv1_3,
            &hostile,
            true,
        );
        panic!("old parser unexpectedly satisfied allocation bound");
    }
    // Input Vecs and printing are constructed outside the observed parser region.
    for (name, input, version, allowed) in [
        (
            "allowed-tls13-eight-small-certificates",
            certificates(8, 32, 0, true),
            ProtocolVersion::TLSv1_3,
            true,
        ),
        (
            "allowed-tls12-eight-small-certificates",
            certificates(8, 32, 0, false),
            ProtocolVersion::TLSv1_2,
            true,
        ),
        (
            "allowed-tls12-sixteen-authorities",
            authorities(16),
            ProtocolVersion::TLSv1_2,
            true,
        ),
        (
            "huge-declared-truncated-handshake",
            vec![11, 255, 255, 255, 0],
            ProtocolVersion::TLSv1_3,
            false,
        ),
        (
            "tls13-nine-certificates",
            certificates(9, 1, 0, true),
            ProtocolVersion::TLSv1_3,
            false,
        ),
        (
            "tls12-seventeen-authorities",
            authorities(17),
            ProtocolVersion::TLSv1_2,
            false,
        ),
        (
            "tls13-owned-extension-over4096",
            certificates(1, 1, 5000, true),
            ProtocolVersion::TLSv1_3,
            false,
        ),
        (
            "tls13-five-thousand-tiny-certificates",
            certificates(5000, 1, 0, true),
            ProtocolVersion::TLSv1_3,
            false,
        ),
    ] {
        inspect(name, version, &input, allowed);
    }
}
