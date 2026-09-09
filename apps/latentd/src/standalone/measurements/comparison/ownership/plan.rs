use serde::{Deserialize, Serialize};
use std::time::Duration;

use super::Result;

pub(super) const SHAPES: [&str; 6] = [
    "warm-echo",
    "payload-64k",
    "payload-near-limit",
    "context-small",
    "context-64k",
    "context-near-limit",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub(super) enum Mode {
    Fixtures,
    Normal,
    Allocation,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    pub schema: String,
    pub profile: String,
    pub mode: Mode,
    pub repetition: u32,
    pub shapes: Vec<String>,
    pub warmup_per_shape: u32,
    pub measured_per_shape: u32,
    pub proofs: Vec<String>,
    pub maximum_run_seconds: String,
    pub maximum_output_bytes: String,
}

impl Plan {
    pub fn validate(&self) -> Result<()> {
        let full = match self.profile.as_str() {
            "full" => true,
            "smoke" => false,
            _ => return Err("ownership profile".into()),
        };
        let (warmup, measured, seconds) = match self.mode {
            Mode::Normal => (if full { 4 } else { 1 }, if full { 32 } else { 3 }, "90"),
            Mode::Allocation => (1, if full { 8 } else { 2 }, "180"),
            Mode::Fixtures => (0, 0, "90"),
        };
        let shape_ok = match self.mode {
            Mode::Normal => self.shapes.iter().map(String::as_str).eq(SHAPES),
            Mode::Allocation => self.shapes.len() == 1 && SHAPES.contains(&self.shapes[0].as_str()),
            Mode::Fixtures => self.shapes.is_empty(),
        };
        let proof_ok = if self.mode == Mode::Normal {
            self.proofs
                .iter()
                .map(String::as_str)
                .eq(["cancel-pending", "drop-pending"])
        } else {
            self.proofs.is_empty()
        };
        if self.schema != "latent.optimization.ownership-plan.v1"
            || !shape_ok
            || !proof_ok
            || self.warmup_per_shape != warmup
            || self.measured_per_shape != measured
            || self.maximum_run_seconds != seconds
            || self.maximum_output_bytes != "8388608"
            || !(1..=if full && self.mode == Mode::Normal {
                7
            } else {
                1
            })
                .contains(&self.repetition)
        {
            return Err("ownership fixed plan".into());
        }
        Ok(())
    }
    pub fn duration(&self) -> Duration {
        if self.mode == Mode::Allocation {
            Duration::from_mins(3)
        } else {
            Duration::from_secs(90)
        }
    }
    pub fn count(&self) -> u32 {
        self.warmup_per_shape + self.measured_per_shape
    }
}

pub(super) fn component(shape: &str) -> &'static str {
    if shape.starts_with("context-") {
        "capabilities"
    } else {
        "optimization"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn profile_mode_cannot_expand_or_disguise_attempt_population() {
        let mut p = Plan {
            schema: "latent.optimization.ownership-plan.v1".into(),
            profile: "smoke".into(),
            mode: Mode::Normal,
            repetition: 1,
            shapes: SHAPES.map(str::to_owned).to_vec(),
            warmup_per_shape: 1,
            measured_per_shape: 3,
            proofs: vec!["cancel-pending".into(), "drop-pending".into()],
            maximum_run_seconds: "90".into(),
            maximum_output_bytes: "8388608".into(),
        };
        p.validate().unwrap();
        p.shapes.swap(0, 1);
        assert!(p.validate().is_err());
        p.shapes.swap(0, 1);
        p.mode = Mode::Allocation;
        assert!(p.validate().is_err());
        p.shapes.truncate(1);
        p.proofs.clear();
        p.measured_per_shape = 2;
        p.maximum_run_seconds = "180".into();
        p.validate().unwrap();
        p.repetition = 2;
        assert!(p.validate().is_err());
    }
}
