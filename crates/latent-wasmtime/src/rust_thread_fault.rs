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

fn emit(authentication: &Authentication, error: &wasmtime::Error, sink: &mut impl Write) {
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
    // An explicit diagnostic binary writes at most eight fixed-format rows to
    // its existing process stderr (fewer than 800 bytes on 64-bit hosts). A
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
        let engine = wasmtime::Engine::default();
        let module = wasmtime::Module::new(&engine, module.finish()).unwrap();
        let mut store = wasmtime::Store::new(&engine, ());
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
        assert!(original.frames().len() > MAX_FRAMES);
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
        assert!(frames.iter().flatten().all(|frame| frame.function == 0
            && frame.module_offset.is_some()
            && frame.function_offset.is_some()));
        let mut output = std::io::Cursor::new([0_u8; 1024]);
        emit(&proof, &error, &mut output);
        let used = usize::try_from(output.position()).unwrap();
        let text = std::str::from_utf8(&output.get_ref()[..used]).unwrap();
        assert_eq!(text.lines().count(), MAX_FRAMES);
        assert!(text.lines().enumerate().all(|(ordinal, line)| {
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
        }
        let private = wasmtime::Error::msg("private unstructured diagnostic must never escape");
        assert_eq!(visit(&proof, &private, |_| panic!("unstructured trace")), 0);
    }
}
