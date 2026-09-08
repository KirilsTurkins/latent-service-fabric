use super::args::{Cli, Command, Operation};
use super::io::immediate;
use super::operation::validate_iterations;
use clap::Parser;

#[test]
fn repository_measurements_cannot_hide_repeated_warm_reopens() {
    for operation in [Operation::ArtifactOpen, Operation::CatalogOpen] {
        assert!(validate_iterations(operation, 1).is_ok());
        assert!(validate_iterations(operation, 2).is_err());
    }
    assert!(validate_iterations(Operation::Hash, 4096).is_ok());
    assert!(validate_iterations(Operation::Hash, 4097).is_err());
    assert!(validate_iterations(Operation::Hash, 0).is_err());
}

#[test]
fn immediate_directory_port_rejects_unexpected_suspension() {
    assert_eq!(immediate(std::future::ready(7)), Ok(7));
    assert_eq!(
        immediate(std::future::pending::<()>()),
        Err("unexpected-directory-suspension")
    );
}

#[test]
fn command_rejects_unknown_or_unbounded_measurement_options() {
    let valid = [
        "probe",
        "measure",
        "--operation",
        "hash",
        "--fixture",
        "fixture",
        "--iterations",
        "3",
    ];
    let parsed = Cli::try_parse_from(valid).unwrap();
    assert!(matches!(parsed.command, Command::Measure(args) if args.iterations == 3));
    for invalid in ["0", "4097", "18446744073709551615"] {
        let mut values = valid;
        values[7] = invalid;
        assert!(Cli::try_parse_from(values).is_err());
    }
}
