"""Uninstalled source for real per-recipient delivery/receive continuations.

Actual rmem accounting and SKB transfer/free points remain in their original
order. Notification failure is separate from successful queue transfer. This
is not installed-kernel, instrumentation or complete callback qualification.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_notifications as prior
from tools import host_stream_kernel_maintained as maintained

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_delivery.json'
NETLINK = 'net/netlink/af_netlink.c'
EXTRAS = {'kernel/capability.c', 'security/commoncap.c', 'include/linux/capability.h', 'include/net/scm.h'}
DEFINITIONS = {'netlink_broadcast_filtered', 'netlink_lock_table', 'netlink_unlock_table',
    'file_ns_capable', 'cap_capable', 'security_capable', 'cred_has_capability', 'selinux_capable',
    'scm_passec_enabled', '__scm_recv_common', 'scm_recv', 'scm_destroy_cred', 'scm_destroy',
    'security_secid_to_secctx', 'security_release_secctx',
    'selinux_secid_to_secctx', 'selinux_release_secctx'}
GATES = prior.GATES + ('actualSenderContinuationExecuted', 'actualReceiverContinuationExecuted',
    'completeScmCallbackClosure', 'completeRecipientCapabilityClosure')
replace = prior.replace
require = prior.require


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['schemaVersion'] == 'lsf.kernel-device-delivery-source.v1' and
        value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-delivery-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-delivery-whole-membership')
    require(set(value['sections']) == set(parent['sections']) | DEFINITIONS and
        all(value['sections'][name] == row for name, row in parent['sections'].items()),
        'device-delivery-definition-membership')
    require(all(value[name] is False for name in GATES), 'device-delivery-uninstalled')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'device-delivery-definition-occurrence')
    end = text.find('\n}\n', starts[0])
    require(end >= 0, 'device-delivery-definition-end')
    raw = text[starts[0]:end + 3]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'], 'device-delivery-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-delivery-whole-membership')
    maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name in DEFINITIONS:
        row = value['sections'][name]
        section(inputs[row['source']].decode(), name)


def private_sender(inputs):
    text = inputs[NETLINK].decode()
    guard = ('\tif (!sk || !lsf_factory_device_recipient_packet(source, sk, skb)) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n'
        '\t\t*notification_error = -EOPNOTSUPP;\n\t\treturn -EOPNOTSUPP;\n\t}\n')
    send = section(text, '__netlink_sendskb')
    send = replace(send, 'static int __netlink_sendskb(struct sock *sk, struct sk_buff *skb)',
        'static int lsf_prepaid_device_netlink_sendskb(struct lsf_device_registration_source source,\n'
        '\tstruct sock *sk, struct sk_buff *skb, int *notification_error)')
    send = replace(send, '\tint len = skb->len;\n', '\tint len;\n\n' + guard + '\tlen = skb->len;\n')
    send = replace(send, '\tsk->sk_data_ready(sk);\n',
        '\t/* Queue transfer is irrevocable: a receiver may have freed skb.\n'
        '\t * Neither notification failure nor this tail can inspect it. */\n'
        '\t*notification_error = lsf_prepaid_device_socket_notify(source, sk, false);\n')
    deliver = section(text, 'netlink_broadcast_deliver')
    deliver = replace(deliver, 'static int netlink_broadcast_deliver(struct sock *sk, struct sk_buff *skb)',
        'static int lsf_prepaid_device_broadcast_deliver(struct lsf_device_registration_source source,\n'
        '\tstruct sock *sk, struct sk_buff *skb, int *notification_error)')
    deliver = replace(deliver, '\tunsigned int rmem, rcvbuf;\n',
        '\tunsigned int rmem, rcvbuf;\n\n' + guard)
    deliver = replace(deliver, '\t\t__netlink_sendskb(sk, skb);\n',
        '\t\tif (lsf_prepaid_device_netlink_sendskb(source, sk, skb, notification_error) < 0)\n'
        '\t\t\treturn -1; /* Unknown pre-transfer state remains charged/quarantined. */\n')
    overrun = section(text, 'netlink_overrun')
    overrun = replace(overrun, 'static void netlink_overrun(struct sock *sk)',
        'static int lsf_prepaid_device_netlink_overrun(struct lsf_device_registration_source source, struct sock *sk)')
    overrun = replace(overrun, 'source, struct sock *sk)\n{\n',
        'source, struct sock *sk)\n{\n\tint error = 0;\n'
        '\tif (!sk || !lsf_factory_device_recipient_current(source, sk)) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
    overrun = replace(overrun, '\t\t\tsk_error_report(sk);\n',
        '\t\t\terror = lsf_prepaid_device_socket_notify(source, sk, true);\n')
    overrun = replace(overrun, '\tatomic_inc(&sk->sk_drops);\n',
        '\tatomic_inc(&sk->sk_drops);\n\treturn error;\n')
    one = section(text, 'do_one_broadcast')
    one = replace(one, 'static void do_one_broadcast(', 'static void lsf_prepaid_device_one_broadcast(')
    one = replace(one, '\tint val;\n', '\tint val, notification_error = 0;\n'
        '\tstruct lsf_device_registration_source source;\n')
    one = replace(one, '\tif (p->failure) {\n\t\tnetlink_overrun(sk);\n\t\treturn;\n\t}\n',
        '\t/* p->skb is still held by the real table-user broadcast extent.\n'
        '\t * Admit after namespace exclusions, BEFORE real LSM capability/audit. */\n'
        '\tif (lsf_factory_device_recipient_begin(p->skb, sk, &source) != 1) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\tp->delivery_failure = 1;\n\t\treturn;\n\t}\n'
        '\tif (p->failure) {\n'
        '\t\tif (lsf_prepaid_device_netlink_overrun(source, sk) < 0)\n'
        '\t\t\tp->delivery_failure = 1;\n'
        '\t\tif (lsf_factory_device_recipient_finish(source) != 1)\n'
        '\t\t\tp->delivery_failure = 1;\n\t\treturn;\n\t}\n')
    capability = ('\t\tif (!file_ns_capable(sk->sk_socket->file, p->net->user_ns,\n'
        '\t\t\t\t     CAP_NET_BROADCAST))\n\t\t\treturn;\n')
    one = replace(one, capability, '')
    marker = '\tif (p->failure) {\n'
    one = replace(one, marker,
        '\tif (!net_eq(sock_net(sk), p->net)) {\n'
        '\t\tval = lsf_prepaid_device_file_ns_capable(source, sk->sk_socket->file,\n'
        '\t\t\tp->net->user_ns, CAP_NET_BROADCAST);\n'
        '\t\tif (val) {\n\t\t\tif (val == -EOPNOTSUPP)\n'
        '\t\t\t\tp->delivery_failure = 1;\n\t\t\tgoto finish;\n\t\t}\n\t}\n' + marker)
    one = replace(one, '\t\tnetlink_overrun(sk);\n',
        '\t\tif (lsf_prepaid_device_netlink_overrun(source, sk) < 0)\n'
        '\t\t\tp->delivery_failure = 1;\n', 2)
    # The maintained uevent callers supply no TX callback. A private foreign
    # callback is refused before invocation, never treated as a filter drop.
    one = replace(one, '\tif (p->tx_filter && p->tx_filter(sk, p->skb2, p->tx_data)) {\n'
        '\t\tkfree_skb(p->skb2);\n\t\tp->skb2 = NULL;\n\t\tgoto out;\n\t}\n',
        '\tif (p->tx_filter) {\n\t\tlsf_factory_device_uevent_poison();\n'
        '\t\tp->delivery_failure = 1;\n\t\tgoto out;\n\t}\n')
    one = replace(one, '\tif (sk_filter(sk, p->skb2)) {\n',
        '\tval = sk_filter(sk, p->skb2);\n'
        '\tif (val == -EOPNOTSUPP) {\n\t\tlsf_factory_device_uevent_poison();\n'
        '\t\tp->delivery_failure = 1;\n\t\tgoto out;\n\t}\n\tif (val) {\n')
    one = replace(one, 'val = netlink_broadcast_deliver(sk, p->skb2);',
        'val = lsf_prepaid_device_broadcast_deliver(source, sk, p->skb2, &notification_error);')
    one = replace(one, 'out:\n\tsock_put(sk);\n',
        '\tif (notification_error < 0)\n\t\tp->delivery_failure = 1;\n'
        'out:\n\tsock_put(sk);\n'
        '\t/* No socket/SKB dereference follows the original sock_put. */\n'
        'finish:\n'
        '\tif (lsf_factory_device_recipient_finish(source) != 1)\n'
        '\t\tp->delivery_failure = 1;\n')
    outer = section(text, 'netlink_broadcast_filtered')
    outer = replace(outer, 'int netlink_broadcast_filtered(', 'int lsf_prepaid_device_broadcast_filtered(')
    outer = replace(outer, '\tstruct sock *sk;\n', '\tstruct sock *sk;\n'
        '\tstruct lsf_device_registration_source source;\n\n'
        '\tif (lsf_factory_device_uevent_birth(skb, LSF_DEVICE_UEVENT_KIND_SKB, &source) != 1 ||\n'
        '\t    !lsf_factory_device_uevent_current(source) || filter) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
    outer = replace(outer, 'do_one_broadcast(sk, &info);', 'lsf_prepaid_device_one_broadcast(sk, &info);')
    return send + '\n' + deliver + '\n' + overrun + '\n' + one + '\n' + outer


def private_capability(inputs):
    raw = section(inputs['kernel/capability.c'].decode(), 'file_ns_capable')
    raw = replace(raw, 'bool file_ns_capable(',
        'int lsf_prepaid_device_file_ns_capable(struct lsf_device_registration_source source, ')
    raw = replace(raw, '\n{\n', '\n{\n'
        '\tif (!file || cap != CAP_NET_BROADCAST ||\n'
        '\t    !lsf_factory_device_recipient_current(source, NULL)) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
    raw = replace(raw, '\t\treturn false;\n', '\t\treturn -EPERM;\n')
    raw = replace(raw, '\tif (security_capable(file->f_cred, ns, cap, CAP_OPT_NONE) == 0)\n'
        '\t\treturn true;\n\n\treturn false;\n',
        '\treturn lsf_prepaid_device_security_capable(source, file->f_cred, ns, cap, CAP_OPT_NONE);\n')
    return raw


def private_selinux_capability(inputs):
    text = inputs['security/selinux/hooks.c'].decode()
    raw = section(text, 'cred_has_capability')
    raw = replace(raw, 'static int cred_has_capability(',
        'static int lsf_prepaid_device_cred_has_capability(const struct lsf_factory_blob *source, ')
    raw = replace(raw, '\tstruct av_decision avd;\n', '')
    raw = replace(raw, '\tint rc;\n', '')
    raw = replace(raw, '\tu32 sid = cred_sid(cred);\n', '\tu32 sid;\n')
    raw = replace(raw, '\tu32 av = CAP_TO_MASK(cap);\n', '\tu32 av;\n')
    raw = replace(raw, '\tad.type = LSM_AUDIT_DATA_CAP;\n',
        '\tif (!source || !lsf_factory_blob_shape(*source) ||\n'
        '\t    source->domain != LSF_FACTORY_OWNER_DEVICE ||\n'
        '\t    source->device.kind != LSF_DEVICE_RECIPIENT_KIND_WORK ||\n'
        '\t    !lsf_factory_device_recipient_current(source->device, NULL) ||\n'
        '\t    !cred || cap != CAP_NET_BROADCAST || opts != CAP_OPT_NONE) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n'
        '\tsid = cred_sid(cred);\n\tav = CAP_TO_MASK(cap);\n\tad.type = LSM_AUDIT_DATA_CAP;\n')
    raw = replace(raw, '\trc = avc_has_perm_noaudit(sid, sid, sclass, av, 0, &avd);\n'
        '\tif (!(opts & CAP_OPT_NOAUDIT)) {\n'
        '\t\tint rc2 = avc_audit(sid, sid, sclass, av, &avd, rc, &ad);\n'
        '\t\tif (rc2)\n\t\t\treturn rc2;\n\t}\n\treturn rc;\n',
        '\t/* For this exact CAP_OPT_NONE, the maintained has_perm body\n'
        '\t * performs the same flags-zero noaudit + mandatory audit/result\n'
        '\t * sequence. No nonaudit option is silently widened. */\n'
        '\treturn lsf_prepaid_avc_has_perm(sid, sid, sclass, av, &ad, source);\n')
    outer = section(text, 'selinux_capable')
    outer = replace(outer, 'static int selinux_capable(',
        'int lsf_prepaid_device_selinux_capable(const struct lsf_factory_blob *source, ')
    outer = replace(outer, 'cred_has_capability(cred, cap, opts, ns == &init_user_ns)',
        'lsf_prepaid_device_cred_has_capability(source, cred, cap, opts, ns == &init_user_ns)')
    return raw + '\n' + outer + '''
bool lsf_prepaid_device_selinux_capable_hook(
    int (*candidate)(const struct cred *, struct user_namespace *, int, unsigned int))
{
    return candidate == selinux_capable;
}
'''


def private_security_capability():
    return '''int lsf_prepaid_device_security_capable(struct lsf_device_registration_source source,
    const struct cred *cred, struct user_namespace *ns, int cap, unsigned int opts)
{
    struct lsm_static_call *scall;
    struct lsf_factory_blob owner;
    int rc = LSM_RET_DEFAULT(capable);
    if (!cred || !ns || cap != CAP_NET_BROADCAST || opts != CAP_OPT_NONE ||
        lsf_factory_device_recipient_blob(source, &owner) != 1)
        return -EOPNOTSUPP;
    /* The immutable active hook list is preflighted BEFORE any callback.
     * Commoncap's original namespace/capability body remains real; SELinux
     * uses the same original PCI owner through mandatory audit and RCU. */
    lsm_for_each_hook(scall, capable) {
        if (scall->hl->hook.capable == cap_capable)
            continue;
#ifdef CONFIG_SECURITY_SELINUX
        if (lsf_prepaid_device_selinux_capable_hook(scall->hl->hook.capable))
            continue;
#endif
        lsf_factory_device_uevent_poison();
        return -EOPNOTSUPP;
    }
    lsm_for_each_hook(scall, capable) {
        if (scall->hl->hook.capable == cap_capable)
            rc = cap_capable(cred, ns, cap, opts);
#ifdef CONFIG_SECURITY_SELINUX
        else
            rc = lsf_prepaid_device_selinux_capable(&owner, cred, ns, cap, opts);
#endif
        if (rc != LSM_RET_DEFAULT(capable))
            break;
    }
    return rc;
}
'''


def private_scm(inputs):
    text = inputs['include/net/scm.h'].decode()
    raw = section(text, 'scm_passec_enabled')
    raw = replace(raw, 'static inline void scm_passec(',
        'static int lsf_prepaid_device_scm_passec(struct lsf_device_registration_source source, ')
    raw = replace(raw, 'security_secid_to_secctx(scm->secid, &secdata, &seclen)',
        'lsf_prepaid_device_security_secctx(source, scm->secid, &secdata, &seclen)')
    raw = replace(raw, '\t\t\tsecurity_release_secctx(secdata, seclen);\n',
        '\t\t\terr = lsf_prepaid_device_security_release_secctx(source, secdata, seclen);\n'
        '\t\t\tif (err)\n\t\t\t\treturn err;\n')
    raw = replace(raw, '\t\t}\n\t}\n}\n',
        '\t\t} else if (err == -EOPNOTSUPP) {\n'
        '\t\t\treturn err; /* A closed producer is not an optional label miss. */\n'
        '\t\t}\n\t}\n\treturn 0;\n}\n')
    common = section(text, '__scm_recv_common')
    common = replace(common, 'static inline bool __scm_recv_common(',
        'static int lsf_prepaid_device_scm_common(struct lsf_device_registration_source source, ')
    common = replace(common, '\n{\n', '\n{\n\tint result;\n'
        '\t/* netlink_recvmsg creates this exact zero cookie and copies only\n'
        '\t * credentials. Its private synchronous callees never write pid/fp.\n'
        '\t * This is not the UNIX PIDFD/file-receive path. */\n'
        '\tif (!scm || scm->pid || scm->fp || !sock || !msg ||\n'
        '\t    !lsf_factory_device_recipient_current(source, sock->sk)) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
    common = replace(common, '\tscm_passec(sock, msg, scm);\n',
        '\tresult = lsf_prepaid_device_scm_passec(source, sock, msg, scm);\n'
        '\tif (result < 0)\n\t\treturn result;\n')
    receive = section(text, 'scm_recv')
    receive = replace(receive, 'static inline void scm_recv(',
        'static int lsf_prepaid_device_scm_recv(struct lsf_device_registration_source source, ')
    receive = replace(receive, '\tif (!__scm_recv_common(sock, msg, scm, flags))\n\t\treturn;\n',
        '\tint result = lsf_prepaid_device_scm_common(source, sock, msg, scm, flags);\n'
        '\tif (result <= 0)\n\t\treturn result;\n')
    receive = replace(receive, '\tscm_destroy_cred(scm);\n', '\tscm_destroy_cred(scm);\n\treturn 0;\n')
    return ('#ifdef CONFIG_SECURITY_NETWORK\n' + raw + '\n#else\n'
        'static int lsf_prepaid_device_scm_passec(struct lsf_device_registration_source source,\n'
        '    struct socket *sock, struct msghdr *msg, struct scm_cookie *scm)\n'
        '{\n    return lsf_factory_device_recipient_current(source, sock->sk) ? 0 : -EOPNOTSUPP;\n}\n'
        '#endif\n\n' + common + '\n' + receive)


def private_receiver(inputs):
    text = inputs[NETLINK].decode()
    wake = section(text, 'netlink_rcv_wake')
    wake = replace(wake, 'static void netlink_rcv_wake(struct sock *sk)',
        'static int lsf_prepaid_device_netlink_rcv_wake(struct lsf_device_registration_source source, struct sock *sk)')
    wake = replace(wake, '\tstruct netlink_sock *nlk = nlk_sk(sk);\n',
        '\tstruct netlink_sock *nlk;\n\tint result = 0;\n'
        '\tif (!sk || !lsf_factory_device_recipient_current(source, sk)) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n'
        '\tnlk = nlk_sk(sk);\n')
    wake = replace(wake, '\t\twake_up_interruptible(&nlk->wait);\n',
        '\t\tresult = lsf_prepaid_device_wake(source, &nlk->wait, TASK_INTERRUPTIBLE, 1, 0, NULL);\n'
        '\treturn result < 0 ? result : 0;\n')
    raw = section(text, 'netlink_recvmsg')
    raw = replace(raw, 'static int netlink_recvmsg(', 'int lsf_prepaid_device_recvmsg_tail(')
    raw = replace(raw, '\t\t\t   int flags)', '\t\t\t   int flags, struct sk_buff *skb)')
    raw = replace(raw, '\tstruct sk_buff *skb, *data_skb;\n', '\tstruct sk_buff *data_skb;\n')
    raw = replace(raw, '\tint err, ret;\n', '\tint err, ret;\n'
        '\tstruct lsf_device_registration_source source;\n')
    raw = replace(raw, '\tskb = skb_recv_datagram(sk, flags, &err);\n'
        '\tif (skb == NULL)\n\t\tgoto out;\n',
        '\t/* The actual receive operation still holds this SKB. No skb_get:\n'
        '\t * its original rmem/free threshold remains visible below. */\n'
        '\tif (lsf_factory_device_recipient_begin(skb, sk, &source) != 1) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
    raw = replace(raw, '\t\tret = netlink_dump(sk, false);\n'
        '\t\tif (ret) {\n\t\t\tWRITE_ONCE(sk->sk_err, -ret);\n'
        '\t\t\tsk_error_report(sk);\n\t\t}\n',
        '\t\t/* The original condition is real, after the original SKB free.\n'
        '\t\t * Arbitrary dump callbacks have no admitted private producer.\n'
        '\t\t * Refuse BEFORE invocation and retain this original owner. */\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\terr = -EOPNOTSUPP;\n\t\tgoto out;\n')
    raw = replace(raw, '\tscm_recv(sock, msg, &scm, flags);\n',
        '\tret = lsf_prepaid_device_scm_recv(source, sock, msg, &scm, flags);\n'
        '\tif (ret < 0)\n\t\terr = ret;\n')
    raw = replace(raw, '\tnetlink_rcv_wake(sk);\n',
        '\tret = lsf_prepaid_device_netlink_rcv_wake(source, sk);\n'
        '\tif (ret < 0)\n\t\terr = ret;\n'
        '\t/* The independent WORK, never a freed packet lookup, owns this\n'
        '\t * last tail. All real callback/sighand/pool locks are released. */\n'
        '\tif (lsf_factory_device_recipient_finish(source) != 1)\n\t\terr = -EOPNOTSUPP;\n')
    return private_scm(inputs) + '\n' + wake + '\n' + raw


def private_selinux_secctx(inputs):
    text = inputs['security/selinux/hooks.c'].decode()
    get = section(text, 'selinux_secid_to_secctx')
    get = replace(get, 'static int selinux_secid_to_secctx(',
        'int lsf_prepaid_device_selinux_secctx(const struct lsf_factory_blob *source, ')
    guard = ('\tif (!source || !lsf_factory_blob_shape(*source) ||\n'
        '\t    source->domain != LSF_FACTORY_OWNER_DEVICE ||\n'
        '\t    source->device.kind != LSF_DEVICE_RECIPIENT_KIND_WORK ||\n'
        '\t    !lsf_factory_device_recipient_current(source->device, NULL)) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
    get = replace(get, '\n{\n', '\n{\n'
        '\tif (!secdata || !seclen) {\n\t\tlsf_factory_device_uevent_poison();\n'
        '\t\treturn -EOPNOTSUPP;\n\t}\n' + guard)
    get = replace(get, 'return security_sid_to_context(secid,\n\t\t\t\t       secdata, seclen);',
        'return lsf_prepaid_security_sid_to_context(secid, secdata, seclen, 0, source);')
    release = section(text, 'selinux_release_secctx')
    release = replace(release, 'static void selinux_release_secctx(',
        'int lsf_prepaid_device_selinux_release_secctx(const struct lsf_factory_blob *source, ')
    release = replace(release, '\tkfree(secdata);\n',
        '\tstruct lsf_factory_blob birth;\n' + guard +
        '\tif (!source || !secdata ||\n'
        '\t    lsf_factory_blob_lookup(secdata, LSF_PREPAID_AUDIT_STRING, &birth) != 1 ||\n'
        '\t    !lsf_factory_blob_same_owner(*source, birth)) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n'
        '\treturn lsf_prepaid_audit_string_return(secdata) == 1 ? 0 : -EOPNOTSUPP;\n')
    return get + '\n' + release + '''
bool lsf_prepaid_device_selinux_secctx_hook(int (*candidate)(u32, char **, u32 *))
{
    return candidate == selinux_secid_to_secctx;
}
bool lsf_prepaid_device_selinux_release_secctx_hook(void (*candidate)(char *, u32))
{
    return candidate == selinux_release_secctx;
}
'''


def private_security_secctx():
    return '''static int lsf_prepaid_device_security_secctx_hooks(void)
{
    struct lsm_static_call *scall;
    unsigned int gets = 0, releases = 0;
    lsm_for_each_hook(scall, secid_to_secctx) {
#ifdef CONFIG_SECURITY_SELINUX
        if (!lsf_prepaid_device_selinux_secctx_hook(scall->hl->hook.secid_to_secctx))
            return -EOPNOTSUPP;
        gets++;
#else
        return -EOPNOTSUPP;
#endif
    }
    lsm_for_each_hook(scall, release_secctx) {
#ifdef CONFIG_SECURITY_SELINUX
        if (!lsf_prepaid_device_selinux_release_secctx_hook(scall->hl->hook.release_secctx))
            return -EOPNOTSUPP;
        releases++;
#else
        return -EOPNOTSUPP;
#endif
    }
    return gets == 1 && releases == 1 ? 0 : -EOPNOTSUPP;
}
int lsf_prepaid_device_security_secctx(struct lsf_device_registration_source source,
    u32 secid, char **secdata, u32 *seclen)
{
    struct lsf_factory_blob owner;
    if (!secdata || !seclen || lsf_factory_device_recipient_blob(source, &owner) != 1 ||
        lsf_prepaid_device_security_secctx_hooks()) {
        lsf_factory_device_uevent_poison();
        return -EOPNOTSUPP;
    }
#ifdef CONFIG_SECURITY_SELINUX
    return lsf_prepaid_device_selinux_secctx(&owner, secid, secdata, seclen);
#else
    return -EOPNOTSUPP;
#endif
}
int lsf_prepaid_device_security_release_secctx(struct lsf_device_registration_source source,
    char *secdata, u32 seclen)
{
    struct lsf_factory_blob owner;
    if (lsf_factory_device_recipient_blob(source, &owner) != 1 ||
        lsf_prepaid_device_security_secctx_hooks()) {
        lsf_factory_device_uevent_poison();
        return -EOPNOTSUPP;
    }
#ifdef CONFIG_SECURITY_SELINUX
    return lsf_prepaid_device_selinux_release_secctx(&owner, secdata, seclen);
#else
    return -EOPNOTSUPP;
#endif
}
'''


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:
        outputs[name] = inputs[name]
    outputs['include/net/lsf_stream_device_delivery.h'] = (OWNED / 'device-delivery-private.h').read_bytes()
    text = outputs[NETLINK].decode()
    original = section(text, 'netlink_broadcast_filtered')
    wrapped = replace(original, '\tstruct sock *sk;\n',
        '\tstruct sock *sk;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tstruct lsf_device_registration_source source;\n'
        '\tint owned = lsf_factory_device_uevent_birth(skb, LSF_DEVICE_UEVENT_KIND_SKB, &source);\n'
        '\tif (owned)\n\t\treturn owned < 0 ? -EOPNOTSUPP :\n'
        '\t\t\tlsf_prepaid_device_broadcast_filtered(ssk, skb, portid, group, allocation, filter, filter_data);\n'
        '#endif\n')
    text = replace(text, original, wrapped)
    receive = section(text, 'netlink_recvmsg')
    wrapped = replace(receive, '\tint err, ret;\n', '\tint err, ret;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tstruct lsf_device_registration_source source;\n'
        '\tint owned;\n#endif\n')
    wrapped = replace(wrapped, '\tif (skb == NULL)\n\t\tgoto out;\n',
        '\tif (skb == NULL)\n\t\tgoto out;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\towned = lsf_factory_device_uevent_birth(skb, LSF_DEVICE_UEVENT_KIND_SKB, &source);\n'
        '\tif (owned)\n\t\treturn owned < 0 ? -EOPNOTSUPP :\n'
        '\t\t\tlsf_prepaid_device_recvmsg_tail(sock, msg, len, flags, skb);\n#endif\n')
    text = replace(text, receive, wrapped)
    text = replace(text, '#include <net/lsf_stream_device_uevent.h>\n',
        '#include <net/lsf_stream_device_uevent.h>\n#include <net/lsf_stream_device_delivery.h>\n')
    text += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-device-delivery.c"\n#endif\n'
    outputs[NETLINK] = text.encode()
    outputs['net/netlink/lsf-device-delivery.c'] = (private_sender(inputs) + '\n' + private_receiver(inputs)).encode()
    for name, output, body in [
        ('kernel/capability.c', 'kernel/lsf-device-delivery-capability.c', private_capability(inputs)),
        ('security/security.c', 'security/lsf-device-delivery-capability.c',
         private_security_capability() + '\n' + private_security_secctx()),
        ('security/selinux/hooks.c', 'security/selinux/lsf-device-delivery-capability.c',
         private_selinux_capability(inputs) + '\n' + private_selinux_secctx(inputs))]:
        outputs[name] += ('\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '#include <net/lsf_stream_device_delivery.h>\n#include "' +
            output.rsplit('/', 1)[1] + '"\n#endif\n').encode()
        outputs[output] = body.encode()
    return outputs
