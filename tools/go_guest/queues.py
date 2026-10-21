"""Versioned reservation of logical Go runnable/resumable capacity.

Apply after the authenticated v5 maintenance overlay. A queue owner is reserved
before a goroutine allocation and held across every park/wake/checkpoint until
physical goroutine destruction. Maintenance slots are prepaid before GC starts.
"""
from tools.go_guest.runtime import replace_once

PROFILE = 'go-component-activation-v6'


def runtime_sources(sources, sdk):
    sources['runtime/runtime2.go'] = replace_once(sources['runtime/runtime2.go'],
        '\tlsfOwner [2]uint64\n', '\tlsfOwner [2]uint64\n\tlsfQueue [2]uint64\n')
    sources['runtime/proc.go'] = replace_once(sources['runtime/proc.go'],
        '\tnewg.lsfOwner = lsfOwner\n',
        '\tnewg.lsfOwner = [2]uint64{lsfOwner[0], lsfOwner[1]}\n'
        '\tnewg.lsfQueue = [2]uint64{lsfOwner[2], lsfOwner[3]}\n')
    text = sources['runtime/os_wasip1.go']
    text = replace_once(text, 'func lsfNewTask(fn *funcval, parent *g) [2]uint64 {',
                        'func lsfNewTask(fn *funcval, parent *g) [4]uint64 {')
    text = replace_once(text, 'if lsfTrustedIdle(fn.fn) { return lsfTakeManagedOwner() }',
                        'if lsfTrustedIdle(fn.fn) { return lsfTakeManagedAdmission() }')
    text = replace_once(text,
        'if funcname(findfunc(fn.fn)) == "runtime.main" { return [2]uint64{} }',
        'if funcname(findfunc(fn.fn)) == "runtime.main" { return [4]uint64{} }')
    text = replace_once(text,
        '\tif lsfActivationTasks == ^uint32(0) { lsfFail("LSF goroutine count overflow") }',
        '\tqueue := lsfReserveQueue([2]uint64{result.generation, result.id}, true)\n'
        '\tif lsfActivationTasks == ^uint32(0) { lsfFail("LSF goroutine count overflow") }')
    text = replace_once(text, '\treturn [2]uint64{result.generation, result.id}\n}',
        '\treturn [4]uint64{result.generation, result.id, queue[0], queue[1]}\n}')
    text = replace_once(text, '\t\tgp.lsfOwner = [2]uint64{}\n',
                        '\t\tgp.lsfOwner = [2]uint64{}\n\t\tgp.lsfQueue = [2]uint64{}\n')
    text = replace_once(text,
        '\tvar result lsfUnitResult\n\tlsfSettle(int64(gp.lsfOwner[0]), int64(gp.lsfOwner[1]), unsafe.Pointer(&result))',
        '\tlsfReleaseQueue(gp.lsfQueue)\n\tgp.lsfQueue = [2]uint64{}\n'
        '\tvar result lsfUnitResult\n\tlsfSettle(int64(gp.lsfOwner[0]), int64(gp.lsfOwner[1]), unsafe.Pointer(&result))')
    text = replace_once(text,
        '\t\tlsfManagedOwners[index] = [2]uint64{result.generation, result.id}',
        '\t\tlsfManagedOwners[index] = [2]uint64{result.generation, result.id}\n'
        '\t\tlsfManagedQueues[index] = lsfReserveQueue(lsfManagedOwners[index], false)')
    text = replace_once(text, '\tfor _, owner := range lsfManagedOwners {',
        '\tfor index, owner := range lsfManagedOwners {\n'
        '\t\tlsfReleaseQueue(lsfManagedQueues[index])')
    text += '\n' + (sdk / 'runtime/queue_bridge.go.in').read_text(encoding='utf-8')
    sources['runtime/os_wasip1.go'] = text
