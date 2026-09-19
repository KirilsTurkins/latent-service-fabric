"""Pinned upstream configuration with only owned mounts and a loopback TLS port."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[2]
LABEL = 'io.latent.harbor-test-run'
INSTALLER = 'https://github.com/goharbor/harbor/releases/download/v2.15.2/harbor-online-installer-v2.15.2.tgz'
INSTALLER_DIGEST = '88f6a7436b31890e8e472972a7433d36b7d6a36de9adeb86337fdc9fe7fb5fa3'
IMAGES = json.loads(Path(__file__).with_name('images.json').read_bytes())


def installer_template(cache: Path) -> dict:
    archive = cache / 'harbor-online-installer-v2.15.2.tgz'
    if archive.exists():
        if archive.is_symlink() or archive.stat().st_size > 1024 * 1024:
            raise RuntimeError('invalid Harbor installer cache')
        data = archive.read_bytes()
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(INSTALLER, timeout=60) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise RuntimeError('Harbor installer byte bound')
    if hashlib.sha256(data).hexdigest() != INSTALLER_DIGEST:
        raise RuntimeError('Harbor installer digest mismatch')
    if not archive.exists():
        cache.mkdir(parents=True, exist_ok=True)
        with archive.open('xb') as output:
            output.write(data)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as bundle:
        member = bundle.getmember('harbor/harbor.yml.tmpl')
        if not member.isfile() or member.size > 128 * 1024:
            raise RuntimeError('invalid Harbor template member')
        return yaml.safe_load(bundle.extractfile(member).read(128 * 1024))


def write_input(root: Path, port: int, password: str, template: dict) -> None:
    for name in ['input', 'common/config', 'data', 'log']:
        (root / name).mkdir(parents=True, exist_ok=True)
    template.update(hostname='harbor.test', external_url=f'https://127.0.0.1:{port}',
                    harbor_admin_password=password, data_volume='/fixture-root/data',
                    https={'port': 443, 'certificate': '/fixture-root/fixtures/server.pem',
                           'private_key': '/fixture-root/fixtures/server.key'})
    template['database'].update(password=password, max_idle_conns=4, max_open_conns=32)
    template['jobservice'].update(max_job_workers=2, job_loggers=['STD_OUTPUT'])
    template['log'] = {'level': 'error', 'local': {
        'rotate_count': 1, 'rotate_size': '1M', 'location': '/fixture-root/log'}}
    template['storage_service'] = {'redirect': {'disable': True}}
    template['proxy'] = {'http_proxy': '', 'https_proxy': '', 'no_proxy': '127.0.0.1,localhost'}
    path = root / 'input/harbor.yml'
    path.write_text(yaml.safe_dump(template), encoding='utf-8')
    path.chmod(0o600)


def owned_path(root: Path, source: str) -> str:
    if source.startswith('/fixture-root/'):
        relative = source.removeprefix('/fixture-root/')
    elif source.startswith('./'):
        relative = source[2:]
    else:
        raise RuntimeError('Harbor mount is outside the fixture')
    selected = root / relative
    if any(part == '..' for part in Path(relative).parts) or not selected.resolve().is_relative_to(root.resolve()):
        raise RuntimeError('Harbor mount escapes the fixture')
    for current in [selected, *selected.parents]:
        if current == root.parent:
            break
        if current.is_symlink():
            raise RuntimeError('Harbor fixture cannot contain linked mounts')
    return str(selected.resolve())


def bounded_compose(raw: dict, root: Path, project: str, token: str, port: int) -> dict:
    if not re.fullmatch(r'lsf-harbor-[0-9a-f]{32}', project) or project != 'lsf-harbor-' + token:
        raise RuntimeError('invalid Harbor ownership identity')
    services = raw.get('services', {})
    if set(services) != (set(IMAGES) - {'prepare'}) | {'log'}:
        raise RuntimeError('unexpected Harbor service graph')
    services.pop('log')
    volumes = {}
    for name, service in services.items():
        expected = IMAGES[name].split('@')[0] + ':v2.15.2'
        if service.get('image') != expected:
            raise RuntimeError('unexpected Harbor image')
        for denied in ['privileged', 'pid', 'ipc', 'devices', 'network_mode', 'volumes_from', 'build']:
            if denied in service:
                raise RuntimeError('unsupported Harbor service authority')
        service['image'] = IMAGES[name]
        if not set(service.get('cap_add', [])).issubset({'CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'SETUID', 'SETGID', 'NET_BIND_SERVICE'}):
            raise RuntimeError('unsupported Harbor container capability')
        service['cap_drop'] = ['ALL']
        service.pop('container_name', None)
        service.pop('ports', None)
        service['restart'] = 'no'
        service['labels'] = {LABEL: token}
        service['mem_limit'] = '1024m' if name == 'postgresql' else '512m'
        service['memswap_limit'] = service['mem_limit']
        service['pids_limit'] = 256
        service['cpus'] = 1
        service['security_opt'] = ['no-new-privileges:true']
        service['logging'] = {'driver': 'json-file', 'options': {'max-size': '1m', 'max-file': '1'}}
        service['depends_on'] = {dependency: {'condition': 'service_healthy'}
                                 for dependency in service.get('depends_on', []) if dependency != 'log'}
        if name == 'postgresql':
            service['shm_size'] = '128m'
        if 'env_file' in service:
            service['env_file'] = [owned_path(root, path) for path in service['env_file']]
        mounts = []
        for mount in service.get('volumes', []):
            if isinstance(mount, str):
                parts = mount.split(':')
                if len(parts) not in (2, 3):
                    raise RuntimeError('invalid Harbor volume')
                source, target = parts[:2]
                mount = {'type': 'bind', 'source': source, 'target': target,
                         'read_only': len(parts) == 3 and parts[2] == 'ro'}
            elif not isinstance(mount, dict) or mount.get('type') != 'bind':
                raise RuntimeError('unsupported Harbor volume')
            source = mount['source']
            owned = owned_path(root, source)
            if source.rstrip('/') in ('/fixture-root/data/database', '/fixture-root/data/redis'):
                volume = 'database' if name == 'postgresql' else 'redis'
                volumes[volume] = {'labels': {LABEL: token}}
                mount = {'type': 'volume', 'source': volume, 'target': mount['target']}
            else:
                mount['source'] = owned
            mounts.append(mount)
        service['volumes'] = mounts
    services['proxy']['ports'] = [{'target': 8443, 'published': str(port), 'host_ip': '127.0.0.1', 'protocol': 'tcp'}]
    services['proxy']['networks'] = ['harbor', 'edge']
    return {'name': project, 'services': services, 'volumes': volumes,
            'networks': {'harbor': {'internal': True, 'labels': {LABEL: token}},
                         'edge': {'internal': False, 'labels': {LABEL: token}}}}
