"""Candidate-only numeric constructor failures; no admission or errno changes.

Every input below is the exact derived source captured by failed de37. The
observation is fixed stack-local data, never an allocation/identity authority.
"""
import hashlib
import re
from tools.host_stream_kernel_cleanup_native import require, replace, function

PREIMAGES = {
    'kernel/lsf-cleanup-lifecycle-task.c': (4199, '8eeebbf87a15b1c94185bd2c3dce1463623e3b9a453c157d9a5c111666a70f7a'),
    'kernel/lsf-cleanup-constructor.c': (18936, '53cb6e2553e4703448230ec648031ef39628087d7254dd16f1de6ea74b0f9faf'),
    'mm/lsf-cleanup-stack.c': (13463, 'c42ff3bb249c2de864bdbff0a1964d9feef65b1f0dff47e1996e90b210951546'),
    'net/factory-cleanup-stack.c': (4401, '511728101b855e06d2fc6fa6f2458fafdbeecec15898e52d82953bf694ce5cb4'),
    'include/net/lsf_stream_cleanup_stack.h': (1031, '21ecfafd48962d6b34e2cd55762eb8ba7060f6edd52a32b152271634dc92f080'),
    'net/factory-cleanup-native-bootstrap.c': (11162, '547fe5009cb0e8fc5b83c52df0685863dd6f02de1a8f9fd2f882e0cc22b3b236'),
}

# Literal, closed numeric meanings; there is no process pointer or dynamic key.
SITES = (
    'ENTRY', 'SIGNAL', 'DUP', 'DUP_PROFILE', 'TASK_CLAIM', 'ARCH_DUP',
    'STACK_ACTOR', 'STACK_GEOMETRY', 'STACK_RESERVE', 'RESERVE_GEOMETRY',
    'RESERVE_SOURCE', 'RESERVE_TASK', 'RESERVE_ALLOCATION', 'CARVE_STATE',
    'CARVE_EXTENT', 'PTE_PGD', 'PTE_P4D', 'PTE_PUD', 'PTE_PMD', 'PTE_NONEMPTY',
    'STACK_PROFILE', 'SCS', 'USER_CPUS', 'TASK_INITIALIZED', 'CREDS', 'RLIMIT',
    'THREAD_LIMIT', 'KTHREAD', 'MPOL', 'SCHED', 'PERF', 'AUDIT', 'SECURITY',
    'SEMUNDO', 'FILES', 'FS', 'SIGHAND', 'SIGNAL_COPY', 'MM', 'NAMESPACES',
    'IO', 'ARCH_THREAD', 'PID', 'PIDFD', 'PIDFD_USER', 'CGROUP', 'SCHED_CGROUP',
    'CONSTRUCTOR_PREPARE', 'PID_NAMESPACE', 'FATAL_SIGNAL', 'TASK_PUBLISH',
    'STACK_UNMAP', 'STACK_FINISH', 'STACK_ABORT', 'TASK_ABORT',
)


class Editor:
    """Each edit must project unambiguously to its authenticated exact input."""
    def __init__(self, text):
        self.original, self.text, self.edits = text, text, []

    def edit(self, old, new):
        self.text = replace(self.text, old, new)
        self.edits.append((old, new))

    def finish(self):
        projected = self.text
        for old, new in reversed(self.edits):
            projected = replace(projected, new, old)
        require(projected == self.original, 'constructor-failure-unchanged-projection')
        return self.text


def failure(site, error, detail='0', observation='observation'):
    require(site in SITES, 'constructor-failure-literal-site')
    return f'lsf_cleanup_failure({observation}, LSF_FAILURE_{site}, {detail}, {error});'


def failing_return(editor, old, site, error, detail='0'):
    """Keep the original condition/evaluation order and original return value."""
    prefix, statement = old.rsplit('\n', 2)[:2]
    require(statement.strip().startswith('return '), 'constructor-failure-return-shape')
    indentation = statement[:len(statement)-len(statement.lstrip())]
    parent = indentation[:-1] if '\t' in indentation else indentation[:-4]
    editor.edit(old, prefix+' {\n'+indentation+failure(site, error, detail)+'\n'+
                statement+'\n'+parent+'}\n')


