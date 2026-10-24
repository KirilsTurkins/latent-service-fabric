//! Test-host-only, explicitly armed numeric observation of one original error.
//!
//! This is not an error sink or authority. No error, module, function name,
//! request or backtrace owner survives capture. Disabled calls do not lock.
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use latent_core::{PlatformError, PlatformErrorCode};
use wasmtime::{Module, Trap, WasmBacktrace};

const MAX_FRAMES: usize = 16;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DevelopmentTrapFrame {
    /// First-seen module ordinal within this one backtrace, not an address.
    pub module: u8,
    pub function: u32,
    pub module_offset: Option<usize>,
    pub function_offset: Option<usize>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DevelopmentTrapSnapshot {
    pub observed_errors: u32,
    pub ambiguous: bool,
    pub trap_kind: Option<&'static str>,
    pub missing_backtrace: bool,
    pub truncated: bool,
    pub total_frames: usize,
    pub frames: [Option<DevelopmentTrapFrame>; MAX_FRAMES],
}

#[derive(Default)]
struct State {
    armed_once: bool,
    observation: DevelopmentTrapSnapshot,
}

#[derive(Default)]
pub(crate) struct DevelopmentTrapObserver {
    enabled: AtomicBool,
    state: Mutex<State>,
}

/// An explicit test-harness opt-in. Dropping it disables further observation.
pub struct DevelopmentTrapGuard<'a>(&'a DevelopmentTrapObserver);

fn refused() -> PlatformError {
    crate::containment::platform_error(
        PlatformErrorCode::StateConflict,
        "development trap observation unavailable",
        false,
    )
}

impl DevelopmentTrapObserver {
    pub(crate) fn arm(&self) -> Result<DevelopmentTrapGuard<'_>, PlatformError> {
        let mut state = self.state.lock().map_err(|_| refused())?;
        if state.armed_once {
            return Err(refused());
        }
        state.armed_once = true;
        self.enabled.store(true, Ordering::Release);
        Ok(DevelopmentTrapGuard(self))
    }

    pub(crate) fn capture(&self, error: &wasmtime::Error) {
        if !self.enabled.load(Ordering::Acquire) {
            return;
        }
        let Ok(mut state) = self.state.lock() else {
            return; // snapshot reports poison; the original outcome is untouched.
        };
        if !self.enabled.load(Ordering::Acquire) {
            return;
        }
        let observed = &mut state.observation;
        observed.observed_errors = observed.observed_errors.saturating_add(1);
        if observed.observed_errors != 1 {
            observed.ambiguous = true;
            return; // Never replace the first original error.
        }
        observed.trap_kind = error
            .downcast_ref::<Trap>()
            .map(crate::containment::development_trap_label);
        let Some(backtrace) = error.downcast_ref::<WasmBacktrace>() else {
            observed.missing_backtrace = true;
            return;
        };
        let frames = backtrace.frames();
        observed.total_frames = frames.len();
        observed.truncated = frames.len() > MAX_FRAMES;
        let mut modules: [Option<&Module>; MAX_FRAMES] = [None; MAX_FRAMES];
        let mut module_count = 0;
        for (index, frame) in frames.iter().take(MAX_FRAMES).enumerate() {
            let ordinal = modules[..module_count]
                .iter()
                .position(|item| Module::same(item.unwrap(), frame.module()))
                .unwrap_or_else(|| {
                    let ordinal = module_count;
                    modules[ordinal] = Some(frame.module());
                    module_count += 1;
                    ordinal
                });
            observed.frames[index] = Some(DevelopmentTrapFrame {
                module: u8::try_from(ordinal).expect("at most sixteen modules"),
                function: frame.func_index(),
                module_offset: frame.module_offset(),
                function_offset: frame.func_offset(),
            });
        }
    }
}

impl DevelopmentTrapGuard<'_> {
    /// Copies only the fixed numeric record; it cannot retain runtime owners.
    pub fn snapshot(&self) -> Result<DevelopmentTrapSnapshot, PlatformError> {
        self.0
            .state
            .lock()
            .map(|state| state.observation)
            .map_err(|_| refused())
    }
}

