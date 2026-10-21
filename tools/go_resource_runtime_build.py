"""Require a normal packaged v5 Go build before the resource lifecycle run."""
from tools import guest_runtime_receipts
from tools.go_resource_runtime_fixture import PROFILE
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_sdk_scratch import package_identity
from tools.rust_capsule_project import read_json


def build_evidence(artifact):
    names=('BUILD-COMPLETE.json','build-observation.json','source-inputs.json',
           'recipe-inputs.json','package-inputs.json','standard-runtime-selection.json',
           'go-runtime-transformations.json','application-dependencies.json',
           'compiler-containment.json','go-module-build-inputs.json')
    identities={name:file_identity(artifact/name,16*1024*1024) for name in names}
    component=file_identity(artifact/'component.wasm',64*1024*1024)
    complete,observation,selected=(read_json(artifact/name,16*1024*1024) for name in
        ('BUILD-COMPLETE.json','build-observation.json','standard-runtime-selection.json'))
    require(complete.get('packageAssembled') is True
        and complete.get('componentDigest')==observation.get('componentDigest')==component['sha256']
        and observation.get('componentSize')==component['bytes']
        and complete.get('observationDigest')==identities['build-observation.json']['sha256']
        and complete.get('sourceDigest')==identities['source-inputs.json']['sha256'],
        'resource-Go-normal-packaged-build-required')
    require(observation.get('parameters')=={'goPackage':'my-greeting','compiler':'componentize-go',
        'target':'wasm32-wasip1','runtime':PROFILE,'locked':True,'ambientWasi':False},
        'resource-Go-exact-v5-build-parameters')
    materials=observation['materials']
    for material,filename in (('build-recipe','recipe-inputs.json'),('package-inputs','package-inputs.json'),
            ('standard-runtime-selection','standard-runtime-selection.json'),
            ('go-runtime-transformations','go-runtime-transformations.json'),
            ('application-dependencies','application-dependencies.json'),
            ('compiler-containment','compiler-containment.json'),('go-module-build-inputs','go-module-build-inputs.json')):
        identity=identities[filename]
        require([row for row in materials if row.get('name')==material]==[
            {'name':material,'digest':identity['sha256'],'size':identity['bytes']}],
            'resource-Go-exact-build-material')
    guest_runtime_receipts.validate(selected,source=identities['source-inputs.json']['sha256'],
        component=component['sha256'],language='go',profile=PROFILE,materials=[r for r in materials if r['name']!='standard-runtime-selection'])
    require(selected['graphState']=='captured' and selected['qualification']=='unknown'
        and selected['apiSupport']=='not-evaluated' and selected['authority']=='none',
        'resource-Go-selection-is-not-qualification-or-authority')
    return {'component':component,'documents':identities,'package':package_identity(artifact,complete)}
