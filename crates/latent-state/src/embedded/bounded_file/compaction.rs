use super::super::{CompactionLimits, CompactionReport, CompactionStop, StoreError};
use super::StoreFileStatus;
use std::{io, sync::Mutex, time::Instant};

#[derive(Debug)]
pub(super) struct IoState {
    pub file_bytes: u64,
    pub maximum_file_bytes: u64,
    pub active: Option<Running>,
    pub last: Option<CompactionReport>,
}
#[derive(Debug)]
pub(super) struct Running {
    limits: CompactionLimits,
    started: Instant,
    report: CompactionReport,
}

#[derive(Clone, Copy)]
pub(super) enum IoKind {
    Read,
    Write,
    Other,
}

impl StoreFileStatus {
    /// Read the fixed last physical observation, without acquiring a view.
    ///
    /// # Errors
    /// Refuses a poisoned/unavailable observation rather than reporting that
    /// an interrupted compaction never happened.
    pub fn last_compaction(&self) -> Result<Option<CompactionReport>, StoreError> {
        self.io
            .lock()
            .map(|state| state.last)
            .map_err(|_| StoreError::Unavailable)
    }

    /// Source bound for redb 4.3 with its installed default 4096-byte pages.
    /// Two page-sized allowances per possible physical page conservatively
    /// cover transient relocation data, paths, maps and freed-page ownership; fixed space
    /// includes the bounded final row checks. The engine cache is separately
    /// owned. No application record set is loaded into a maintenance vector.
    ///
    /// # Errors
    /// Refuses an unavailable observation, overflow or excessive growth input.
    pub fn compaction_scratch_requirement(
        &self,
        maximum_growth_bytes: u64,
    ) -> Result<u64, StoreError> {
        let state = self.io.lock().map_err(|_| StoreError::Unavailable)?;
        scratch_requirement(&state, maximum_growth_bytes)
    }

    pub(in crate::embedded) fn begin_compaction(
        &self,
        limits: CompactionLimits,
    ) -> Result<Lease<'_>, StoreError> {
        limits.validate()?;
        let mut state = self.io.lock().map_err(|_| StoreError::Unavailable)?;
        if state.active.is_some() || self.close_observed() {
            return Err(StoreError::Capacity);
        }
        let scratch = scratch_requirement(&state, limits.maximum_growth_bytes)?;
        if scratch > limits.maximum_scratch_bytes {
            return Err(StoreError::Capacity);
        }
        let bytes = state.file_bytes;
        state.active = Some(Running {
            limits,
            started: Instant::now(),
            report: CompactionReport {
                engine_started: false,
                engine_completed: false,
                changed: Some(false),
                stop: None,
                read_bytes: 0,
                write_bytes: 0,
                io_operations: 0,
                file_bytes_before: bytes,
                observed_file_bytes: bytes,
                peak_file_bytes: bytes,
                elapsed_micros: 0,
                scratch_requirement_bytes: scratch,
                scratch_limit_bytes: limits.maximum_scratch_bytes,
            },
        });
        Ok(Lease {
            state: &self.io,
            finished: false,
        })
    }

    pub(super) fn charge(&self, kind: IoKind, bytes: usize, end: Option<u64>) -> io::Result<()> {
        let mut state = self
            .io
            .lock()
            .map_err(|_| io::Error::other("store I/O observation unavailable"))?;
        let Some(active) = state.active.as_mut() else {
            return Ok(());
        };
        let bytes =
            u64::try_from(bytes).map_err(|_| io::Error::other("store I/O charge overflow"))?;
        let report = &mut active.report;
        let stop = if report.stop.is_some() {
            report.stop
        } else if Instant::now() >= active.limits.deadline {
            Some(CompactionStop::Deadline)
        } else if report.io_operations >= active.limits.maximum_io_operations {
            Some(CompactionStop::OperationBudget)
        } else if matches!(kind, IoKind::Read)
            && report
                .read_bytes
                .checked_add(bytes)
                .is_none_or(|total| total > active.limits.maximum_read_bytes)
        {
            Some(CompactionStop::ReadBudget)
        } else if matches!(kind, IoKind::Write)
            && report
                .write_bytes
                .checked_add(bytes)
                .is_none_or(|total| total > active.limits.maximum_write_bytes)
        {
            Some(CompactionStop::WriteBudget)
        } else if end.is_some_and(|end| {
            end.saturating_sub(report.file_bytes_before) > active.limits.maximum_growth_bytes
        }) {
            Some(CompactionStop::GrowthBudget)
        } else {
            None
        };
        if let Some(stop) = stop {
            report.stop = Some(stop);
            return Err(io::Error::other("bounded store compaction refused I/O"));
        }
        report.io_operations += 1;
        match kind {
            IoKind::Read => report.read_bytes += bytes,
            IoKind::Write => report.write_bytes += bytes,
            IoKind::Other => (),
        }
        Ok(())
    }

    pub(super) fn observed(&self, length: Option<(u64, bool)>, succeeded: bool) -> io::Result<()> {
        let mut state = self
            .io
            .lock()
            .map_err(|_| io::Error::other("store I/O observation unavailable"))?;
        if succeeded {
            if let Some((length, exact)) = length {
                state.file_bytes = if exact {
                    length
                } else {
                    state.file_bytes.max(length)
                };
            }
        }
        let length = state.file_bytes;
        if let Some(active) = state.active.as_mut() {
            if !succeeded && active.report.stop.is_none() {
                active.report.stop = Some(CompactionStop::PhysicalFailure);
            }
            active.report.observed_file_bytes = length;
            active.report.peak_file_bytes = active.report.peak_file_bytes.max(length);
        }
        Ok(())
    }
}