def header(text):
    editor = Editor(text)
    declaration = '''
/* Numeric observations live only on the current constructor's existing stack.
 * Optional NULL observers preserve existing private APIs and other callers. */
enum lsf_cleanup_failure_site {
'''+''.join(f'    LSF_FAILURE_{name} = {i},\n' for i, name in enumerate(SITES, 1))+'''};
struct lsf_cleanup_failure_observation {
    unsigned int site, detail, unwind;
    int origin;
};
static inline void lsf_cleanup_failure(struct lsf_cleanup_failure_observation *observation,
    unsigned int site, unsigned int detail, int error)
{
    if (observation && !observation->site) {
        observation->site = site;
        observation->detail = detail;
        observation->origin = error;
    }
}
static inline void lsf_cleanup_failure_unwind(struct lsf_cleanup_failure_observation *observation,
    unsigned int site)
{
    if (observation && !observation->unwind)
        observation->unwind = site;
}
void lsf_factory_cleanup_constructor_failure(const struct lsf_cleanup_failure_observation *, int);
struct task_struct *lsf_prepaid_cleanup_dup_initialized_observed(
    struct lsf_cleanup_task_source, int, struct lsf_cleanup_failure_observation *);
int lsf_prepaid_cleanup_stack_create_observed(struct lsf_cleanup_task_source,
    struct task_struct *, struct lsf_cleanup_failure_observation *);
int lsf_factory_cleanup_stack_reserve_observed(struct lsf_cleanup_task_source,
    struct task_struct *, unsigned long, void **, struct lsf_cleanup_failure_observation *);
'''
    editor.edit('#endif\n', declaration+'#endif\n')
    return editor.finish()


def duplicate(text):
    editor = Editor(text)
    editor.edit('    struct task_struct *src)\n',
        '    struct task_struct *src, struct lsf_cleanup_failure_observation *observation)\n')
    editor.edit('    raw_spin_unlock_irqrestore(&src->pi_lock, flags);\n',
        '    raw_spin_unlock_irqrestore(&src->pi_lock, flags);\n'
        '    if (error)\n        '+failure('USER_CPUS', 'error')+'\n')
    old = ('struct task_struct *lsf_prepaid_cleanup_dup_initialized(\n'
        '    struct lsf_cleanup_task_source source, int node)\n')
    editor.edit(old, old.replace('dup_initialized(', 'dup_initialized_observed(')
        .replace('int node)', 'int node, struct lsf_cleanup_failure_observation *observation)'))
    failing_return(editor,
        '\t    IS_ENABLED(CONFIG_KMSAN) || IS_ENABLED(CONFIG_DEBUG_LOCK_ALLOC))\n'
        '\t\treturn ERR_PTR(-EOPNOTSUPP);\n', 'DUP_PROFILE', '-EOPNOTSUPP')
    failing_return(editor, '\tif (!tsk)\n\t\treturn ERR_PTR(-EOPNOTSUPP);\n',
        'TASK_CLAIM', '-EOPNOTSUPP')
    editor.edit('\terr = lsf_prepaid_cleanup_stack_create(source, tsk);\n',
        '\terr = lsf_prepaid_cleanup_stack_create_observed(source, tsk, observation);\n')
    editor.edit('\terr = lsf_cleanup_dup_empty_user_cpus(tsk, orig);\n',
        '\terr = lsf_cleanup_dup_empty_user_cpus(tsk, orig, observation);\n')
    for call, site, label in (
            ('arch_dup_task_struct(tsk, orig)', 'ARCH_DUP', 'free_tsk'),
            ('lsf_prepaid_cleanup_stack_create_observed(source, tsk, observation)', 'DUP', 'free_tsk'),
            ('scs_prepare(tsk, node)', 'SCS', 'free_stack'),
            ('lsf_cleanup_dup_empty_user_cpus(tsk, orig, observation)', 'USER_CPUS', 'free_stack')):
        old = f'\terr = {call};\n\tif (err)\n\t\tgoto {label};\n'
        editor.edit(old, f'\terr = {call};\n\tif (err) {{\n\t\t'+failure(site, 'err')+
            f'\n\t\tgoto {label};\n\t}}\n')
    failing_return(editor,
        '\tif (!lsf_factory_cleanup_task_initialized(source, tsk))\n\t\treturn ERR_PTR(-EIO);\n',
        'TASK_INITIALIZED', '-EIO')
    for call, site in (
            ('lsf_prepaid_cleanup_stack_abort_unpublished(source, tsk)', 'STACK_ABORT'),
            ('!lsf_factory_cleanup_task_abort(source, tsk)', 'TASK_ABORT')):
        old = f'\tif ({call})\n\t\treturn ERR_PTR(-EIO);\n'
        editor.edit(old, f'\tif ({call}) {{\n\t\tlsf_cleanup_failure_unwind(observation, LSF_FAILURE_{site});\n'
            '\t\treturn ERR_PTR(-EIO);\n\t}\n')
    wrapper = '''
struct task_struct *lsf_prepaid_cleanup_dup_initialized(
    struct lsf_cleanup_task_source source, int node)
{
    return lsf_prepaid_cleanup_dup_initialized_observed(source, node, NULL);
}
'''
    editor.edit('\nint lsf_prepaid_cleanup_abort_initialized(', wrapper+'\nint lsf_prepaid_cleanup_abort_initialized(')
    return editor.finish()


