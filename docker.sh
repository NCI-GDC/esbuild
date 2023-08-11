#!/bin/bash
set -eo pipefail

PARAM=${1:-push};

IMAGE_NAME="${DOCKER_RELEASE_REGISTRY:=quay.io}/ncigdc/esbuild"

# setup active branch name, default to using git if build is happening on local
if [ ${TRAVIS_BRANCH+x} ]; then
  GIT_BRANCH=$TRAVIS_BRANCH;
elif [ ${GITLAB_CI+x} ]; then
  GIT_BRANCH=$CI_COMMIT_BRANCH
else
  GIT_BRANCH=$(git symbolic-ref --short -q HEAD);
fi

# replace slashes with underscore
GIT_BRANCH=${GIT_BRANCH/\//_}

VERSION=$(cat VERSION.txt)

BUILD_COMMAND=(build \
  --label org.opencontainers.image.version="${VERSION}" \
  --label org.opencontainers.image.created="$(date -Iseconds)" \
  --label org.opencontainers.image.revision="$(git rev-parse HEAD)" \
  --label org.opencontainers.ref.name="esbuild:${GIT_BRANCH}" \
  --build-arg CURRENT_VERSION="${BASE_CONTAINER_VERSION}" \
  --ssh default -t "$IMAGE_NAME:$GIT_BRANCH")

echo "${BUILD_COMMAND[@]}"

docker "${BUILD_COMMAND[@]}" .

if [ "$PARAM" = "push" ]; then
  docker push "$IMAGE_NAME:$GIT_BRANCH"
fi
