FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df
RUN groupadd --gid 10001 lsf-edge && useradd --uid 10001 --gid 10001 --no-create-home lsf-edge
COPY --chown=0:0 tools/trusted_edge/config.mjs tools/trusted_edge/request.mjs tools/trusted_edge/edge.mjs tools/trusted_edge/upstream.mjs tools/trusted_edge/compressed.mjs tools/trusted_edge/representation.mjs /opt/lsf/edge/
COPY --chown=0:0 tools/static-release/files.mjs tools/static-release/model.mjs /opt/lsf/static-release/
USER 10001:10001
ENV UV_THREADPOOL_SIZE=4
WORKDIR /opt/lsf
ENTRYPOINT ["node", "--max-old-space-size=128", "/opt/lsf/edge/edge.mjs"]
CMD ["/etc/lsf/edge.json"]
