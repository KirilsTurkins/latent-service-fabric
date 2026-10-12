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
        // The publication batch predates the dispatch guard so unwinding
        // releases the fair turn before reclaiming any unaccepted assignment.
        let mut publications = Vec::new();
        let (sequence, dispatch) = self.register_owned_request(class, request, sender, true)?;
        let mut registration = WaitRegistration::new(Arc::clone(&self.inner), id, sequence);
        self.inner.pump_owned(
            class,
            dispatch.expect("immediate registration owns its fair turn"),
            &mut publications,
        );
        match receiver.try_recv() {
            Ok(result) => {
                registration.disarm();
                result?.accept()
            }
            Err(oneshot::error::TryRecvError::Empty) => {
                registration.remove(PlatformErrorCode::ResourceExhausted);
                // This bounded original pass found no fair capacity. Closing
                // the receiver leaves no executing activation or pool waiter.
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