def reserve(text):
    editor = Editor(text)
    old = ('int lsf_factory_cleanup_stack_reserve(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *actual_task, unsigned long bytes, void **address)\n')
    editor.edit(old, old.replace('stack_reserve(', 'stack_reserve_observed(')
        .replace('void **address)', 'void **address, struct lsf_cleanup_failure_observation *observation)'))
    failing_return(editor,
        '        bytes != actual_bytes || !bytes || bytes > LSF_FACTORY_INFRA_BYTES)\n'
        '        return result;\n', 'RESERVE_GEOMETRY', 'result')
    for tail, site in (
        ('        factory.device->cleanup_stack_attempted)', 'RESERVE_SOURCE'),
        ('        actual_task != (void *)((char *)page_address(factory.pages) + task->offset))', 'RESERVE_TASK'),
        ('            LSF_DEVICE_CLEANUP_STACK, source.task, &ticket, &offset))', 'RESERVE_ALLOCATION')):
        editor.edit(tail+'\n        goto out;\n', tail+' {\n        '+failure(site, 'result')+
            '\n        goto out;\n    }\n')
    wrapper = '''
int lsf_factory_cleanup_stack_reserve(struct lsf_cleanup_task_source source,
    struct task_struct *actual_task, unsigned long bytes, void **address)
{
    return lsf_factory_cleanup_stack_reserve_observed(source, actual_task, bytes, address, NULL);
}
'''
    editor.edit('\nvoid *lsf_factory_cleanup_stack_current(', wrapper+'\nvoid *lsf_factory_cleanup_stack_current(')
    return editor.finish()


