"""Captured standard clock/entropy lowering; no ambient WASI installation."""
from pathlib import Path
import re

from tools.c_guest.bindings import regular_tree
from tools.stage_runtime_wit import copy_wit_tree, dependencies

PROFILE = 'c-standard-clock-entropy-v1'
LOGGING_PROFILE = 'c-standard-stdio-v1'
COMBINED_PROFILE = 'c-standard-facilities-v1'
DEFAULT = 'closed-synchronous-v1'
IMPORTS = ('latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0', 'latent:random/random@0.1.0')
SUPPORTED = frozenset((DEFAULT, PROFILE, LOGGING_PROFILE, COMBINED_PROFILE))
PROFILE_IMPORTS = {PROFILE: IMPORTS, LOGGING_PROFILE: ('latent:log/log@0.1.0',),
                   COMBINED_PROFILE: (*IMPORTS, 'latent:log/log@0.1.0')}
PROFILE_SOURCES = {PROFILE: ('standard-clock-entropy.c',), LOGGING_PROFILE: ('standard-stdio.c',),
                   COMBINED_PROFILE: ('standard-clock-entropy.c', 'standard-stdio.c')}
RECIPE = ('tools/c_guest/standard_facilities.py',)


def selected_profile(project, graph=None):
    profile = project.get('runtimeProfile', DEFAULT)
    if type(profile) is not str or profile not in SUPPORTED:
        raise ValueError('unsupported-c-standard-runtime-profile')
    declared = graph.get('selection', {}).get('runtimeProfile') if graph is not None else None
    if declared is not None and declared != profile:
        raise ValueError('c-runtime-profile-dependency-selection-mismatch')
    return profile


def code_view(text: str) -> str:
    """Mask comments/literals at equal offsets; the WIT parser remains authoritative."""
    visible, position = list(text), 0
    while position < len(text):
        if text.startswith('//', position):
            end = text.find('\n', position + 2)
            if end == -1:
                end = len(text)
        elif text.startswith('/*', position):
            end, depth = position + 2, 1
            while end < len(text) and depth:
                if text.startswith('/*', end):
                    depth += 1
                    end += 2
                elif text.startswith('*/', end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            if depth:
                raise ValueError('c-runtime-profile-unterminated-wit-comment')
        elif text[position] == '"':
            end = position + 1
            while end < len(text):
                if text[end] == '\\':
                    end += 2
                elif text[end] == '"':
                    end += 1
                    break
                else:
                    end += 1
            else:
                raise ValueError('c-runtime-profile-unterminated-wit-string')
        else:
            position += 1
            continue
        for offset in range(position, end):
            if text[offset] not in '\r\n':
                visible[offset] = ' '
        position = end
    return ''.join(visible)


def stage(source: Path, world: str, destination: Path, platform: Path, *, profile=PROFILE) -> Path:
    selected_profile({'runtimeProfile': profile})
    if profile not in PROFILE_IMPORTS:
        raise ValueError('c-runtime-profile-has-no-derived-contracts')
    imports = PROFILE_IMPORTS[profile]
    source, destination, platform = source.resolve(), destination.resolve(), platform.resolve()
    if any(destination == root or destination in root.parents or root in destination.parents
           for root in (source, platform)):
        raise ValueError('c-runtime-profile-derived-wit-must-not-overlap-inputs')
    regular_tree(source, '.wit')
    leaf = world.rsplit('/', 1)[-1].split('@', 1)[0]
    if not re.fullmatch('[a-z][a-z0-9-]*', leaf):
        raise ValueError('c-runtime-profile-world-name-unsupported')
    pattern = re.compile(r'\bworld\s+' + re.escape(leaf) + r'\s*\{')
    texts = {path: path.read_text(encoding='utf-8') for path in sorted(source.glob('*.wit'))}
    visible = {path: code_view(text) for path, text in texts.items()}
    matches = [(path, match) for path, text in visible.items() for match in pattern.finditer(text)]
    if len(matches) != 1:
        raise ValueError('c-runtime-profile-requires-one-selected-world-declaration')
    path, match = matches[0]
    text = texts[path]
    if any(re.search(r'\bimport\s+' + re.escape(name) + r'\s*;', visible[path]) for name in imports):
        raise ValueError('c-runtime-profile-imports-must-be-owned-by-profile')
    if destination.exists():
        raise ValueError('c-runtime-profile-requires-fresh-derived-wit')
    copy_wit_tree(source, destination)
    additions = ''.join('\n    import ' + name + ';' for name in imports) + '\n'
    (destination / path.name).write_text(text[:match.end()] + additions + text[match.end():], encoding='utf-8')
    for package in dependencies(destination, platform):
        regular_tree(package, '.wit')
        copy_wit_tree(package, destination / 'deps' / package.name)
    return destination
