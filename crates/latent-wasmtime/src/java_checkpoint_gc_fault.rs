//! Developer-only bounded numeric frames for the authenticated Java GC probe.
//!
//! The observer copies no error text, function/module name, native address or
//! source data and never replaces the original error. It is compiled only into
//! the explicitly rebuilt diagnostic node used by the owning hosted workflow.
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
    if !matches!(authentication, Authentication::Verified(_))
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
            "LSF-JAVA-GC-FAULT:{ordinal}:{}:{}:{}",
            frame.function,
            frame.module_offset.unwrap_or(usize::MAX),
            frame.function_offset.unwrap_or(usize::MAX),
        );
        ordinal += 1;
    });
}

pub(crate) fn record(authentication: &Authentication, error: &wasmtime::Error) {
    if !matches!(authentication, Authentication::Verified(_)) {
        return;
    }
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
    fn java_gc_fault_visits_only_eight_numeric_frames_for_authenticated_profile() {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], []);
        module.section(&types);
        let mut functions = FunctionSection::new();
        functions.function(0);
        module.section(&functions);
        let mut exports = ExportSection::new();
        exports.export("private-name", ExportKind::Func, 0);
        module.section(&exports);
        let mut code = CodeSection::new();
        let mut function = Function::new([]);
        function
            .instruction(&Instruction::Call(0))
            .instruction(&Instruction::End);
        code.function(&function);
        module.section(&code);
        // Exercise the owning runtime engine policy. Ordinary nodes disable
        // backtraces; this explicit feature fixes the diagnostic cap at eight.
        let engine = crate::WasmtimeConfig::default().runtime_engine().unwrap();
        let module = wasmtime::Module::new(&engine, module.finish()).unwrap();
        let mut store = wasmtime::Store::new(&engine, ());
        let instance = wasmtime::Instance::new(&mut store, &module, &[]).unwrap();
        let function = instance
            .get_typed_func::<(), ()>(&mut store, "private-name")
            .unwrap();
        let error = function.call(&mut store, ()).unwrap_err();
        let original = error.downcast_ref::<wasmtime::WasmBacktrace>().unwrap();
        assert!(original.frames().len() > MAX_FRAMES);
        let proof = Authentication::Verified([0x11; 32]);
        let mut output = std::io::Cursor::new([0_u8; 1024]);
        emit(&proof, &error, &mut output);
        let used = usize::try_from(output.position()).unwrap();
        let text = std::str::from_utf8(&output.get_ref()[..used]).unwrap();
        assert_eq!(text.lines().count(), MAX_FRAMES);
        assert!(text.lines().enumerate().all(|(ordinal, line)| {
            let prefix = format!("LSF-JAVA-GC-FAULT:{ordinal}:");
            line.strip_prefix(&prefix).is_some_and(|numbers| {
                numbers.split(':').count() == 3
                    && numbers.split(':').all(|number| {
                        !number.is_empty() && number.bytes().all(|byte| byte.is_ascii_digit())
                    })
            })
        }));
        assert!(!text.contains("private-name"));
        for other in [
            Authentication::Disabled,
            Authentication::CVerified([0x11; 32]),
            Authentication::RustSyncVerified([0x11; 32]),
        ] {
            assert_eq!(visit(&other, &error, |_| panic!("wrong profile trace")), 0);
        }
    }
}
