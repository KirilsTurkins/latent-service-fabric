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
static int last_timeout,interest_seen,allow_host,timer_polls,timer_fail,inspect_calls,send_shut,shutdown_calls;
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
    reentry_ok=reentry_ok && fcntl(current_fd,F_SETFL,fcntl(current_fd,F_GETFL) & ~O_NONBLOCK)==0 &&
        fcntl(current_fd,F_GETFL)==O_RDWR && lsf_test_errno==EBUSY;
    if(!host_equals(request->host,"127.0.0.1",9) || request->port!=8080 ||
       request->transport!=LATENT_NETWORK_STREAMS_TRANSPORT_TCP || request->timeout_millis.is_some)
        __builtin_trap();
    if(!allow_host){*error=(latent_network_streams_stream_error_t){.code=LATENT_NETWORK_STREAMS_ERROR_CODE_DENIED};return false;}
    send_shut=0;*out=(latent_network_streams_own_connection_t){71};return true;
}
bool latent_network_streams_write(latent_network_streams_borrow_connection_t connection,
        probe_list_u8_t *bytes,uint32_t *timeout,uint32_t *out,latent_network_streams_stream_error_t *error) {
    ++host_calls;if(connection.__handle!=71 || timeout || !bytes->ptr || bytes->len!=3)__builtin_trap();
    reentry_ok=(__lsf_c_net_close(current_fd)==-1 && lsf_test_errno==EBUSY);
    if(send_shut){*error=(latent_network_streams_stream_error_t){.code=LATENT_NETWORK_STREAMS_ERROR_CODE_INVALID_STATE};return false;}
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
    (void)error;if(connection.__handle!=71 || (how!=LATENT_NETWORK_STREAMS_SHUTDOWN_MODE_SEND &&
        how!=LATENT_NETWORK_STREAMS_SHUTDOWN_MODE_BOTH))__builtin_trap();
    bool send_blocked=(__lsf_c_net_send(current_fd,"xyz",3,0)==-1 && lsf_test_errno==EBUSY);
    bool close_blocked=(__lsf_c_net_close(current_fd)==-1 && lsf_test_errno==EBUSY);
    reentry_ok=send_blocked && close_blocked;
    ++host_calls;++shutdown_calls;send_shut=1;
    *out=(latent_network_streams_observation_t){.state=how==LATENT_NETWORK_STREAMS_SHUTDOWN_MODE_SEND ?
        LATENT_NETWORK_STREAMS_STATE_WRITE_SHUT : LATENT_NETWORK_STREAMS_STATE_CLOSED};return true;
}
bool latent_network_streams_close(latent_network_streams_own_connection_t connection,
        latent_network_streams_observation_t *out,latent_network_streams_stream_error_t *error) {
    (void)error;if(connection.__handle!=71)__builtin_trap();++close_calls;*out=(latent_network_streams_observation_t){0};return true;
}
int original_poll(struct pollfd *,nfds_t,int) __asm__("poll");
int original_poll(struct pollfd *fds,nfds_t count,int timeout) {
    (void)fds;if(count!=0 || timeout!=2)__builtin_trap();++timer_polls;
    if(timer_fail) { lsf_test_errno=timer_fail;return -1; }
    return 0;
}

