#!/usr/bin/env bash
# Run only an already installed, authorized standalone Mule runtime.
set -euo pipefail
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "console" && "$1" != "start" ) ]]; then
  echo "Usage: launch.sh [console|start] (requires P06_MULE_HOME, JAVA_HOME and P06_RUNTIME_CONFIG)" >&2
  exit 2
fi
: "${P06_MULE_HOME:?Set the authorized existing Mule runtime directory}"
: "${JAVA_HOME:?Set the reviewed Java 17 installation}"
: "${P06_RUNTIME_CONFIG:?Set the protected external Mule configuration file}"
if [[ ! -x "$P06_MULE_HOME/bin/mule" || ! -x "$JAVA_HOME/bin/java" || ! -r "$P06_RUNTIME_CONFIG" ]]; then
  echo "The runtime, Java installation or protected configuration file is unavailable." >&2
  exit 2
fi
if [[ "$P06_RUNTIME_CONFIG" != /* ]]; then
  echo "P06_RUNTIME_CONFIG must be an absolute path outside the checkout." >&2
  exit 2
fi
p06_java_version="$("$JAVA_HOME/bin/java" -version 2>&1)"
if [[ ! "$p06_java_version" =~ version\ \"17[.\"] ]]; then
  echo "This Mule profile requires Java 17. No runtime was started." >&2
  exit 2
fi
# These are JVM system properties, not YAML application properties. Do not add
# user-supplied trailing arguments that could override the retry policy.
exec "$P06_MULE_HOME/bin/mule" "${1:-console}" \
  -M-Dmule.http.client.maxRetries=0 \
  -M-Dmule.http.client.retryOnAllMethods=false \
  "-M-DP06_RUNTIME_CONFIG=$P06_RUNTIME_CONFIG"
