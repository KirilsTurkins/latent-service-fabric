/* SPDX-License-Identifier: Apache-2.0 */
// lsf-example-begin: capsule
#include "lsf/text.h"

bool exports_examples_shipping_api_quote(uint32_t items, bool express, uint32_t *value,
                                         probe_string_t *error) {
    if (items < 1 || items > 100) {
        lsf_text_error(error, "Choose between 1 and 100 items.");
        return false;
    }
    *value = (express ? 1200u : 500u) + items * 75u;
    return true;
}
// lsf-example-end: capsule
