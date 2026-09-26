//! Descendants get one normal fair dispatch pass and never wait on an ancestor.
use super::{
    class_named, error, AdmittedSchedulingRequest, LocalScheduler, PlatformError,
    PlatformErrorCode, ScheduledActivation, WaitRegistration,
};
use std::sync::Arc;
use tokio::sync::oneshot;

impl LocalScheduler {
    pub(super) fn try_enqueue_owned(
        &self,
        request: AdmittedSchedulingRequest,
    ) -> Result<ScheduledActivation, PlatformError> {
        let class = class_named(&request.permit.obligations().cell_class)
            .ok_or_else(|| error(PlatformErrorCode::InvalidArgument, "cell-class"))?;
        if let Err(error) = self.validate_request(&request) {
            self.inner.record_error(class, &error);
            return Err(error);
        }
        let id = request.permit.activation_id().clone();
        let (sender, mut receiver) = oneshot::channel();
        let sequence = self.register_request(class, request, sender)?;
        let mut registration = WaitRegistration::new(Arc::clone(&self.inner), id, sequence);
        self.inner.pump(class);
        match receiver.try_recv() {
            Ok(result) => {
                registration.disarm();
                result?.accept()
            }
            Err(oneshot::error::TryRecvError::Empty) => {
                registration.remove(PlatformErrorCode::ResourceExhausted);
                // A racing pump can still own a selected, unaccepted handoff.
                // Closing its receiver reclaims that exact lease and permit via
                // PendingAssignment; it cannot create an executing activation.
                Err(error(
                    PlatformErrorCode::ResourceExhausted,
                    "immediate-capacity-unavailable",
                ))
            }
            Err(oneshot::error::TryRecvError::Closed) => {
                registration.remove(PlatformErrorCode::Unavailable);
                Err(error(PlatformErrorCode::Unavailable, "handoff-closed"))
            }
        }
    }
}
