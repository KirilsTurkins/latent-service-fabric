/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in bus.c AFTER its actual acpi_dev_walk_context/type adapter.
 * Count BEFORE the original adapter filters non-ACPI children, so an arbitrary
 * population of ordinary child devices cannot bypass the finite walk bound.
 * Original device_for_each_child retains all klist/reference/exit semantics. */
struct lsf_acpi_bounded_walk {
    struct acpi_dev_walk_context original;
    unsigned int visited;
};

static int lsf_prepaid_acpi_dev_for_one_check(struct device *dev, void *context)
{
    struct lsf_acpi_bounded_walk *owned = context;

    if (++owned->visited > LSF_DEVICE_ACPI_CHILDREN)
        return -EOPNOTSUPP;
    return acpi_dev_for_one_check(dev, &owned->original);
}

int lsf_prepaid_acpi_dev_for_each_child(struct acpi_device *parent,
                                      int (*fn)(struct acpi_device *, void *),
                                      void *data)
{
    struct lsf_acpi_bounded_walk owned = {
        .original = {
            .fn = fn,
            .data = data,
        },
    };

    return device_for_each_child(&parent->dev, &owned,
                                 lsf_prepaid_acpi_dev_for_one_check);
}
