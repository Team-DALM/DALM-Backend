#!/usr/bin/env bash
# Run on EC2 from a checkout at the intended release commit.
set -euo pipefail
cd "$(dirname "$0")"
test -f .env || { echo 'Create deploy/aws/.env first (see README.md).' >&2; exit 1; }
# Prevent overlapping deployments on the same host.
exec 9>.deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
export DALM_IMAGE_TAG
DALM_IMAGE_TAG="$(git rev-parse HEAD)"
docker compose config --quiet
docker compose build api
docker compose up -d --wait redis
# Never start the new API if migrations fail.
docker compose run --rm --no-deps migrate
docker compose up -d --no-build --wait --wait-timeout 180 api
curl --fail --silent --show-error http://127.0.0.1:8000/ready
