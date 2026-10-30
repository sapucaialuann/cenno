#!/bin/bash
# Creates a self-signed "Cenno Local Signing" certificate for local builds.
#
# An ad-hoc signature is tied to the exact binary, so macOS sees every rebuild
# as a new app and forgets its Camera and Accessibility permissions. Signed
# with this certificate, the app is identified by its bundle ID and the
# certificate instead, so the permissions survive rebuilds on this Mac.
#
# The certificate lives in its own keychain with a fixed password, so the
# build can unlock it without asking for yours. It only signs local test
# builds; releases need an Apple Developer ID. Run it once per Mac.
set -euo pipefail
NAME="Cenno Local Signing"
KC="$HOME/Library/Keychains/cenno-signing.keychain-db"
KC_PASS=cenno

if security find-identity -p codesigning "$KC" 2>/dev/null | grep -q "$NAME"; then
  echo "\"$NAME\" already exists in $KC"
  exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/cfg" <<EOF
[req]
distinguished_name=dn
x509_extensions=ext
prompt=no
[dn]
CN=$NAME
[ext]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature
extendedKeyUsage=critical,codeSigning
EOF
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$TMP/cfg" \
  -keyout "$TMP/key.pem" -out "$TMP/cert.pem" 2>/dev/null
openssl pkcs12 -export -legacy -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
  -out "$TMP/id.p12" -passout pass:$KC_PASS 2>/dev/null \
  || openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
       -out "$TMP/id.p12" -passout pass:$KC_PASS

[ -f "$KC" ] || security create-keychain -p $KC_PASS "$KC"
security set-keychain-settings "$KC"          # never lock on a timer
security unlock-keychain -p $KC_PASS "$KC"
security import "$TMP/id.p12" -k "$KC" -P $KC_PASS -T /usr/bin/codesign
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k $KC_PASS "$KC" >/dev/null
# Add the keychain to the search list, keeping the ones already there.
security list-keychains -d user -s $(security list-keychains -d user | tr -d '"' | grep -v cenno-signing) "$KC"
echo "created \"$NAME\" in $KC"
