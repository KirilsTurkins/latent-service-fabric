/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplemental serialized audit policy, formatter, clock, queue and Linux
 * layout doubles. Actual private buffer/common/end and maintained SKB/factory
 * bodies execute; no Linux audit delivery or concurrency is claimed. */
#define LSF_AUDIT_SKB_REFERENCE_ENTRY audit_skb_reference_main
#include "audit-skb-reference.c"
#undef LSF_AUDIT_SKB_REFERENCE_ENTRY
#include <stdarg.h>

#define EIO 5
#define EINVAL 22
#define EAGAIN 11
#define AUDIT_BUFSIZ 1024
#define AUDIT_AVC 1400
#define NLMSG_HDRLEN 16u
#define __GFP_NOWARN 8u
#define AF_INET 2
#define LSM_AUDIT_DATA_NET 2
#define LSM_AUDIT_DATA_NONE 7
struct audit_context { unsigned int unused; };
struct audit_buffer { struct sk_buff *skb; struct audit_context *ctx; gfp_t gfp_mask; };
struct nlmsghdr { unsigned int nlmsg_len; };
struct sock { unsigned int sk_family; };
struct lsm_network_audit { unsigned int family; const struct sock *sk; };
struct selinux_audit_data;
struct common_audit_data { unsigned int type; union { struct lsm_network_audit *net; } u; struct selinux_audit_data *selinux_audit_data; };
static struct { struct sk_buff *items[16]; unsigned int count; } audit_queue;
static unsigned int rate_allowed, policy_suppressed, lost, woken, callbacks_order;
static int post_error, format_error;
static unsigned int context_calls, failed_context_call, trace_calls;
static unsigned int kauditd_wait;
static unsigned int nlmsg_total_size(unsigned int bytes) { return bytes + NLMSG_HDRLEN; }
static struct nlmsghdr *nlmsg_hdr(struct sk_buff *skb) { return (void *)skb->data; }
static struct nlmsghdr *nlmsg_put(struct sk_buff *skb, unsigned int pid, unsigned int sequence,
                                 int type, unsigned int length, unsigned int flags)
{
    (void)pid; (void)sequence; (void)type; (void)flags;
    skb_put(skb, NLMSG_HDRLEN + length); return nlmsg_hdr(skb);
}
static void kfree_skb(struct sk_buff *skb)
{ if (skb && --skb->users.count == 0) retire_skb(skb); }
static int audit_rate_check(void) { return (int)rate_allowed; }
static void audit_log_lost(const char *message) { (void)message; lost++; }
static void skb_queue_tail(void *queue, struct sk_buff *skb)
{ assert(queue == &audit_queue && audit_queue.count < 16); audit_queue.items[audit_queue.count++] = skb; }
static void wake_up_interruptible(void *wait) { assert(wait == &kauditd_wait); woken++; }
#include "audit-buffer-private.c"
#include "audit-end-derived-reference.h"
static struct audit_context *audit_context(void) { return NULL; }
static struct audit_buffer *lsf_prepaid_audit_log_start(struct audit_context *context,
    gfp_t priority, int type, const struct lsf_factory_blob *source, int *error)
{
    *error = 0;
    if (policy_suppressed)
        return NULL;
    struct audit_buffer *buffer = lsf_prepaid_audit_buffer_alloc(context, priority, type, source);
    if (!buffer) *error = -ENOMEM;
    return buffer;
}
static void dump_common_audit_data(struct audit_buffer *buffer, struct common_audit_data *data)
{
    (void)data; callbacks_order = callbacks_order * 10 + 2;
    if (format_error) lsf_prepaid_audit_error(buffer, format_error);
}
#include "lsm-audit-private.c"
static void pre_callback(struct audit_buffer *buffer, void *data)
{ (void)buffer; (void)data; callbacks_order = callbacks_order * 10 + 1; }
static int post_callback(struct audit_buffer *buffer, void *data, const struct lsf_factory_blob *source)
{ (void)buffer; (void)data; assert(source == &parent); callbacks_order = callbacks_order * 10 + 3; return post_error; }
struct av_decision { u32 allowed, auditallow, auditdeny; };
struct selinux_audit_data { u32 ssid, tsid, requested, audited, denied; u16 tclass; int result; };
/* The maintained class map includes its terminal sentinel; class 1 must be
 * strictly below ARRAY_SIZE just as in the actual slow audit guard. */
static const struct { const char *name; const char *perms[32]; } secclass_map[] = {
    {"socket", {"connect"}}, {NULL, {NULL}}
};
#define ARRAY_SIZE(value) (sizeof(value)/sizeof((value)[0]))
#define WARN_ON(value) (value)
#define likely(value) (value)
#define noinline __attribute__((noinline))
static void audit_log_format(struct audit_buffer *buffer, const char *format, ...)
{ (void)buffer; (void)format; }
static void audit_log_n_untrustedstring(struct audit_buffer *buffer, const char *text, u32 bytes)
{ (void)buffer; assert(text && bytes); }
/* The policy/context conversion is a labeled test double. The actual post
 * callback still reserves/returns real private string births and propagates
 * the exact producer failure rather than swallowing it as a numeric fallback. */
