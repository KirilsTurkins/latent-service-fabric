These are exact public metadata bytes from the first successful Kubernetes
bootstrap, source `c404b9467466d16a39b76acd6171fdbb456f7542`, owner
`lsf-112-8c22b65b1529`. The original Linux root is
`/bench/kubernetes/lsf-112-8c22b65b1529`.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| bootstrap.json | 8005 | 94312e41af0907ca440a869f9ce3023facb1ba7f1778eeea0e295a43cd2c2501 |
| bootstrap.ndjson | 73155 | a31d96ced713f68154ff6616b3fa4511cec080994f1842987e352487a162afe9 |

The fourteen original operations verify the Docker API, owned nodes,
controller connection, kubectl download, Kubernetes node UIDs, and worker
directory creation. No guest invocation occurs in this fixture. Credential
contents and the large kubectl binary/archive are excluded. Tests validate the
original journal independently and use a separate tiny synthetic archive for
the tar/member/hash checks; these fixture files alone are not a complete
publishable bootstrap proof.
