#[path = "optimization_native/mod.rs"]
mod native;

fn main() -> std::process::ExitCode {
    native::main()
}
