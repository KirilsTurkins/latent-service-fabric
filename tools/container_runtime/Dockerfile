FROM python:3.13.5-slim-bookworm@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419 AS python
FROM ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3
COPY --from=python /usr/local/ /usr/local/
COPY --chown=0:0 release/ /opt/lsf/release/
COPY --chown=0:0 runtime/ /opt/lsf/runtime/
RUN install -d -m 0700 -o 10001 -g 10001 /var/lib/lsf /var/cache/lsf \
    && install -d -m 0750 -o 0 -g 10001 /etc/lsf \
    && /usr/local/bin/python3 -I -c "import fcntl, hashlib, json, platform, selectors, zlib"
USER 10001:10001
WORKDIR /var/lib/lsf
ENV PYTHONDONTWRITEBYTECODE=1
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/local/bin/python3", "-I", "/opt/lsf/runtime/entrypoint.py"]
CMD ["serve"]
