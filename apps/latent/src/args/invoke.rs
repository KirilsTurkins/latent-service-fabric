use std::path::PathBuf;

use clap::Args;

#[derive(Args)]
pub struct InvokeArgs {
    #[arg(long)]
    pub service: String,
    #[arg(long)]
    pub contract: String,
    #[arg(long)]
    pub function: String,
    /// Payload file, or '-' for standard input.
    #[arg(long)]
    pub input: PathBuf,
    #[arg(long)]
    pub route: Option<String>,
    #[arg(long)]
    pub activation_id: Option<String>,
    #[arg(long)]
    pub root_activation_id: Option<String>,
    #[arg(long)]
    pub parent_activation_id: Option<String>,
    #[arg(long, default_value = "application/vnd.latent.wit-values.v1+json")]
    pub media_type: String,
    #[arg(long)]
    pub deadline_unix_millis: Option<u64>,
    #[arg(long, default_value_t = 0)]
    pub priority: u8,
    #[arg(long)]
    pub idempotency_key: Option<String>,
    #[arg(long, value_name = "KEY=VALUE")]
    pub metadata: Vec<String>,
    #[arg(long, value_name = "FILE")]
    pub budget: Option<PathBuf>,
    #[arg(long)]
    pub cpu_fuel: Option<u64>,
    #[arg(long)]
    pub memory_bytes: Option<u64>,
    #[arg(long)]
    pub wall_time_ms: Option<u64>,
    #[arg(long)]
    pub log_bytes: Option<u64>,
    /// Create a new file containing the returned payload's raw bytes.
    #[arg(long, value_name = "FILE")]
    pub payload_output: Option<PathBuf>,
}
