#[path = "../examples/echo_capsule/logic.rs"]
mod logic;

use logic::{MessageRejection, MAX_LOG_ACTIVATION_ID_BYTES, MAX_MESSAGE_BYTES};

#[test]
fn echoes_normal_input_without_modification() {
    let message = "hello from the capsule".to_owned();
    assert_eq!(logic::echo(message.clone()), Ok(message));
}

#[test]
fn rejects_an_empty_message() {
    assert_eq!(logic::echo(String::new()), Err(MessageRejection::Empty));
}

#[test]
fn accepts_the_documented_byte_limit() {
    let message = "x".repeat(MAX_MESSAGE_BYTES);
    assert_eq!(logic::echo(message.clone()), Ok(message));
}

#[test]
fn rejects_a_message_over_the_documented_byte_limit() {
    let message = "x".repeat(MAX_MESSAGE_BYTES + 1);
    assert_eq!(logic::echo(message), Err(MessageRejection::OverLimit));
}

#[test]
fn applies_the_limit_to_utf8_bytes() {
    let message = "é".repeat((MAX_MESSAGE_BYTES / 2) + 1);
    assert_eq!(logic::echo(message), Err(MessageRejection::OverLimit));
}

#[test]
fn bounds_activation_ids_without_splitting_utf8() {
    let prefix = "é".repeat(MAX_LOG_ACTIVATION_ID_BYTES);
    let activation_id = format!("{prefix}suffix");
    let bounded = logic::bounded_utf8_prefix(&activation_id, MAX_LOG_ACTIVATION_ID_BYTES);
    assert!(bounded.len() <= MAX_LOG_ACTIVATION_ID_BYTES);
    assert!(activation_id.starts_with(bounded));
    assert_eq!(bounded, "é".repeat(MAX_LOG_ACTIVATION_ID_BYTES / 2));
}
