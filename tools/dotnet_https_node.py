"""Reuse one captured client component for real TLS trust and ownership checks."""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import shutil
import ssl
import sys
import tempfile
import time

from tools import dotnet_standard_http_node as base
from tools.dotnet_published_http_node import DOMAIN
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.owned_test_process import run_owned
from tools.phase2_operator_process import Process, require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_http_tls_peer import CONFIGURATION
from tools.rust_capsule_node import RecordingClient, delete_all, deploy, selected_revision
from tools.rust_capsule_project import ROOT, fresh, write_json
from tools.standard_http.tls_peer import validate_tls

CASES = (
    ('flurl-domain',0,'/conformance/json',DOMAIN),
    ('refit-domain',1,'/conformance/json',DOMAIN),
    ('flurl-404',4,'/conformance/status/404','1:404:error:domain-error'),
    ('refit-404',5,'/conformance/status/404','1:404:error:domain-error'),
    ('flurl-500',6,'/conformance/status/500','1:500:error:domain-error'),
    ('refit-500',7,'/conformance/status/500','1:500:error:domain-error'),
    ('flurl-pending-cancel',8,'/conformance/hold/headers','1:cancelled'),
    ('refit-pending-cancel',9,'/conformance/hold/headers','1:cancelled'),
    ('early-body-dispose',18,'/conformance/body/partial','1:early:4'),
    ('fresh-flurl',0,'/conformance/json',DOMAIN),
    ('fresh-refit',1,'/conformance/json',DOMAIN),
)
REFUSALS = (('flurl-certificate-refused',0,'/conformance/json','1:transport-error'),
            ('refit-certificate-refused',1,'/conformance/json','1:transport-error'))
MATERIALS = ('tools/dotnet_https_node.py','tools/dotnet_published_http_node.py',
    'tools/dotnet_standard_http_node.py','tools/qualify_http_tls_peer.py',
    'tools/standard_http/process_peer.py','tools/standard_http/tls_peer.py',
    'tools/standard_http/peer.py','tools/standard_http/protocol.py','tools/standard_http/vectors.py',
    'tools/standard_http/observations.py','tools/rust_capsule_node.py')


def certificate(private, name, *, wrong_name=False):
    configuration = private/(name+'.cnf')
    text = CONFIGURATION.replace('subjectAltName = IP:127.0.0.1',
        'subjectAltName = DNS:wrong.invalid') if wrong_name else CONFIGURATION
    configuration.write_text(text,encoding='ascii',newline='\n')
    cert,key = private/(name+'.pem'),private/(name+'-private.pem')
    openssl = Path(shutil.which('openssl') or 'missing-openssl').resolve(strict=True)
    before = file_identity(openssl)
    result = run_owned([str(openssl),'req','-newkey','ec','-pkeyopt','ec_paramgen_curve:prime256v1',
        '-nodes','-x509','-sha256','-days','1','-config',str(configuration),'-keyout',str(key),'-out',str(cert)],
        cwd=private,timeout=15,maximum=65536)
    require(result.returncode==0 and result.cleaned and before==file_identity(openssl),
            'dotnet-https-owned-certificate-tool')
    return cert,key,ssl.PEM_cert_to_DER_cert(cert.read_text(encoding='ascii'))


def peer_result(value,profile):
    validate_tls(value)
    trusted = profile=='trusted'
    require(value['state']=='stopped' and value['failure'] is None
        and value['acceptedConnections']==(11 if trusted else 2)
        and value['startedRequests']==(11 if trusted else 0)
        and value['completedResponseWrites']==(8 if trusted else 0)
        and value['openConnections']==value['listeningOrigins']==value['rejectedRequests']==value['committedMutations']==0,
        'dotnet-https-exact-peer-retirement')
    require(not any(row['kind']=='gate-released' for row in value['events']),
            'dotnet-https-held-gates-never-released')
    if trusted:
        require([row.get('vector') for row in value['requests']]==[
            'domain-json','domain-json','http-404','http-404','http-500','http-500',
            'pending-headers','pending-headers','partial-body','domain-json','domain-json']
            and all(row['authorizationPresent'] is True and row['tls']['version'] in {'TLSv1.2','TLSv1.3'}
                    for row in value['requests']), 'dotnet-https-exact-trusted-domain-contacts')
        held={row['request'] for row in value['requests'] if row['vector'] in {'pending-headers','partial-body'}}
        require({row['request'] for row in value['events'] if row['kind']=='gate-pending'}==held
            and all(row['responseBytesWritten']==0 for row in value['requests'] if row['vector']=='pending-headers'),
            'dotnet-https-real-incomplete-headers-and-body')
    else:
        require(all(row['tls']['state']=='handshake-failed' and row.get('authorizationPresent',False) is False
            and row.get('vector') is None and row['responseBytesWritten']==0 for row in value['requests']),
            'dotnet-https-no-http-or-credential-before-trust')
    return {'contacts':value['acceptedConnections'],'httpRequests':value['startedRequests'],
        'completedWrites':value['completedResponseWrites'],'certificateRefusal':not trusted}


