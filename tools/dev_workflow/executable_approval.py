"""Select a reviewed executable closure for a maintained guest compiler."""
import argparse

from .common import DevError, require, sha
from .project import LANGUAGES, guest_recipe_arguments


def maintained(descriptor: dict) -> bool:
    language = descriptor['language']
    recipe = descriptor['build']
    tools = {row['name']: row for row in recipe['tools']}
    return (language in {'rust', 'java', 'dotnet'}
            and recipe.get('adapter') == {'language': language, 'ownerIssue': LANGUAGES[language], 'version': '1'}
            and recipe['argv'] == guest_recipe_arguments(language) and recipe['workingDirectory'] == 'app'
            and recipe['outputRoot'] == 'output' and recipe['hostTargets'] == ['linux-x86_64']
            and recipe.get('inventory', {}).get('path') == 'guest-tools.json'
            and tools.get('python', {}).get('path') == 'sdk/bin/python'
            and tools.get('python', {}).get('version') == '3.13.5'
            and tools.get('recipe', {}).get('path') == 'recipe/tools/dev_guest_recipe.py'
            and tools.get('recipe', {}).get('version') == '1')


def selection(descriptor: dict, value: str | None) -> str | None:
    if value is not None:
        sha(value)
        require(maintained(descriptor), 'executable-approval-requires-maintained-compiler-adapter')
    return value


def watch_arguments(descriptor: dict, action: str, value: str | None) -> list[str]:
    if value is None:
        return []
    require(action == 'watch', 'executable-approval-requires-watch')
    selection(descriptor, value)
    return ['--executable-approval', value]


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
                        help='exact retained request digest for Rust build tools, Java processors or .NET generators')
