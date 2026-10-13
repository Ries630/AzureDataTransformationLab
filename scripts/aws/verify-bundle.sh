#!/usr/bin/env bash
# 配布物の自己整合性を検査する。出所の確認には別経路のZIP hashが必要。
set -euo pipefail
bundle_root="${1:-.}"
[[ -d "$bundle_root" && ! -L "$bundle_root" ]] || { echo '通常のbundleディレクトリを指定してください。' >&2; exit 1; }
cd -- "$bundle_root"
command -v sha256sum >/dev/null || { echo 'sha256sumが必要です。WSLなどのLinuxで実行してください。' >&2; exit 1; }

# hash一覧にパスの脱出・曖昧な形式・重複・symlinkがないことを先に確認する。
check_list() {
  local list="$1" path line part cumulative
  local seen='|'
  [[ -f "$list" && ! -L "$list" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[0-9a-f]{64}\ \ .+$ ]] || return 1
    path="${line:66}"
    [[ "$path" != /* && "$path" != *\\* && "$path" != *'|'* && "$path" != *':'* ]] || return 1
    [[ "$path" != manifest.sha256 && "$path" != *$'\r'* && "$path" != *$'\t'* ]] || return 1
    [[ "$seen" != *"|$path|"* ]] || return 1
    seen="${seen}${path}|"
    cumulative=''
    IFS='/' read -r -a components <<< "$path"
    for part in "${components[@]}"; do
      [[ -n "$part" && "$part" != '.' && "$part" != '..' ]] || return 1
      cumulative="${cumulative:+$cumulative/}$part"
      [[ ! -L "$cumulative" ]] || return 1
    done
    [[ -f "$path" ]] || return 1
    if [[ "$list" == manifest.sha256 ]]; then
      [[ "$path" == manifest.json || "$path" == checksums.sha256 ]] || return 1
    else
      [[ "$path" != manifest.json && "$path" != checksums.sha256 ]] || return 1
    fi
  done < "$list"
  [[ "$seen" != '|' ]] || return 1
  if [[ "$list" == checksums.sha256 ]]; then
    payload_seen="$seen"
  fi
  if [[ "$list" == manifest.sha256 ]]; then
    [[ "$seen" == '|manifest.json|checksums.sha256|' || "$seen" == '|checksums.sha256|manifest.json|' ]] || return 1
  fi
}
check_list manifest.sha256 || { echo 'manifest hash一覧が不正です。' >&2; exit 1; }
sha256sum --check --strict manifest.sha256
check_list checksums.sha256 || { echo 'payload hash一覧が不正です。' >&2; exit 1; }
sha256sum --check --strict checksums.sha256
# 展開直後のキットだけを対象にし、一覧外ファイルや特殊ファイルも拒否する。
while IFS= read -r -d '' file; do
  [[ -f "$file" && ! -L "$file" ]] || { echo '特殊ファイルが含まれています。' >&2; exit 1; }
  relative="${file#./}"
  [[ "$relative" == manifest.json || "$relative" == manifest.sha256 || "$relative" == checksums.sha256 || "$payload_seen" == *"|$relative|"* ]] || { echo "一覧外ファイル: $relative" >&2; exit 1; }
done < <(find . -mindepth 1 ! -type d -print0)
printf '%s\n' '整合性を確認しました。出所は信頼できる別経路のZIP SHA-256と照合してください。'
