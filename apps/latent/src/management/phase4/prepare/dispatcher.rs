use super::{c, finish, phase4, Operation, Request};
use crate::{
    args::dispatcher::{DispatcherAction, DispatcherCommand, DispatcherControlArgs},
    error::Failure,
};

fn control(value: &DispatcherControlArgs, action: DispatcherAction) -> c::ControlDispatcherRequest {
    c::ControlDispatcherRequest {
        profile: Some(phase4::current_profile()),
        scope: c::DispatcherScope::Node as i32,
        operation_id: value.operation_id.clone(),
        action: match action {
            DispatcherAction::Pause => c::DispatcherAction::Pause,
            DispatcherAction::Resume => c::DispatcherAction::Resume,
        } as i32,
        expected_generation: Some(c::DispatcherGeneration {
            owner_epoch: value.expected_owner_epoch,
            revision: value.expected_revision,
        }),
    }
}
pub fn prepare_dispatcher(command: &DispatcherCommand) -> Result<Operation, Failure> {
    command.validate()?;
    finish(match command {
        DispatcherCommand::Inspect(_) => Request::from(c::InspectDispatcherRequest {
            profile: Some(phase4::current_profile()),
            scope: c::DispatcherScope::Node as i32,
        }),
        DispatcherCommand::Pause(value) => Request::from(control(value, DispatcherAction::Pause)),
        DispatcherCommand::Resume(value) => Request::from(control(value, DispatcherAction::Resume)),
        DispatcherCommand::Operation(value) => Request::from(c::GetDispatcherOperationRequest {
            original: Some(control(&value.original, value.original_action)),
        }),
    })
}
