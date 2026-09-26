use super::*;
#[test]
fn receipts_require_exact_stream_positive_sequence_and_unambiguous_shapes() {
    assert_eq!(
        ack(br#"{"stream":"ORDERS","seq":7,"duplicate":true}"#, "ORDERS"),
        Ok((7, true))
    );
    for bytes in [
        br#"{"stream":"OTHER","seq":7}"#.as_slice(),
        br#"{"stream":"ORDERS","seq":0}"#,
        br#"{"stream":"ORDERS","stream":"ORDERS","seq":7}"#,
        b"{",
    ] {
        assert_eq!(ack(bytes, "ORDERS"), Err(EventError::Uncertain));
    }
    assert_eq!(
        ack(br#"{"error":{"code":500,"err_code":10077}}"#, "ORDERS"),
        Err(EventError::Uncertain)
    );
    assert_eq!(
        ack(br#"{"error":{"code":400,"err_code":10060}}"#, "ORDERS"),
        Err(EventError::InvalidEvent)
    );
}
#[test]
fn frames_reject_foreign_inboxes_unbounded_lengths_and_protocol_extensions() {
    assert_eq!(frame(b"MSG inbox 1 42", "inbox"), Ok((0, 42)));
    assert_eq!(frame(b"HMSG inbox 1 16 32", "inbox"), Ok((16, 32)));
    for bytes in [
        b"MSG other 1 4".as_slice(),
        b"MSG inbox 2 4",
        b"MSG inbox 1 4097",
        b"MSG inbox 1 +4",
        b"MSG inbox 1 4 extra",
        b"HMSG inbox 1 9 4",
    ] {
        assert!(frame(bytes, "inbox").is_err());
    }
    assert!(info(br#"INFO {"headers":true,"max_payload":1000,"tls_required":false}"#).is_err());
    assert!(guard(b"[[[[[[[[[0]]]]]]]]]").is_err());
}
