#!/bin/bash
# Disposable CI proof of a no-prompt, separate code-signing Keychain.
# This uses a synthetic one-day identity, never the release certificate or key.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != true || -z "${RUNNER_TEMP:-}" ]]; then
  printf 'This probe runs only on a disposable GitHub macOS runner.\n' >&2
  exit 2
fi

probe_dir="$(mktemp -d "$RUNNER_TEMP/codex-vault-signing-XXXXXX")"
probe_keychain="$probe_dir/signing.keychain-db"
cleanup() {
  if [[ -f "$probe_keychain" ]]; then
    security delete-keychain "$probe_keychain" >/dev/null 2>&1 || true
  fi
  if [[ "$probe_dir" == "$RUNNER_TEMP"/codex-vault-signing-* ]]; then
    rm -r -- "$probe_dir"
  fi
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj '/CN=Codex Vault CI Signing Probe' \
  -addext 'basicConstraints=critical,CA:FALSE' \
  -addext 'keyUsage=digitalSignature' \
  -addext 'extendedKeyUsage=codeSigning' \
  -keyout "$probe_dir/synthetic.key" -out "$probe_dir/synthetic.crt" \
  >/dev/null 2>&1
openssl pkcs12 -export -inkey "$probe_dir/synthetic.key" \
  -in "$probe_dir/synthetic.crt" -out "$probe_dir/synthetic.p12" \
  -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1 \
  -passout pass:synthetic-ci-only >/dev/null 2>&1
openssl pkcs12 -in "$probe_dir/synthetic.p12" \
  -passin pass:synthetic-ci-only -info -noout >/dev/null 2>&1

# Empty passwords are restricted to this disposable Keychain containing only
# the synthetic CI key. Production signing must use a protected build Keychain.
security create-keychain -p '' "$probe_keychain"
security unlock-keychain -p '' "$probe_keychain"
security import "$probe_dir/synthetic.p12" -k "$probe_keychain" \
  -f pkcs12 -P synthetic-ci-only -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S 'apple-tool:,apple:' -k '' \
  "$probe_keychain" >/dev/null

cp /usr/bin/true "$probe_dir/probe-executable"
codesign --force --sign 'Codex Vault CI Signing Probe' \
  --keychain "$probe_keychain" "$probe_dir/probe-executable"
codesign --verify --strict "$probe_dir/probe-executable"
printf 'Synthetic isolated-Keychain signing passed without a GUI prompt.\n'
