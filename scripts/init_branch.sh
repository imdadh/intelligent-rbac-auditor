#!/usr/bin/env bash
# Creates and checks out the feature branch for the Intelligent RBAC Policy Auditor.
#
# Usage:
#   chmod +x scripts/init_branch.sh
#   ./scripts/init_branch.sh
#
# Idempotent: if the branch already exists locally it is checked out without
# attempting a duplicate create.
set -euo pipefail

BRANCH="feature/intelligent-rbac-auditor"

if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
    echo "Branch '${BRANCH}' already exists — checking it out."
    git checkout "${BRANCH}"
else
    git checkout -b "${BRANCH}"
    echo "Created and checked out branch '${BRANCH}'."
fi
