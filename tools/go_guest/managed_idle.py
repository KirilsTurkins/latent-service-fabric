"""Account source-pinned Go maintenance capacity before worker allocation."""
from tools.go_guest.runtime import replace_once

PROFILE = 'go-component-activation-v5'


def runtime_sources(sources, sdk):
    sources['runtime/proc.go'] = replace_once(sources['runtime/proc.go'],
        '\tdoInit(runtime_inittasks) // Must be before defer.',
        '\tlsfPrepareManagedIdle()\n\tdoInit(runtime_inittasks) // Must be before defer.')
    sources['runtime/proc.go'] = replace_once(sources['runtime/proc.go'],
        'func execute(gp *g, inheritTime bool) {\n\tif gp.lsfParked { lsfTaskWake(gp) }',
        'func execute(gp *g, inheritTime bool) {\n\tlsfManagedBeforeRun(gp)\n\tif gp.lsfParked { lsfTaskWake(gp) }')
    text = sources['runtime/os_wasip1.go']
    text = replace_once(text, 'if lsfTrustedIdle(fn.fn) { return [2]uint64{} }',
                        'if lsfTrustedIdle(fn.fn) { return lsfTakeManagedOwner() }')
    text = replace_once(text, 'gp != current && status != _Gdead && !lsfTrustedIdle(gp.startpc)',
        'gp != current && status != _Gdead && !(lsfTrustedIdle(gp.startpc) && lsfManagedOwner(gp))')
    for name in ('lsfTaskDestroyed', 'lsfTaskPark', 'lsfTaskWake'):
        argument = 'gp *g'
        opening = 'func ' + name + '(' + argument + ') {\n\tif gp.lsfOwner[1] == 0 { return }'
        body = ('\n\tif lsfManagedOwner(gp) {\n\t\tlsfManagedBeforeRun(gp)\n'
                + ('\t\tgp.lsfOwner = [2]uint64{}\n' if name == 'lsfTaskDestroyed' else '')
                + '\t\treturn\n\t}')
        text = replace_once(text, opening, opening + body)
    text = replace_once(text, '\tlsfActivationActive = false\n}',
                        '\tlsfRetireManagedIdle()\n\tlsfActivationActive = false\n}')
    text += '\n' + (sdk / 'runtime/managed_idle.go.in').read_text(encoding='utf-8')
    sources['runtime/os_wasip1.go'] = text
