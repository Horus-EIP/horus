#!/bin/sh
set -eu

cert=/etc/nginx/certs/horus.crt
key=/etc/nginx/certs/horus.key
https_conf=/etc/nginx/conf.d/https.conf

if [ "${HORUS_LAN_TLS:-0}" = "1" ] && [ -s "$cert" ] && [ -s "$key" ]; then
    echo "Horus gateway: enabling LAN HTTPS on port 3443 with the configured certificate."
    exit 0
fi

rm -f "$https_conf"
if [ "${HORUS_LAN_TLS:-0}" = "1" ]; then
    echo >&2 "Horus gateway: LAN HTTPS requested but its certificate pair is missing; LAN access stays disabled."
elif [ "$HORUS_WEB_BIND" != "127.0.0.1" ]; then
    echo >&2 "Horus gateway: LAN HTTPS disabled; install a trusted certificate and matching key at src/infra/certs/horus.crt and horus.key."
fi
