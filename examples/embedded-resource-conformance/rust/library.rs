use std::sync::atomic::{AtomicUsize, Ordering};

static VISITS: AtomicUsize = AtomicUsize::new(0);

pub fn run(mode: &str) -> String {
    assert_eq!(VISITS.fetch_add(1, Ordering::Relaxed), 0, "resource state survived retirement");
    format!("{}|fresh=1", outside_embedded_resource_data::read(mode))
}
