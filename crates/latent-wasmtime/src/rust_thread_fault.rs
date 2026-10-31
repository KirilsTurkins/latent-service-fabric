//! Developer-only borrowed numeric frames from an actual authenticated fault.
//!
//! No error text, guest function/module name, native address or source data is
//! copied. This observer never replaces the original error. Diagnostic stderr
//! I/O is byte bounded, not time bounded: a full pipe can block. It runs before
//! wall observation/finalization and can perturb timing or terminal stop
//! observation. This explicit feature is not normal qualification evidence.
//! The original Wasmtime error retains all original backtrace/native owners.
use crate::component_threading::Authentication;
use std::io::Write;

const MAX_FRAMES: usize = 8;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Frame {
    function: u32,
    module_offset: Option<usize>,
    function_offset: Option<usize>,
}

fn visit(
    authentication: &Authentication,
    error: &wasmtime::Error,
    mut sink: impl FnMut(Frame),
) -> usize {
    if !matches!(authentication, Authentication::RustSyncVerified(_))
        || error.downcast_ref::<wasmtime::Trap>().is_none()
    {
        return 0;
    }
    let Some(trace) = error.downcast_ref::<wasmtime::WasmBacktrace>() else {
        return 0;
    };
    let mut count = 0;
    for frame in trace.frames().iter().take(MAX_FRAMES) {
        sink(Frame {
            function: frame.func_index(),
            module_offset: frame.module_offset(),
            function_offset: frame.func_offset(),
        });
        count += 1;
    }
    count
}

// The pinned wasmtime-environ 48.0.7 Trap is an original unit enum. Its
// source-defined u8 ordinal is borrowed from the actual typed error; no error
// text, guest data, native address or invented frame is formatted.
fn trap_code(authentication: &Authentication, error: &wasmtime::Error) -> Option<u8> {
    if !matches!(authentication, Authentication::RustSyncVerified(_)) {
        return None;
    }
    error.downcast_ref::<wasmtime::Trap>().map(|trap| *trap as u8)
}

fn emit(authentication: &Authentication, error: &wasmtime::Error, sink: &mut impl Write) {
    if let Some(code) = trap_code(authentication, error) {
        let _ = writeln!(sink, "LSF-RUST40-TRAP:{code}");
    }
    let mut ordinal = 0;
    visit(authentication, error, |frame| {
        let _ = writeln!(
            sink,
            "LSF-RUST40-FAULT:{ordinal}:{}:{}:{}",
            frame.function,
            frame.module_offset.unwrap_or(usize::MAX),
            frame.function_offset.unwrap_or(usize::MAX),
        );
        ordinal += 1;
    });
}

pub(crate) fn record(authentication: &Authentication, error: &wasmtime::Error) {
    if !matches!(authentication, Authentication::RustSyncVerified(_)) {
        return;
    }
    // The explicit binary writes at most one original Trap code and eight
    // fixed-format frame rows (fewer than 832 bytes on 64-bit hosts). A
    // draining sink is required by the owning diagnostic programme; writing is
    // not time bounded and its duration enters measured wall consumption.
    // There is no retained allocation,
    // global cache, new public error field, or guest-controlled formatted text.
    emit(authentication, error, &mut std::io::stderr().lock());
}

#[cfg(test)]
mod tests {
    use super::*;
    use wasm_encoder::{
        CodeSection, ExportKind, ExportSection, Function, FunctionSection, Instruction, Module,
        TypeSection,
    };

