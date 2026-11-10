/* Source-level adapter controls. The stream provider below is a test double;
 * this program is not a signed component or physical-retirement witness. */
#include "probe.h"
#include <errno.h>
#include <netinet/in.h>
#include <stdint.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <time.h>
#include <lsf/standard-streams.h>

extern int __lsf_c_net_socket(int,int,int);
extern int __lsf_c_net_connect(int,const struct sockaddr *,socklen_t);
extern ssize_t __lsf_c_net_send(int,const void *,size_t,int);
extern ssize_t __lsf_c_net_recv(int,void *,size_t,int);
extern int __lsf_c_net_close(int);
extern int __lsf_c_net_select(int,fd_set *,fd_set *,fd_set *,const struct timeval *);
extern int __lsf_c_net_pselect(int,fd_set *,fd_set *,fd_set *,const struct timespec *);

int lsf_test_errno;
void *memcpy(void *out,const void *in,size_t size) {
    unsigned char *dst=out;const unsigned char *src=in;
    for(size_t i=0;i<size;++i) dst[i]=src[i];return out;
}
void *memset(void *out,int value,size_t size) {
    unsigned char *dst=out;for(size_t i=0;i<size;++i) dst[i]=(unsigned char)value;return out;
}

static int current_fd,mode,host_calls,close_calls,drop_calls,free_calls,reentry_ok;
static int last_timeout,interest_seen,allow_host,timer_polls,inspect_calls;
static uint8_t message[]={'a','b','c'};
static bool host_equals(probe_string_t host,const char *text,size_t size) {
    if(host.len!=size)return false;
    for(size_t i=0;i<size;++i)if(host.ptr[i]!=(uint8_t)text[i])return false;
    return true;
}

latent_network_streams_borrow_connection_t latent_network_streams_borrow_connection(latent_network_streams_own_connection_t value) {
    return (latent_network_streams_borrow_connection_t){value.__handle};
}
latent_network_streams_borrow_chunk_t latent_network_streams_borrow_chunk(latent_network_streams_own_chunk_t value) {
    return (latent_network_streams_borrow_chunk_t){value.__handle};
}
bool latent_network_streams_connect(latent_network_streams_connect_request_t *request,
        latent_network_streams_own_connection_t *out,latent_network_streams_stream_error_t *error) {
    ++host_calls;
    reentry_ok=(__lsf_c_net_close(current_fd)==-1 && lsf_test_errno==EBUSY);
    if(!host_equals(request->host,"127.0.0.1",9) || request->port!=8080 ||
       request->transport!=LATENT_NETWORK_STREAMS_TRANSPORT_TCP || request->timeout_millis.is_some)
        __builtin_trap();
    if(!allow_host){*error=(latent_network_streams_stream_error_t){.code=LATENT_NETWORK_STREAMS_ERROR_CODE_DENIED};return false;}
    *out=(latent_network_streams_own_connection_t){71};return true;
}
bool latent_network_streams_write(latent_network_streams_borrow_connection_t connection,
        probe_list_u8_t *bytes,uint32_t *timeout,uint32_t *out,latent_network_streams_stream_error_t *error) {
    ++host_calls;if(connection.__handle!=71 || timeout || !bytes->ptr || bytes->len!=3)__builtin_trap();
    reentry_ok=(__lsf_c_net_close(current_fd)==-1 && lsf_test_errno==EBUSY);
    if(mode==1){*error=(latent_network_streams_stream_error_t){.code=LATENT_NETWORK_STREAMS_ERROR_CODE_UNCERTAIN,
        .accepted_prefix_bytes=1,.may_have_applied=true};return false;}
    *out=2;return true;
}
bool latent_network_streams_read(latent_network_streams_borrow_connection_t connection,
        uint32_t maximum,uint32_t *timeout,latent_network_streams_option_own_chunk_t *out,
        latent_network_streams_stream_error_t *error) {
    (void)error;++host_calls;if(connection.__handle!=71 || timeout || maximum!=3)__builtin_trap();
    *out=(latent_network_streams_option_own_chunk_t){.is_some=mode!=2,.val={31}};return true;
}
bool latent_network_streams_chunk_bytes(latent_network_streams_borrow_chunk_t chunk,
        probe_list_u8_t *out,latent_network_streams_stream_error_t *error) {
    (void)error;if(chunk.__handle!=31)__builtin_trap();
    reentry_ok=(__lsf_c_net_close(current_fd)==-1 && lsf_test_errno==EBUSY);
    *out=(probe_list_u8_t){.ptr=message,.len=3};return true;
}
void latent_network_streams_chunk_drop_own(latent_network_streams_own_chunk_t chunk) {
    if(chunk.__handle!=31)__builtin_trap();++drop_calls;
}
void probe_list_u8_free(probe_list_u8_t *bytes) {
    if(bytes->ptr!=message || bytes->len!=3)__builtin_trap();++free_calls;
}
bool latent_network_streams_ready(latent_network_streams_borrow_connection_t connection,
        latent_network_streams_interest_t interest,uint32_t *timeout,
        latent_network_streams_readiness_t *out,latent_network_streams_stream_error_t *error) {
    ++host_calls;if(connection.__handle!=71)__builtin_trap();
    reentry_ok=(__lsf_c_net_close(current_fd)==-1 && lsf_test_errno==EBUSY);
    interest_seen=interest;last_timeout=timeout?(int)*timeout:-1;
    if(mode==3 || mode==4){*error=(latent_network_streams_stream_error_t){.code=LATENT_NETWORK_STREAMS_ERROR_CODE_TIMEOUT};return false;}
    if(mode==5){*error=(latent_network_streams_stream_error_t){.code=LATENT_NETWORK_STREAMS_ERROR_CODE_DENIED};return false;}
    *out=(latent_network_streams_readiness_t){.readable=true,.writable=true};return true;
}
void latent_network_streams_inspect(latent_network_streams_borrow_connection_t connection,
        latent_network_streams_observation_t *out) {
    if(connection.__handle!=71)__builtin_trap();++inspect_calls;
    *out=(latent_network_streams_observation_t){.state=mode==4?LATENT_NETWORK_STREAMS_STATE_FAILED:LATENT_NETWORK_STREAMS_STATE_OPEN};
}
bool latent_network_streams_shutdown(latent_network_streams_borrow_connection_t connection,
        latent_network_streams_shutdown_mode_t how,latent_network_streams_observation_t *out,
        latent_network_streams_stream_error_t *error) {
    (void)how;(void)error;if(connection.__handle!=71)__builtin_trap();*out=(latent_network_streams_observation_t){0};return true;
}
bool latent_network_streams_close(latent_network_streams_own_connection_t connection,
        latent_network_streams_observation_t *out,latent_network_streams_stream_error_t *error) {
    (void)error;if(connection.__handle!=71)__builtin_trap();++close_calls;*out=(latent_network_streams_observation_t){0};return true;
}
int original_poll(struct pollfd *,nfds_t,int) __asm__("poll");
int original_poll(struct pollfd *fds,nfds_t count,int timeout) {
    (void)fds;if(count!=0 || timeout!=2)__builtin_trap();++timer_polls;return 0;
}

