#include <stdint.h>
#include <stddef.h>
#include "c-sync-reference-abi.h"
#include "thread-abi.h"
struct timespec;
#define RECORD_LIMIT 32u
static int fake_errno;
#undef errno
#define errno fake_errno
static struct lsf_c_thread root,first,second;
static int flag,initializations,finished,first_done,second_done,live,admitted,settled,parked,woken,scenario;
__attribute__((import_module("test"),import_name("context"))) uint32_t test_context(void);
__attribute__((import_module("test"),import_name("yield"))) void test_yield(void);
static void *memcpy(void *destination,const void *source,size_t size){unsigned char *d=destination;const unsigned char *s=source;for(size_t i=0;i<size;++i)d[i]=s[i];return destination;}
static void require(int value){if(!value)__builtin_trap();}
static struct lsf_c_thread *current(void){return (struct lsf_c_thread *)(uintptr_t)test_context();}
static int ensure_root_owners(struct lsf_c_thread *v){if(!v->task.id)v->task=(struct lsf_c_token){1,1};return 0;}
static int acquire(unsigned kind,const struct lsf_c_token *parent,struct lsf_c_token *out){require(kind==LSF_C_WAIT&&parent->id);++admitted;++live;*out=(struct lsf_c_token){1,(uint64_t)admitted+10};return 0;}
static void settle(struct lsf_c_token *v){require(v->id&&live);--live;++settled;*v=(struct lsf_c_token){0};}
static void park(struct lsf_c_token v){require(v.id);++parked;}
static void wake(struct lsf_c_token v){require(v.id);++woken;}
#include "synchronization.c"
void setup(void){
 root=(struct lsf_c_thread){.low=0x100000,.high=0x110000,.phase=LSF_C_RUNNING,.canonical_id=10,.task={1,1}};
 first=(struct lsf_c_thread){.low=0x200000,.high=0x210000,.phase=LSF_C_RUNNING,.canonical_id=11,.task={1,2}};
 second=(struct lsf_c_thread){.low=0x300000,.high=0x310000,.phase=LSF_C_RUNNING,.canonical_id=12,.task={1,3}};
 root.root=&root;root.next=&first;first.root=&root;first.next=&second;second.root=&root;
 flag=initializations=finished=first_done=second_done=live=admitted=settled=parked=woken=scenario=0;fake_errno=37;
}
void set_scenario(int value){scenario=value;}
uint32_t root_pointer(void){return (uint32_t)(uintptr_t)&root;}
uint32_t first_pointer(void){return (uint32_t)(uintptr_t)&first;}
uint32_t second_pointer(void){return (uint32_t)(uintptr_t)&second;}
static void initialize(void){
 ++initializations;
 if(scenario==1){(void)pthread_once(&flag,initialize);__builtin_trap();}
 if(scenario==2)__builtin_trap();
 test_yield();finished=42;
}
int start_root(void){return pthread_once(&flag,initialize);}
int start_first(void){call_once((once_flag *)&flag,initialize);first_done=(finished==42&&flag==1);return first_done;}
int start_second(void){int e=__pthread_once(&flag,initialize);second_done=(e==0&&finished==42&&flag==1);return second_done;}
int read_flag(void){return flag;}int read_init(void){return initializations;}int read_finished(void){return finished;}
int read_live(void){return live;}int read_admitted(void){return admitted;}int read_settled(void){return settled;}
int read_parked(void){return parked;}int read_woken(void){return woken;}