def run(artifact: Path,native: dict,output: Path):
    output=fresh(output)
    original={name:file_identity(path,512*1024**2) for name,path in native.items()}
    sources={name:file_identity(ROOT/name) for name in MATERIALS}
    component=file_identity(artifact/'component.wasm')
    record={'schemaVersion':'latent.dotnet.https.node.v1','status':'incomplete','sources':sources,
        'component':component,'native':original,'profiles':[],'fullTicketQualification':False}
    stage='same-component-signing'
    try:
        signed=output/'releases';environment=build_environment(output)
        result=run_bounded_result([str(native['capsule_authoring']),'demo-sign',str(signed),str(artifact)],
            output,environment,timeout_seconds=30,max_output_bytes=65536)
        require(result.returncode==0,'dotnet-https-normal-signing')
        for profile in ('trusted','wrong-name','untrusted-issuer'):
            stage=profile;destination=output/profile;destination.mkdir()
            with tempfile.TemporaryDirectory(prefix='lsf-dotnet-https-private-') as temporary, \
                    owned_cancellation() as cancellation, ExitStack() as cleanup:
                private=Path(temporary)
                for name in ('peer','node','client'):(private/name).mkdir(mode=0o700)
                credential=private/'peer/authorization'
                secret=('Bearer '+secrets.token_hex(32)).encode('ascii')
                credential.write_bytes(secret);credential.chmod(0o600)
                cert,key,der=certificate(private,'server',wrong_name=profile=='wrong-name')
                if profile=='untrusted-issuer':_,_,root=certificate(private,'foreign-root')
                else:root=der
                (destination/'server-certificate.der').write_bytes(der)
                (destination/'operator-trust.der').write_bytes(root)
                client=RecordingClient(native['latent'],private/'client',cancellation,time.monotonic()+240,
                    evidence=destination/'controls',invocation_timeout_millis=120000)
                peer=Process([sys.executable,'-B',str(ROOT/'tools/standard_http/process_peer.py'),
                    '--credential',str(credential),'--certificate',str(cert),'--private-key',str(key)],
                    private/'peer',environment,cancellation,maximum=65536)
                cleanup.callback(peer.close)
                startup=peer.line(min(client.deadline,time.monotonic()+10))
                config=base.configuration(private/'node',signed,startup,credential)
                value=json.loads(config.read_bytes())
                provider=value['providers']['httpStreaming']['configuration']
                provider.update(extraRoots=[list(root)],publicRoots=False)
                write_json(config,value)
                node=connect(client,native['latentd'],private/'node',config,'examples',1)
                cleanup.callback(node.close);probe=Probe(node,original['latentd'])
                release=signed/'dotnet-standard-http'
                published=client.call('release','publish-package',release/'package','--evidence',
                    release/'evidence/index.json','--operation-id','https-publish','--expected-generation','0')
                publication=published['data']['operation']['publication']['id']
                origin=startup['origins']['primary']
                require(origin['scheme']=='https','dotnet-https-explicit-encrypted-origin')
                _,grants=base.grants(client,node,publication,origin)
                target=deploy(client,release/'deployment.json',publication,grants=grants)
                pin=selected_revision(client,target)
                require(pin['releaseDigest']==component['sha256'],'dotnet-https-unchanged-component-revision')
                observations=[]
                for label,which,path,expected in (CASES if profile=='trusted' else REFUSALS):
                    row=base.invoke(client,target,which,f"https://{origin['host']}:{origin['port']}"+path,'https-'+label)
                    write_json(destination/('invocation-'+label+'.json'),row)
                    require(row['exitCode']==0 and row['decoded']==[expected] and row['processReaped'] is True
                        and row['response']['outcomeKnown'] is True and row['response']['data']['resolvedRevision']==pin,
                        'dotnet-https-exact-ordinary-library-result')
                    consumption=row['response']['data']['consumption']
                    require(type(consumption['outboundRequests']) is int and consumption['outboundRequests']==1
                        and 0<int(consumption['cpuFuel'])<=target['budget']['cpuFuel']
                        and 0<int(consumption['peakMemoryBytes'])<=target['budget']['memoryBytes'],
                        'dotnet-https-original-budgets')
                    base.retire(client,target,probe,destination,label)
                    observations.append({'case':label,'invocation':row,'physicalRetirementVerified':True})
                delete_all(client,[target['name']]);stop(client,node)
                shutdown=stopped_record(node)
                peer.stop();raw=bytes(peer.buffers[0]);observation=json.loads(raw.splitlines()[-1])
                encoded=json.dumps(observation).encode('ascii')
                require(all(token not in body for token in (secret,secret.removeprefix(b'Bearer '))
                    for body in (raw,encoded)) and peer.owner.finished,'dotnet-https-peer-reaped-and-secret-free')
                write_json(destination/'peer-observation.json',observation)
                record['profiles'].append({'profile':profile,'cases':observations,'peer':peer_result(observation,profile),
                    'shutdown':shutdown,'serverCertificate':file_identity(destination/'server-certificate.der'),
                    'operatorTrust':file_identity(destination/'operator-trust.der')})
                write_json(output/'progress.json',record)
        require(original=={name:file_identity(path,512*1024**2) for name,path in native.items()}
            and sources=={name:file_identity(ROOT/name) for name in MATERIALS}
            and component==file_identity(artifact/'component.wasm'),'dotnet-https-final-source-component-native')
        record.update(status='passed',guestExecutions=15,componentRecompiled=False)
        write_json(output/'qualification.json',record)
        return record
    except BaseException:
        record.update(status='failed',stage=stage)
        write_json(output/'FAILED.json',record)
        raise
