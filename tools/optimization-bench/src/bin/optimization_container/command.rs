use std::path::{Path, PathBuf};

use clap::{Parser, ValueEnum};

use super::Result;

pub(super) const LISTEN: &str = "0.0.0.0:7070";
pub(super) const CHILD_LISTEN: &str = "127.0.0.1:7071";

#[derive(Clone, Copy, ValueEnum)]
pub(super) enum App {
    Lsf,
    Native,
}

impl App {
    pub fn name(self) -> &'static str {
        match self {
            Self::Lsf => "lsf",
            Self::Native => "native",
        }
    }
}

/// Credentials are deliberately excluded from Debug/CLI error output.
#[derive(Parser)]
pub(super) struct Args {
    #[arg(long, value_enum)]
    pub app: App,
    #[arg(long)]
    pub executable: PathBuf,
    #[arg(long)]
    pub output: PathBuf,
    #[arg(long)]
    pub config: Option<PathBuf>,
    #[arg(long)]
    pub token_file: Option<PathBuf>,
    #[arg(long)]
    pub service: Option<String>,
}

fn absolute(path: &Path) -> bool {
    path.is_absolute()
        && path.as_os_str().len() <= 4096
        && !path
            .components()
            .any(|part| matches!(part, std::path::Component::ParentDir))
}

impl Args {
    pub fn validate(&self) -> Result<()> {
        if !absolute(&self.executable) || !absolute(&self.output) {
            return Err("invalid-wrapper-path");
        }
        let expected = match self.app {
            App::Lsf => "latentd",
            App::Native => "optimization-native",
        };
        if self.executable.file_name().and_then(|name| name.to_str()) != Some(expected) {
            return Err("invalid-wrapper-executable");
        }
        match self.app {
            App::Lsf
                if self.token_file.is_none()
                    && self.service.is_none()
                    && self.config.as_deref().is_some_and(absolute) =>
            {
                Ok(())
            }
            App::Native
                if self.config.is_none()
                    && self.token_file.as_deref().is_some_and(absolute)
                    && self.service.as_deref().is_some_and(valid_service) =>
            {
                Ok(())
            }
            _ => Err("invalid-wrapper-app-arguments"),
        }
    }
}

fn valid_service(value: &str) -> bool {
    value == "optimization/workloads"
        || value
            .strip_prefix("optimization/workloads-")
            .is_some_and(|suffix| {
                suffix
                    .parse::<u32>()
                    .is_ok_and(|index| (1..=31).contains(&index) && suffix == index.to_string())
            })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_names_are_closed_and_app_arguments_do_not_mix() {
        assert!(valid_service("optimization/workloads-31"));
        for name in [
            "optimization/workloads-0",
            "optimization/workloads-01",
            "optimization/workloads-32",
        ] {
            assert!(!valid_service(name));
        }
        let base = std::env::temp_dir();
        let mut args = Args {
            app: App::Native,
            executable: base.join("optimization-native"),
            output: base.join("out"),
            config: None,
            token_file: Some(base.join("token")),
            service: Some("optimization/workloads".into()),
        };
        assert!(args.validate().is_ok());
        args.config = Some(base.join("config"));
        assert!(args.validate().is_err());
    }
}
