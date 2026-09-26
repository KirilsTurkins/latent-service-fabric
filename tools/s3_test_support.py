"""Synthetic SigV4 setup client for the owned S3 conformance server only."""
from __future__ import annotations

import datetime
import hashlib
import hmac
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ACCESS = "LSFPUBLICS3TEST"
SECRET = "LSF-PUBLIC-TEST-ONLY-S3-SECRET"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, port: int, ca: Path):
        self.host = f"127.0.0.1:{port}"
        self.client = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ca))))

    def request(self, method: str, path: str, query=(), body=b"", headers=None):
        now = datetime.datetime.now(datetime.timezone.utc)
        stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        payload = hashlib.sha256(body).hexdigest()
        supplied = dict(headers or {})
        supplied.update({"host": self.host, "x-amz-date": stamp, "x-amz-content-sha256": payload})
        names = sorted(supplied)
        encoded = sorted((urllib.parse.quote(k, safe="-_.~"), urllib.parse.quote(v, safe="-_.~")) for k, v in query)
        query = "&".join(k + "=" + v for k, v in encoded)
        canonical_headers = "".join(k + ":" + " ".join(supplied[k].split()) + "\n" for k in names)
        canonical = "\n".join([method, path, query, canonical_headers, ";".join(names), payload])
        scope = day + "/us-east-1/s3/aws4_request"
        to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        key = ("AWS4" + SECRET).encode()
        for value in [day, "us-east-1", "s3", "aws4_request"]:
            key = hmac.new(key, value.encode(), hashlib.sha256).digest()
        signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
        supplied["authorization"] = f'AWS4-HMAC-SHA256 Credential={ACCESS}/{scope}, SignedHeaders={";".join(names)}, Signature={signature}'
        request = urllib.request.Request("https://" + self.host + path + ("?" + query if query else ""), data=body, headers=supplied, method=method)
        try:
            response = self.client.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            result = response.read(65537)
            if len(result) > 65536:
                raise RuntimeError("S3 setup response exceeds its finite limit")
            return response.status, dict(response.headers.items()), result

    def prepare(self):
        deadline = time.monotonic() + 25
        while True:
            try:
                with self.client.open("https://" + self.host + "/minio/health/live", timeout=1) as response:
                    if response.status != 200:
                        raise RuntimeError("S3 health status")
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("bounded S3 startup failed") from None
                time.sleep(0.25)
        bucket = "/lsf-test-bucket"
        if self.request("PUT", bucket)[0] != 200:
            raise RuntimeError("S3 test bucket creation failed")
        body = b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>Enabled</Status></VersioningConfiguration>'
        if self.request("PUT", bucket, [("versioning", "")], body)[0] != 200:
            raise RuntimeError("S3 test versioning setup failed")


if __name__ == "__main__":
    import json
    import sys
    client = Client(int(sys.argv[1]), Path(sys.argv[2]))
    if len(sys.argv) == 3:
        client.prepare()
    else:
        if len(sys.argv) != 5:
            raise RuntimeError("invalid synthetic replacement arguments")
        records = Path(sys.argv[3]) / "records"
        names = list(records.iterdir())
        if len(names) > 16:
            raise RuntimeError("test inventory exceeds its expected bound")
        found = []
        for path in names:
            if path.suffix == ".json" and not path.is_symlink() and path.stat().st_size <= 16384:
                record = json.loads(path.read_bytes())
                if record["digest"] == sys.argv[4]:
                    found.append((path.stem, record["nonce"]))
        if len(found) != 1:
            raise RuntimeError("test replacement requires exactly one owned record")
        key, nonce = found[0]
        if len(key) != 64 or len(nonce) != 32 or any(c not in "0123456789abcdef" for c in key + nonce):
            raise RuntimeError("invalid test object key")
        status, _, _ = client.request("PUT", f"/lsf-test-bucket/conformance/{key}-{nonce}", body=b"different-current-version")
        if status != 200:
            raise RuntimeError("synthetic object replacement failed")
