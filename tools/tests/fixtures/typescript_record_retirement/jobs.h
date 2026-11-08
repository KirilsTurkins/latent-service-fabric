#pragma once
#include <cstdint>
using latent_runtime_activation_error_t = uint8_t;
using latent_runtime_activation_owner_kind_t = uint8_t;
struct latent_runtime_activation_token_t { uint64_t generation; uint64_t id; };
struct latent_runtime_activation_result_u64_error_t { bool is_err; union { uint64_t ok; latent_runtime_activation_error_t err; } val; };
enum : uint8_t { LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_STATE=1, LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN, LATENT_RUNTIME_ACTIVATION_ERROR_RESOURCE_EXHAUSTED, LATENT_RUNTIME_ACTIVATION_ERROR_CANCELLED, LATENT_RUNTIME_ACTIVATION_ERROR_UNAVAILABLE };
enum : uint8_t { LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TASK=0, LATENT_RUNTIME_ACTIVATION_OWNER_KIND_QUEUED_WORK=3, LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TIMER=5 };
using jobs_subtask_t = uint32_t;
using jobs_subtask_status_t = uint32_t;
using jobs_subtask_state_t = uint32_t;
using jobs_waitable_set_t = uint32_t;
struct jobs_event_t { uint32_t event; uint32_t waitable; uint32_t code; };
enum : uint32_t { JOBS_SUBTASK_STARTING=0, JOBS_SUBTASK_STARTED=1, JOBS_SUBTASK_RETURNED=2, JOBS_SUBTASK_STARTED_CANCELLED=3, JOBS_SUBTASK_RETURNED_CANCELLED=4, JOBS_EVENT_NONE=0, JOBS_EVENT_SUBTASK=1 };
#define JOBS_SUBTASK_STATE(status) ((status) & 15u)
#define JOBS_SUBTASK_HANDLE(status) ((status) >> 4)
extern "C" {
bool latent_runtime_activation_register(latent_runtime_activation_owner_kind_t, latent_runtime_activation_token_t*, latent_runtime_activation_token_t*, latent_runtime_activation_error_t*);
bool latent_runtime_activation_park(latent_runtime_activation_token_t*, latent_runtime_activation_error_t*);
bool latent_runtime_activation_wake(latent_runtime_activation_token_t*, latent_runtime_activation_error_t*);
bool latent_runtime_activation_settle(latent_runtime_activation_token_t*, latent_runtime_activation_error_t*);
bool latent_runtime_activation_close(latent_runtime_activation_error_t*);
bool latent_runtime_activation_timer_start(uint64_t, uint64_t*, latent_runtime_activation_token_t*, latent_runtime_activation_token_t*, latent_runtime_activation_error_t*);
bool latent_runtime_activation_timer_stop(latent_runtime_activation_token_t*, latent_runtime_activation_error_t*);
jobs_subtask_status_t latent_runtime_activation_timer_next(latent_runtime_activation_token_t, latent_runtime_activation_result_u64_error_t*);
void jobs_subtask_drop(jobs_subtask_t);
void jobs_waitable_join(uint32_t, jobs_waitable_set_t);
jobs_waitable_set_t jobs_waitable_set_new();
void jobs_waitable_set_drop(jobs_waitable_set_t);
void jobs_waitable_set_wait(jobs_waitable_set_t, jobs_event_t*);
void jobs_waitable_set_poll(jobs_waitable_set_t, jobs_event_t*);
}
