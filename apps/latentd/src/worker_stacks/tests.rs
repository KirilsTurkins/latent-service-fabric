use super::*;

#[test]
fn checked_profile_rejects_invalid_worker_and_blocking_counts() {
    for values in [
        (0, 1, 1),
        (33, 1, 1),
        (1, 0, 1),
        (1, 9, 1),
        (1, 1, 0),
        (1, 1, 3),
        (usize::MAX, 1, 1),
    ] {
        assert!(NodeWorkerStacks::checked(values.0, values.1, values.2).is_none());
    }
}

#[test]
fn two_blocking_workers_have_one_shared_checked_stack_envelope() {
    let first = NodeWorkerStacks::checked(2, 2, 1).unwrap();
    let second = NodeWorkerStacks::checked(2, 2, 2).unwrap();
    assert_eq!(first.invocation.maximum_threads(), 3);
    assert_eq!(first.control.maximum_threads(), 3);
    assert_eq!(second.control.maximum_threads(), 4);
    assert_eq!(
        second.control.maximum_mapping_bytes(),
        4 * THREAD_MAPPING_ALLOWANCE
    );
    assert_eq!(THREAD_STACK_BYTES, 2 * 1024 * 1024);
    assert_eq!(THREAD_GUARD_ALLOWANCE, 64 * 1024);
}

#[cfg(target_os = "linux")]
mod linux {
    use super::*;
    use std::{
        fs::File,
        io::Read,
        sync::Barrier,
        time::{Duration, Instant},
    };

    #[derive(Debug)]
    struct Mapping {
        usable: usize,
        guard: usize,
    }
    fn mapping(raw: &str, address: usize) -> Result<Mapping, &'static str> {
        let mut ranges = Vec::new();
        for line in raw.lines() {
            let mut fields = line.split_whitespace();
            let range = fields.next().ok_or("map-fields")?;
            let permission = fields.next().ok_or("map-permission")?;
            let (start, end) = range.split_once('-').ok_or("map-range")?;
            let start = usize::from_str_radix(start, 16).map_err(|_| "map-start")?;
            let end = usize::from_str_radix(end, 16).map_err(|_| "map-end")?;
            if start >= end || ranges.len() >= 65536 {
                return Err("map-bound");
            }
            ranges.push((start, end, permission));
        }
        let selected: Vec<_> = ranges
            .iter()
            .enumerate()
            .filter_map(|(index, (start, end, _))| {
                (*start <= address && address < *end).then_some(index)
            })
            .collect();
        let [index] = selected.as_slice() else {
            return Err("map-owner");
        };
        let (start, end, permission) = ranges[*index];
        if permission != "rw-p" || *index == 0 {
            return Err("stack-mapping");
        }
        let (guard_start, guard_end, guard_permission) = ranges[*index - 1];
        let usable = end - start;
        let guard = guard_end - guard_start;
        if guard_end != start
            || guard_permission != "---p"
            || guard == 0
            || guard > THREAD_GUARD_ALLOWANCE
            || usable > THREAD_STACK_BYTES
            || usable
                .checked_add(guard)
                .is_none_or(|size| size > THREAD_MAPPING_ALLOWANCE)
        {
            println!("STACK_MAPPING_REFUSED usable={usable} guard={guard} envelope={THREAD_MAPPING_ALLOWANCE}");
            return Err("stack-envelope");
        }
        Ok(Mapping { usable, guard })
    }
    fn current() -> Result<Mapping, &'static str> {
        let marker = 0u8;
        let address = std::ptr::from_ref(&marker).addr();
        let mut raw = String::new();
        File::open("/proc/self/maps")
            .map_err(|_| "maps-open")?
            .take(4 * 1024 * 1024 + 1)
            .read_to_string(&mut raw)
            .map_err(|_| "maps-read")?;
        if raw.len() > 4 * 1024 * 1024 {
            return Err("maps-size");
        }
        mapping(&raw, address)
    }
    fn record(result: Result<Mapping, &'static str>) {
        let found = result.expect("actual Linux stack must fit the pinned mapping and guard");
        println!(
            "STACK_MAPPING usable={} guard={} envelope={}",
            found.usable, found.guard, THREAD_MAPPING_ALLOWANCE
        );
    }

    #[test]
    fn stack_map_parser_rejects_missing_guard_ambiguous_and_oversized_ranges() {
        let valid = "1000-2000 ---p 00000000 00:00 0\n2000-202000 rw-p 00000000 00:00 0\n";
        let result = mapping(valid, 0x3000).unwrap();
        assert_eq!((result.usable, result.guard), (THREAD_STACK_BYTES, 4096));
        for malformed in [
            valid.replace("---p", "rw-p"),
            valid.replace("202000", "402000"),
            valid.to_owned() + "2000-202000 rw-p 00000000 00:00 0\n",
            "2000-202000 rw-p 00000000 00:00 0\n".into(),
        ] {
            assert!(mapping(&malformed, 0x3000).is_err());
        }
    }

    #[test]
    fn actual_linux_worker_and_blocking_stacks_are_bounded_and_guarded() {
        let profile = NodeWorkerStacks::checked(2, 2, 2).unwrap().control;
        let count = Arc::new(AtomicUsize::new(0));
        let runtime = profile.build("stack-reference", &count).unwrap();
        let barrier = Arc::new(Barrier::new(3));
        let workers: Vec<_> = (0..2)
            .map(|_| {
                let barrier = Arc::clone(&barrier);
                runtime.spawn(async move {
                    let result = current();
                    barrier.wait();
                    result
                })
            })
            .collect();
        barrier.wait();
        assert_eq!(count.load(Ordering::SeqCst), 2);
        runtime.block_on(async {
            for worker in workers {
                record(worker.await.unwrap());
            }
        });
        let barrier = Arc::new(Barrier::new(3));
        let blocking: Vec<_> = (0..2)
            .map(|_| {
                let barrier = Arc::clone(&barrier);
                runtime.spawn_blocking(move || {
                    let result = current();
                    barrier.wait();
                    result
                })
            })
            .collect();
        barrier.wait();
        assert_eq!(count.load(Ordering::SeqCst), profile.maximum_threads());
        runtime.block_on(async {
            for thread in blocking {
                record(thread.await.unwrap());
            }
        });
        runtime.shutdown_timeout(Duration::from_secs(2));
        assert_eq!(count.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn timed_out_shutdown_retains_live_blocking_thread_owner_until_real_stop() {
        let count = Arc::new(AtomicUsize::new(0));
        let runtime = NodeWorkerStacks::checked(1, 1, 1)
            .unwrap()
            .control
            .build("retained-stack-reference", &count)
            .unwrap();
        let entered = Arc::new(Barrier::new(2));
        let release = Arc::new(Barrier::new(2));
        let (started, released) = (Arc::clone(&entered), Arc::clone(&release));
        let owner = runtime.spawn_blocking(move || {
            started.wait();
            released.wait();
        });
        entered.wait();
        drop(owner);
        runtime.shutdown_timeout(Duration::from_millis(10));
        assert!(count.load(Ordering::SeqCst) >= 1);
        release.wait();
        let deadline = Instant::now() + Duration::from_secs(2);
        while count.load(Ordering::SeqCst) != 0 && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(1));
        }
        assert_eq!(count.load(Ordering::SeqCst), 0);
    }
}
