use super::{capacity, contract, Access, Arc, NamespaceRead, OwnedPhase4Response, PlatformError};
struct Owner {
    namespace: NamespaceRead,
    access: Arc<Access>,
}
impl crate::phase4::Phase4ResponseOwner for Owner {
    fn reserved_bytes(&self) -> usize {
        self.access.permit.reserved_response_bytes()
    }
    fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        self.access.publish(&self.namespace, publish)
    }
}
pub(super) fn owned(
    access: Arc<Access>,
    namespace: NamespaceRead,
    response: contract::Response,
) -> Result<OwnedPhase4Response, PlatformError> {
    let needed = response
        .encoded_len()
        .checked_mul(4)
        .and_then(|bytes| bytes.checked_add(16384))
        .ok_or_else(capacity)?;
    if needed > access.permit.reserved_response_bytes() {
        return Err(capacity());
    }
    access.publish(&namespace, &mut || {})?;
    Ok(OwnedPhase4Response::new(
        response,
        Arc::new(Owner { namespace, access }),
    ))
}
