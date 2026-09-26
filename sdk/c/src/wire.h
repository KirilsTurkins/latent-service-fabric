#ifndef LSF_C_WIRE_H
#define LSF_C_WIRE_H

#include <latent/transport.h>
#include <pb.h>
#include <pb_common.h>
#include <pb_decode.h>
#include <pb_encode.h>

#define LSF_NO_OFFSET SIZE_MAX
#define LSF_WIRE_STORAGE 2048u
#define LSF_MAX_ELEMENTS 4096u
#define LSF_MAX_DEPTH 16u

typedef struct lsf_arena_block lsf_arena_block;
typedef struct lsf_arena {
    latent_transport *owner;
    lsf_arena_block *blocks;
    size_t used;
    size_t maximum;
} lsf_arena;

typedef enum lsf_wire_kind {
    LSF_STRING, LSF_BYTES, LSF_U64, LSF_U32, LSF_I32, LSF_BOOL, LSF_MESSAGE
} lsf_wire_kind;

typedef struct lsf_message lsf_message;
typedef struct lsf_field {
    uint32_t tag;
    lsf_wire_kind kind;
    size_t offset;
    size_t presence;
    size_t count;
    size_t stride;
    uint32_t oneof;
    bool map;
    const lsf_message *message;
} lsf_field;

struct lsf_message {
    const pb_msgdesc_t *wire;
    const lsf_field *fields;
    size_t field_count;
    size_t native_size;
    size_t wire_size;
};

typedef struct lsf_codec {
    lsf_arena *arena;
    size_t maximum;
    size_t elements;
    unsigned depth;
    uint64_t deadline;
    bool limit;
} lsf_codec;

typedef struct lsf_pb_slot {
    lsf_codec *codec;
    const lsf_field *definition;
    void *object;
    size_t capacity;
} lsf_pb_slot;

typedef struct lsf_rpc {
    const char *path;
    const lsf_message *request;
    const lsf_message *response;
} lsf_rpc;

bool lsf_wire_callback(pb_istream_t *input, pb_ostream_t *output,
                       const pb_field_iter_t *field);
bool lsf_encode(const lsf_message *message, const void *value, uint8_t *output,
                size_t capacity, size_t *length, uint64_t deadline, bool *limit);
bool lsf_decode(const lsf_message *message, const uint8_t *input, size_t length,
                void *value, lsf_arena *arena, uint64_t deadline, bool *limit);
void *lsf_arena_allocate(lsf_arena *arena, size_t size);
void lsf_arena_clear(lsf_arena *arena);
void *lsf_allocate(latent_transport *owner, size_t size);
void lsf_deallocate(latent_transport *owner, void *pointer);
uint64_t lsf_now(void);
bool lsf_text_equal(latent_string left, latent_string right);
bool lsf_utf8(const uint8_t *data, size_t length);

#endif
