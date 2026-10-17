"""Explicit detached selection for the maintained Rust executable-input consumer."""
import argparse

from .common import DevError, require, sha


ARGV = ['python', '-I', '-B', '@tool:recipe', '--language', 'rust', '--project', '.', '--output', '../output']


def maintained(descriptor: dict) -> bool:
    recipe = descriptor['build']
    tools = {row['name']: row for row in recipe['tools']}
    return (descriptor['language'] == 'rust'
            and recipe.get('adapter') == {'language': 'rust', 'ownerIssue': 544, 'version': '1'}
            and recipe['argv'] == ARGV and recipe['workingDirectory'] == 'app'
            and recipe['outputRoot'] == 'output' and recipe['hostTargets'] == ['linux-x86_64']
            and recipe.get('inventory', {}).get('path') == 'guest-tools.json'
            and tools.get('python', {}).get('path') == 'sdk/bin/python'
            and tools.get('python', {}).get('version') == '3.13.5'
            and tools.get('recipe', {}).get('path') == 'recipe/tools/dev_guest_recipe.py'
            and tools.get('recipe', {}).get('version') == '1')


def selection(descriptor: dict, value: str | None) -> str | None:
    if value is not None:
        sha(value)
        require(maintained(descriptor), 'executable-approval-requires-maintained-rust-adapter')
    return value


class Once(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            parser.error('executable approval must be selected once')
        try:
            sha(values)
        except DevError:
            parser.error('executable approval requires sha256:<64 lowercase hex>')
        setattr(namespace, self.dest, values)


def option(parser) -> None:
    parser.add_argument('--executable-approval', action=Once,
                        help='explicit exact retained Rust build-script/proc-macro request digest')
