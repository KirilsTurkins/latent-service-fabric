"""Bounded one-connection test proxy that withholds server HTTP/2 stream frames."""
import socket, threading
class ResponseFault:
    def __init__(self, endpoint):
        host, port = endpoint.rsplit(':', 1)
        self.upstream_address = (host, int(port))
        self.listener = socket.socket(); self.listener.bind(('127.0.0.1', 0)); self.listener.listen(1); self.listener.settimeout(20)
        self.port = self.listener.getsockname()[1]; self.blocked = threading.Event(); self.done = threading.Event()
        self.connections = []; self.blocked_frames = 0; self.blocked_bytes = 0; self.failure = None
        self.request_streams = set(); self.extra_connections = 0
        self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()
    @staticmethod
    def exact(sock, count):
        value = bytearray()
        while len(value) < count:
            data = sock.recv(count-len(value))
            if not data: raise EOFError()
            value.extend(data)
        return bytes(value)
    def run(self):
        try:
            client,_=self.listener.accept(); upstream=socket.create_connection(self.upstream_address, timeout=10)
            client.settimeout(None); upstream.settimeout(None); self.connections=[client,upstream]
            def forward():
                try:
                    preface=self.exact(client,24)
                    if preface != b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n": raise ValueError('http2-preface')
                    upstream.sendall(preface)
                    while not self.done.is_set():
                        header=self.exact(client,9); size=int.from_bytes(header[:3],'big'); stream=int.from_bytes(header[5:9],'big') & 0x7fffffff
                        if size > 1024*1024: raise ValueError('bounded-request-frame-size')
                        payload=self.exact(client,size)
                        if header[3] == 1 and stream:
                            self.request_streams.add(stream)
                            if len(self.request_streams) > 8: raise ValueError('bounded-request-streams')
                        upstream.sendall(header+payload)
                except (EOFError,OSError) as error:
                    if not self.done.is_set(): self.failure=type(error).__name__
                except Exception as error: self.failure=type(error).__name__
            self.forwarder=threading.Thread(target=forward,daemon=True); self.forwarder.start()
            while not self.done.is_set():
                header=self.exact(upstream,9); size=int.from_bytes(header[:3],'big'); stream=int.from_bytes(header[5:9],'big') & 0x7fffffff
                if size > 1024*1024: raise ValueError('bounded-frame-size')
                payload=self.exact(upstream,size)
                if stream:
                    self.blocked_frames += 1; self.blocked_bytes += len(header)+size
                    if self.blocked_bytes > 1024*1024: raise ValueError('bounded-discarded-response')
                    self.blocked.set()
                else: client.sendall(header+payload)
        except (EOFError, OSError) as error:
            if not self.done.is_set(): self.failure=type(error).__name__
        except Exception as error: self.failure=type(error).__name__
    def close(self):
        if self.done.is_set(): return
        self.done.set()
        for sock in self.connections:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            sock.close()
        self.listener.setblocking(False)
        while True:
            try: extra,_=self.listener.accept()
            except (BlockingIOError,OSError): break
            self.extra_connections += 1; extra.close()
            if self.extra_connections > 8: raise RuntimeError('bounded-extra-connections')
        self.listener.close(); self.thread.join(timeout=5)
        if self.thread.is_alive(): raise RuntimeError('proxy-thread-not-retired')
        if hasattr(self,'forwarder'):
            self.forwarder.join(timeout=5)
            if self.forwarder.is_alive(): raise RuntimeError('proxy-forwarder-not-retired')
