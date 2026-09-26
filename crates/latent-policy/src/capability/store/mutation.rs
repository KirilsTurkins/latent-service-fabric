use super::super::{capacity, error, invalid, unavailable};
use super::{
    codec,
    model::{Outcome, RecordView},
    Compiled, Loaded, MutationRequest, OperationReceipt, PolicyRead, PolicyStore, Stamp,
};
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::{atomic::Ordering, Arc};
use std::time::Instant;

impl PolicyStore {
    /// Preflight must construct and validate the bounded wire response before
    /// this method writes anything. A replay returns its original receipt even
    /// if that row has since changed; it never restores the historical grant.
    pub fn mutate(
        &self,
        request: MutationRequest<'_>,
        deadline: Instant,
        preflight: impl FnOnce(&OperationReceipt) -> Result<(), PlatformError>,
    ) -> Result<PolicyRead<OperationReceipt>, PlatformError> {
        request.validate()?;
        check_deadline(deadline)?;
        let lease = self.owner.mutation_lease()?;
        let mut state = self.lock()?;
        let _panic_guard = PoisonOnUnwind(&self.owner);
        let parsed = request
            .document
            .map(|bytes| Compiled::parse(request.kind, request.tenant, bytes))
            .transpose()?;
        let document = parsed
            .as_ref()
            .map(|value| std::str::from_utf8(value.canonical()).map_err(|_| invalid()))
            .transpose()?;
        let fingerprint = fingerprint(request, document)?;
        if let Some(old) = state.image.outcomes.iter().find(|value| {
            value.receipt.tenant == request.tenant
                && value.receipt.operation_id == request.operation_id
        }) {
            if old.fingerprint != fingerprint {
                return Err(conflict());
            }
            preflight(&old.receipt)?;
            check_deadline(deadline)?;
            return Ok(PolicyRead {
                value: old.receipt.clone(),
                lease,
            });
        }
        let index = state
            .image
            .records
            .iter()
            .position(|row| row.matches(request.tenant, request.kind, request.id));
        let previous = index.map(|index| &state.image.records[index]);
        if previous.map_or(0, |row| row.revision) != request.expected_revision
            || (previous.is_none() && document.is_none())
        {
            return Err(conflict());
        }
        if index.is_none() && state.image.records.len() == self.limits.maximum_records {
            return Err(capacity());
        }
        let revision = state.image.generation.checked_add(1).ok_or_else(capacity)?;
        let digest = parsed
            .as_ref()
            .map(Compiled::digest)
            .or_else(|| previous.map(|row| row.digest.as_str()))
            .ok_or_else(invalid)?
            .to_owned();
        let receipt = OperationReceipt {
            operation_id: request.operation_id.into(),
            tenant: request.tenant.into(),
            id: request.id.into(),
            kind: request.kind,
            revision,
            digest: digest.clone(),
            revoked: document.is_none(),
        };
        preflight(&receipt)?;
        check_deadline(deadline)?;
        let mut next = state.image.clone();
        next.generation = revision;
        let row = RecordView {
            tenant: request.tenant.into(),
            id: request.id.into(),
            kind: request.kind,
            revision,
            digest,
            document: document.map(str::to_owned),
        };
        if let Some(index) = index {
            next.records[index] = row;
        } else {
            next.records.push(row);
        }
        if next.outcomes.len() == self.limits.maximum_outcomes {
            next.outcomes.remove(0);
        }
        next.outcomes.push(Outcome {
            fingerprint,
            receipt: receipt.clone(),
        });
        let bytes = codec::encode(&next, self.limits.maximum_catalog_bytes)?;
        check_deadline(deadline)?;
        let _fence = self.owner.fence.try_write().map_err(|_| unavailable())?;
        self.owner.check()?;
        if let Err(error) = state.persist(&bytes, revision) {
            self.owner.poison();
            return Err(error);
        }
        install(&mut state, next, parsed, index);
        // After the first filesystem mutation cancellation cannot abandon the
        // commit. A late waiter recovers this exact outcome by operation ID.
        Ok(PolicyRead {
            value: receipt,
            lease,
        })
    }
}
fn fingerprint(
    request: MutationRequest<'_>,
    document: Option<&str>,
) -> Result<String, PlatformError> {
    Ok(codec::digest(&codec::encode(
        &(
            "lsf-capability-mutation-v1",
            request.tenant,
            request.actor,
            request.id,
            request.kind,
            request.operation_id,
            request.expected_revision,
            document,
        ),
        super::super::MAX_DOCUMENT_BYTES * 2 + 4096,
    )?))
}
fn install(
    state: &mut super::State,
    image: super::model::Image,
    parsed: Option<Compiled>,
    index: Option<usize>,
) {
    let loaded = Loaded {
        stamp: index.map_or_else(
            || Stamp::new(image.generation),
            |index| Arc::clone(&state.loaded[index].stamp),
        ),
        document: parsed.map(Arc::new),
    };
    loaded
        .stamp
        .revision
        .store(image.generation, Ordering::Release);
    if let Some(index) = index {
        state.loaded[index] = loaded;
    } else {
        state.loaded.push(loaded);
    }
    state.image = image;
}
struct PoisonOnUnwind<'a>(&'a super::Owner);
impl Drop for PoisonOnUnwind<'_> {
    fn drop(&mut self) {
        if std::thread::panicking() {
            self.0.poison();
        }
    }
}
pub(super) fn check_deadline(deadline: Instant) -> Result<(), PlatformError> {
    if Instant::now() >= deadline {
        return Err(error(
            PlatformErrorCode::DeadlineExceeded,
            "capability-policy-deadline",
        ));
    }
    Ok(())
}
fn conflict() -> PlatformError {
    error(
        PlatformErrorCode::StateConflict,
        "capability-policy-conflict",
    )
}