impl Drop for DevelopmentTrapGuard<'_> {
    fn drop(&mut self) {
        self.0.enabled.store(false, Ordering::Release);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_capture_is_empty_and_second_arm_is_refused_even_after_drop() {
        let observer = DevelopmentTrapObserver::default();
        observer.capture(&wasmtime::Error::msg("unretained private text"));
        let guard = observer.arm().unwrap();
        assert_eq!(
            guard.snapshot().unwrap(),
            DevelopmentTrapSnapshot::default()
        );
        assert!(observer.arm().is_err());
        drop(guard);
        assert!(observer.arm().is_err());
    }

    #[test]
    fn first_error_is_not_replaced_and_guard_drop_stops_capture() {
        let observer = DevelopmentTrapObserver::default();
        let guard = observer.arm().unwrap();
        observer.capture(&Trap::UnreachableCodeReached.into());
        let first = guard.snapshot().unwrap();
        assert_eq!(first.trap_kind, Some("unreachable-code"));
        assert!(first.missing_backtrace);
        observer.capture(&Trap::IntegerDivisionByZero.into());
        let second = guard.snapshot().unwrap();
        assert_eq!(second.observed_errors, 2);
        assert!(second.ambiguous);
        assert_eq!(second.trap_kind, first.trap_kind);
        drop(guard);
        observer.capture(&Trap::StackOverflow.into());
        assert_eq!(observer.state.lock().unwrap().observation, second);
    }

    #[test]
    fn actual_backtrace_is_bounded_numeric_and_does_not_retain_runtime_owners() {
        use wasm_encoder::{
            CodeSection, ExportKind, ExportSection, Function, FunctionSection, Instruction,
            Module as Encoder, TypeSection,
        };
        let mut wasm = Encoder::new();
        let mut types = TypeSection::new();
        types.ty().function([], []);
        wasm.section(&types);
        let mut functions = FunctionSection::new();
        for _ in 0..20 {
            functions.function(0);
        }
        wasm.section(&functions);
        let mut exports = ExportSection::new();
        exports.export("run", ExportKind::Func, 19);
        wasm.section(&exports);
        let mut code = CodeSection::new();
        for index in 0..20 {
            let mut body = Function::new([]);
            if index == 0 {
                body.instruction(&Instruction::Unreachable);
            } else {
                body.instruction(&Instruction::Call(index - 1));
            }
            body.instruction(&Instruction::End);
            code.function(&body);
        }
        wasm.section(&code);
        let observer = DevelopmentTrapObserver::default();
        let guard = observer.arm().unwrap();
        {
            let mut config = wasmtime::Config::new();
            config
                .wasm_backtrace(true)
                .cranelift_opt_level(wasmtime::OptLevel::None);
            let engine = wasmtime::Engine::new(&config).unwrap();
            let module = Module::new(&engine, wasm.finish()).unwrap();
            let mut store = wasmtime::Store::new(&engine, ());
            let instance = wasmtime::Instance::new(&mut store, &module, &[]).unwrap();
            let function = instance
                .get_typed_func::<(), ()>(&mut store, "run")
                .unwrap();
            let error = function.call(&mut store, ()).unwrap_err();
            observer.capture(&error);
        } // Original error, Store, Module and Engine are all destroyed first.
        let value = guard.snapshot().unwrap();
        assert_eq!(value.observed_errors, 1);
        assert_eq!(value.trap_kind, Some("unreachable-code"));
        assert!(!value.missing_backtrace && !value.ambiguous && value.truncated);
        assert_eq!(value.total_frames, 20);
        assert_eq!(value.frames.iter().flatten().count(), MAX_FRAMES);
        for frame in value.frames.iter().flatten() {
            assert_eq!(frame.module, 0);
            assert!(frame.function < 20);
            assert!(frame.module_offset.is_some() && frame.function_offset.is_some());
        }
        assert!(serde_json::to_vec(&value).unwrap().len() <= 8192);
    }
}