    #[test]
    fn rust_thread_fault_visits_only_eight_numeric_original_frames_for_authenticated_rust() {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], []);
        module.section(&types);
        let mut functions = FunctionSection::new();
        functions.function(0);
        module.section(&functions);
        let mut exports = ExportSection::new();
        exports.export(
            "private-guest-export-must-never-be-printed",
            ExportKind::Func,
            0,
        );
        module.section(&exports);
        let mut code = CodeSection::new();
        let mut function = Function::new([]);
        function
            .instruction(&Instruction::Call(0))
            .instruction(&Instruction::End);
        code.function(&function);
        module.section(&code);
        // Use the actual owning runtime engine policy, not Wasmtime's default:
        // ordinary nodes disable backtraces and this explicit feature fixes the
        // diagnostic node to eight numeric frames.
        let engine = crate::WasmtimeConfig::default().runtime_engine().unwrap();
        let module = wasmtime::Module::new(&engine, module.finish()).unwrap();
        let mut store = wasmtime::Store::new(&engine, ());
        // The owning engine meters every Store. Give this synthetic recursive
        // control enough finite fuel to reach Wasmtime's stack guard; the
        // production diagnostic still uses the invocation's admitted budget.
        store.set_fuel(1_000_000_000).unwrap();
        // The owning engine also enables epoch interruption. No host advances
        // epochs in this synthetic control, so a finite deadline keeps the
        // recursion on the stack-overflow path without changing runtime policy.
        store.set_epoch_deadline(1_000);
        let instance = wasmtime::Instance::new(&mut store, &module, &[]).unwrap();
        let function = instance
            .get_typed_func::<(), ()>(&mut store, "private-guest-export-must-never-be-printed")
            .unwrap();
        let error = function.call(&mut store, ()).unwrap_err();
        assert_eq!(
            error.downcast_ref::<wasmtime::Trap>(),
            Some(&wasmtime::Trap::StackOverflow)
        );
        let original = error.downcast_ref::<wasmtime::WasmBacktrace>().unwrap();
        // The owning diagnostic engine itself retains at most eight frames.
        assert_eq!(original.frames().len(), MAX_FRAMES);
        let mut frames = [None; MAX_FRAMES];
        let mut index = 0;
        let proof = Authentication::RustSyncVerified([0x11; 32]);
        assert_eq!(
            visit(&proof, &error, |frame| {
                frames[index] = Some(frame);
                index += 1;
            }),
            MAX_FRAMES
        );
        for (observed, source) in frames.iter().zip(original.frames()) {
            assert_eq!(source.func_index(), 0);
            // Wasmtime may have no instruction mapping for an individual
            // frame. Preserve its actual Options, never invent an address.
            assert_eq!(
                *observed,
                Some(Frame {
                    function: source.func_index(),
                    module_offset: source.module_offset(),
                    function_offset: source.func_offset(),
                })
            );
        }
        let mut output = std::io::Cursor::new([0_u8; 1024]);
        emit(&proof, &error, &mut output);
        let used = usize::try_from(output.position()).unwrap();
        let text = std::str::from_utf8(&output.get_ref()[..used]).unwrap();
        assert_eq!(trap_code(&proof, &error), Some(0));
        assert_eq!(wasmtime::Trap::from_u8(0), Some(wasmtime::Trap::StackOverflow));
        let frame_text = text.strip_prefix("LSF-RUST40-TRAP:0\n").unwrap();
        assert_eq!(frame_text.lines().count(), MAX_FRAMES);
        for (line, (ordinal, source)) in frame_text
            .lines()
            .zip(original.frames().iter().enumerate())
        {
            assert_eq!(
                line,
                format!(
                    "LSF-RUST40-FAULT:{ordinal}:{}:{}:{}",
                    source.func_index(),
                    source.module_offset().unwrap_or(usize::MAX),
                    source.func_offset().unwrap_or(usize::MAX)
                )
            );
        }
        assert!(frame_text.lines().enumerate().all(|(ordinal, line)| {
            let prefix = format!("LSF-RUST40-FAULT:{ordinal}:");
            line.strip_prefix(&prefix).is_some_and(|numbers| {
                numbers.split(':').count() == 3
                    && numbers.split(':').all(|number| {
                        !number.is_empty() && number.bytes().all(|byte| byte.is_ascii_digit())
                    })
            })
        }));
        assert!(!text.contains("private-guest-export"));
        for other in [
            Authentication::Disabled,
            Authentication::CVerified([0x11; 32]),
            Authentication::Verified([0x11; 32]),
        ] {
            assert_eq!(
                visit(&other, &error, |_| panic!("unauthenticated trace")),
                0
            );
            assert_eq!(trap_code(&other, &error), None);
            let mut denied = std::io::Cursor::new([0_u8; 1024]);
            emit(&other, &error, &mut denied);
            assert_eq!(denied.position(), 0);
        }
        let private = wasmtime::Error::msg("private unstructured diagnostic must never escape");
        assert_eq!(visit(&proof, &private, |_| panic!("unstructured trace")), 0);
        assert_eq!(trap_code(&proof, &private), None);
        let mut denied = std::io::Cursor::new([0_u8; 1024]);
        emit(&proof, &private, &mut denied);
        assert_eq!(denied.position(), 0);

        // A typed component-runtime Trap may have no Wasm stack. Preserve its
        // exact original ordinal separately without fabricating any frames.
        let host = wasmtime::Error::from(wasmtime::Trap::CannotEnterComponent);
        assert!(host.downcast_ref::<wasmtime::WasmBacktrace>().is_none());
        assert_eq!(trap_code(&proof, &host), Some(17));
        assert_eq!(visit(&proof, &host, |_| panic!("invented host frame")), 0);
        let mut scalar = std::io::Cursor::new([0_u8; 1024]);
        emit(&proof, &host, &mut scalar);
        assert_eq!(
            &scalar.get_ref()[..scalar.position() as usize],
            b"LSF-RUST40-TRAP:17\n"
        );
    }
}
