#!/bin/bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="AutumnDesktop"
SCHEME="AutumnDesktop"
BUNDLE_ID="com.autumn.desktop"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$ROOT_DIR/desktop"
PROJECT_FILE="$PROJECT_DIR/AutumnDesktop.xcodeproj"
DERIVED_DATA="/tmp/autumn_desktop_derived"
LOG_DIR="$ROOT_DIR/build/logs"
LOG_FILE="$LOG_DIR/build_and_run.log"
APP_BUNDLE="$DERIVED_DATA/Build/Products/Debug/$APP_NAME.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/$APP_NAME"

usage() {
  echo "usage: $0 [run|--debug|--logs|--telemetry|--verify]" >&2
}

if ! command -v xcodegen >/dev/null 2>&1; then
  echo "error: xcodegen is required. Install with: brew install xcodegen" >&2
  exit 1
fi

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

mkdir -p "$LOG_DIR"
: >"$LOG_FILE"

echo "Generating Xcode project..."
(cd "$PROJECT_DIR" && xcodegen generate) >>"$LOG_FILE" 2>&1

echo "Building $APP_NAME..."
if ! xcodebuild \
    -project "$PROJECT_FILE" \
    -scheme "$SCHEME" \
    -configuration Debug \
    -destination 'platform=macOS,name=My Mac' \
    -derivedDataPath "$DERIVED_DATA" \
    build >>"$LOG_FILE" 2>&1; then
  echo "Build failed. Last log lines:" >&2
  tail -80 "$LOG_FILE" >&2
  exit 1
fi

echo "Build succeeded. Log: $LOG_FILE"

open_app() {
  /usr/bin/open -n "$APP_BUNDLE"
}

case "$MODE" in
  run)
    open_app
    ;;
  --debug|debug)
    lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    open_app
    sleep 2
    if ! pgrep -x "$APP_NAME" >/dev/null; then
      echo "$APP_NAME did not stay running. Recent launch policy/log lines:" >&2
      /usr/bin/log show --last 1m --style compact \
        --predicate "process == \"$APP_NAME\" || eventMessage CONTAINS[c] \"$APP_NAME\"" 2>/dev/null \
        | tail -40 >&2 || true
      exit 1
    fi
    echo "$APP_NAME is running."
    ;;
  *)
    usage
    exit 2
    ;;
esac
