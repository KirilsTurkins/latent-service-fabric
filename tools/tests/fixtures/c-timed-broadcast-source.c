/* Serialized source regression only. Every broker/canonical port is an
 * explicit double. This does not execute a signed guest or original ledger. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <threads.h>
#include "thread-abi.h"
/* Freestanding control implementations; no second CRT/libc is built. */
void *memcpy(void *out,const void *in,size_t size) {
    unsigned char *destination=out;const unsigned char *source=in;
    for (size_t index=0;index<size;++index) destination[index]=source[index];return out;
}
void *memset(void *out,int value,size_t size) {
    unsigned char *destination=out;
    for (size_t index=0;index<size;++index) destination[index]=(unsigned char)value;return out;
}
#define RECORD_LIMIT 32u
struct token_result { uint8_t tag,pad[7]; union { struct lsf_c_token token; uint8_t error; } value; };
struct unit_result { uint8_t tag,error; };
static void require(int value) { if (!value) __builtin_trap(); }
static int token_live(struct lsf_c_token token) { return token.generation && token.id; }
static struct lsf_c_thread *current(void) { __builtin_trap(); }
static int ensure_root_owners(struct lsf_c_thread *root) { (void)root;__builtin_trap(); }
static int acquire(unsigned kind,struct lsf_c_token *parent,struct lsf_c_token *out) {
    (void)kind;(void)parent;(void)out;__builtin_trap();
}
static void settle(struct lsf_c_token *value) { (void)value;__builtin_trap(); }
static void park(struct lsf_c_token value) { (void)value;__builtin_trap(); }
static void wake(struct lsf_c_token value) { (void)value;__builtin_trap(); }
static int runtime_error(uint8_t value) { (void)value;__builtin_trap(); }
#include "synchronization.c"

static pthread_cond_t condition;
static pthread_mutex_t gate;
static struct sync_wait first,second,arrival;
static unsigned interleaved;

__attribute__((export_name("test_interleave")))
void test_interleave(void) {
    require(!interleaved++);
    struct sync_cond value=sync_cond_read(&condition);
    /* The later node must remain in the ACTUAL queue while stop awaits. */
    require(value.head==&second && value.tail==&second && value.waiters==1);
    require(first.notified && !first.linked && second.linked && !second.notified);
    sync_remove(&value.head,&value.tail,&value.waiters,&second);
    value.mutex=NULL;
    /* Model that actual later waiter finishing and its stack being reclaimed.
     * A stale cached pointer cannot be used by the broadcaster afterward. */
    memset(&second,0xa5,sizeof(second));
    arrival=(struct sync_wait){.linked=1,.timer={1,13}};
    require(sync_cond_publish_sequence(&value,&arrival)==0);
    value.head=value.tail=&arrival;value.waiters=1;value.mutex=&gate;
    sync_cond_write(&condition,value);
}

__attribute__((export_name("test_start")))
unsigned test_start(void) {
    require(sync_cond_init(&condition,0)==0);
    struct sync_cond value=sync_cond_read(&condition);
    first=(struct sync_wait){.linked=1,.timer={1,11},.next=&second};
    second=(struct sync_wait){.linked=1,.timer={1,12}};
    require(sync_cond_publish_sequence(&value,&first)==0);
    require(sync_cond_publish_sequence(&value,&second)==0);
    value.head=&first;value.tail=&second;value.waiters=2;value.mutex=&gate;
    sync_cond_write(&condition,value);
    require(sync_cond_wake(&condition,1)==0);
    value=sync_cond_read(&condition);
    require(interleaved==1 && value.head==&arrival && value.tail==&arrival && value.waiters==1);
    require(arrival.linked && !arrival.notified && arrival.timer.id==13);
    require(first.notified && !first.linked && !token_live(first.timer));
    return 1;
}
