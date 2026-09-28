"""Docker ownership checks for the disposable, finite Harbor service graph."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from .config import IMAGES, LABEL


def command(arguments: list[str], timeout: float = 60) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    if len(result.stdout) > 1024 * 1024 or len(result.stderr) > 1024 * 1024:
        raise RuntimeError('Harbor tool diagnostic bound exceeded')
    if result.returncode:
        # Container preparation can read private configuration. Classify known
        # failure markers without printing raw output, credentials or arguments.
        observed = (result.stdout + result.stderr).lower()
        reasons = [name for name, marker in {
            'permission': 'permission denied', 'operation-permission': 'operation not permitted',
            'missing-file': 'filenotfounderror', 'missing-directory': 'no such file or directory',
            'readonly-filesystem': 'read-only file system', 'attribute': 'attributeerror',
            'image-rate-limit': 'toomanyrequests', 'image-authority': 'unauthorized',
            'unknown-image': 'manifest unknown', 'disk-capacity': 'no space left',
            'unhealthy': 'unhealthy', 'dependency': 'dependency failed', 'certificate': 'certificate',
            'port-conflict': 'address already in use', 'timeout': 'timed out',
        }.items() if marker in observed]
        stage = arguments[1] if len(arguments) > 1 and arguments[1] in {'run', 'pull', 'compose', 'volume', 'network', 'container'} else 'tool'
        raise RuntimeError(f'{Path(arguments[0]).name} {stage} failed ({result.returncode}); markers: {",".join(reasons) or "unclassified"}')
    return result.stdout.strip()


def image_available(image: str) -> None:
    result = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        command(['docker', 'pull', '--quiet', image], timeout=300)


class Owner:
    def __init__(self, root: Path, token: str):
        if not re.fullmatch(r'[0-9a-f]{32}', token):
            raise RuntimeError('invalid Harbor ownership token')
        self.root = root.resolve()
        self.token = token
        self.project = 'lsf-harbor-' + token
        self.label = LABEL + '=' + token

    def prepare(self) -> None:
        image_available(IMAGES['prepare'])
        mounts = [(self.root / 'input', '/input'), (self.root / 'data', '/data'),
                  (self.root, '/compose_location'), (self.root / 'common/config', '/config'),
                  (self.root, '/hostfs/fixture-root')]
        arguments = ['docker', 'run', '--rm', '--network', 'none', '--label', self.label,
                     '--memory', '512m', '--memory-swap', '512m', '--cpus', '1', '--pids-limit', '128',
                     '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL']
        for capability in ['CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'SETUID', 'SETGID']:
            arguments += ['--cap-add', capability]
        for source, target in mounts:
            arguments += ['--mount', f'type=bind,source={source},target={target}']
        command([*arguments, IMAGES['prepare'], 'prepare'], timeout=120)

    def launch(self) -> None:
        self.environment_ownership()
        for name, image in IMAGES.items():
            if name != 'prepare':
                image_available(image)
        command(['docker', 'compose', '--project-name', self.project, '--file', str(self.root / 'compose.json'),
                 'up', '--detach', '--no-build', '--pull', 'never'], timeout=180)

    def environment_ownership(self) -> None:
        # Upstream prepare creates root-owned 0600 env files. Compose reads
        # those on the host before creating a container; retain 0600 while
        # handing only the approved env files to this fixture's invoking user.
        import os
        if os.name == 'nt':
            return
        compose = json.loads((self.root / 'compose.json').read_bytes())
        selected = sorted({str(Path(name).relative_to(self.root))
                           for service in compose['services'].values()
                           for name in service.get('env_file', [])})
        if len(selected) > 8 or any(not re.fullmatch(r'common/config/[a-z]+/env', name) for name in selected):
            raise RuntimeError('Harbor environment file ownership bound')
        program = (
            'import os,stat\n'
            f'for name in {selected!r}:\n'
            ' path="/owned/"+name\n'
            ' info=os.lstat(path)\n'
            ' if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>65536: raise RuntimeError("environment file bound")\n'
            f' os.chown(path,{os.getuid()},{os.getgid()},follow_symlinks=False)\n'
            ' os.chmod(path,0o600,follow_symlinks=False)\n'
        )
        command(['docker', 'run', '--rm', '--network', 'none', '--label', self.label,
                 '--memory', '128m', '--pids-limit', '32', '--cap-drop', 'ALL',
                 '--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'FOWNER',
                 '--security-opt', 'no-new-privileges:true',
                 '--mount', f'type=bind,source={self.root},target=/owned',
                 '--entrypoint', 'python3', IMAGES['prepare'], '-c', program], timeout=30)

    def close(self) -> None:
        for kind, listing in [
            ('container', ['docker', 'ps', '--all', '--quiet', '--no-trunc', '--filter', 'label=' + self.label]),
            ('volume', ['docker', 'volume', 'ls', '--quiet', '--filter', 'label=' + self.label]),
            ('network', ['docker', 'network', 'ls', '--quiet', '--no-trunc', '--filter', 'label=' + self.label]),
        ]:
            identifiers = command(listing, timeout=15).splitlines()
            if len(identifiers) > 16:
                raise RuntimeError('Harbor owned resource count exceeded')
            for identifier in identifiers:
                labels = '.Config.Labels' if kind == 'container' else '.Labels'
                identity = '.Name' if kind == 'volume' else '.Id'
                template = '{"id":{{json ' + identity + '}},"labels":{{json ' + labels + '}}}'
                value = json.loads(command(['docker', kind, 'inspect', '--format', template, identifier], timeout=15))
                if not isinstance(value, dict) or not isinstance(value.get('labels'), dict) or value['labels'].get(LABEL) != self.token:
                    raise RuntimeError('refusing to remove unowned Harbor resource')
                selected = value.get('id', '')
                if kind == 'volume':
                    valid = selected.startswith(self.project + '_') and re.fullmatch(r'[a-z0-9_-]+', selected)
                else:
                    valid = re.fullmatch(r'[0-9a-f]{64}', selected)
                if not valid:
                    raise RuntimeError('invalid Harbor resource identity')
                remove = ['docker', kind, 'rm'] + (['--force'] if kind == 'container' else [])
                command([*remove, selected], timeout=20)

    def release_files(self) -> None:
        import os
        if os.name == 'nt':
            return
        program = (
            'import os\n'
            'count=0\n'
            'for directory, folders, files in os.walk("/owned", followlinks=False):\n'
            ' for path in [directory]+[os.path.join(directory,name) for name in files]:\n'
            '  count+=1\n'
            '  if count>8192: raise RuntimeError("fixture file bound")\n'
            f'  os.chown(path,{os.getuid()},{os.getgid()},follow_symlinks=False)\n'
        )
        command(['docker', 'run', '--rm', '--network', 'none', '--memory', '128m', '--pids-limit', '32',
                 '--cap-drop', 'ALL', '--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE',
                 '--security-opt', 'no-new-privileges:true', '--mount', f'type=bind,source={self.root},target=/owned',
                 '--entrypoint', 'python3', IMAGES['prepare'], '-c', program], timeout=30)
