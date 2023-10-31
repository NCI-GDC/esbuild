#!/bin/bash
set -eox pipefail

PARAM=${1:-DO_NOT_PUSH};

IMAGE_NAME="${DOCKER_RELEASE_REGISTRY:=quay.io}/ncigdc/esbuild"

# setup active branch name, default to using git if build is happening on local
if [ ${TRAVIS_BRANCH+x} ]; then
  GIT_BRANCH=$TRAVIS_BRANCH;
  GIT_COMMIT_HASH=$TRAVIS_COMMIT
elif [ ${GITLAB_CI+x} ]; then
  GIT_BRANCH=$CI_COMMIT_REF_NAME
  GIT_COMMIT_HASH=$CI_COMMIT_SHA
else
  GIT_BRANCH=$(git symbolic-ref --short -q HEAD);
  GIT_COMMIT_HASH=$(git rev-parse HEAD)
fi

# replace slashes with underscore
GIT_BRANCH=${GIT_BRANCH/\//_}

VERSION=$(cat VERSION.txt)

BUILD_COMMAND=(build \
  --label org.opencontainers.image.version="${VERSION}" \
  --label org.opencontainers.image.created="$(date -Iseconds)" \
  --label org.opencontainers.image.revision="${GIT_COMMIT_HASH}" \
  --label org.opencontainers.ref.name="esbuild:${GIT_BRANCH}" \
  --build-arg CURRENT_VERSION="${BASE_CONTAINER_VERSION:=2.3.1}" \
  --build-arg REGISTRY="${BASE_CONTAINER_REGISTRY%\/ncigdc}" \
  --build-arg GIT_COMMIT_HASH="${GIT_COMMIT_HASH}" \
  --ssh default \
  -t "$IMAGE_NAME:$GIT_BRANCH" \
  -t "$IMAGE_NAME:$GIT_COMMIT_HASH")

docker "${BUILD_COMMAND[@]}" .

if [ "$PARAM" = "push" ]; then
  docker image ls "$IMAGE_NAME"
  docker push -a "$IMAGE_NAME"
fi
