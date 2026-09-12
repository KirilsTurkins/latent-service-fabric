use clap::{Args, Subcommand};
use std::path::{Path, PathBuf};

#[derive(Subcommand)]
pub enum PackageCommand {
    /// Package explicitly supplied bytes; does not compile source or create provenance.
    Build(PackageBuildArgs),
    /// Inspect exact package identities and semantics without granting trust.
    Inspect(PackageDirectoryArgs),
    /// Check publisher, provenance, SBOM and tenant under an explicit local policy.
    Verify(PackageVerifyArgs),
    /// Push exact package and selected detached evidence; never retries automatically.
    Push(PackagePushArgs),
    /// Resolve a reference once and export its exact package and detached evidence.
    Pull(PackagePullArgs),
}

#[derive(Args)]
pub struct PackageBuildArgs {
    #[arg(long)]
    pub source: PathBuf,
    #[arg(long)]
    pub input_root: PathBuf,
    #[arg(long = "output-dir")]
    pub output_dir: PathBuf,
    #[arg(long)]
    pub sbom_inputs: Option<PathBuf>,
}

#[derive(Args)]
pub struct PackageDirectoryArgs {
    pub directory: PathBuf,
}

#[derive(Args)]
pub struct PackageVerifyArgs {
    pub directory: PathBuf,
    #[arg(long)]
    pub evidence_index: PathBuf,
    #[arg(long)]
    pub evidence_root: PathBuf,
    #[arg(long)]
    pub policy: PathBuf,
}

#[derive(Args)]
pub struct PackagePushArgs {
    pub directory: PathBuf,
    /// Explicit closed registry configuration file, separate from node credentials.
    #[arg(long, value_name = "FILE")]
    pub registry_profile: PathBuf,
    #[arg(long)]
    pub reference: String,
    #[arg(long, requires = "evidence_root")]
    pub evidence_index: Option<PathBuf>,
    #[arg(long, requires = "evidence_index")]
    pub evidence_root: Option<PathBuf>,
}

#[derive(Args)]
pub struct PackagePullArgs {
    #[arg(long, value_name = "FILE")]
    pub registry_profile: PathBuf,
    #[arg(long)]
    pub reference: String,
    #[arg(long = "output-dir")]
    pub output_dir: PathBuf,
    /// Separate new directory for detached evidence and its index.json.
    #[arg(long)]
    pub evidence_output: PathBuf,
}

impl PackageCommand {
    pub fn name(&self) -> &'static str {
        match self {
            Self::Build(_) => "package build",
            Self::Inspect(_) => "package inspect",
            Self::Verify(_) => "package verify",
            Self::Push(_) => "package push",
            Self::Pull(_) => "package pull",
        }
    }
    pub fn validate(&self, tenant: Option<&str>) -> Result<(), crate::error::Failure> {
        use super::validation::{identifier, path_argument};
        let path = |p: &Path| path_argument(p);
        match self {
            Self::Build(a) => {
                for p in [&a.source, &a.input_root, &a.output_dir] {
                    path(p)?;
                }
                if let Some(p) = &a.sbom_inputs {
                    path(p)?;
                    crate::input::single_stdin(&[&a.source, p])?;
                }
            }
            Self::Inspect(a) => path(&a.directory)?,
            Self::Verify(a) => {
                identifier(
                    tenant.ok_or_else(|| {
                        crate::error::Failure::local(
                            "tenant-required",
                            "Package verification requires --tenant.",
                        )
                    })?,
                    128,
                )?;
                for p in [&a.directory, &a.evidence_index, &a.evidence_root, &a.policy] {
                    path(p)?;
                }
                crate::input::single_stdin(&[&a.evidence_index, &a.policy])?;
            }
            Self::Push(a) => {
                for p in [&a.directory, &a.registry_profile] {
                    path(p)?;
                }
                for p in [&a.evidence_index, &a.evidence_root].into_iter().flatten() {
                    path(p)?;
                }
                identifier(&a.reference, 256)?;
            }
            Self::Pull(a) => {
                for p in [&a.registry_profile, &a.output_dir, &a.evidence_output] {
                    path(p)?;
                }
                identifier(&a.reference, 256)?;
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::PackageCommand;
    use crate::args::{Cli, Command, OutputFormat};
    use clap::Parser;

    #[test]
    fn package_output_directory_and_global_output_format_have_distinct_ids() {
        for arguments in [
            vec![
                "latent",
                "--output",
                "json",
                "package",
                "build",
                "--source",
                "source.json",
                "--input-root",
                "inputs",
                "--output-dir",
                "package",
            ],
            vec![
                "latent",
                "--output",
                "json",
                "package",
                "pull",
                "--registry-profile",
                "registry.json",
                "--reference",
                "candidate",
                "--output-dir",
                "package",
                "--evidence-output",
                "evidence",
            ],
        ] {
            let cli = Cli::try_parse_from(arguments).unwrap();
            assert_eq!(cli.output, OutputFormat::Json);
            cli.validate().unwrap();
            match cli.command {
                Command::Package(PackageCommand::Build(args)) => {
                    assert_eq!(args.output_dir.to_str(), Some("package"));
                }
                Command::Package(PackageCommand::Pull(args)) => {
                    assert_eq!(args.output_dir.to_str(), Some("package"));
                }
                _ => panic!("unexpected command"),
            }
        }
    }
}
