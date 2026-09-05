fn terminal_state_for_platform_error(code: PlatformErrorCode) -> ActivationTerminalState {
    match code {
        PlatformErrorCode::DeadlineExceeded => ActivationTerminalState::DeadlineExceeded,
        PlatformErrorCode::Cancelled => ActivationTerminalState::Cancelled,
        PlatformErrorCode::ResourceExhausted => ActivationTerminalState::ResourceExhausted,
        PlatformErrorCode::GuestTrap => ActivationTerminalState::GuestTrap,
        PlatformErrorCode::StateConflict => ActivationTerminalState::StateConflict,
        PlatformErrorCode::DependencyFailed => ActivationTerminalState::DependencyFailed,
        PlatformErrorCode::AdmissionRejected
        | PlatformErrorCode::PermissionDenied
        | PlatformErrorCode::Unauthenticated
        | PlatformErrorCode::InvalidArgument
        | PlatformErrorCode::NotFound
        | PlatformErrorCode::IncompatibleContract
        | PlatformErrorCode::RouteUnavailable => ActivationTerminalState::Rejected,
        _ => ActivationTerminalState::PlatformFailed,
    }
}