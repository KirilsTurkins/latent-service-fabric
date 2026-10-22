"""Uninstalled real wait callback source; epoll/instrumentation remain open.

The original application and ordinary kernel functions are not replaced.
Private callback identities are checked in the original waitqueue lock extent;
unknown callbacks poison/retain before their unclosed invocation. This prefix
does not yet wire the netlink sender or independent receiver continuation.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_security as prior
from tools import host_stream_kernel_maintained as maintained

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_notifications.json'
EXTRAS = {'kernel/sched/wait.c', 'kernel/sched/core.c', 'fs/select.c', 'fs/eventpoll.c', 'include/linux/wait.h'}
DEFINITIONS = {'__wake_up_common', '__wake_up_common_lock', '__wake_up_sync_key', 'autoremove_wake_function',
    '__pollwake', 'pollwake', 'default_wake_function', 'ep_poll_callback',
    'ep_poll_safewake_debug', 'ep_poll_safewake_normal', 'ep_pm_stay_awake_rcu',
    'sock_def_readable', 'sock_def_error_report'}
GATES = prior.GATES + ('actualOwnedWaitExecuted', 'completeWaitCallbackSet',
    'actualEpollNotificationExecuted', 'instrumentationAdmissionQualified')
replace = prior.replace
require = prior.require


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['schemaVersion'] == 'lsf.kernel-device-notifications-source.v1' and
        value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-notifications-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-notifications-whole-membership')
    require(set(value['sections']) == set(parent['sections']) | DEFINITIONS and
        all(value['sections'][name] == row for name, row in parent['sections'].items()),
        'device-notifications-definitions')
    require(all(value[name] is False for name in GATES), 'device-notifications-uninstalled')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'device-notifications-definition-occurrence')
    end = text.find('\n}\n', starts[0])
    require(end >= 0, 'device-notifications-definition-end')
    raw = text[starts[0]:end + 3]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'], 'device-notifications-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-notifications-whole-membership')
    maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name in DEFINITIONS:
        row = value['sections'][name]
        section(inputs[row['source']].decode(), name)


def private_poll(inputs):
    text = inputs['fs/select.c'].decode()
    inner = section(text, '__pollwake')
    inner = replace(inner, 'static int __pollwake(', 'static int lsf_prepaid_device_pollwake_inner(')
    outer = section(text, 'pollwake')
    outer = replace(outer, 'static int pollwake(',
        'int lsf_prepaid_device_pollwake(struct lsf_device_registration_source source, ')
    outer = replace(outer, '\tstruct poll_table_entry *entry;\n',
        '\tstruct poll_table_entry *entry;\n\n'
        '\t/* The real waitqueue lock still protects this entry/function. */\n'
        '\tif (!lsf_factory_device_recipient_current(source, NULL))\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '\tif (wait->func != pollwake) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
    outer = replace(outer, '__pollwake(wait, mode, sync, key)',
        'lsf_prepaid_device_pollwake_inner(wait, mode, sync, key)')
    return inner + '\n' + outer + '''
bool lsf_prepaid_device_pollwake_matches(wait_queue_func_t candidate)
{
    return candidate == pollwake;
}
'''


def private_wait(inputs):
    text = inputs['kernel/sched/wait.c'].decode()
    common = section(text, '__wake_up_common')
    common = replace(common, 'static int __wake_up_common(',
        'static int lsf_prepaid_device_wake_common(struct lsf_device_registration_source source, ')
    common = replace(common, 'int nr_exclusive, int wake_flags, void *key)',
        'int nr_exclusive, int wake_flags, void *key, int *error)')
    # No registration can change this list/function cohort between preflight
    # and callback: the actual original waitqueue lock stays held throughout.
    common = replace(common, '\tlockdep_assert_held(&wq_head->lock);\n',
        '\tlockdep_assert_held(&wq_head->lock);\n\n'
        '\tif (!lsf_factory_device_recipient_current(source, NULL)) {\n'
        '\t\t*error = -EOPNOTSUPP;\n\t\treturn nr_exclusive;\n\t}\n'
        '\tlist_for_each_entry(curr, &wq_head->head, entry) {\n'
        '\t\tif (curr->func != default_wake_function &&\n'
        '\t\t    curr->func != autoremove_wake_function &&\n'
        '\t\t    !lsf_prepaid_device_pollwake_matches(curr->func)\n'
        '#ifdef CONFIG_EPOLL\n'
        '\t\t    && !lsf_prepaid_device_epoll_matches(curr->func)\n#endif\n'
        '\t\t   ) {\n'
        '\t\t\tlsf_factory_device_uevent_poison();\n'
        '\t\t\t*error = -EOPNOTSUPP;\n\t\t\treturn nr_exclusive;\n\t\t}\n\t}\n')
    common = replace(common, '\t\tret = curr->func(curr, mode, wake_flags, key);\n',
        '\t\tif (lsf_prepaid_device_pollwake_matches(curr->func))\n'
        '\t\t\tret = lsf_prepaid_device_pollwake(source, curr, mode, wake_flags, key);\n'
        '#ifdef CONFIG_EPOLL\n'
        '\t\telse if (lsf_prepaid_device_epoll_matches(curr->func))\n'
        '\t\t\tret = lsf_prepaid_device_epoll_callback(source, curr, mode, wake_flags, key);\n#endif\n'
        '\t\telse\n\t\t\tret = curr->func(curr, mode, wake_flags, key);\n')
    common = replace(common, '\t\tif (ret < 0)\n\t\t\tbreak;\n',
        '\t\tif (ret < 0) {\n\t\t\t*error = ret;\n\t\t\tbreak;\n\t\t}\n')
    lock = section(text, '__wake_up_common_lock')
    lock = replace(lock, 'static int __wake_up_common_lock(',
        'int lsf_prepaid_device_wake(struct lsf_device_registration_source source, ')
    lock = replace(lock, '\tint remaining;\n', '\tint remaining;\n\tint error = 0;\n\n'
        '\tif (!wq_head || !lsf_factory_device_recipient_current(source, NULL)) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
    lock = replace(lock, '__wake_up_common(wq_head, mode, nr_exclusive, wake_flags,\n\t\t\tkey)',
        'lsf_prepaid_device_wake_common(source, wq_head, mode, nr_exclusive, wake_flags,\n\t\t\tkey, &error)')
    lock = replace(lock, '\treturn nr_exclusive - remaining;\n',
        '\treturn error ? error : nr_exclusive - remaining;\n')
    return common + '\n' + lock + '''
int lsf_prepaid_device_wake_sync(struct lsf_device_registration_source source,
    struct wait_queue_head *head, unsigned int mode, void *key)
{
    return lsf_prepaid_device_wake(source, head, mode, 1, WF_SYNC, key);
}

int lsf_prepaid_device_wake_locked(struct lsf_device_registration_source source,
    struct wait_queue_head *head, unsigned int mode, int exclusive, int flags, void *key)
{
    int error = 0, remaining;
    if (!head || !lsf_factory_device_recipient_current(source, NULL)) {
        lsf_factory_device_uevent_poison();
        return -EOPNOTSUPP;
    }
    lockdep_assert_held(&head->lock);
    remaining = lsf_prepaid_device_wake_common(source, head, mode, exclusive, flags, key, &error);
    return error ? error : exclusive - remaining;
}
'''


def private_epoll(inputs):
    text = inputs['fs/eventpoll.c'].decode()
    safewakes = []
    for variant in ('debug', 'normal'):
        raw = section(text, 'ep_poll_safewake_' + variant)
        declaration, body = raw.split('\n{\n', 1)
        declaration = replace(declaration, 'static void ep_poll_safewake(',
            'static void lsf_prepaid_device_epoll_safewake(struct lsf_device_registration_source source, ')
        closing = declaration.rfind(')')
        declaration = declaration[:closing] + ', int *error' + declaration[closing:]
        guard = ('\tif (!lsf_factory_device_recipient_current(source, NULL)) {\n'
            '\t\t*error = -EOPNOTSUPP;\n\t\treturn;\n\t}\n')
        if variant == 'debug':
            body = replace(body, '\tu8 nests = 0;\n', '\tu8 nests = 0;\n\tint result;\n\n' + guard)
            body = replace(body, '\twake_up_locked_poll(&ep->poll_wait, EPOLLIN | pollflags);\n',
                '\tresult = lsf_prepaid_device_wake_locked(source, &ep->poll_wait,\n'
                '\t\tTASK_NORMAL, 1, 0, poll_to_key(EPOLLIN | pollflags));\n')
            body = replace(body, '\tspin_unlock_irqrestore(&ep->poll_wait.lock, flags);\n',
                '\tspin_unlock_irqrestore(&ep->poll_wait.lock, flags);\n'
                '\tif (result < 0)\n\t\t*error = result;\n')
        else:
            body = '\tint result;\n' + guard + replace(body,
                '\twake_up_poll(&ep->poll_wait, EPOLLIN | pollflags);\n',
                '\tresult = lsf_prepaid_device_wake(source, &ep->poll_wait,\n'
                '\t\tTASK_NORMAL, 1, 0, poll_to_key(EPOLLIN | pollflags));\n'
                '\tif (result < 0)\n\t\t*error = result;\n')
        safewakes.append(declaration + '\n{\n' + body)
    raw = section(text, 'ep_poll_callback')
    raw = replace(raw, 'static int ep_poll_callback(',
        'int lsf_prepaid_device_epoll_callback(struct lsf_device_registration_source source, ')
    raw = replace(raw, '\tstruct epitem *epi = ep_item_from_wait(wait);\n', '\tstruct epitem *epi;\n')
    raw = replace(raw, '\tstruct eventpoll *ep = epi->ep;\n', '\tstruct eventpoll *ep;\n')
    raw = replace(raw, '\tint ewake = 0;\n', '\tint ewake = 0;\n\tint error = 0;\n\n'
        '\tif (!lsf_factory_device_recipient_current(source, NULL))\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '\tif (wait->func != ep_poll_callback) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n'
        '\tepi = ep_item_from_wait(wait);\n\tep = epi->ep;\n')
    raw = replace(raw, '\t\t\twake_up_sync(&ep->wq);\n',
        '\t\t\terror = lsf_prepaid_device_wake_sync(source, &ep->wq, TASK_NORMAL, NULL);\n')
    raw = replace(raw, '\t\t\twake_up(&ep->wq);\n',
        '\t\t\terror = lsf_prepaid_device_wake(source, &ep->wq, TASK_NORMAL, 1, 0, NULL);\n')
    raw = replace(raw, 'ep_poll_safewake(ep, epi, pollflags & EPOLL_URING_WAKE)',
        'lsf_prepaid_device_epoll_safewake(source, ep, epi, pollflags & EPOLL_URING_WAKE, &error)')
    # Retain the actual POLLFREE unlink/whead invalidation even on a poisoned
    # descendant. A refusal must not leave a dangling normal wait entry.
    raw = replace(raw, '\treturn ewake;\n', '\treturn error < 0 ? error : ewake;\n')
    return ('#ifdef CONFIG_DEBUG_LOCK_ALLOC\n' + safewakes[0] + '\n#else\n' + safewakes[1] +
        '\n#endif\n\n' + raw + '''
bool lsf_prepaid_device_epoll_matches(wait_queue_func_t candidate)
{
    return candidate == ep_poll_callback;
}
''')


def private_socket_notifications(inputs):
    text = inputs['net/core/sock.c'].decode()
    pieces = []
    for name, private in [('sock_def_readable', 'lsf_prepaid_device_sock_readable'),
                          ('sock_def_error_report', 'lsf_prepaid_device_sock_error')]:
        raw = section(text, name)
        signature = ('static void ' if name == 'sock_def_error_report' else 'void ') + name + '('
        raw = replace(raw, signature, 'static int ' + private + '(struct lsf_device_registration_source source, ')
        raw = replace(raw, '\tstruct socket_wq *wq;\n',
            '\tstruct socket_wq *wq;\n\tint result = 0;\n\n'
            '\tif (!sk || !lsf_factory_device_recipient_current(source, sk)) {\n'
            '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
        if name == 'sock_def_readable':
            raw = replace(raw, '\t\twake_up_interruptible_sync_poll(&wq->wait, EPOLLIN | EPOLLPRI |\n'
                '\t\t\t\t\t\tEPOLLRDNORM | EPOLLRDBAND);\n',
                '\t\tresult = lsf_prepaid_device_wake_sync(source, &wq->wait, TASK_INTERRUPTIBLE,\n'
                '\t\t\tpoll_to_key(EPOLLIN | EPOLLPRI | EPOLLRDNORM | EPOLLRDBAND));\n')
        else:
            raw = replace(raw, '\t\twake_up_interruptible_poll(&wq->wait, EPOLLERR);\n',
                '\t\tresult = lsf_prepaid_device_wake(source, &wq->wait, TASK_INTERRUPTIBLE,\n'
                '\t\t\t1, 0, poll_to_key(EPOLLERR));\n')
        raw = replace(raw, '\tsk_wake_async_rcu(sk,', '\tlsf_prepaid_device_sk_wake_async_rcu(source, sk,')
        raw = replace(raw, '\trcu_read_unlock();\n', '\trcu_read_unlock();\n'
            '\treturn result < 0 ? result :\n'
            '\t\t(lsf_factory_device_recipient_current(source, sk) ? 0 : -EOPNOTSUPP);\n')
        pieces.append(raw)
    return '\n'.join(pieces) + '''
int lsf_prepaid_device_socket_notify(struct lsf_device_registration_source source,
    struct sock *sk, bool error_report)
{
    void (*callback)(struct sock *);
    if (!sk || !lsf_factory_device_recipient_current(source, sk)) {
        lsf_factory_device_uevent_poison();
        return -EOPNOTSUPP;
    }
    /* One original callback-load snapshot, not an address registration. A
     * concurrent replacement does not change the function already selected
     * for this invocation. Only the exact maintained default body is copied. */
    if (error_report) {
        callback = READ_ONCE(sk->sk_error_report);
        if (callback == sock_def_error_report)
            return lsf_prepaid_device_sock_error(source, sk);
    } else {
        callback = READ_ONCE(sk->sk_data_ready);
        if (callback == sock_def_readable)
            return lsf_prepaid_device_sock_readable(source, sk);
    }
    lsf_factory_device_uevent_poison();
    return -EOPNOTSUPP;
}
'''


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:
        outputs[name] = inputs[name]
    outputs['include/net/lsf_stream_device_notification.h'] = (
        OWNED / 'device-notification-private.h').read_bytes()
    outputs['net/factory-device-notifications.c'] = (OWNED / 'factory-device-notifications.c').read_bytes()
    outputs['net/factory.c'] = replace(outputs['net/factory.c'].decode(),
        '#include "factory-device-security.c"\n',
        '#include "factory-device-security.c"\n#include "factory-device-notifications.c"\n').encode()
    for name, output, raw in [('kernel/sched/wait.c', 'kernel/sched/lsf-device-notification-wait.c', private_wait(inputs)),
                              ('fs/select.c', 'fs/lsf-device-notification-poll.c', private_poll(inputs)),
                              ('fs/eventpoll.c', 'fs/lsf-device-notification-epoll.c', private_epoll(inputs)),
                              ('net/core/sock.c', 'net/core/lsf-device-notification-sock.c', private_socket_notifications(inputs))]:
        outputs[name] += ('\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '#include <net/lsf_stream_device_notification.h>\n#include "' +
            output.rsplit('/', 1)[1] + '"\n#endif\n').encode()
        outputs[output] = raw.encode()
    return outputs
