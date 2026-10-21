/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in glue.c after the original find_child_walk_data and callbacks.
 * The real upstream ACPI/device child iterator keeps its own reference rules.
 * Caller holds the original scan AND deletion mutexes. */
struct lsf_acpi_child_walk {
    struct find_child_walk_data original;
    struct pci_dev *consumer;
    int error;
};

static int lsf_prepaid_check_one_child(struct acpi_device *adev, void *data)
{
    struct lsf_acpi_child_walk *owned = data;
    struct find_child_walk_data *wd = &owned->original;

    if (!adev->pnp.type.bus_address || acpi_device_adr(adev) != wd->address)
        return 0;
    if (!wd->adev) {
        owned->error = lsf_prepaid_acpi_reference(owned->consumer, adev);
        if (owned->error)
            return 1;
        wd->adev = adev;
        return 0;
    }
    /* Original ambiguity scoring executes AML _STA, which can allocate.
     * Do not skip that policy and report no companion: reject this profile. */
    owned->error = -EOPNOTSUPP;
    return 1;
}

int lsf_prepaid_acpi_find_child_device(struct pci_dev *consumer,
                                      struct acpi_device *parent,
                                      unsigned long long address,
                                      bool check_children,
                                      struct acpi_device **result)
{
    struct lsf_acpi_child_walk owned = {
        .consumer = consumer,
        .original = {
            .address = address,
            .check_children = check_children,
            .check_sta = true,
            .adev = NULL,
            .score = 0,
        },
    };
    int walked = 0;

    /* The fixed modern-net profile does not claim ACPI bridge scoring. */
    if (check_children)
        return -EOPNOTSUPP;
    if (parent)
        walked = lsf_prepaid_acpi_dev_for_each_child(parent, lsf_prepaid_check_one_child, &owned);
    if (owned.error)
        return owned.error;
    if (walked)
        return -EOPNOTSUPP;
    *result = owned.original.adev;
    return 0;
}
