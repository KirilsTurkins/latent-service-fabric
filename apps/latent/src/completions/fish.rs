//! Supply positional enum values omitted by the pinned Fish generator.
//! Command paths, option arity and choices all come from the built Clap tree.

use std::{collections::BTreeSet, io, io::Write};

use clap::Command;

pub(super) fn augment(command: &Command, mut bytes: Vec<u8>) -> io::Result<Vec<u8>> {
    bytes.extend_from_slice(include_str!("fish.fish").as_bytes());
    collect(command, command.get_name(), &[], &mut bytes)?;
    Ok(bytes)
}

fn quote(value: &str) -> String {
    format!("'{}'", value.replace('\\', "\\\\").replace('\'', "\\'"))
}

fn collect(command: &Command, root: &str, path: &[String], bytes: &mut Vec<u8>) -> io::Result<()> {
    let mut options = BTreeSet::new();
    for arg in command.get_arguments() {
        let suffix = if arg.get_action().takes_values() {
            if arg
                .get_num_args()
                .is_some_and(|range| range.min_values() == 0)
            {
                "=?"
            } else {
                "="
            }
        } else {
            ""
        };
        for long in arg.get_long_and_visible_aliases().into_iter().flatten() {
            options.insert(quote(&format!("{long}{suffix}")));
        }
        for short in arg.get_short_and_visible_aliases().into_iter().flatten() {
            options.insert(quote(&format!("{short}{suffix}")));
        }
    }
    for arg in command.get_positionals().filter(|arg| !arg.is_hide_set()) {
        let Some(index) = arg.get_index() else {
            continue;
        };
        let mut condition = format!(
            "__latent_complete_positional {} {}",
            path.len() + index - 1,
            path.len()
        );
        for value in path
            .iter()
            .map(|value| quote(value))
            .chain(options.iter().cloned())
        {
            condition.push(' ');
            condition.push_str(&value);
        }
        for value in arg
            .get_value_parser()
            .possible_values()
            .into_iter()
            .flatten()
        {
            if !value.is_hide_set() {
                // Fish parses -a's data once more when selecting candidates.
                // Quote both layers so spaces and substitutions remain data.
                writeln!(
                    bytes,
                    "complete -c {} -n {} -f -a {}",
                    quote(root),
                    quote(&condition),
                    quote(&quote(value.get_name()))
                )?;
            }
        }
    }
    for child in command
        .get_subcommands()
        .filter(|child| !child.is_hide_set())
    {
        for alias in child.get_name_and_visible_aliases() {
            let mut child_path = path.to_vec();
            child_path.push(alias.to_owned());
            collect(child, root, &child_path, bytes)?;
        }
    }
    Ok(())
}
