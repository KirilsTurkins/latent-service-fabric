FROM debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818
COPY optimization-container /opt/lsf/optimization-container
COPY app/ /opt/lsf/
ENTRYPOINT ["/opt/lsf/optimization-container"]
