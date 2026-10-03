use exports::wasi::{cli, clocks, filesystem, io, random};
struct ClosedRuntime;
struct ClosedDescriptor;
struct ClosedDirectoryEntries;
struct ClosedTerminalInput;
struct ClosedTerminalOutput;
impl io::poll::Guest for ClosedRuntime {
    type Pollable = ClosedPoll;
    fn poll(inputs: Vec<io::poll::PollableBorrow<'_>>) -> Vec<u32> {
        ClosedPoll::poll(inputs)
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
        io::streams::InputStream::new(ClosedInput::closed())
    }
}
impl cli::stdout::Guest for ClosedRuntime {
    fn get_stdout() -> io::streams::OutputStream {
        io::streams::OutputStream::new(ClosedOutput::closed())
    }
}
impl cli::stderr::Guest for ClosedRuntime {
    fn get_stderr() -> io::streams::OutputStream {
        io::streams::OutputStream::new(ClosedOutput::closed())
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
        ClosedPoll::timer(_when, true)
    }
    fn subscribe_duration(_when: u64) -> io::poll::Pollable {
        ClosedPoll::timer(_when, false)
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
    type DirectoryEntryStream = ClosedDirectoryEntries;
}
impl filesystem::types::GuestDirectoryEntryStream for ClosedDirectoryEntries {
    fn read_directory_entry(
        &self,
    ) -> Result<Option<filesystem::types::DirectoryEntry>, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
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
    fn get_flags(
        &self,
    ) -> Result<filesystem::types::DescriptorFlags, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn advise(
        &self,
        _offset: u64,
        _length: u64,
        _advice: filesystem::types::Advice,
    ) -> Result<(), filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn read(
        &self,
        _length: u64,
        _offset: u64,
    ) -> Result<(Vec<u8>, bool), filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn write(&self, _buffer: Vec<u8>, _offset: u64) -> Result<u64, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn read_directory(
        &self,
    ) -> Result<filesystem::types::DirectoryEntryStream, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn sync(&self) -> Result<(), filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn stat(&self) -> Result<filesystem::types::DescriptorStat, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn stat_at(
        &self,
        _path_flags: filesystem::types::PathFlags,
        _path: String,
    ) -> Result<filesystem::types::DescriptorStat, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn open_at(
        &self,
        _path_flags: filesystem::types::PathFlags,
        _path: String,
        _open_flags: filesystem::types::OpenFlags,
        _flags: filesystem::types::DescriptorFlags,
    ) -> Result<filesystem::types::Descriptor, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn readlink_at(&self, _path: String) -> Result<String, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn unlink_file_at(&self, _path: String) -> Result<(), filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn metadata_hash(
        &self,
    ) -> Result<filesystem::types::MetadataHashValue, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
    fn metadata_hash_at(
        &self,
        _path_flags: filesystem::types::PathFlags,
        _path: String,
    ) -> Result<filesystem::types::MetadataHashValue, filesystem::types::ErrorCode> {
        Err(filesystem::types::ErrorCode::NotPermitted)
    }
}
