FROM docker@sha256:eb952fbf036947347bff9f303878c86ec3df00af0341f4cca59b1d1924d6668d AS docker
FROM python:3.13.5-slim-bookworm@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419
COPY --from=docker /usr/local/bin/docker /usr/bin/docker
ENTRYPOINT ["/usr/local/bin/python3", "-I", "/source/tools/container_runtime/qualification_operator.py"]