#define CHECK(value) do { if(!(value))return __LINE__; } while(0)
_Static_assert(MSG_NOSIGNAL == 0x4000, "unexpected stream profile flag");
_Static_assert(SO_RCVTIMEO == 66, "unexpected WASI receive-timeout option");
_Static_assert(SO_RCVTIMEO != SO_TYPE, "timeout must not alias the supported socket option");
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
    /* Match the native SO_TYPE value-result contract for short buffers. */
    int expected_type=SOCK_STREAM, calls_before=host_calls;
    const unsigned char *expected=(const unsigned char *)&expected_type;
    for(socklen_t requested=0;requested<=sizeof(expected_type)+2;++requested) {
        unsigned char bytes[sizeof(expected_type)+2];memset(bytes,0xa5,sizeof(bytes));
        socklen_t actual=requested;lsf_test_errno=ERANGE;
        CHECK(__lsf_c_net_getsockopt(current_fd,SOL_SOCKET,SO_TYPE,bytes,&actual)==0);
        CHECK(actual==(requested<sizeof(expected_type)?requested:sizeof(expected_type)));
        CHECK(lsf_test_errno==ERANGE);
        for(size_t i=0;i<sizeof(bytes);++i) CHECK(bytes[i]==(i<actual?expected[i]:0xa5));
    }
    socklen_t zero=0,one=1;
    CHECK(__lsf_c_net_getsockopt(current_fd,SOL_SOCKET,SO_TYPE,NULL,&zero)==0 && zero==0);
    CHECK(__lsf_c_net_getsockopt(current_fd,SOL_SOCKET,SO_TYPE,NULL,&one)==-1 && lsf_test_errno==EINVAL && one==1);
    CHECK(host_calls==calls_before);
    CHECK(__lsf_c_net_fcntl(current_fd,F_GETFL)==O_RDWR);
    CHECK(__lsf_c_net_fcntl(current_fd,F_SETFL,O_NONBLOCK)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(__lsf_c_net_setsockopt(current_fd,SOL_SOCKET,SO_TYPE,&socket_type,sizeof(socket_type))==-1 && lsf_test_errno==ENOTSUP);
    struct timeval timeout={0};
    CHECK(setsockopt(current_fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout))==-1 && lsf_test_errno==ENOTSUP);
    timeout.tv_usec=1000;
    CHECK(setsockopt(current_fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout))==-1 && lsf_test_errno==ENOTSUP);
    socket_type_len=sizeof(socket_type);
    CHECK(getsockopt(current_fd,SOL_SOCKET,SO_RCVTIMEO,&socket_type,&socket_type_len)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(host_calls==calls_before);
    CHECK(setsockopt(-1,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout))==-1 && lsf_test_errno==EBADF);
    allow_host=0;CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==-1);
    CHECK(lsf_test_errno==EACCES && reentry_ok && host_calls==1);
    CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==-1 && lsf_test_errno==EIO);
    CHECK(host_calls==1);
    CHECK(__lsf_c_net_close(current_fd)==0 && close_calls==0);
    current_fd=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);allow_host=1;
    CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==0 && reentry_ok);
    calls_before=host_calls;
    CHECK(fcntl(current_fd,F_SETFL,fcntl(current_fd,F_GETFL) & ~O_NONBLOCK)==0);
    CHECK(fcntl(current_fd,F_GETFL)==O_RDWR);
    CHECK(setsockopt(current_fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout))==-1 && lsf_test_errno==ENOTSUP);
    CHECK(host_calls==calls_before);
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

__attribute__((export_name("send_nosignal_controls"))) int send_nosignal_controls(void) {
    mode=0;allow_host=1;current_fd=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);
    struct sockaddr_in peer=address();CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==0);
    int before=host_calls;
    CHECK(__lsf_c_net_send(current_fd,"xyz",3,0x40)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(__lsf_c_net_send(current_fd,"xyz",3,MSG_NOSIGNAL|0x40)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(__lsf_c_net_send(current_fd,"xyz",3,-1)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(host_calls==before);
    struct lsf_stream_error diagnostic;
    CHECK(lsf_stream_last_error(current_fd,&diagnostic)==-1 && lsf_test_errno==ENOENT);
    CHECK(send(current_fd,"xyz",3,MSG_NOSIGNAL)==2 && reentry_ok);
    CHECK(host_calls==before+1);
    mode=1;CHECK(__lsf_c_net_send(current_fd,"xyz",3,MSG_NOSIGNAL)==1);
    CHECK(lsf_stream_last_error(current_fd,&diagnostic)==0 && diagnostic.may_have_applied);
    CHECK(diagnostic.code==LATENT_NETWORK_STREAMS_ERROR_CODE_UNCERTAIN && diagnostic.accepted_prefix_bytes==1);
    before=host_calls;
    CHECK(__lsf_c_net_send(current_fd,"xyz",3,MSG_NOSIGNAL)==-1 && lsf_test_errno==EIO);
    CHECK(host_calls==before && __lsf_c_net_close(current_fd)==0);

    mode=0;current_fd=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);
    CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==0);
    CHECK(__lsf_c_net_shutdown(current_fd,SHUT_WR)==0);
    before=host_calls;
    CHECK(__lsf_c_net_send(current_fd,"xyz",3,MSG_NOSIGNAL)==-1 && lsf_test_errno==EPIPE);
    CHECK(__lsf_c_net_send(current_fd,NULL,0,MSG_NOSIGNAL)==-1 && lsf_test_errno==EPIPE);
    CHECK(host_calls==before && __lsf_c_net_close(current_fd)==0);
    CHECK(__lsf_c_net_send(current_fd,"xyz",3,MSG_NOSIGNAL)==-1 && lsf_test_errno==EBADF);
    return 0;
}

