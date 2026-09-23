//! Capability-constrained WASI support for the pinned NativeAOT library profile.
//! GC timing requires the explicitly admitted LSF monotonic clock. This guest
//! adapter neither obtains ambient authority nor owns an OS resource.
#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: "../../sdk/dotnet-guest/runtime/wit",
    world: "closed",
});

use exports::wasi::{cli, clocks, filesystem, io, random};

struct ClosedRuntime;
struct ClosedInput;
struct ClosedOutput;
struct ClosedPoll;
struct ClosedError;
struct ClosedDescriptor;
struct ClosedTerminalInput;
struct ClosedTerminalOutput;

impl io::poll::Guest for ClosedRuntime {
    type Pollable = ClosedPoll;
}
impl io::poll::GuestPollable for ClosedPoll {
    fn block(&self) {
        panic!("WASI polling is unsupported; await a declared LSF capability");
    }
}
impl io::error::Guest for ClosedRuntime {
    type Error = ClosedError;
}
impl io::error::GuestError for ClosedError {}
impl io::streams::Guest for ClosedRuntime {
    type InputStream = ClosedInput;
    type OutputStream = ClosedOutput;
}
impl io::streams::GuestInputStream for ClosedInput {}
impl io::streams::GuestOutputStream for ClosedOutput {
    fn check_write(&self) -> Result<u64, io::streams::StreamError> {
        Err(io::streams::StreamError::Closed)
    }
    fn write(&self, _contents: Vec<u8>) -> Result<(), io::streams::StreamError> {
        Err(io::streams::StreamError::Closed)
    }
    fn blocking_flush(&self) -> Result<(), io::streams::StreamError> {
        Err(io::streams::StreamError::Closed)
    }
    fn subscribe(&self) -> io::poll::Pollable {
        panic!("WASI stream subscriptions are unsupported");
    }
}
impl cli::environment::Guest for ClosedRuntime {
    fn get_environment() -> Vec<(String, String)> {
        Vec::new()
    }
}
impl cli::exit::Guest for ClosedRuntime {
    fn exit(_status: Result<(), ()>) {
        panic!("a capsule cannot exit its host process");
    }
}
impl cli::stdin::Guest for ClosedRuntime {
    fn get_stdin() -> io::streams::InputStream {
        io::streams::InputStream::new(ClosedInput)
    }
}
impl cli::stdout::Guest for ClosedRuntime {
    fn get_stdout() -> io::streams::OutputStream {
        io::streams::OutputStream::new(ClosedOutput)
    }
}
impl cli::stderr::Guest for ClosedRuntime {
    fn get_stderr() -> io::streams::OutputStream {
        io::streams::OutputStream::new(ClosedOutput)
    }
}
impl cli::terminal_input::Guest for ClosedRuntime {
    type TerminalInput = ClosedTerminalInput;
}
impl cli::terminal_input::GuestTerminalInput for ClosedTerminalInput {}
impl cli::terminal_output::Guest for ClosedRuntime {
    type TerminalOutput = ClosedTerminalOutput;
}
impl cli::terminal_output::GuestTerminalOutput for ClosedTerminalOutput {}
impl cli::terminal_stdin::Guest for ClosedRuntime {
    fn get_terminal_stdin() -> Option<cli::terminal_input::TerminalInput> {
        None
    }
}
impl cli::terminal_stdout::Guest for ClosedRuntime {
    fn get_terminal_stdout() -> Option<cli::terminal_output::TerminalOutput> {
        None
    }
}
impl cli::terminal_stderr::Guest for ClosedRuntime {
    fn get_terminal_stderr() -> Option<cli::terminal_output::TerminalOutput> {
        None
    }
}
impl clocks::monotonic_clock::Guest for ClosedRuntime {
    fn now() -> u64 {
        // NativeAOT's GC requests this during initialization. Never synthesize
        // timestamps or install WASI in the node: this ordinary LSF import is
        // manifest-declared, bound by admission and charged by the host.
        latent::clock::monotonic::now_nanos()
    }
    fn subscribe_instant(_when: u64) -> io::poll::Pollable {
        panic!("WASI timers are unsupported");
    }
    fn subscribe_duration(_when: u64) -> io::poll::Pollable {
        panic!("WASI timers are unsupported");
    }
}
impl clocks::wall_clock::Guest for ClosedRuntime {
    fn now() -> clocks::wall_clock::Datetime {
        panic!("WASI clocks are unsupported; import latent:clock/wall explicitly");
    }
}
impl random::random::Guest for ClosedRuntime {
    fn get_random_bytes(_len: u64) -> Vec<u8> {
        panic!("WASI entropy is unsupported; import latent:random/random explicitly");
    }
}
impl filesystem::preopens::Guest for ClosedRuntime {
    fn get_directories() -> Vec<(filesystem::types::Descriptor, String)> {
        Vec::new()
    }
}
impl filesystem::types::Guest for ClosedRuntime {
    type Descriptor = ClosedDescriptor;
}
impl filesystem::types::GuestDescriptor for ClosedDescriptor {
    fn read_via_stream(
        &self,
        _offset: u64,
    ) -> Result<io::streams::InputStream, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn write_via_stream(
        &self,
        _offset: u64,
    ) -> Result<io::streams::OutputStream, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn append_via_stream(&self) -> Result<io::streams::OutputStream, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn get_flags(&self) -> Result<filesystem::types::DescriptorFlags, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn stat(&self) -> Result<filesystem::types::DescriptorStat, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn metadata_hash(&self) -> Result<filesystem::types::MetadataHashValue, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
}

export!(ClosedRuntime);
