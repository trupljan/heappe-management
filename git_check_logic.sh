#!/bin/bash
set -e
REPO_PATH=$1
cd "$REPO_PATH"
git config --global --add safe.directory "$REPO_PATH"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git fetch --quiet origin "$CURRENT_BRANCH"
LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse FETCH_HEAD)
echo "{\"local\": \"$LOCAL_HASH\", \"remote\": \"$REMOTE_HASH\", \"branch\": \"$CURRENT_BRANCH\"}"