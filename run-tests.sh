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

# Use -n auto for parallel test execution unless -n is already explicitly specified
XDIST_ARGS=()
if [[ "$*" != *"-n "* ]] && [[ "$*" != *"-n="* ]]; then
    XDIST_ARGS=("-n" "auto")
fi

# ./run-tests.sh <assembly> [body] runs everything that covers that assembly: its own tests under
# tests/<assembly>/, plus its slice of the project-wide tests/test_*_all.py suites, which
# --assembly/--body narrow (see tests/conftest.py). The generic suites that test shared machinery
# rather than any assembly (test_cli.py, test_hardware.py, ...) are left out by not naming them.
if [ -n "$1" ] && [ -d "src/$1" ]; then
    assembly="$1"
    shift

    SCOPE_ARGS=(--assembly="$assembly")
    PATHS=(tests/test_*_all.py)
    if [ -n "$1" ] && [[ "$1" != -* ]]; then
        # A body was named, so the assembly's own tests — which aren't per-body — aren't in scope.
        SCOPE_ARGS+=(--body="$1")
        shift
    elif [ -d "tests/$assembly" ]; then
        PATHS=("tests/$assembly" "${PATHS[@]}")
    fi

    python -m pytest "${XDIST_ARGS[@]}" "${SCOPE_ARGS[@]}" "${PATHS[@]}" "$@"
else
    python -m pytest "${XDIST_ARGS[@]}" "$@"
fi

