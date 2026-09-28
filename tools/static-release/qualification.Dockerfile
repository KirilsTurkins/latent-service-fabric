# Disposable frontend qualification only; this is not a runtime hosting image.
FROM ghcr.io/project-zot/zot-minimal-linux-amd64@sha256:f1ffb7a5bbddc0feea83646e29c587ecf39b3193733b447749d4c9ead111a395 AS registry
FROM ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3
COPY --from=registry /usr/local/bin/zot-linux-amd64-minimal /usr/local/bin/zot
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates curl xz-utils libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --silent --show-error --location --max-time 120 \
      https://nodejs.org/dist/v24.19.0/node-v24.19.0-linux-x64.tar.xz -o /tmp/node.tar.xz \
    && echo '14b342e71204f811bde6153be8e04b62aef63c236fef92b55f9c83154b409647  /tmp/node.tar.xz' | sha256sum --check \
    && tar -xJf /tmp/node.tar.xz --strip-components=1 -C /usr/local \
    && rm /tmp/node.tar.xz \
    && useradd --create-home --uid 10001 frontend
USER 10001:10001
WORKDIR /home/frontend
ENTRYPOINT ["node"]
