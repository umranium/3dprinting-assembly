#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
    fi
else
    source .venv/bin/activate
fi

if [ "$1" == "--check" ]; then
    echo "Checking code formatting with Ruff..."
    python -m ruff format --check .
    echo "Checking lint rules with Ruff..."
    python -m ruff check .
else
    echo "Formatting code with Ruff..."
    python -m ruff format .
    echo "Organizing imports with Ruff..."
    python -m ruff check --select I --fix .
fi
