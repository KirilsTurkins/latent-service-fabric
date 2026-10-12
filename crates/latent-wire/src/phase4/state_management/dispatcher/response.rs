use super::{capacity, contract, Access, Arc, OwnedPhase4Response, PlatformError};
impl crate::phase4::Phase4ResponseOwner for Access {
    fn reserved_bytes(&self) -> usize {
        self.permit.reserved_response_bytes()
    }
    fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        Access::with_current(self, &mut || {
            publish();
            Ok(())
        })
    }
}
pub(super) fn owned(
    access: Arc<Access>,
    response: contract::Response,
) -> Result<OwnedPhase4Response, PlatformError> {
    let needed = response
        .encoded_len()
        .checked_mul(4)
        .and_then(|v| v.checked_add(16384))
        .ok_or_else(capacity)?;
    if needed > access.permit.reserved_response_bytes() {
        return Err(capacity());
    }
    access.with_current(&mut || Ok(()))?;
    Ok(OwnedPhase4Response::new(response, access))
}
