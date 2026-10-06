#!/bin/sh
# Installs secret-drop for the current user. It lists every change and asks before making it.
exec python3 "$(cd "$(dirname "$0")" && pwd)/secret-drop" install "$@"
