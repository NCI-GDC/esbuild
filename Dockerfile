ARG BASE_VERSION=4.4.1
ARG REGISTRY=docker.osdc.io/ncigdc
ARG PYTHON_VERSION=python3.13

FROM ${REGISTRY}/${PYTHON_VERSION}-builder:${BASE_VERSION} AS build
ARG SERVICE_NAME
ENV UV_PROJECT_ENVIRONMENT='/venv'
ENV UV_NO_DEV="true"
ENV UV_NO_EDITABLE="true"
ENV UV_LOCKED="true"

WORKDIR /${SERVICE_NAME}
COPY . .

RUN uv sync

FROM ${REGISTRY}/${PYTHON_VERSION}:${BASE_VERSION}

ARG BUILD_DATE
ARG COMMIT
ARG GIT_BRANCH
ARG SERVICE_NAME
ARG PYTHON_VERSION
ENV GIT_COMMIT=$COMMIT
ENV PATH="/venv/bin:$PATH"

LABEL org.opencontainers.image.title="${SERVICE_NAME}" \
      org.opencontainers.image.description="Docker image for building the GDC Elasticsearch indices." \
      org.opencontainers.image.source="https://github.com/NCI-GDC/${SERVICE_NAME}" \
      org.opencontainers.image.vendor="NCI GDC" \
      org.opencontainers.image.ref.name="${SERVICE_NAME}:${GIT_BRANCH}" \
      org.opencontainers.image.revision="${COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}"

# We need to install libpq for psycopg2 to function.
RUN dnf install -y libpq-17.4

COPY --from=build --chown=app:app /venv /venv

WORKDIR /app
USER app:app