def stack(text):
    editor = Editor(text)
    editor.edit('static pte_t *lsf_cleanup_existing_pte(unsigned long address)\n',
        'static pte_t *lsf_cleanup_existing_pte_observed(unsigned long address,\n'
        '    struct lsf_cleanup_failure_observation *observation, unsigned int index)\n')
    for level in ('pgd', 'p4d', 'pud', 'pmd'):
        condition = (f'    if ({level}_none(*{level}) || {level}_bad(*{level})'+
            (')' if level == 'pgd' else f' || {level}_leaf(*{level}))'))
        failing_return(editor, condition+'\n        return NULL;\n',
            'PTE_'+level.upper(), '-EOPNOTSUPP', 'index')
    editor.edit('static int lsf_cleanup_stack_carve(struct lsf_cleanup_stack *stack)\n',
        'static int lsf_cleanup_stack_carve(struct lsf_cleanup_stack *stack,\n'
        '    struct lsf_cleanup_failure_observation *observation)\n')
    for original, conditions, site in (
        ('    if (!vmap_initialized || lsf_cleanup_stack_live ||\n'
         '        list_empty(&free_vmap_area_list))\n        goto out;\n',
         ('!vmap_initialized', 'lsf_cleanup_stack_live', 'list_empty(&free_vmap_area_list)'), 'CARVE_STATE'),
        ('    if (!IS_ALIGNED(start, THREAD_ALIGN) || start < VMALLOC_START ||\n'
         '        free->va_end > VMALLOC_END || free->va_end <= start ||\n'
         '        free->va_end - start <= size)\n        goto out;\n',
         ('!IS_ALIGNED(start, THREAD_ALIGN)', 'start < VMALLOC_START', 'free->va_end > VMALLOC_END',
          'free->va_end <= start', 'free->va_end - start <= size'), 'CARVE_EXTENT')):
        # Identical short-circuit order and reads, still under the original
        # lock. No reason is inferred by re-reading a failed guard afterwards.
        expanded = ''.join('    if ('+condition+') {\n        '+failure(site, 'result', str(i))+
            '\n        goto out;\n    }\n' for i, condition in enumerate(conditions, 1))
        editor.edit(original, expanded)
    wrapper = '''static pte_t *lsf_cleanup_existing_pte(unsigned long address)
{
    return lsf_cleanup_existing_pte_observed(address, NULL, 0);
}

'''
    editor.edit('static int lsf_cleanup_stack_carve(', wrapper+'static int lsf_cleanup_stack_carve(')
    # Both selected and unsupported compile-time profiles share one old API.
    signature = ('int lsf_prepaid_cleanup_stack_create(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *task)\n')
    require(editor.text.count(signature) == 2, 'constructor-failure-both-stack-profiles')
    for _ in range(2):
        offset = editor.text.index(signature)
        new = signature.replace('stack_create(', 'stack_create_observed(').replace(
            'struct task_struct *task)', 'struct task_struct *task, struct lsf_cleanup_failure_observation *observation)')
        # Different suffixes give each reverse edit an unambiguous occurrence.
        end = editor.text.index('\n}', offset)+3
        body = editor.text[offset:end]
        changed = replace(body, signature, new)
        if '(void)source;' in body:
            changed = replace(changed, '    return -EOPNOTSUPP;\n',
                '    '+failure('STACK_PROFILE', '-EOPNOTSUPP')+'\n    return -EOPNOTSUPP;\n')
        else:
            changed = replace(changed,
                '    if (current != kthreadd_task || in_interrupt() || !task ||\n'
                '        lsf_prepaid_cleanup_stack_geometry(&bytes))\n        return -EOPNOTSUPP;\n',
                '    if (current != kthreadd_task || in_interrupt() || !task) {\n'
                '        '+failure('STACK_ACTOR', '-EOPNOTSUPP')+'\n        return -EOPNOTSUPP;\n    }\n'
                '    if (lsf_prepaid_cleanup_stack_geometry(&bytes)) {\n'
                '        '+failure('STACK_GEOMETRY', '-EOPNOTSUPP')+'\n        return -EOPNOTSUPP;\n    }\n')
            changed = replace(changed, 'lsf_factory_cleanup_stack_reserve(source, task, bytes, &address)',
                'lsf_factory_cleanup_stack_reserve_observed(source, task, bytes, &address, observation)')
            changed = replace(changed, '    if (error)\n        return error;\n',
                '    if (error) {\n        '+failure('STACK_RESERVE', 'error')+'\n        return error;\n    }\n')
            changed = replace(changed, 'lsf_cleanup_stack_carve(stack)', 'lsf_cleanup_stack_carve(stack, observation)')
            changed = replace(changed, 'lsf_cleanup_existing_pte(start + i * PAGE_SIZE)',
                'lsf_cleanup_existing_pte_observed(start + i * PAGE_SIZE, observation, i)')
            changed = replace(changed, '            error = -EOPNOTSUPP;\n',
                '            error = -EOPNOTSUPP;\n            '+failure('PTE_NONEMPTY', 'error', 'i')+'\n')
            changed = replace(changed, '    if (lsf_cleanup_stack_unmap(stack)) {\n',
                '    if (lsf_cleanup_stack_unmap(stack)) {\n'
                '        lsf_cleanup_failure_unwind(observation, LSF_FAILURE_STACK_UNMAP);\n')
            changed = replace(changed, '    if (!lsf_factory_cleanup_stack_finish(source, stack))\n        return -EIO;\n',
                '    if (!lsf_factory_cleanup_stack_finish(source, stack)) {\n'
                '        lsf_cleanup_failure_unwind(observation, LSF_FAILURE_STACK_FINISH);\n'
                '        return -EIO;\n    }\n')
        editor.edit(body, changed)
    wrapper = '''
int lsf_prepaid_cleanup_stack_create(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    return lsf_prepaid_cleanup_stack_create_observed(source, task, NULL);
}
'''
    editor.edit(text[-len('#endif\n'):], '#endif\n'+wrapper)
    return editor.finish()


