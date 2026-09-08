#[path = "../client/mod.rs"]
mod client;

fn main() {
    if let Err(error) = client::run() {
        eprintln!("optimization-client: {error}");
        std::process::exit(1);
    }
}
