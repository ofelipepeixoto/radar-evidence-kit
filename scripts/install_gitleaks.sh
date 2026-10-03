#!/usr/bin/env bash
# Original Radar control; fixed official asset, verified before execution.
set -euo pipefail
task_scan_dir="${1:?Informe um diretório temporário dedicado}"
mkdir -p "$task_scan_dir"
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
  --max-time 120 --retry 0 \
  https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz \
  --output "$task_scan_dir/gitleaks.tar.gz"
(cd "$task_scan_dir" && printf '%s  %s\n' \
  '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb' \
  'gitleaks.tar.gz' | sha256sum --check --status)
tar --no-same-owner -xzf "$task_scan_dir/gitleaks.tar.gz" -C "$task_scan_dir" gitleaks LICENSE
test "$("$task_scan_dir/gitleaks" version)" = '8.30.1'