def constructor(text):
    editor = Editor(text)
    signature = 'struct task_struct *lsf_prepaid_cleanup_copy_process('
    old = function(editor.text, signature)
    body = Editor(old)
    body.edit('\tint pidfd = -1, retval;\n', '\tint pidfd = -1, retval;\n'
        '\tstruct lsf_cleanup_failure_observation observation = {0};\n'
        '\tunsigned int failure_site = LSF_FAILURE_ENTRY;\n\tint kthread_error;\n')
    body.edit('lsf_prepaid_cleanup_dup_initialized(source, node)',
        'lsf_prepaid_cleanup_dup_initialized_observed(source, node, &observation)')
    # Mark the exact attempted call/check. The original return value is never
    # assigned from an observer, including the pre-existing kthread errno issue.
    rules = (
        ('retval = -ERESTARTNOINTR;', 'SIGNAL'), ('retval = -ENOMEM;\n\tp =', 'DUP'),
        ('retval = lsf_prepaid_cleanup_copy_creds', 'CREDS'),
        ('retval = -EAGAIN;\n\tif (is_rlimit', 'RLIMIT'),
        ('retval = -EAGAIN;\n\tif (data_race', 'THREAD_LIMIT'),
        ('p->mempolicy = p->mempolicy ?', 'MPOL'), ('retval = sched_fork', 'SCHED'),
        ('retval = lsf_prepaid_cleanup_perf_event_init_task', 'PERF'),
        ('retval = perf_event_init_task', 'PERF'), ('retval = lsf_prepaid_cleanup_audit_alloc', 'AUDIT'),
        ('retval = audit_alloc', 'AUDIT'), ('retval = lsf_prepaid_cleanup_security_task_alloc', 'SECURITY'),
        ('retval = security_task_alloc', 'SECURITY'), ('retval = copy_semundo', 'SEMUNDO'),
        ('retval = copy_files', 'FILES'), ('retval = copy_fs', 'FS'),
        ('retval = lsf_cleanup_copy_sighand', 'SIGHAND'), ('retval = lsf_cleanup_copy_signal', 'SIGNAL_COPY'),
        ('retval = copy_mm', 'MM'), ('retval = copy_namespaces', 'NAMESPACES'),
        ('retval = lsf_prepaid_cleanup_copy_io', 'IO'), ('retval = copy_io', 'IO'),
        ('retval = copy_thread', 'ARCH_THREAD'), ('pid = lsf_prepaid_cleanup_alloc_pid', 'PID'),
        ('retval = __pidfd_prepare', 'PIDFD'), ('retval = put_user(pidfd', 'PIDFD_USER'),
        ('retval = lsf_prepaid_cleanup_cgroup_can_fork', 'CGROUP'),
        ('retval = cgroup_can_fork', 'CGROUP'), ('retval = sched_cgroup_fork', 'SCHED_CGROUP'),
        ('retval = lsf_prepaid_cleanup_constructor_prepare', 'CONSTRUCTOR_PREPARE'),
        ('retval = -ENOMEM;\n\t\tgoto bad_fork_core_free;', 'PID_NAMESPACE'),
        ('retval = -EINTR;', 'FATAL_SIGNAL'), ('retval = -EIO;', 'TASK_PUBLISH'),
    )
    for anchor, site in rules:
        pattern = re.compile(r'(?m)^([\t ]*)'+re.escape(anchor))
        matches = list(pattern.finditer(body.text))
        require(len(matches) == 1, 'constructor-failure-full-copy-site')
        match = matches[0]
        body.edit(match[0], match[1]+f'failure_site = LSF_FAILURE_{site};\n'+match[0])
    body.edit('\t\tif (lsf_prepaid_cleanup_kthread_prepare(source, p))\n'
        '\t\t\tgoto bad_fork_cleanup_delayacct;\n',
        '\t\tkthread_error = lsf_prepaid_cleanup_kthread_prepare(source, p);\n'
        '\t\tif (kthread_error) {\n\t\t\t'+failure('KTHREAD', 'kthread_error', observation='&observation')+
        '\n\t\t\tgoto bad_fork_cleanup_delayacct;\n\t\t}\n')
    # Direct pre-lock failures do not use fork_out's not-yet-initialized node.
    returns = list(re.finditer(r'(?m)^(\t+)return ERR_PTR\((-E[A-Z0-9]+)\);$', body.text))
    require(len(returns) == 9, 'constructor-failure-direct-return-membership')
    for ordinal, match in reversed(list(enumerate(returns, 1))):
        indent = match[1]
        new = (indent[:-1]+'{\n'+indent+failure('ENTRY', match[2], str(ordinal), '&observation')+
            '\n'+indent+'lsf_factory_cleanup_constructor_failure(&observation, '+match[2]+');\n'+
            match[0]+'\n'+indent[:-1]+'}')
        # Disjoint condition/return ranges retain every original guard byte.
        begin = returns[ordinal-2].end() if ordinal > 1 else 0
        chunk = body.text[begin:match.end()]
        body.edit(chunk, chunk[:match.start()-begin]+new)
    for call, site in (
        ('!lsf_factory_cleanup_task_abort_begin(source, p)', 'TASK_ABORT'),
        ('lsf_prepaid_cleanup_constructor_abort_stack(source, p)', 'STACK_ABORT')):
        body.edit(f'\tif ({call})\n\t\tgoto fork_out;\n',
            f'\tif ({call}) {{\n\t\tlsf_cleanup_failure_unwind(&observation, LSF_FAILURE_{site});\n'
            '\t\tgoto fork_out;\n\t}\n')
    body.edit('\tspin_unlock_irq(&current->sighand->siglock);\n\treturn ERR_PTR(retval);\n',
        '\tspin_unlock_irq(&current->sighand->siglock);\n'
        '\t'+failure('ENTRY', 'retval', 'failure_site', '&observation')+'\n'
        '\tlsf_factory_cleanup_constructor_failure(&observation, retval);\n'
        '\treturn ERR_PTR(retval);\n')
    # The active site is the site itself, not a detail; nested first failure wins.
    body.edit('lsf_cleanup_failure(&observation, LSF_FAILURE_ENTRY, failure_site, retval);',
        'lsf_cleanup_failure(&observation, failure_site, 0, retval);')
    editor.edit(old, body.finish())
    return editor.finish()


