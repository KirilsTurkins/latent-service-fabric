/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_INTENTS_H
#define LSF_GUEST_INTENTS_H
#include "state.h"

typedef struct {
    lsf_state_call_t borrow;
    latent_intents_staging_stage_args_t arguments;
} lsf_intent_call_t;

/* The builder borrows its bytes/strings. Keep them in the callback frame until
 * retirement; it contains no provider, grant, effect ID or automatic retry. */
static inline latent_intents_staging_intent_t lsf_intent(probe_string_t binding,
    probe_string_t operation, latent_state_key_value_value_t payload, probe_option_u64_t expiry) {
    return (latent_intents_staging_intent_t){binding, operation, payload, expiry};
}
static inline probe_subtask_status_t lsf_intent_stage(lsf_intent_call_t *call, lsf_state_command_t *command,
    latent_intents_staging_intent_t intent, latent_intents_staging_result_staged_intent_intent_error_t *result) {
    lsf_state_check(command->cell, LSF_STATE_COMMAND);
    lsf_state_call_begin(&call->borrow, command->cell);
    call->arguments = (latent_intents_staging_stage_args_t){
        latent_state_key_value_borrow_transaction(command->cell->raw.command), intent};
    return latent_intents_staging_stage(&call->arguments, result);
}
static inline void lsf_intent_retire(lsf_intent_call_t *call) { lsf_state_call_retire(&call->borrow); }
#endif
