# syntax=docker/dockerfile:1

ARG CURRENT_VERSION=2.3.3
ARG REGISTRY=quay.io

FROM ${REGISTRY}/ncigdc/python3.9-builder:${CURRENT_VERSION} as build

RUN mkdir -p -m 0600 ~/.ssh && ssh-keyscan github.com >> ~/.ssh/known_hosts

WORKDIR /esbuild
COPY requirements.txt requirements.txt
RUN --mount=type=ssh pip3 install --no-deps --no-cache-dir -r /esbuild/requirements.txt
COPY . .
RUN pip install --no-deps --no-cache-dir .


FROM ${REGISTRY}/ncigdc/python3.9:${CURRENT_VERSION}

ARG GIT_COMMIT_HASH
ENV GIT_COMMIT_HASH=${GIT_COMMIT_HASH}

LABEL org.opencontainers.image.title="esbuild" \
      org.opencontainers.image.description="Docker image for building the GDC Elasticsearch indices." \
      org.opencontainers.image.source="https://github.com/NCI-GDC/esbuild"

COPY --from=build /venv/lib/python3.9/site-packages /venv/lib/python3.9/site-packages
COPY --from=build \
     /venv/bin/esbuild-cli \
     /venv/bin/compare_indices.py \
     /venv/bin/master.py \
     /venv/bin/minion.py \
     /venv/bin/

WORKDIR /app