#define CHECK(value) do { if(!(value))return __LINE__; } while(0)
static struct sockaddr_in address(void) {
    struct sockaddr_in result={.sin_family=AF_INET};
    unsigned char octets[]={127,0,0,1},port[]={0x1f,0x90};
    memcpy(&result.sin_addr,octets,sizeof(octets));memcpy(&result.sin_port,port,sizeof(port));return result;
}

__attribute__((export_name("descriptor_controls"))) int descriptor_controls(void) {
    int fds[8];
    for(int i=0;i<8;++i){fds[i]=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);CHECK(fds[i]==i+3);}
    CHECK(__lsf_c_net_socket(AF_INET,SOCK_STREAM,0)==-1 && lsf_test_errno==EMFILE);
    for(int i=0;i<8;++i)CHECK(__lsf_c_net_close(fds[i])==0);
    CHECK(__lsf_c_net_socket(AF_INET6,SOCK_STREAM,0)==-1 && lsf_test_errno==EAFNOSUPPORT);
    CHECK(__lsf_c_net_socket(AF_INET,SOCK_DGRAM,0)==-1 && lsf_test_errno==ENOTSUP);
    struct sockaddr_in peer=address();current_fd=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);CHECK(current_fd==3);
    CHECK(__lsf_c_net_bind(current_fd,(struct sockaddr *)&peer,sizeof(peer))==-1 && lsf_test_errno==ENOTSUP);
    int socket_type=0;socklen_t socket_type_len=sizeof(socket_type);
    CHECK(__lsf_c_net_getsockopt(current_fd,SOL_SOCKET,SO_TYPE,&socket_type,&socket_type_len)==0);
    CHECK(socket_type==SOCK_STREAM && socket_type_len==sizeof(socket_type));
    CHECK(__lsf_c_net_fcntl(current_fd,F_GETFL)==O_RDWR);
    CHECK(__lsf_c_net_fcntl(current_fd,F_SETFL,O_NONBLOCK)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(__lsf_c_net_setsockopt(current_fd,SOL_SOCKET,SO_TYPE,&socket_type,sizeof(socket_type))==-1 && lsf_test_errno==ENOTSUP);
    allow_host=0;CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==-1);
    CHECK(lsf_test_errno==EACCES && reentry_ok && host_calls==1);
    CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==-1 && lsf_test_errno==EIO);
    CHECK(host_calls==1);
    CHECK(__lsf_c_net_close(current_fd)==0 && close_calls==0);
    current_fd=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);allow_host=1;
    CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==0 && reentry_ok);
    CHECK(__lsf_c_net_send(current_fd,"xyz",3,0)==2 && reentry_ok);
    char input[3];CHECK(__lsf_c_net_recv(current_fd,input,3,0)==3 && reentry_ok);
    CHECK(input[0]=='a' && input[1]=='b' && input[2]=='c' && drop_calls==1 && free_calls==1);
    mode=2;CHECK(__lsf_c_net_recv(current_fd,input,3,0)==0);
    CHECK(__lsf_c_net_recv(current_fd,input,0,1)==-1 && lsf_test_errno==ENOTSUP);
    mode=1;CHECK(__lsf_c_net_send(current_fd,"xyz",3,0)==1);
    struct lsf_stream_error diagnostic;
    CHECK(lsf_stream_last_error(current_fd,&diagnostic)==0 && diagnostic.may_have_applied);
    CHECK(diagnostic.code==LATENT_NETWORK_STREAMS_ERROR_CODE_UNCERTAIN && diagnostic.accepted_prefix_bytes==1);
    CHECK(__lsf_c_net_send(current_fd,"xyz",3,0)==-1 && lsf_test_errno==EIO);
    CHECK(__lsf_c_net_close(current_fd)==0 && close_calls==1);
    return 0;
}

