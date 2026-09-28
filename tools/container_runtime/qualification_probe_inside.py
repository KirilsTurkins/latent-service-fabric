"""Real HTTP checks of the private adapter, including actual ingress saturation."""
import http.client
import json
import socket
import sys
import time


def get(path='/ready', method='GET', headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', 18181, timeout=1)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        raw = response.read(1025)
        assert len(raw) <= 1024 and response.getheader('Cache-Control') == 'no-store'
        assert response.getheader('X-Content-Type-Options') == 'nosniff'
        assert raw == b'' if method == 'HEAD' else set(json.loads(raw)) == {'status'}
        return response.status
    finally:
        connection.close()


def wait_for(status, path='/ready', seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if get(path) == status:
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.1)
    raise AssertionError('private probe did not reach expected bounded state')


mode = sys.argv[1]
if mode == 'ready':
    wait_for(200)
    assert get('/startup') == get('/live') == get('/ready', 'HEAD') == 200
    assert get('/ready', 'POST') == 405 and get('/unknown') == 404
    assert get(headers={'Host': 'foreign.example'}) == 400
    assert get(headers={'Forwarded': 'host=foreign.example'}) == 400
elif mode in {'unavailable', 'wrong-node'}:
    wait_for(503)
    assert get('/live') == 503
    if mode == 'wrong-node':
        assert get('/startup') == 503
elif mode == 'overload':
    held = []
    try:
        for _ in range(4):
            connection = socket.create_connection(('127.0.0.1', 18080), timeout=1)
            connection.sendall(b'GET / HTTP/1.1\r\n')
            held.append(connection)
        wait_for(503, seconds=6)
        assert get('/live') == 200, 'load must not become a liveness restart loop'
    finally:
        for connection in held:
            connection.close()
    wait_for(200)
else:
    raise AssertionError('unknown probe drill')
print(json.dumps({'passed': True, 'mode': mode, 'statusOnly': True, 'applicationInvoked': False}))
