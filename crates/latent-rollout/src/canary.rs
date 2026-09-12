mod evaluate;
mod model;
mod promote;
mod windows;
pub(crate) use evaluate::run as evaluate;
pub use model::*;
pub(crate) use promote::{run as promote, PromotionInput};
pub(crate) use windows::ObservationWindows;

use crate::{invalid, Result};
use latent_control_store::rollouts::{RolloutCommand, RolloutRequest};

pub(crate) fn is_promotion(request: &RolloutRequest) -> bool {
    matches!(
        request,
        RolloutRequest::Change {
            command: RolloutCommand::Promote { .. },
            ..
        }
    )
}
pub(crate) fn require_promotion(request: &RolloutRequest) -> Result<()> {
    if is_promotion(request) {
        Ok(())
    } else {
        Err(invalid("rollout-promotion-command-required"))
    }
}
