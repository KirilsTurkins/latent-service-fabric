use super::{
    capacity, codec, corrupt, filename, io, AuditCursor, AuditPageCoverage, AuditPageStop,
    AuditQueryRequest, AuditStoredRecord, Result, Store,
};
use std::time::Instant;
impl Store {
    #[expect(
        clippy::too_many_lines,
        reason = "The bounded cursor scan keeps its deadline, continuation and page ownership decisions together"
    )]
    pub fn query(
        &self,
        q: &AuditQueryRequest,
        deadline: Instant,
        dropped: u64,
    ) -> Result<(
        Vec<AuditStoredRecord>,
        AuditPageCoverage,
        Option<AuditCursor>,
    )> {
        check_deadline(deadline)?;
        let filter = codec::digest(&codec::encode(&(&q.scope, &q.filter), 4096)?);
        let (mut after, high) = if let Some(cursor) = &q.cursor {
            if cursor.0.len() > 256 {
                return Err(super::super::invalid());
            }
            let p: Vec<_> = cursor.0.split(':').collect();
            if p.len() != 5
                || p[0] != "1"
                || p[1] != self.head.epoch
                || p[2] != filter
                || !codec::hex(p[3], 16)
                || !codec::hex(p[4], 16)
            {
                return Err(super::super::invalid());
            }
            let a = u64::from_str_radix(p[3], 16).map_err(|_| corrupt())?;
            let h = u64::from_str_radix(p[4], 16).map_err(|_| corrupt())?;
            if a > h || h >= self.head.next_sequence {
                return Err(super::super::invalid());
            }
            (a, h)
        } else {
            (0, self.head.next_sequence - 1)
        };
        let mut events = Vec::new();
        let mut scanned = 0;
        let mut used = 1024usize;
        let mut stop = AuditPageStop::End;
        for e in self
            .entries
            .iter()
            .skip(usize::try_from(after).map_err(|_| corrupt())?)
        {
            if e.sequence > high {
                break;
            }
            check_deadline(deadline)?;
            if scanned == self.limits.maximum_scan_entries {
                stop = AuditPageStop::ScanLimit;
                break;
            }
            if events.len() == q.limit {
                stop = AuditPageStop::RecordLimit;
                break;
            }
            let matches = e.scope == q.scope
                && q.filter.kind.is_none_or(|k| e.kind == Some(k))
                && q.filter.actor.as_ref().is_none_or(|a| a == &e.actor)
                && q.filter.from_unix_millis.is_none_or(|t| e.time >= t)
                && q.filter.to_unix_millis.is_none_or(|t| e.time <= t);
            if matches {
                let cost = e
                    .bytes
                    .checked_mul(2)
                    .and_then(|b| b.checked_add(1024))
                    .ok_or_else(capacity)?;
                if cost > q.maximum_bytes - used {
                    if events.is_empty() {
                        return Err(super::super::error(
                            latent_core::PlatformErrorCode::ResourceExhausted,
                            "audit-page-too-small",
                        ));
                    }
                    stop = AuditPageStop::ByteLimit;
                    break;
                }
                let bytes = io::read(
                    &self.root.path.join("records").join(filename(e.sequence)),
                    self.limits.maximum_record_bytes,
                )?;
                if bytes.len() != e.bytes || codec::digest(&bytes) != e.digest {
                    return Err(corrupt());
                }
                let record = codec::decode(&bytes, self.limits.maximum_record_bytes)?;
                codec::record(&record)?;
                #[cfg(test)]
                EXPIRE_AFTER_READ.with(|flag| {
                    if flag.get() {
                        EXPIRED.with(|v| v.set(true));
                    }
                });
                events.try_reserve_exact(1).map_err(|_| capacity())?;
                events.push(record);
                used += cost;
            }
            scanned += 1;
            after = e.sequence;
        }
        if after == high {
            stop = AuditPageStop::End;
        }
        let next = (after < high).then(|| {
            AuditCursor(format!(
                "1:{}:{filter}:{after:016x}:{high:016x}",
                self.head.epoch
            ))
        });
        check_deadline(deadline)?;
        Ok((
            events,
            AuditPageCoverage {
                epoch: self.head.epoch.clone(),
                retained_floor: 1,
                high_watermark: high,
                scanned,
                stop,
                dropped_observations: dropped,
                unknown_outcomes: self.unknown,
                previous_session_loss_unknown: self.previous_session_loss_unknown,
            },
            next,
        ))
    }
}
fn check_deadline(deadline: Instant) -> Result<()> {
    #[cfg(test)]
    let injected = EXPIRED.with(std::cell::Cell::get);
    #[cfg(not(test))]
    let injected = false;
    if Instant::now() >= deadline || injected {
        return Err(super::super::error(
            latent_core::PlatformErrorCode::DeadlineExceeded,
            "audit-query-deadline",
        ));
    }
    Ok(())
}
#[cfg(test)]
thread_local! {
    pub(super) static EXPIRE_AFTER_READ:std::cell::Cell<bool>=const{std::cell::Cell::new(false)};
    pub(super) static EXPIRED:std::cell::Cell<bool>=const{std::cell::Cell::new(false)};
}