__attribute__((export_name("readiness_controls"))) int readiness_controls(void) {
    mode=0;host_calls=0;allow_host=1;current_fd=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);
    struct sockaddr_in peer=address();CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==0);
    fd_set reads,writes,except;FD_ZERO(&reads);FD_ZERO(&writes);FD_ZERO(&except);
    FD_SET(current_fd,&reads);FD_SET(current_fd,&writes);struct timeval zero={0,0};
    CHECK(__lsf_c_net_select(current_fd+1,&reads,&writes,&except,NULL)==2 && reentry_ok);
    CHECK(interest_seen==LATENT_NETWORK_STREAMS_INTEREST_EITHER && last_timeout==-1);
    CHECK(FD_ISSET(current_fd,&reads) && FD_ISSET(current_fd,&writes));
    int before=host_calls;FD_SET(current_fd,&except);
    CHECK(__lsf_c_net_select(current_fd+1,&reads,&writes,&except,&zero)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(host_calls==before);FD_ZERO(&except);
    int second=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);CHECK(second==4);
    FD_SET(second,&reads);
    CHECK(__lsf_c_net_select(second+1,&reads,NULL,NULL,&zero)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(host_calls==before);FD_CLR(second,&reads);CHECK(__lsf_c_net_close(second)==0);
    struct timespec nano={0,1};
    CHECK(__lsf_c_net_pselect(current_fd+1,&reads,NULL,NULL,&nano)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(nano.tv_sec==0 && nano.tv_nsec==1 && FD_ISSET(current_fd,&reads) && host_calls==before);
    struct timeval fractional={0,1};
    CHECK(__lsf_c_net_select(current_fd+1,&reads,NULL,NULL,&fractional)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(__lsf_c_net_select(current_fd+1,&reads,NULL,NULL,&zero)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(FD_ISSET(current_fd,&reads) && host_calls==before);
    struct timeval invalid={0,1000000};
    CHECK(__lsf_c_net_select(current_fd+1,&reads,NULL,NULL,&invalid)==-1 && lsf_test_errno==EINVAL);
    CHECK(__lsf_c_net_pselect(current_fd+1,&reads,NULL,NULL,NULL)==1 && last_timeout==-1);
    FD_SET(current_fd,&reads);mode=3;
    CHECK(__lsf_c_net_select(current_fd+1,&reads,NULL,NULL,NULL)==-1 && lsf_test_errno==ETIMEDOUT);
    CHECK(inspect_calls==0 && FD_ISSET(current_fd,&reads));
    CHECK(__lsf_c_net_send(current_fd,"xyz",3,0)==-1 && lsf_test_errno==EIO);
    CHECK(__lsf_c_net_close(current_fd)==0);
    struct pollfd urgent={.fd=3,.events=POLLIN|POLLPRI,.revents=123};
    before=host_calls;
    CHECK(__lsf_c_net_poll(&urgent,1,0)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(urgent.revents==123 && host_calls==before);
    CHECK(__lsf_c_net_poll(NULL,0,2)==0 && timer_polls==1);
    return 0;
}
