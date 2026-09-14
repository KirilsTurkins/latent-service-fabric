use super::*;
use hickory_proto::rr::{
    rdata::{A, CNAME},
    Record,
};
fn fixture() -> (Message, Name, HttpDestination) {
    let name = Name::from_ascii("localhost.").unwrap();
    let mut message = Message::new(41, MessageType::Response, OpCode::Query);
    message.add_query(Query::query(name.clone(), RecordType::A));
    let destination = crate::tests::config(12345).destinations.remove(0);
    (message, name, destination)
}
#[test]
fn transaction_question_lengths_and_compression_cycles_fail_closed() {
    let (mut message, name, destination) = fixture();
    message.add_answer(Record::from_rdata(
        name.clone(),
        30,
        RData::A(A("127.0.0.1".parse().unwrap())),
    ));
    assert!(decode::response(
        &message.to_vec().unwrap(),
        40,
        &name,
        RecordType::A,
        &destination
    )
    .is_err());
    assert!(decode::response(
        &message.to_vec().unwrap(),
        41,
        &name,
        RecordType::AAAA,
        &destination
    )
    .is_err());
    let mut bytes = message.to_vec().unwrap();
    bytes[6..8].copy_from_slice(&u16::MAX.to_be_bytes());
    assert!(decode::preflight(&bytes).is_err());
    let mut bytes = vec![0; 18];
    bytes[0..2].copy_from_slice(&41u16.to_be_bytes());
    bytes[2] = 0x80;
    bytes[5] = 1;
    bytes[12] = 0xc0;
    bytes[13] = 12;
    bytes[15] = 1;
    bytes[17] = 1;
    assert!(decode::response(&bytes, 41, &name, RecordType::A, &destination).is_err());
    assert!(decode::preflight(&[0; 4097]).is_err());
}
#[test]
fn aliases_are_finite_and_all_returned_addresses_are_checked() {
    let (mut message, name, destination) = fixture();
    message.add_answer(Record::from_rdata(
        name.clone(),
        20,
        RData::CNAME(CNAME(name.clone())),
    ));
    assert!(decode::response(
        &message.to_vec().unwrap(),
        41,
        &name,
        RecordType::A,
        &destination
    )
    .is_err());
    message.answers.clear();
    message.add_answer(Record::from_rdata(
        name.clone(),
        20,
        RData::A(A("127.0.0.1".parse().unwrap())),
    ));
    message.add_answer(Record::from_rdata(
        Name::from_ascii("unrelated.invalid.").unwrap(),
        20,
        RData::A(A("169.254.169.254".parse().unwrap())),
    ));
    assert!(matches!(
        decode::response(
            &message.to_vec().unwrap(),
            41,
            &name,
            RecordType::A,
            &destination
        ),
        Err(HttpError::PermissionDenied)
    ));
    message.answers.clear();
    let mut previous = name.clone();
    for n in 0..6 {
        let next = Name::from_ascii(format!("alias{n}.invalid.")).unwrap();
        message.add_answer(Record::from_rdata(
            previous,
            10,
            RData::CNAME(CNAME(next.clone())),
        ));
        previous = next;
    }
    assert!(decode::response(
        &message.to_vec().unwrap(),
        41,
        &name,
        RecordType::A,
        &destination
    )
    .is_err());
}
