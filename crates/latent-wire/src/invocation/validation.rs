use std::time::Duration;

use latent_activation::{ActivationOutcome, ActivationStatus, RetainedActivationOutcome};
use latent_core::{ActivationId, InvocationPrincipal};
use prost::Message;
use tonic::{Request, Status};

use super::{
    invocation_request_from_proto, proto, InvocationLimits, InvocationResponse, PrincipalPolicy,
};

include!("validation_parts/validation_01.rs");
include!("validation_parts/validation_02.rs");
