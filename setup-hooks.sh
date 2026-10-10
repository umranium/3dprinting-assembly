#!/usr/bin/env bash
# Script to install the git pre-commit hook in this repository.

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

if [ ! -d ".git" ]; then
    echo "Error: Not a git repository or not at the project root."
    exit 1
fi

echo "Installing Git pre-commit hook..."
mkdir -p .git/hooks
cp githooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

echo "Git pre-commit hook successfully installed! Checks will run automatically before every commit."
