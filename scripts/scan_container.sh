#!/usr/bin/env sh
set -eu
image=${1:?Pass the built runtime image}
report=${2:-container-audit.json}
scanner_dir=$(mktemp -d)
trap 'rm -rf "$scanner_dir"' EXIT HUP INT TERM
curl -fsSL https://github.com/aquasecurity/trivy/releases/download/v0.75.0/trivy_0.75.0_Linux-64bit.tar.gz -o "$scanner_dir/scanner.tar.gz"
printf '%s  %s\n' 'c6e65abddb348e25f10549df887045629cf28cc72453cd1c63acb717316b3f3f' "$scanner_dir/scanner.tar.gz" | sha256sum -c -
tar -xzf "$scanner_dir/scanner.tar.gz" -C "$scanner_dir" trivy
"$scanner_dir/trivy" image --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --format json --output "$report" "$image"
