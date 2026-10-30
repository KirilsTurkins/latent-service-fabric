/* SPDX-License-Identifier: GPL-2.0-only */
#include <net/lsf_stream_q35_msi_private.h>
int lsf_q35_x86_vector_known(const struct irq_domain *domain)
{
    return domain && domain == x86_vector_domain && domain->ops == &x86_vector_domain_ops;
}
