"""Independent ordinary URLConnection fixture; never a library eligibility gate."""
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_capsule_project import create
from tools.java_http_client import PROFILE_ID
from tools.rust_capsule_project import ROOT, digest, read_file


def project(directory: Path) -> Path:
    app = create(directory, 'greeting', 'java-standard-http')
    source = ROOT/'examples/java-standard-http'
    java = read_file(source/'Capsule.java')
    wit = read_file(source/'world.wit')
    (app/'src/dev/latent/app/Capsule.java').write_bytes(java)
    (app/'wit/world.wit').write_bytes(wit)
    descriptor = json.loads(read_file(app/'capsule-project.json'))
    descriptor.update(world='examples:java-standard-http/service@1.0.0',
                      httpClient={'profile': PROFILE_ID})
    descriptor['limits']['outboundRequests'] = 8
    (app/'capsule-project.json').write_text(json.dumps(descriptor, indent=2)+'\n', encoding='utf-8')
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template'] = {'name': 'java-standard-http', 'sourceDigest': digest(java), 'witDigest': digest(wit)}
    (app/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf-8')
    return app


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    project(parser.parse_args().directory)
