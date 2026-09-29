#!/bin/zsh
cd "$(dirname "$0")"
source .venv/bin/activate
exec python diktering.py
