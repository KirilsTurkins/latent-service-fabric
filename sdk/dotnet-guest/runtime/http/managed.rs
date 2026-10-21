//! Compiler-private logical owner bridge. It adds no grant or replacement
//! limit, and it never treats native resource destruction as Task completion.
use super::{
    exports::latent::dotnet_managed_work::owner::Guest, latent::runtime::activation as runtime,
    owner, ClosedRuntime,
};

fn error(value: runtime::Error) -> u32 {
    match value {
        runtime::Error::Unavailable => 0,
        runtime::Error::PermissionDenied => 1,
        runtime::Error::ResourceExhausted => 2,
        runtime::Error::Cancelled => 3,
        runtime::Error::Deadline => 4,
        runtime::Error::InvalidState => 5,
        runtime::Error::InvalidToken => 6,
    }
}

fn parent(generation: u64, id: u64) -> Result<Option<runtime::Token>, u32> {
    match (generation, id) {
        (0, 0) => Ok(None),
        (0, _) | (_, 0) => Err(6),
        _ => Ok(Some(runtime::Token { generation, id })),
    }
}

impl Guest for ClosedRuntime {
    fn reserve(kind: u32, generation: u64, id: u64) -> Result<(u64, u64), u32> {
        let kind = match kind {
            0 => runtime::OwnerKind::Task,
            1 => runtime::OwnerKind::ManagedIdleWorker,
            2 => runtime::OwnerKind::Executor,
            3 => runtime::OwnerKind::QueuedWork,
            4 => runtime::OwnerKind::Wait,
            5 => runtime::OwnerKind::Timer,
            6 => runtime::OwnerKind::Result,
            7 => runtime::OwnerKind::Native,
            _ => return Err(5),
        };
        runtime::register(kind, parent(generation, id)?)
            .map(|token| (token.generation, token.id))
            .map_err(error)
    }

    fn settle(generation: u64, id: u64) -> Result<(), u32> {
        let token = parent(generation, id)?.ok_or(6u32)?;
        runtime::settle(token).map_err(error)
    }

    fn close() -> Result<(), u32> {
        runtime::close().map_err(error)
    }

    fn context(generation: u64, id: u64) {
        // The exact copied CoreLib registry supplies only its still-owned Task
        // token. Every actual child registration revalidates it in the host.
        owner::set_continuation(parent(generation, id).expect("invalid managed work context"));
    }
}
