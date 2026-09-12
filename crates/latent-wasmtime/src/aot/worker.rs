//! Disposable worker entry point. It never seals or authenticates native output.

use super::protocol::WorkerOptions;

/// Runs only the standalone compiler-child command and returns its exit status.
/// This changes process-wide limits and installs irreversible thread restrictions;
/// applications must invoke the separate binary, never call this in their node.
#[must_use]
pub fn run_aot_compiler_worker() -> i32 {
    use std::io::Write as _;

    // Compiler panics may contain arbitrary input/host details. The parent only
    // receives our fixed diagnostic, and still owns termination and reaping.
    std::panic::set_hook(Box::new(|_| {}));
    let result = std::panic::catch_unwind(|| {
        let (options, clean) =
            WorkerOptions::parse(std::env::args_os().skip(1)).map_err(|_| "invalid arguments")?;
        run(options, clean)
    });
    let reason = match result {
        Ok(Ok(())) => return 0,
        Ok(Err(reason)) => reason,
        Err(_) => "compiler panic",
    };
    let _ = writeln!(std::io::stderr(), "aot compiler worker failed: {reason}");
    2
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn run(options: WorkerOptions, clean: bool) -> Result<(), &'static str> {
    use super::{profile, protocol, sandbox, AotCompilerLimits};
    use std::io::Write as _;

    let mut arguments = options
        .arguments()
        .map_err(|_| "invalid arguments")?
        .map(std::ffi::OsString::from);
    arguments[0] = protocol::CLEAN_WORKER_ARGUMENT.into();
    sandbox::prepare_launch(
        options.sandbox,
        options.parent_pid,
        (!clean).then_some(arguments.as_slice()),
    )
    .map_err(|_| "worker launch rejected")?;
    let mut input = Input(std::io::stdin());
    let mut output = Output(std::io::stdout());
    // Only this fixed four-byte header is read before bootstrap. The parent
    // authenticates /proc/pid/exe before sending it. Dump protection is applied
    // at final entry after the child's own last /proc inventory too. There is no
    // buffering/read-ahead and no Wasm or variable-length allocation here.
    let bootstrap_length =
        protocol::bootstrap_length(&mut input).map_err(|_| "invalid bootstrap length")?;
    let prepared = sandbox::bootstrap(options.sandbox, options.parent_pid)
        .map_err(|_| "sandbox bootstrap rejected")?;
    let bootstrap =
        protocol::body(&mut input, bootstrap_length).map_err(|_| "invalid bootstrap body")?;
    let limits = AotCompilerLimits {
        maximum_output_bytes: options.maximum_output_bytes,
        ..AotCompilerLimits::default()
    };
    let (engine, compatibility) = profile::engine_from_bootstrap(&bootstrap, limits)
        .map_err(|_| "invalid engine bootstrap")?;
    drop(bootstrap);
    let enforced = prepared
        .enter()
        .map_err(|_| "sandbox enforcement rejected")?;
    if enforced.profile_id() != sandbox::PROFILE_ID {
        return Err("sandbox identity mismatch");
    }
    output
        .write_all(&protocol::readiness(&compatibility))
        .map_err(|_| "readiness pipe failed")?;
    output.flush().map_err(|_| "readiness pipe failed")?;
    compile(&enforced, &engine, options, &mut input, &mut output)
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn compile(
    _enforced: &super::sandbox::EnforcedSandbox,
    engine: &wasmtime::Engine,
    options: WorkerOptions,
    input: &mut Input,
    output: &mut Output,
) -> Result<(), &'static str> {
    use super::protocol;
    use std::io::Write as _;

    let length = protocol::input_length(input, options.maximum_input_bytes)
        .map_err(|_| "invalid component length")?;
    let bytes = protocol::body(input, length).map_err(|_| "invalid component body")?;
    protocol::end_of_input(input).map_err(|_| "trailing component input")?;
    let native = engine
        .precompile_component(&bytes)
        .map_err(|_| "component compilation failed")?;
    drop(bytes);
    if native.is_empty() || native.len() > options.maximum_output_bytes {
        return Err("native output limit exceeded");
    }
    let length = u64::try_from(native.len()).map_err(|_| "native output limit exceeded")?;
    output
        .write_all(&length.to_le_bytes())
        .map_err(|_| "native output pipe failed")?;
    output
        .write_all(&native)
        .map_err(|_| "native output pipe failed")?;
    output.flush().map_err(|_| "native output pipe failed")
}

#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
fn run(_options: WorkerOptions, _clean: bool) -> Result<(), &'static str> {
    Err("unsupported compiler platform")
}

// Direct safe descriptor I/O avoids std's input readahead across readiness.
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
struct Input(std::io::Stdin);

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
impl std::io::Read for Input {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        rustix::io::read(&self.0, buffer).map_err(Into::into)
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
struct Output(std::io::Stdout);

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
impl std::io::Write for Output {
    fn write(&mut self, buffer: &[u8]) -> std::io::Result<usize> {
        rustix::io::write(&self.0, buffer).map_err(Into::into)
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
