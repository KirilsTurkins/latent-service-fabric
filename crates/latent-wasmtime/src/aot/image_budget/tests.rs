use super::*;

fn budget(images: usize, image: usize, total: usize) -> Arc<NativeImageBudget> {
    NativeImageBudget::new(NativeImageLimits {
        maximum_images: images,
        maximum_image_bytes: image,
        maximum_total_bytes: total,
    })
    .unwrap()
}

#[test]
fn fixed_limits_are_lowerable_and_reject_zero_or_inconsistent_totals() {
    assert_eq!(NativeImageLimits::default().maximum_images, 64);
    for limits in [
        NativeImageLimits {
            maximum_images: 0,
            ..Default::default()
        },
        NativeImageLimits {
            maximum_images: 4097,
            ..Default::default()
        },
        NativeImageLimits {
            maximum_image_bytes: 0,
            ..Default::default()
        },
        NativeImageLimits {
            maximum_image_bytes: 256 * 1024 * 1024 + 1,
            ..Default::default()
        },
        NativeImageLimits {
            maximum_total_bytes: 1024 * 1024 * 1024 + 1,
            ..Default::default()
        },
        NativeImageLimits {
            maximum_total_bytes: 1,
            ..Default::default()
        },
    ] {
        assert!(limits.validate().is_err());
    }
    budget(1, 1, 1);
}

#[test]
fn page_rounding_charges_tail_padding_and_checks_overflow() {
    for (bytes, expected) in [(1, 4096), (4096, 4096), (4097, 8192)] {
        assert_eq!(rounded(bytes, 4096).unwrap(), expected);
    }
    for (bytes, page) in [(0, 4096), (1, 0), (1, 3), (usize::MAX, 4096)] {
        assert!(rounded(bytes, page).is_err());
    }
}

#[test]
fn rejected_reservations_do_not_change_usage_or_loader_attempts() {
    let budget = budget(2, 8192, 8192);
    let first = budget.reserve_rounded(4096).unwrap();
    let used = budget.snapshot();
    assert!(budget.reserve_rounded(8192).is_err());
    assert!(budget.reserve_rounded(usize::MAX).is_err());
    assert_eq!(budget.snapshot(), used);
    let second = budget.reserve_rounded(4096).unwrap();
    assert!(budget.reserve_rounded(1).is_err());
    assert_eq!(budget.snapshot().loader_attempts, 0);
    drop((first, second));
    assert_eq!(budget.snapshot().images, 0);
    assert_eq!(budget.snapshot().bytes, 0);
}

#[test]
fn successful_load_changes_only_loading_subset_and_retains_full_charge() {
    let budget = budget(1, 8192, 8192);
    let mut image = budget.reserve_rounded(8192).unwrap();
    image.record_attempt();
    assert_eq!(budget.snapshot().loading_images, 1);
    assert_eq!(budget.snapshot().loading_bytes, 8192);
    image.loaded();
    image.loaded();
    let used = budget.snapshot();
    assert_eq!((used.images, used.bytes), (1, 8192));
    assert_eq!((used.loading_images, used.loading_bytes), (0, 0));
    assert_eq!(used.loader_attempts, 1);
    assert!(budget.reserve_rounded(1).is_err());
    drop(image);
    let used = budget.snapshot();
    assert_eq!(
        (
            used.images,
            used.bytes,
            used.loading_images,
            used.loading_bytes
        ),
        (0, 0, 0, 0)
    );
    assert_eq!(used.loader_attempts, 1);
}

#[test]
fn failed_loading_refunds_after_its_actual_owner_finishes() {
    let budget = budget(1, 4096, 4096);
    let image = budget.reserve_rounded(4096).unwrap();
    let (started_tx, started_rx) = std::sync::mpsc::sync_channel(0);
    let (release_tx, release_rx) = std::sync::mpsc::sync_channel(0);
    let thread = std::thread::spawn(move || {
        image.record_attempt();
        started_tx.send(()).unwrap();
        release_rx.recv().unwrap();
        drop(image);
    });
    started_rx.recv().unwrap();
    assert!(budget.reserve_rounded(1).is_err());
    assert_eq!(budget.snapshot().loading_images, 1);
    release_tx.send(()).unwrap();
    thread.join().unwrap();
    assert_eq!(budget.snapshot().bytes, 0);
    assert_eq!(budget.snapshot().loading_bytes, 0);
}

#[test]
fn loader_attempt_counter_saturates() {
    let budget = budget(1, 1, 1);
    budget.state().loader_attempts = u64::MAX;
    let image = budget.reserve_rounded(1).unwrap();
    image.record_attempt();
    assert_eq!(budget.snapshot().loader_attempts, u64::MAX);
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn real_page_size_is_reserved_before_native_load() {
    let page = rustix::param::page_size();
    let budget = budget(1, page, page);
    let permit = budget.reserve(1).unwrap();
    assert_eq!(budget.snapshot().bytes, page);
    drop(permit);
    assert!(budget.reserve(page + 1).is_err());
}