fn scratch_requirement(state: &IoState, maximum_growth_bytes: u64) -> Result<u64, StoreError> {
    if maximum_growth_bytes > 64 * 1024 * 1024 {
        return Err(StoreError::Invalid);
    }
    state
        .file_bytes
        .checked_add(maximum_growth_bytes)
        .map(|bytes| bytes.min(state.maximum_file_bytes).div_ceil(4096))
        .and_then(|pages| pages.checked_mul(8192))
        .and_then(|bytes| bytes.checked_add(256 * 1024))
        .ok_or(StoreError::Capacity)
}

pub(in crate::embedded) struct Lease<'a> {
    state: &'a Mutex<IoState>,
    finished: bool,
}
impl Lease<'_> {
    pub(in crate::embedded) fn started(&mut self) {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .active
            .as_mut()
            .expect("retained compaction lease")
            .report
            .engine_started = true;
    }
    pub(in crate::embedded) fn finish(
        mut self,
        engine_completed: bool,
        changed: Option<bool>,
    ) -> CompactionReport {
        let report = finish(self.state, engine_completed, changed);
        self.finished = true;
        report
    }
}
fn finish(
    state: &Mutex<IoState>,
    engine_completed: bool,
    changed: Option<bool>,
) -> CompactionReport {
    let mut state = state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let mut active = state.active.take().expect("one retained compaction lease");
    active.report.elapsed_micros =
        u64::try_from(active.started.elapsed().as_micros()).unwrap_or(u64::MAX);
    active.report.engine_completed = engine_completed;
    active.report.changed = if active.report.engine_started {
        changed
    } else {
        Some(false)
    };
    if active.report.stop.is_none() {
        if Instant::now() >= active.limits.deadline {
            active.report.stop = Some(CompactionStop::Deadline);
        } else if !engine_completed {
            active.report.stop = Some(if active.report.engine_started {
                CompactionStop::PhysicalFailure
            } else {
                CompactionStop::PreflightRefusal
            });
        }
    }
    state.last = Some(active.report);
    active.report
}
impl Drop for Lease<'_> {
    fn drop(&mut self) {
        if !self.finished {
            finish(self.state, false, None);
        }
    }
}
