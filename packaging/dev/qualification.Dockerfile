# Qualification OS prerequisites only: no LSF source, runtime compiler or SDK.
FROM python@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419 AS python
FROM ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3 AS prerequisites
ARG DEBIAN_FRONTEND=noninteractive
ARG UBUNTU_SNAPSHOT=20260924T120000Z
COPY --from=python /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
RUN apt-get update -qq --snapshot "$UBUNTU_SNAPSHOT" \
    && apt-get install -y --no-install-recommends --snapshot "$UBUNTU_SNAPSHOT" \
       ca-certificates=20260601~24.04.1 openssl=3.0.13-0ubuntu3.15 \
       openssh-client=1:9.6p1-3ubuntu13.19 openssh-server=1:9.6p1-3ubuntu13.19 \
       python3=3.12.3-0ubuntu2.1 libexpat1=2.6.1-2ubuntu0.5 \
       libgdbm6t64=1.23-5.1build1 libgdbm-compat4t64=1.23-5.1build1 \
       libreadline8t64=8.2-4build1 libsqlite3-0=3.45.1-1ubuntu2.8 libicu74=74.2-1ubuntu3.1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=python /usr/local/ /usr/local/
RUN rm -rf /usr/local/lib/python3.13/site-packages /usr/local/bin/pip* \
    && ldconfig \
    && useradd --uid 23001 --create-home --shell /bin/bash lsfqa \
    && useradd --uid 23002 --create-home --shell /bin/bash lsfremote \
    && chmod 0700 /home/lsfqa /home/lsfremote \
    && passwd -d lsfremote
FROM prerequisites
# This helper was independently authenticated and extracted before image build.
# It is copied here, and will execute only as the dedicated unprivileged users.
COPY --chown=0:0 helper.pyz /opt/latent-dev/helper.pyz
COPY --chown=0:0 conductor/ /qualification/
RUN chmod 0755 /opt/latent-dev /qualification \
    && chmod 0644 /opt/latent-dev/helper.pyz /qualification/*.py
ENTRYPOINT ["/usr/local/bin/python3.13", "-I", "-B", "/qualification/dev_packaged_linux_entry.py"]
