/* SPDX-License-Identifier: GPL-2.0-only */
#include <net/lsf_stream_q35_msi_private.h>
int lsf_q35_msi_template_known(const struct msi_domain_template *template)
{
    return template == &pci_msix_template;
}
