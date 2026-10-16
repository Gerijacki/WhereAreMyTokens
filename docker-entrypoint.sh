#!/bin/sh
# docker run ghcr.io/gerijacki/wherearemytokens [serve | demo | <command>]
#   serve (default)  the dashboard, API and collector on :8787
#   demo             the same on synthetic data: nothing is read from your machine
#   anything else    run as is, e.g. `wamt agent` or `wamt device add laptop`
set -e
case "${1:-serve}" in
  serve)
    shift $(( $# > 0 ? 1 : 0 ))
    exec wamt serve --host 0.0.0.0 --port 8787 "$@" ;;
  demo)
    export WAMT_DATABASE_URL="sqlite:////tmp/wamt-demo.db" WAMT_CLAUDE_DATA_DIR=/tmp/demo-data WAMT_SOURCE_NAME=demo
    wamt demo --dir /tmp/demo-data
    wamt ingest > /dev/null && wamt insights > /dev/null  # complete on the first page load
    echo "WhereAreMyTokens demo: open http://localhost:8787 (or the port you published)"
    exec wamt serve --host 0.0.0.0 --port 8787 ;;
  *)
    exec "$@" ;;
esac