static int lsf_prepaid_security_sid_to_context(u32 sid, char **text, u32 *bytes,
                                              int invalid, const struct lsf_factory_blob *source)
{
    (void)sid; (void)invalid; context_calls++; *text = NULL; *bytes = 0;
    if (context_calls == failed_context_call) return -ENOMEM;
    *text = lsf_factory_child_allocate(*source, 4, LSF_PREPAID_AUDIT_STRING);
    if (!*text) return -ENOMEM;
    memcpy(*text, "ctx", 4); *bytes = 4; return 0;
}
static void trace_selinux_audited(const struct selinux_audit_data *data,
                                 const char *source, const char *target, const char *class_name)
{
    struct lsf_factory_blob birth;
    assert(data && class_name);
    if (source) assert(lsf_factory_blob_lookup(source, LSF_PREPAID_AUDIT_STRING, &birth) == 1);
    if (target) assert(lsf_factory_blob_lookup(target, LSF_PREPAID_AUDIT_STRING, &birth) == 1);
    trace_calls++;
}
#include "avc-audit-derived-reference.h"
static void mandatory_reset(void)
{
    audit_reset(); audit_queue.count = 0; rate_allowed = 1; policy_suppressed = lost = woken = callbacks_order = 0;
    post_error = format_error = 0;
    context_calls = failed_context_call = trace_calls = 0;
}
static void mandatory_observed(const char *label)
{ lsf_ref_write("AUDIT_CONTROL ", 14); lsf_ref_write(label, lsf_ref_length(label)); lsf_ref_write(" PASS\n", 6); }
int main(void)
{
    struct audit_buffer *buffer;
    struct lsf_prepaid_context *owner;
    struct common_audit_data data = {.type = LSM_AUDIT_DATA_NONE};
    assert(audit_skb_reference_main() == 0);
    mandatory_reset(); owner = &factory.pool.contexts[0];
    buffer = lsf_prepaid_audit_buffer_alloc(NULL, GFP_ATOMIC, AUDIT_AVC, &parent);
    assert(buffer && owner->live == 4 && !heap_count);
    assert(lsf_prepaid_audit_log_end(buffer, 0) == 0);
    assert(audit_queue.count == 1 && woken == 1 && owner->live == 3);
    mandatory_observed("real-audit-end-queues-complete-skb-without-refunding-header-or-head");
    owner->closed = 1; factory.pool.stopped = 1;
    assert(lsf_prepaid_return(&factory.pool, parent.context->key, parent.ticket));
    assert(!lsf_prepaid_recycle(&factory.pool, parent.context->key));
    kfree_skb(audit_queue.items[0]); assert(owner->live == 0);
    assert(lsf_prepaid_recycle(&factory.pool, parent.context->key));
    mandatory_observed("queued-audit-outlives-formatter-and-root-until-real-selected-final-free");
    mandatory_reset(); owner = &factory.pool.contexts[0];
    buffer = lsf_prepaid_audit_buffer_alloc(NULL, GFP_ATOMIC, AUDIT_AVC, &parent); assert(buffer);
    lsf_prepaid_audit_error(buffer, -ENOMEM);
    assert(lsf_prepaid_audit_log_end(buffer, 0) == -ENOMEM);
    assert(owner->live == 1 && !audit_queue.count && !woken);
    mandatory_observed("formatter-expansion-failure-cannot-queue-truncated-success");
    mandatory_reset(); owner = &factory.pool.contexts[0];
    buffer = lsf_prepaid_audit_buffer_alloc(NULL, GFP_ATOMIC, AUDIT_AVC, &parent); assert(buffer);
    assert(lsf_prepaid_audit_log_end(buffer, -EOPNOTSUPP) == -EOPNOTSUPP);
    assert(owner->live == 1 && !audit_queue.count && !woken);
    mandatory_observed("context-callback-closed-error-discards-partial-record");
    mandatory_reset(); owner = &factory.pool.contexts[0]; rate_allowed = 0;
    buffer = lsf_prepaid_audit_buffer_alloc(NULL, GFP_ATOMIC, AUDIT_AVC, &parent); assert(buffer);
    assert(lsf_prepaid_audit_log_end(buffer, 0) == -EAGAIN);
    assert(owner->live == 1 && lost == 1 && !audit_queue.count && !woken);
    mandatory_observed("original-rate-policy-refusal-is-explicit-closed-error");
    mandatory_reset(); owner = &factory.pool.contexts[0];
    owner->cursor = LSF_TCP_BYTES - SKB_ALIGN(sizeof(struct lsf_prepaid_audit_envelope));
    assert(!lsf_prepaid_audit_buffer_alloc(NULL, GFP_ATOMIC, AUDIT_AVC, &parent));
    assert(owner->live == 1 && !heap_count && !audit_queue.count);
    mandatory_observed("nested-skb-refusal-retires-unpublished-formatter-without-fallback");
    mandatory_reset(); owner = &factory.pool.contexts[0];
    assert(lsf_prepaid_common_lsm_audit(&data, pre_callback, post_callback, &parent) == 0);
    assert(callbacks_order == 123 && audit_queue.count == 1 && owner->live == 3);
    kfree_skb(audit_queue.items[0]); assert(owner->live == 1);
    mandatory_observed("common-audit-preserves-real-pre-common-post-order-before-queue");
    mandatory_reset(); owner = &factory.pool.contexts[0]; format_error = -ENOMEM;
    assert(lsf_prepaid_common_lsm_audit(&data, pre_callback, post_callback, &parent) == -ENOMEM);
    assert(callbacks_order == 123 && !audit_queue.count && owner->live == 1);
    mandatory_observed("void-common-formatter-error-remains-visible-to-permission-caller");
    mandatory_reset(); owner = &factory.pool.contexts[0]; post_error = -EOPNOTSUPP;
    assert(lsf_prepaid_common_lsm_audit(&data, pre_callback, post_callback, &parent) == -EOPNOTSUPP);
    assert(callbacks_order == 123 && !audit_queue.count && owner->live == 1);
    mandatory_observed("post-callback-failure-is-not-mandatory-audit-success");
    mandatory_reset(); owner = &factory.pool.contexts[0]; policy_suppressed = 1;
    assert(lsf_prepaid_common_lsm_audit(&data, pre_callback, post_callback, &parent) == 0);
    assert(!callbacks_order && !audit_queue.count && owner->live == 1);
    mandatory_observed("original-policy-suppression-does-not-manufacture-an-audit-record");
    mandatory_reset(); owner = &factory.pool.contexts[0]; data.type = 1;
    assert(lsf_prepaid_common_lsm_audit(&data, pre_callback, post_callback, &parent) == -EOPNOTSUPP);
    assert(!callbacks_order && !audit_queue.count && owner->live == 1);
    mandatory_observed("unsupported-path-format-refuses-before-any-allocation-or-callback");
    mandatory_reset(); owner = &factory.pool.contexts[0];
    struct av_decision decision = {1, 0, 0}; data.type = LSM_AUDIT_DATA_NONE;
    assert(lsf_prepaid_avc_audit(1, 2, 1, 1, &decision, 0, &data, &parent) == 0);
    assert(!context_calls && !trace_calls && !audit_queue.count && owner->live == 1);
    mandatory_observed("actual-original-audit-selection-preserves-policy-no-audit-case");
    mandatory_reset(); owner = &factory.pool.contexts[0]; decision.auditallow = 1;
    assert(lsf_prepaid_avc_audit(1, 2, 1, 1, &decision, 0, &data, &parent) == 0);
    assert(context_calls == 4 && trace_calls == 1 && audit_queue.count == 1 && owner->live == 3);
    kfree_skb(audit_queue.items[0]); assert(owner->live == 1);
    mandatory_observed("actual-avc-callbacks-retain-trace-and-return-normal-plus-invalid-context-births");
    mandatory_reset(); owner = &factory.pool.contexts[0]; failed_context_call = 1;
    assert(lsf_prepaid_avc_audit(1, 2, 1, 1, &decision, 0, &data, &parent) == -ENOMEM);
    assert(context_calls == 4 && trace_calls == 1 && !audit_queue.count && owner->live == 1);
    mandatory_observed("context-allocation-failure-cannot-become-numeric-fallback-success");
    mandatory_reset(); owner = &factory.pool.contexts[0]; failed_context_call = 3;
    assert(lsf_prepaid_avc_audit(1, 2, 1, 1, &decision, 0, &data, &parent) == -ENOMEM);
    assert(context_calls == 4 && trace_calls == 1 && !audit_queue.count && owner->live == 1);
    mandatory_observed("invalid-context-allocation-failure-remains-closed-after-trace");
    mandatory_reset(); owner = &factory.pool.contexts[0];
    assert(lsf_prepaid_avc_audit(1, 2, 1, 1, &decision, 0, &data, NULL) == -EOPNOTSUPP);
    assert(!context_calls && !audit_queue.count && owner->live == 1);
    mandatory_observed("missing-original-source-refuses-even-when-policy-might-not-audit");
    mandatory_reset(); owner = &factory.pool.contexts[0]; decision = (struct av_decision){0,0,0};
    assert(lsf_prepaid_avc_audit(1, 2, 1, 1, &decision, -13, &data, &parent) == 0);
    assert(!context_calls && !audit_queue.count && owner->live == 1);
    mandatory_observed("actual-dontaudit-decision-does-not-invent-a-record-or-override-permission-result");
    mandatory_reset(); owner = &factory.pool.contexts[0]; decision = (struct av_decision){1,1,0};
    assert(lsf_prepaid_avc_audit(1, 2, 0, 1, &decision, 0, &data, &parent) == -EINVAL);
    assert(!context_calls && !audit_queue.count && owner->live == 1);
    mandatory_observed("original-invalid-security-class-refuses-before-audit-buffer");
    assert(!heap_count && !heap_returns);
    return 0;
}
