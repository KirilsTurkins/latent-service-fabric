"""Four affected defining TUs; prior 24-object programme remains unchanged."""
from pathlib import Path
import hashlib
import json
from tools import host_stream_kernel_cleanup_programme as prior
from tools import host_stream_kernel_cleanup_constructor_wait as change

ROOT = prior.ROOT
baseline = prior.baseline
require = prior.require
baseline_source = prior.baseline_source
source_names = prior.source_names
source_fixture_configuration = prior.source_fixture_configuration
TARGETS = ('net/factory.o','kernel/kthread.o','kernel/workqueue.o','drivers/acpi/osl.o')
FREEZE = ROOT/'research/standard-outbound/linux-6.12-lineage/cleanup-constructor-wait-source-freeze-r1.json'
GEOMETRY = {name:prior.GEOMETRY[name] for name in TARGETS}
symbol,fields = GEOMETRY['kernel/workqueue.o']
GEOMETRY['kernel/workqueue.o'] = symbol,(*fields,
    ('birthCompletionBytes','sizeof(((struct lsf_cleanup_provider_control *)NULL)->born)'),
    ('constructorExpiryBytes','sizeof(((struct lsf_cleanup_provider_control *)NULL)->constructor_expires)'))
symbol,fields = GEOMETRY['drivers/acpi/osl.o']
GEOMETRY['drivers/acpi/osl.o'] = symbol,(*fields,
    ('constructorWaitqueueBytes','sizeof(lsf_acpi_provider_constructor_wait)'))


def compose(base, originals, config):
    parent=prior.compose(base,originals,config)
    parent_path=ROOT/'research/standard-outbound/linux-6.12-lineage/cleanup-constructor-source-freeze-r1.json'
    parent_raw=parent_path.read_bytes()
    previous=json.loads(parent_raw)
    def identity(raw):
        return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    require({name:identity(raw) for name,raw in parent.items()}==previous['derived'],
        'cleanup-constructor-original-322-derived-freeze')
    outputs=change.transform(parent,{})
    frozen=json.loads(FREEZE.read_bytes())
    require(frozen['schemaVersion']=='lsf.cleanup-constructor-wait-source-freeze.v1' and
        frozen['parentFreeze']==identity(parent_raw) and
        all(frozen[key] is False for key in ('initialBirthBounded','publicIoCallIntegrated',
            'actualLinuxExecution','consumerSelected','completeAllocationClosure','productionInstallation')),
        'cleanup-constructor-new-source-freeze')
    delta={name:identity(raw) for name,raw in outputs.items() if parent.get(name)!=raw}
    require(len(outputs)==322 and len(delta)==7 and delta==frozen['derivedDelta'],
        'cleanup-constructor-exact-seven-derived-delta')
    return outputs


def local_freeze():
    result = prior.local_freeze()
    for path in (Path(__file__),Path(change.__file__),change.FIXTURE,FREEZE):
        result[path.relative_to(ROOT).as_posix()] = baseline.objects.identity(path)
    return result


def geometry_suffix(target):
    name, fields = GEOMETRY[target]
    return ('\n/* Compile-only actual TU layout, never installation evidence. */\n'
        'const unsigned long long '+name+'[]\n'
        '__attribute__((used, aligned(8), section("'+baseline.GEOMETRY_SECTION+'"))) = {\n'
        '    0x4c534647454f4d31ULL, '+str(len(fields))+'ULL,\n'+
        ''.join('    (unsigned long long)('+expression+'),\n' for _,expression in fields)+'};\n').encode()


def fitting(values):
    """Only newly measured records/statics; no copied full-graph fit claim."""
    wq,factory = values['kernel/workqueue.o'],values['net/factory.o']
    require(wq['cpuMaximum']==64,'cleanup-constructor-original-cpu-maximum')
    require((factory['backingBytes'],factory['infrastructureBytes'],factory['bootstrapCeiling'],
        factory['allocationSlots'])==(524288,196608,1048576,256),'cleanup-constructor-original-caps')
    charged = {}
    for part in ('pool','worker','pwq','attrs','control','context'):
        size = wq['contextMaximumBytes' if part=='context' else part+'Bytes']
        alignment = wq[part+'Alignment']
        require(size>0 and 0<alignment<=4096 and not alignment&(alignment-1),
            'cleanup-constructor-finite-record-geometry')
        charged[part]=(size+alignment-1+63)&~63
    require(sum(charged.values())<=factory['infrastructureBytes'],
        'cleanup-constructor-record-subgraph-fit')
    require(wq['birthCompletionBytes']>0 and wq['constructorExpiryBytes']==8 and
        values['drivers/acpi/osl.o']['constructorWaitqueueBytes']>0,
        'cleanup-constructor-actual-pending-storage')
    return dict(providerRecordBytes=charged,providerRecordTotal=sum(charged.values()),
        providerRecords=6,providerRecordSubgraphFits=True,
        bootstrapAddedWaitqueueBytes=values['drivers/acpi/osl.o']['constructorWaitqueueBytes'],
        birthCompletionBytes=wq['birthCompletionBytes'],constructorExpiryBytes=wq['constructorExpiryBytes'],
        completeBootstrapRemeasured=False,wholeInfrastructureFitQualified=False,
        initialBirthBounded=False,publicIoCallIntegrated=False,actualLinuxExecution=False,
        consumerSelected=False,completeAllocationClosure=False,productionInstallation=False)