PRINTER = '''
/* Sole terminal printer: callers have finished original unwind and unlocked.
 * Numeric fields only; normal committed source keeps this predicate zero. */
void lsf_factory_cleanup_constructor_failure(
    const struct lsf_cleanup_failure_observation *observation, int returned)
{
    if (lsf_factory_constructor_qualification() && observation && observation->site)
        pr_info("LSFVM1 constructor-failure site=%u detail=%u origin=%d returned=%d unwind=%u\\n",
            observation->site, observation->detail, observation->origin, returned, observation->unwind);
}
'''


def transform(outputs):
    for name, (size, checksum) in PREIMAGES.items():
        require(name in outputs and type(outputs[name]) is bytes and len(outputs[name]) == size and
            hashlib.sha256(outputs[name]).hexdigest() == checksum,
            'constructor-failure-derived-preimage')
    result = dict(outputs)
    for name, operation in (
        ('include/net/lsf_stream_cleanup_stack.h', header),
        ('kernel/lsf-cleanup-lifecycle-task.c', duplicate),
        ('net/factory-cleanup-stack.c', reserve),
        ('mm/lsf-cleanup-stack.c', stack),
        ('kernel/lsf-cleanup-constructor.c', constructor)):
        result[name] = operation(outputs[name].decode()).encode()
    result['net/factory-cleanup-native-bootstrap.c'] += PRINTER.encode()
    require(set(result) == set(outputs) and
        {name for name in result if result[name] != outputs[name]} == set(PREIMAGES),
        'constructor-failure-only-six-derived-files')
    return result
