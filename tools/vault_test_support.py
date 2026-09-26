"""Fixed, public synthetic KV fixture operations; never an operator client."""
from __future__ import annotations

import http.client
import json
import ssl
import sys
import time

ROOT_TOKEN = "lsf-public-vault-root"
FIRST_TOKEN = "lsf-public-vault-reader-a"
SECOND_TOKEN = "lsf-public-vault-reader-b"


class Client:
    def __init__(self, port, ca):
        self.port = int(port)
        self.context = ssl.create_default_context(cafile=str(ca))
        self.calls = 0

    def call(self, method, path, body=None):
        self.calls += 1
        if self.calls > 64:
            raise RuntimeError("Vault fixture request limit")
        connection = http.client.HTTPSConnection("127.0.0.1", self.port,
                                                 context=self.context, timeout=2)
        try:
            encoded = None if body is None else json.dumps(body).encode()
            if encoded is not None and len(encoded) > 8192:
                raise RuntimeError("Vault fixture input bound")
            connection.request(method, "/v1/" + path, encoded,
                               {"X-Vault-Token": ROOT_TOKEN, "Content-Type": "application/json"})
            response = connection.getresponse()
            payload = response.read(65537)
            if len(payload) > 65536:
                raise RuntimeError("Vault fixture response bound")
            result = json.loads(payload) if payload else None
            return response.status, result
        finally:
            connection.close()

    def apply(self, method, path, body, status):
        if self.call(method, path, body)[0] != status:
            raise RuntimeError("Vault fixture operation failed")

    def setup(self):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                status, value = self.call("GET", "sys/health")
                if status == 200 and value.get("version") == "2.1.0":
                    break
            except OSError:
                pass
            time.sleep(.2)
        else:
            raise RuntimeError("pinned Vault did not become ready")
        self.apply("PUT", "sys/policies/acl/lsf-fixture",
                   {"policy": 'path "secret/data/fixture" { capabilities = ["read"] }'}, 204)
        for token in (FIRST_TOKEN, SECOND_TOKEN):
            self.apply("POST", "auth/token/create", {"id": token, "policies": ["lsf-fixture"],
                       "no_default_policy": True, "ttl": "10m", "renewable": False}, 200)
        self.apply("POST", "secret/data/fixture", {"data": {"value": "Alpha"}}, 200)

    def operate(self, operation):
        if operation == "setup":
            self.setup()
        elif operation == "reset-fixture":
            self.apply("DELETE", "secret/metadata/fixture", None, 204)
            self.apply("POST", "secret/data/fixture", {"data": {"value": "Alpha"}}, 200)
        elif operation == "write-beta":
            self.apply("POST", "secret/data/fixture", {"data": {"value": "Beta"}}, 200)
        elif operation == "delete-latest":
            self.apply("POST", "secret/delete/fixture", {"versions": [2]}, 204)
        elif operation == "restore-latest":
            self.apply("POST", "secret/undelete/fixture", {"versions": [2]}, 204)
        elif operation == "destroy-first":
            self.apply("PUT", "secret/destroy/fixture", {"versions": [1]}, 204)
        elif operation == "revoke-second":
            self.apply("POST", "auth/token/revoke", {"token": SECOND_TOKEN}, 204)
        else:
            raise RuntimeError("unsupported Vault fixture operation")


if __name__ == "__main__":
    try:
        Client(sys.argv[1], sys.argv[2]).operate(sys.argv[3])
    except Exception:
        print("Vault fixture control failed", file=sys.stderr)
        sys.exit(1)
    print("Vault fixture control passed")
