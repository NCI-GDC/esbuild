ARG BASE_VERSION=3.1.0
ARG REGISTRY=docker.osdc.io/ncigdc
ARG PYTHON_VERSION=python3.13

FROM ${REGISTRY}/${PYTHON_VERSION}-builder:${BASE_VERSION} AS build
ARG PIP_INDEX_URL
ENV PIP_INDEX_URL=$PIP_INDEX_URL
ARG SERVICE_NAME=esbuild

# avoids used detach heads in computing versions in gitlab
ARG GIT_BRANCH_NAME
ENV CI_COMMIT_REF_NAME=$GIT_BRANCH_NAME

WORKDIR /${SERVICE_NAME}
COPY . .

RUN pip install --upgrade setuptools pip \
    && pip install versionista>=1.1.0

# confirm the version number is expected and does not include +dirty
# this is due to the COPY . . that might be missing some file entries
# due to .dockerignore.
RUN python3 -m setuptools_scm \
    && pip install --no-deps -r requirements.txt .

FROM ${REGISTRY}/${PYTHON_VERSION}:${BASE_VERSION}

ARG BUILD_DATE
ARG COMMIT
ARG GIT_BRANCH
ARG SERVICE_NAME
ARG PYTHON_VERSION
ENV GIT_COMMIT=$COMMIT

LABEL org.opencontainers.image.title="${SERVICE_NAME}" \
      org.opencontainers.image.description="Docker image for building the GDC Elasticsearch indices." \
      org.opencontainers.image.source="https://github.com/NCI-GDC/${SERVICE_NAME}" \
      org.opencontainers.image.vendor="NCI GDC" \
      org.opencontainers.image.ref.name="${SERVICE_NAME}:${GIT_BRANCH}" \
      org.opencontainers.image.revision="${COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}"

COPY --from=build /venv/lib/${PYTHON_VERSION}/site-packages /venv/lib/${PYTHON_VERSION}/site-packages
COPY --from=build \
     /venv/bin/esbuild-cli \
     /venv/bin/compare_indices.py \
     /venv/bin/master.py \
     /venv/bin/minion.py \
     /venv/bin/

WORKDIR /app
