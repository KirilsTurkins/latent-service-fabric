//! Opt-in, bounded host evidence of the original retirement refusal.
use std::{
    ffi::OsStr,
    io::Write,
    sync::atomic::{AtomicUsize, Ordering},
};

const ENVIRONMENT: &str = "LSF_JAVA_CONTROL_REFUSAL_DIAGNOSTIC";
const PREFIX: &str = "LSF-RUNTIME-OWNER-REFUSAL-V1";
const MAX_RECORDS: usize = 4;
const MAX_OWNERS: u32 = 8192;
static RECORDS: AtomicUsize = AtomicUsize::new(0);

fn write_record(enabled: bool, counter: &AtomicUsize, writer: &mut impl Write, owners: [u32; 7]) {
    if !enabled
        || owners.iter().all(|count| *count == 0)
        || owners.iter().any(|count| *count > MAX_OWNERS)
        || owners.iter().map(|count| u64::from(*count)).sum::<u64>() > u64::from(MAX_OWNERS)
    {
        return;
    }
    if counter
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |seen| {
            if seen < MAX_RECORDS {
                Some(seen + 1)
            } else {
                None
            }
        })
        .is_err()
    {
        return;
    }
    // These are the original seven accounting buckets: tasks includes managed
    // idle workers. No token, guest value or arbitrary error text is accepted.
    let _ = writeln!(
        writer,
        "{PREFIX} tasks={} executors={} queued-work={} waits={} timers={} results={} native={}",
        owners[0], owners[1], owners[2], owners[3], owners[4], owners[5], owners[6]
    );
}

pub(super) fn record(owners: [u32; 7]) {
    if std::env::var_os(ENVIRONMENT).as_deref() == Some(OsStr::new("1")) {
        write_record(true, &RECORDS, &mut std::io::stderr(), owners);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_zero_and_invalid_counts_do_not_consume_refusal_allowance() {
        let counter = AtomicUsize::new(0);
        let mut output = Vec::new();
        write_record(false, &counter, &mut output, [1, 0, 0, 0, 0, 0, 0]);
        for owners in [[0; 7], [8193, 0, 0, 0, 0, 0, 0], [8192, 1, 0, 0, 0, 0, 0]] {
            write_record(true, &counter, &mut output, owners);
        }
        assert!(output.is_empty());
        assert_eq!(counter.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn exact_closed_bucket_records_are_bounded_and_process_capped() {
        let counter = AtomicUsize::new(0);
        let mut output = Vec::new();
        for _ in 0..100 {
            write_record(true, &counter, &mut output, [1, 2, 3, 4, 5, 6, 7]);
        }
        let expected = concat!(
            "LSF-RUNTIME-OWNER-REFUSAL-V1 tasks=1 executors=2 queued-work=3",
            " waits=4 timers=5 results=6 native=7\n"
        )
        .as_bytes();
        assert_eq!(output, expected.repeat(MAX_RECORDS));
        assert_eq!(counter.load(Ordering::Relaxed), MAX_RECORDS);
        assert!(output.len() <= MAX_RECORDS * 160);
        let mut maximum = Vec::new();
        write_record(
            true,
            &AtomicUsize::new(0),
            &mut maximum,
            [8192, 0, 0, 0, 0, 0, 0],
        );
        assert!(maximum.len() <= 160);
    }

    #[test]
    fn failed_witness_write_does_not_escape_or_change_original_counts() {
        struct Broken;
        impl Write for Broken {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::ErrorKind::BrokenPipe.into())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let owners = [0, 0, 0, 1, 0, 0, 0];
        write_record(true, &AtomicUsize::new(0), &mut Broken, owners);
        assert_eq!(owners, [0, 0, 0, 1, 0, 0, 0]);
    }
}
