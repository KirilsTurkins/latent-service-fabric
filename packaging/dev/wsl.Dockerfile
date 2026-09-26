# Build-time Docker only. End users import the authenticated rootfs with WSL2.
FROM python@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419 AS python
FROM ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3
ARG DEBIAN_FRONTEND=noninteractive
ARG UBUNTU_SNAPSHOT=20260924T120000Z
# The pinned Python image supplies TLS roots until the pinned Ubuntu CA package
# is installed. Repository signatures remain checked by Ubuntu's archive keyring.
COPY --from=python /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
RUN apt-get update -qq --snapshot "$UBUNTU_SNAPSHOT" \
    && apt-get install -y --no-install-recommends --snapshot "$UBUNTU_SNAPSHOT" \
    ca-certificates=20260601~24.04.1 openssl=3.0.13-0ubuntu3.15 \
    libexpat1=2.6.1-2ubuntu0.5 libgdbm6t64=1.23-5.1build1 \
    libgdbm-compat4t64=1.23-5.1build1 libreadline8t64=8.2-4build1 \
    libicu74=74.2-1ubuntu3.1 \
    readline-common=8.2-4build1 libsqlite3-0=3.45.1-1ubuntu2.8 \
    python3=3.12.3-0ubuntu2.1 python3-minimal=3.12.3-0ubuntu2.1 \
    libpython3-stdlib=3.12.3-0ubuntu2.1 python3.12=3.12.3-1ubuntu0.17 \
    python3.12-minimal=3.12.3-1ubuntu0.17 libpython3.12-stdlib=3.12.3-1ubuntu0.17 \
    libpython3.12-minimal=3.12.3-1ubuntu0.17 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=python /usr/local/ /usr/local/
RUN rm -rf /usr/local/lib/python3.13/site-packages /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13
COPY helper.pyz /opt/latent-dev/helper.pyz
COPY wsl.conf /etc/wsl.conf
COPY rootfs_inventory.py /opt/latent-dev/rootfs_inventory.py
COPY LSF-LICENSE /opt/latent-dev/LSF-LICENSE
COPY source.json /opt/latent-dev/source.json
RUN ldconfig && chmod 0755 /opt/latent-dev && chmod 0644 /opt/latent-dev/* /etc/wsl.conf \
    && /usr/local/bin/python3.13 -I /opt/latent-dev/rootfs_inventory.py \
    && /usr/bin/python3 -I -c 'import ctypes, fcntl, hashlib, json, ssl, subprocess, tarfile, zipfile' \
    && /usr/local/bin/python3.13 -I -c 'import bz2, ctypes, dbm.gnu, fcntl, hashlib, lzma, readline, sqlite3, ssl, zipfile; import sys; assert sys.version_info[:3] == (3, 13, 5)'
# No listener, system service, compiler, kernel or caller credentials in this image.
CMD ["/usr/sbin/nologin"]