__attribute__((export_name("descriptor_flags_controls"))) int descriptor_flags_controls(void) {
    int before=host_calls;
    int plain=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);CHECK(plain==3);
    CHECK(__lsf_c_net_fcntl(plain,F_GETFD)==0);
    CHECK(__lsf_c_net_fcntl(plain,F_SETFD,FD_CLOEXEC)==0);
    CHECK(__lsf_c_net_fcntl(plain,F_GETFD)==FD_CLOEXEC);
    CHECK(__lsf_c_net_fcntl(plain,F_SETFD,0)==0);
    CHECK(__lsf_c_net_fcntl(plain,F_GETFD)==0);
    CHECK(__lsf_c_net_close(plain)==0);

    int marked=__lsf_c_net_socket(AF_INET,SOCK_STREAM|SOCK_CLOEXEC,0);CHECK(marked==3);
    CHECK(__lsf_c_net_fcntl(marked,F_GETFL)==O_RDWR);
    CHECK(__lsf_c_net_fcntl(marked,F_GETFD)==FD_CLOEXEC);
    /* This is the ordinary blocking selection used by unchanged clients. */
    int flags=fcntl(marked,F_GETFL);
    lsf_test_errno=ERANGE;
    CHECK(fcntl(marked,F_SETFL,flags & ~O_NONBLOCK)==0 && lsf_test_errno==ERANGE);
    CHECK(fcntl(marked,F_SETFL,0)==0 && lsf_test_errno==ERANGE);
    CHECK(fcntl(marked,F_GETFL)==O_RDWR && fcntl(marked,F_GETFD)==FD_CLOEXEC);
    CHECK(fcntl(marked,F_SETFL,O_RDWR|O_NONBLOCK)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(fcntl(marked,F_SETFL,O_APPEND)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(fcntl(marked,F_GETFL)==O_RDWR && fcntl(marked,F_GETFD)==FD_CLOEXEC);
    int second=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);CHECK(second==4);
    CHECK(__lsf_c_net_fcntl(second,F_GETFD)==0);
    CHECK(__lsf_c_net_fcntl(marked,F_SETFD,0)==0);
    CHECK(__lsf_c_net_fcntl(marked,F_GETFD)==0);
    CHECK(__lsf_c_net_fcntl(marked,F_SETFD,FD_CLOEXEC)==0);
    CHECK(__lsf_c_net_fcntl(marked,F_SETFD,FD_CLOEXEC|2)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(__lsf_c_net_fcntl(marked,F_GETFD)==FD_CLOEXEC);
    CHECK(__lsf_c_net_fcntl(second,F_GETFD)==0);
    CHECK(__lsf_c_net_close(second)==0);
    CHECK(__lsf_c_net_close(marked)==0);

    int reused=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);CHECK(reused==3);
    CHECK(__lsf_c_net_fcntl(reused,F_GETFD)==0);
    CHECK(__lsf_c_net_socket(AF_INET,SOCK_STREAM|SOCK_CLOEXEC|SOCK_NONBLOCK,0)==-1 &&
          lsf_test_errno==ENOTSUP);
    CHECK(__lsf_c_net_fcntl(reused,F_SETFL,O_NONBLOCK)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(__lsf_c_net_close(reused)==0);
    CHECK(__lsf_c_net_fcntl(reused,F_GETFD)==-1 && lsf_test_errno==EBADF);
    CHECK(fcntl(reused,F_SETFL,0)==-1 && lsf_test_errno==EBADF);
    CHECK(fcntl(-1,F_SETFL,0)==-1 && lsf_test_errno==EBADF);
    CHECK(host_calls==before);
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
    struct pollfd inactive[65];
    for(size_t i=0;i<65;++i) inactive[i]=(struct pollfd){.fd=i%2?-1:-5,.events=POLLIN|POLLPRI,.revents=123};
    CHECK(__lsf_c_net_poll(inactive,9,2)==0 && timer_polls==2);
    for(size_t i=0;i<65;++i) CHECK(inactive[i].revents==(i<9?0:123));
    for(size_t i=0;i<64;++i) inactive[i].revents=123;
    timer_fail=EAGAIN;
    CHECK(__lsf_c_net_poll(inactive,64,2)==-1 && lsf_test_errno==EAGAIN && timer_polls==3);
    for(size_t i=0;i<64;++i) CHECK(inactive[i].revents==123);
    timer_fail=ECANCELED;
    CHECK(__lsf_c_net_poll(inactive,64,2)==-1 && lsf_test_errno==ECANCELED && timer_polls==4);
    for(size_t i=0;i<64;++i) CHECK(inactive[i].revents==123);
    timer_fail=0;inactive[63].fd=3;
    CHECK(__lsf_c_net_poll(inactive,64,2)==-1 && lsf_test_errno==ENOTSUP && timer_polls==4);
    inactive[63].fd=-1;
    CHECK(__lsf_c_net_poll(inactive,64,2)==0 && timer_polls==5);
    for(size_t i=0;i<64;++i) CHECK(inactive[i].revents==0);
    CHECK(__lsf_c_net_poll(inactive,65,2)==-1 && lsf_test_errno==ENOTSUP && timer_polls==5);
    CHECK(__lsf_c_net_poll(NULL,9,2)==-1 && lsf_test_errno==EINVAL && timer_polls==5);
    CHECK(host_calls==before);
    return 0;
}

__attribute__((export_name("half_close_controls"))) int half_close_controls(void) {
    mode=0;allow_host=1;current_fd=__lsf_c_net_socket(AF_INET,SOCK_STREAM,0);
    struct sockaddr_in peer=address();CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==0);
    int before_shutdown=shutdown_calls;
    CHECK(__lsf_c_net_shutdown(current_fd,SHUT_WR)==0 && shutdown_calls==before_shutdown+1 && reentry_ok);
    int repeated=__lsf_c_net_shutdown(current_fd,SHUT_WR);
    int before=host_calls;
    CHECK(__lsf_c_net_shutdown(current_fd,SHUT_RDWR)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(host_calls==before && shutdown_calls==before_shutdown+1);
    ssize_t written=__lsf_c_net_send(current_fd,"xyz",3,0);int write_errno=lsf_test_errno;
    char received[3];ssize_t count=__lsf_c_net_recv(current_fd,received,sizeof(received),0);
    CHECK(count==3 && received[0]=='a' && received[1]=='b' && received[2]=='c');
    CHECK(repeated==0 && shutdown_calls==before_shutdown+1);
    CHECK(written==-1 && write_errno==EPIPE && host_calls==before+1);
    CHECK(__lsf_c_net_send(current_fd,NULL,0,0)==-1 && lsf_test_errno==EPIPE);
    struct lsf_stream_error diagnostic;
    CHECK(lsf_stream_last_error(current_fd,&diagnostic)==-1 && lsf_test_errno==ENOENT);
    CHECK(__lsf_c_net_close(current_fd)==0);
    return 0;
}

__attribute__((export_name("full_shutdown_refusal_controls"))) int full_shutdown_refusal_controls(void) {
    mode=0;allow_host=1;current_fd=__lsf_c_net_socket(AF_INET,SOCK_STREAM|SOCK_CLOEXEC,0);
    struct sockaddr_in peer=address();CHECK(__lsf_c_net_connect(current_fd,(struct sockaddr *)&peer,sizeof(peer))==0);
    CHECK(__lsf_c_net_fcntl(current_fd,F_GETFD)==FD_CLOEXEC);
    int before=host_calls, before_close=close_calls, before_shutdown=shutdown_calls;
    CHECK(__lsf_c_net_shutdown(current_fd,SHUT_RD)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(__lsf_c_net_shutdown(current_fd,SHUT_RDWR)==-1 && lsf_test_errno==ENOTSUP);
    CHECK(host_calls==before && shutdown_calls==before_shutdown && close_calls==before_close);
    CHECK(__lsf_c_net_fcntl(current_fd,F_GETFD)==FD_CLOEXEC);
    struct lsf_stream_error diagnostic;
    CHECK(lsf_stream_last_error(current_fd,&diagnostic)==-1 && lsf_test_errno==ENOENT);
    CHECK(__lsf_c_net_send(current_fd,"xyz",3,0)==2);
    char received[3];CHECK(__lsf_c_net_recv(current_fd,received,sizeof(received),0)==3);
    CHECK(received[0]=='a' && received[1]=='b' && received[2]=='c');
    CHECK(__lsf_c_net_close(current_fd)==0 && close_calls==before_close+1);
    CHECK(__lsf_c_net_recv(current_fd,received,sizeof(received),0)==-1 && lsf_test_errno==EBADF);
    return 0;
}
