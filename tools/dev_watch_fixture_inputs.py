"""Scaffold the shared reviewed stimuli for the real-node source watch driver."""
from pathlib import Path

from tools.dev_watch_case_inputs import edit, populate
from tools.dev_workflow import paths, project
from tools.dev_workflow.common import decode


def author(payload: Path, destination: Path) -> dict:
    entry = decode(paths.read(payload, "templates.json"))["templates"]["greeting"]
    template = payload / entry["path"]
    manifest = decode(paths.read(template, "template.json"))
    project.scaffold(template, destination, manifest, entry["identity"])
    return populate(destination, manifest["project"])
