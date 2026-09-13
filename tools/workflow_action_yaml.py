"""Read executable action references from bounded YAML syntax trees."""
from __future__ import annotations

from dataclasses import dataclass

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

MAX_EVENTS = 16384
MAX_DEPTH = 64


@dataclass(frozen=True)
class Reference:
    value: str
    line: int
    comment: str | None


def references(text: str) -> list[Reference]:
    # Bound the parser before constructing a syntax tree. No Python objects are
    # constructed from YAML tags, and aliases share nodes rather than expanding.
    depth = 0
    for count, event in enumerate(yaml.parse(text, Loader=yaml.BaseLoader), 1):
        if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
            depth += 1
        elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
            depth -= 1
        if count > MAX_EVENTS or depth > MAX_DEPTH:
            raise ValueError("YAML exceeds syntax-node or nesting limit")
    document = yaml.compose(text, Loader=yaml.BaseLoader)
    if not isinstance(document, MappingNode):
        raise ValueError("workflow/action document must be a mapping")
    lines = text.splitlines()
    # Inspect every mapping once, rejecting duplicate/merge keys so authority
    # cannot depend on which YAML consumer picks a duplicate field.
    pending, seen = [document], set()
    while pending:
        node = pending.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, MappingNode):
            keys = set()
            for key, value in node.value:
                if not isinstance(key, ScalarNode) or key.value in keys or key.value == "<<":
                    raise ValueError("duplicate, merge, or nonscalar YAML mapping key")
                keys.add(key.value)
                pending.append(value)
        elif isinstance(node, SequenceNode):
            pending.extend(node.value)

    def mapping(node):
        if not isinstance(node, MappingNode):
            raise ValueError("executable job/step must be a YAML mapping")
        return {key.value: value for key, value in node.value}

    found = []

    def use(node):
        if not isinstance(node, ScalarNode) or node.start_mark.line != node.end_mark.line:
            raise ValueError("uses must be a single-line scalar action reference")
        # The parser resolves quoted keys, flow mappings and aliases. Only the
        # trailing source comment is lexical; run-script contents are never uses.
        suffix = lines[node.end_mark.line][node.end_mark.column:]
        comment = suffix.partition("#")[2].strip() or None
        found.append(Reference(node.value, node.start_mark.line + 1, comment))

    def steps(node):
        if not isinstance(node, SequenceNode):
            raise ValueError("executable steps must be a YAML sequence")
        for step in node.value:
            fields = mapping(step)
            if "uses" in fields:
                use(fields["uses"])

    fields = mapping(document)
    if "jobs" in fields:
        for job in mapping(fields["jobs"]).values():
            fields_job = mapping(job)
            if "uses" in fields_job:
                use(fields_job["uses"])
            if "steps" in fields_job:
                steps(fields_job["steps"])
    elif "runs" in fields:
        fields_run = mapping(fields["runs"])
        using = fields_run.get("using")
        if not isinstance(using, ScalarNode):
            raise ValueError("local action must declare runs.using")
        if using.value == "composite":
            if "steps" not in fields_run:
                raise ValueError("composite action must declare steps")
            steps(fields_run["steps"])
    else:
        raise ValueError("document must declare workflow jobs or action runs")
    return found
