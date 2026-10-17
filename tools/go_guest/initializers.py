"""Run original linked Go module initialization inside an admitted async root."""
from tools.go_guest.runtime import replace_once

MODULE_INITIALIZATION = '''	last := lastmoduledatap // grab before loop starts. Any added modules after this point will do their own doInit calls.
	for m := &firstmoduledata; true; m = m.next {
		doInit(m.inittasks)
		if m == last {
			break
		}
	}'''


def runtime_sources(sources, sdk):
    # runtime_inittasks, GC enablement and the original runtime startup remain
    # in runtime.main. Preserve the exact linked module order for the first
    # actual async root, where host suspension and original owners exist.
    text = replace_once(sources['runtime/proc.go'], MODULE_INITIALIZATION, '\tlsfPrepareApplicationInit()')
    # Module initialization keeps logical Go ordering, not a native main-thread
    # identity. Application affinity cannot silently pin the component scheduler.
    for name in ('LockOSThread', 'UnlockOSThread'):
        text = replace_once(text, 'func ' + name + '() {', 'func ' + name + '() {\n'
            '\tif lsfActivationActive { lsfFail("LSF native thread affinity is unsupported") }')
    sources['runtime/proc.go'] = text
    sources['runtime/os_wasip1.go'] += '\n' + (sdk / 'runtime/initializer_bridge.go.in').read_text()


def async_source(text):
    text = replace_once(text, '\tgo closure()',
        '\tgo func() {\n\t\tlsfActivationInitialize()\n\t\tclosure()\n\t}()')
    return text + '\n//go:linkname lsfActivationInitialize runtime.lsfActivationInitialize\nfunc lsfActivationInitialize()\n'
