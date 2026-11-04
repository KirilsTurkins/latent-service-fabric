#!/usr/bin/env python3
"""Preview the existing CI selection offline; unresolved worktrees select full."""
from pathlib import Path
import argparse
import json
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--base', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--head')
    group.add_argument('--worktree', action='store_true')
    parser.add_argument('--output', choices=('human', 'json'), default='human')
    args = parser.parse_args(argv)
    root = Path.cwd()
    try:
        def resolve(ref):
            if not ref or ref.startswith('-'):
                raise ci_profile.ProfileError('invalid-revision')
            value = ci_profile.git_command(root, 'rev-parse', '--verify', ref + '^{commit}')
            return ci_profile.sha(value.decode('ascii').strip())
        base = resolve(args.base)
        head = resolve('HEAD' if args.worktree else args.head)
        dirty = ci_profile.git_command(root, 'status', '--porcelain', '-z', '--untracked-files=normal')
        if args.worktree and dirty:
            decision = ci_profile.Decision('full', 'uncommitted-worktree', 0)
        else:
            event = {'pull_request': {'base': {'sha': base}, 'head': {'sha': head}}}
            decision = ci_profile.classify_event('pull_request', event, root)
        outputs = decision.outputs()
        result = {'profile': decision.profile, 'reason': decision.reason,
                  'changed_files': decision.changed_files, 'renderer': decision.renderer,
                  'fast_packages': json.loads(outputs['fast_packages']),
                  'selected_jobs': json.loads(outputs['expected_jobs']),
                  'owner_groups': [decision.reason.split(':', 1)[1]]
                                  if decision.reason.startswith('isolated-tooling:') else []}
        if args.output == 'json': print(json.dumps(result, sort_keys=True))
        else:
            print('CI profile: {profile}; reason: {reason}; selected jobs: {selected_jobs}; owner groups: {owner_groups}'.format(**result))
        return 0
    except (ci_profile.ProfileError, OSError, UnicodeError, ValueError) as error:
        print('CI preview error: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
