//! One cached host-pressure observation shared by admission and inventory.

use std::io::Read;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

use latent_admission::{NodeLoadSnapshot, NodeLoadSource};
use latent_core::{PlatformError, PlatformErrorCode};
use tokio::sync::oneshot;
use tokio::task::JoinHandle;

use super::error;

#[derive(Default)]
pub(super) struct HostLoad {
    accepting: AtomicBool,
    value: RwLock<Option<NodeLoadSnapshot>>,
}

impl HostLoad {
    pub(super) fn start_accepting(&self) {
        self.accepting.store(true, Ordering::Release);
    }

    pub(super) fn stop_accepting(&self) {
        self.accepting.store(false, Ordering::Release);
    }

    fn refresh(&self) {
        let value = pressure("/proc/pressure/cpu")
            .zip(pressure("/proc/pressure/memory"))
            .map(|(cpu, memory)| NodeLoadSnapshot {
                accepting: false,
                cpu_pressure_milli: cpu,
                memory_pressure_milli: memory,
                // No additional external queue estimate. Admission already derives
                // its own delay from atomically reserved class backlog.
                queue_delay_millis: 0,
                observed_at: Instant::now(),
            });
        if let Ok(mut slot) = self.value.write() {
            *slot = value;
        }
    }
}

impl NodeLoadSource for HostLoad {
    fn snapshot(&self) -> Result<NodeLoadSnapshot, PlatformError> {
        let mut value = self
            .value
            .read()
            .ok()
            .and_then(|value| *value)
            .ok_or_else(|| {
                error(
                    PlatformErrorCode::Unavailable,
                    "host pressure observation unavailable",
                )
            })?;
        // A late sample can never reopen admission after shutdown starts.
        value.accepting = self.accepting.load(Ordering::Acquire);
        Ok(value)
    }
}

pub(super) struct LoadSampler {
    stop: Option<oneshot::Sender<()>>,
    task: JoinHandle<()>,
}

impl LoadSampler {
    pub(super) fn start(
        load: Arc<HostLoad>,
        interval: Duration,
        runtime: &tokio::runtime::Handle,
        supply_chain: Option<Arc<latent_policy::supply_chain::SupplyChainAuthority>>,
    ) -> Self {
        load.refresh();
        let (stop, mut stopped) = oneshot::channel();
        let task = runtime.spawn(async move {
            let mut timer = tokio::time::interval(interval);
            timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
            loop {
                tokio::select! {
                    biased;
                    _ = &mut stopped => break,
                    _ = timer.tick() => {
                        // The one existing control owner renews a single durable
                        // lease. Invocations only try the in-memory fence and
                        // fail closed while busy/uncovered; they never fsync.
                        if let Some(authority) = &supply_chain {
                            let _ = authority.renew_clock_lease();
                        }
                        load.refresh();
                    },
                }
            }
        });
        Self {
            stop: Some(stop),
            task,
        }
    }

    pub(super) async fn shutdown(mut self, timeout: Duration) -> Result<(), PlatformError> {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        tokio::time::timeout(timeout, &mut self.task)
            .await
            .map_err(|_| {
                error(
                    PlatformErrorCode::DeadlineExceeded,
                    "load sampler shutdown timed out",
                )
            })?
            .map_err(|_| error(PlatformErrorCode::Internal, "load sampler failed"))
    }
}

impl Drop for LoadSampler {
    fn drop(&mut self) {
        self.task.abort();
    }
}

fn pressure(path: &str) -> Option<u16> {
    let mut bytes = [0_u8; 513];
    let mut file = std::fs::File::open(path).ok()?;
    let mut used = 0;
    while used < bytes.len() {
        let read = file.read(&mut bytes[used..]).ok()?;
        if read == 0 {
            break;
        }
        used += read;
    }
    if used == bytes.len() {
        return None;
    }
    parse_pressure(std::str::from_utf8(&bytes[..used]).ok()?)
}

/// Kernel PSI `some.avg10` is percentage time with at least one stalled task,
/// not CPU utilization or resident memory. Preserve a measured zero explicitly.
/// <https://docs.kernel.org/accounting/psi.html>
fn parse_pressure(value: &str) -> Option<u16> {
    let mut lines = value.lines().filter(|line| line.starts_with("some "));
    let line = lines.next()?;
    if lines.next().is_some() {
        return None;
    }
    let mut values = line
        .split_ascii_whitespace()
        .filter_map(|field| field.strip_prefix("avg10="));
    let ratio = values.next()?;
    if values.next().is_some() {
        return None;
    }
    let (whole, fraction) = ratio.split_once('.')?;
    if whole.is_empty()
        || whole.len() > 3
        || fraction.len() != 2
        || !whole
            .bytes()
            .chain(fraction.bytes())
            .all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    let hundredths = whole
        .parse::<u16>()
        .ok()?
        .checked_mul(100)?
        .checked_add(fraction.parse::<u16>().ok()?)?;
    (hundredths <= 10_000).then_some(hundredths / 10)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pressure_preserves_zero_and_rejects_missing_ambiguous_or_invalid_samples() {
        assert_eq!(
            parse_pressure("some avg10=0.00 avg60=1.00 total=42\n"),
            Some(0)
        );
        assert_eq!(
            parse_pressure("some avg10=12.39\nfull avg10=1.00\n"),
            Some(123)
        );
        assert_eq!(parse_pressure("some avg10=100.00\n"), Some(1000));
        for text in [
            "",
            "full avg10=0.00",
            "some avg10=NaN",
            "some avg10=-1.00",
            "some avg10=100.01",
            "some avg10=0.0",
            "some avg10=0.00 avg10=1.00",
            "some avg10=0.00\nsome avg10=1.00",
        ] {
            assert_eq!(parse_pressure(text), None, "{text}");
        }
    }

    #[test]
    fn missing_observation_and_stop_never_become_a_fresh_accepting_zero() {
        let load = HostLoad::default();
        load.start_accepting();
        assert!(load.snapshot().is_err());
        *load.value.write().unwrap() = Some(NodeLoadSnapshot {
            accepting: true,
            cpu_pressure_milli: 0,
            memory_pressure_milli: 0,
            queue_delay_millis: 0,
            observed_at: Instant::now(),
        });
        assert!(load.snapshot().unwrap().accepting);
        load.stop_accepting();
        assert!(!load.snapshot().unwrap().accepting);
        *load.value.write().unwrap() = None;
        assert!(load.snapshot().is_err());
    }
}
