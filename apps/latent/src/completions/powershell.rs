//! Fill the pinned `PowerShell` generator's value/path and option-scanning gaps.
//! The upstream generator still emits every command/flag completion. This
//! adapter derives only parsing/value metadata from the same built Clap tree.

use std::{collections::BTreeMap, io};

use clap::{Arg, Command, ValueHint};
use serde::Serialize;

#[derive(Clone, Serialize)]
struct Value {
    takes_value: bool,
    values: Vec<String>,
    path: &'static str,
}

#[derive(Serialize)]
struct Node {
    options: BTreeMap<String, Value>,
    positionals: Vec<Value>,
    children: BTreeMap<String, String>,
}

pub(super) fn augment(command: &Command, bytes: Vec<u8>) -> io::Result<Vec<u8>> {
    let script = String::from_utf8(bytes).map_err(io::Error::other)?;
    // These are generator scaffolding, not product command names. Fail closed
    // if an upstream update changes it, rather than silently dropping support.
    let start = "    $commandElements = $commandAst.CommandElements\n";
    let end = "    $completions = @(switch ($command) {";
    let before = script.find(start).ok_or_else(incompatible_generator)?;
    let after = script.find(end).ok_or_else(incompatible_generator)?;
    if after <= before {
        return Err(incompatible_generator());
    }
    let mut nodes = BTreeMap::new();
    collect(command, command.get_name(), &mut nodes);
    let metadata = serde_json::to_string(&nodes).map_err(io::Error::other)?;
    // A quoted literal is data, never an evaluated PowerShell expression.
    let metadata = quote(&metadata);
    let root = quote(command.get_name());
    let scanner = include_str!("powershell.ps1")
        .replace("@@ROOT@@", &root)
        .replace("@@GRAMMAR@@", &metadata);
    Ok(format!("{}{scanner}{}", &script[..before], &script[after..]).into_bytes())
}

fn incompatible_generator() -> io::Error {
    io::Error::other("the pinned PowerShell completion scaffolding changed")
}

fn quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''").replace('’', "'’"))
}

fn value(arg: &Arg) -> Value {
    Value {
        takes_value: arg.get_action().takes_values(),
        values: arg
            .get_value_parser()
            .possible_values()
            .into_iter()
            .flatten()
            .filter(|value| !value.is_hide_set())
            .map(|value| value.get_name().to_owned())
            .collect(),
        path: match arg.get_value_hint() {
            ValueHint::DirPath => "directory",
            ValueHint::FilePath | ValueHint::AnyPath => "file",
            _ => "",
        },
    }
}

fn collect(command: &Command, path: &str, nodes: &mut BTreeMap<String, Node>) {
    let mut options = BTreeMap::new();
    for arg in command.get_arguments().filter(|arg| !arg.is_hide_set()) {
        for long in arg.get_long_and_visible_aliases().into_iter().flatten() {
            options.insert(format!("--{long}"), value(arg));
        }
        for short in arg.get_short_and_visible_aliases().into_iter().flatten() {
            options.insert(format!("-{short}"), value(arg));
        }
    }
    let mut positionals: Vec<_> = command.get_positionals().collect();
    positionals.sort_by_key(|arg| arg.get_index());
    let mut children = BTreeMap::new();
    for child in command
        .get_subcommands()
        .filter(|child| !child.is_hide_set())
    {
        let child_path = format!("{path};{}", child.get_name());
        for alias in child.get_name_and_visible_aliases() {
            children.insert(alias.to_owned(), child_path.clone());
        }
        collect(child, &child_path, nodes);
    }
    nodes.insert(
        path.to_owned(),
        Node {
            options,
            positionals: positionals.into_iter().map(value).collect(),
            children,
        },
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::CommandFactory;

    #[test]
    fn metadata_tracks_nested_values_paths_and_inherited_options() {
        let mut command = crate::args::Cli::command();
        command.build();
        let mut nodes = BTreeMap::new();
        collect(&command, command.get_name(), &mut nodes);
        let build = &nodes["latent;package;build"];
        assert_eq!(build.options["--source"].path, "file");
        assert_eq!(build.options["--input-root"].path, "directory");
        assert_eq!(build.options["--config"].path, "file");
        assert_eq!(build.options["--output"].values, ["human", "json"]);
        assert_eq!(
            nodes["latent;package;inspect"].positionals[0].path,
            "directory"
        );
        assert_eq!(
            nodes["latent;policy;get"].options["--kind"].values,
            ["policy", "provider-binding"]
        );
    }

    #[test]
    fn changed_upstream_scaffolding_is_an_error_not_an_incomplete_script() {
        let command = crate::args::Cli::command();
        assert!(augment(&command, b"unexpected upstream source".to_vec()).is_err());
    }

    #[test]
    fn shell_literals_escape_apostrophes_without_evaluation() {
        assert_eq!(quote("can't $(invoke)"), "'can''t $(invoke)'");
    }
}
