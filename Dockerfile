# syntax=docker/dockerfile:1.0-experimental

ARG base_version=1.0.1
ARG registry=quay.io

FROM ${registry}/ncigdc/python37-builder:${base_version} as build

RUN mkdir -p -m 0600 ~/.ssh && ssh-keyscan github.com >> ~/.ssh/known_hosts

COPY requirements.txt /app/requirements.txt
WORKDIR /app
RUN --mount=type=ssh pip install --no-deps -r requirements.txt

COPY . .

RUN pip install --no-deps .

FROM ${registry}/ncigdc/python37:${base_version}

COPY --from=build /usr/local/lib/python3.7/dist-packages /usr/local/lib/python3.7/dist-packages
COPY --from=build /usr/local/bin/esbuild-cli /usr/local/bin/

ENTRYPOINT [ "/usr/local/bin/esbuild-cli" ]
