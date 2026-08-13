#!/bin/sh
set -u

MODE=${1:-all}
FAILURES=0
WARNINGS=0

pass() { printf 'PASS  %s\n' "$*"; }
warn() { WARNINGS=$((WARNINGS + 1)); printf 'WARN  %s\n' "$*"; }
fail() { FAILURES=$((FAILURES + 1)); printf 'FAIL  %s\n' "$*"; }
has() { command -v "$1" >/dev/null 2>&1; }

tracked_files() {
  git ls-files --cached --others --exclude-standard
}

check_format() {
  bad=$(tracked_files | while IFS= read -r file; do
    [ -f "$file" ] || continue
    case "$file" in *.png|*.jpg|*.jpeg|*.gif|*.ico) continue ;; esac
    if LC_ALL=C grep -n '[[:blank:]]$' "$file" >/dev/null 2>&1; then printf '%s\n' "$file"; fi
    last=$(tail -c 1 "$file" 2>/dev/null || true)
    if [ -n "$last" ]; then printf '%s (missing final newline)\n' "$file"; fi
  done)
  if [ -z "$bad" ]; then pass 'text files have no trailing whitespace and end with a newline.'; else fail "file formatting issues:\n$bad"; fi
}

check_links() {
  if python3 - "$PWD" <<'PY'
import pathlib, re, sys
root = pathlib.Path(sys.argv[1])
errors = []
pattern = re.compile(r'(?<!!)\[[^]]+\]\(([^)]+)\)')
for source in root.rglob('*.md'):
    if '.git' in source.parts:
        continue
    for line_no, line in enumerate(source.read_text(encoding='utf-8').splitlines(), 1):
        for raw in pattern.findall(line):
            target = raw.split()[0].strip('<>').split('#', 1)[0]
            if not target or re.match(r'^[a-z][a-z0-9+.-]*:', target):
                continue
            if not (source.parent / target).resolve().exists():
                errors.append(f'{source.relative_to(root)}:{line_no}: missing {target}')
if errors:
    print('\n'.join(errors))
    raise SystemExit(1)
PY
  then pass 'internal Markdown links resolve.'; else fail 'internal Markdown links are broken.'; fi
}

check_secrets() {
  if has gitleaks; then
    if gitleaks detect --no-banner --no-git --source . >/dev/null; then pass 'gitleaks found no accidental secrets.'; else fail 'gitleaks detected a potential secret.'; fi
  else
    if tracked_files | xargs grep -EIn '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|password[[:space:]]*=[[:space:]]*[^[:space:]#]+)' 2>/dev/null; then
      fail 'portable scan detected a potential secret.'
    else
      warn 'gitleaks is unavailable; portable high-confidence secret patterns passed.'
    fi
  fi
}

check_make() {
  if has make; then
    if make --dry-run help >/dev/null; then pass 'Makefile parses and help target is runnable.'; else fail 'Makefile validation failed.'; fi
  elif awk '/^(help|doctor|validate|lint|docs-check):/ {found[$1]=1} END {exit length(found) == 5 ? 0 : 1}' Makefile; then
    warn 'GNU Make is unavailable; required target declarations exist, but Make could not parse the file.'
  else
    fail 'Makefile is missing one or more required targets.'
  fi
}

check_shell() {
  syntax_failed=0
  shellcheck_failed=0
  for file in scripts/*.sh; do
    if ! sh -n "$file"; then
      syntax_failed=1
    fi
    if has shellcheck && ! shellcheck "$file"; then
      shellcheck_failed=1
    fi
  done
  if [ "$syntax_failed" -eq 0 ]; then
    pass 'shell syntax is valid.'
  else
    fail 'shell syntax validation failed.'
  fi
  if has shellcheck; then
    if [ "$shellcheck_failed" -eq 0 ]; then
      pass 'shellcheck passed.'
    else
      fail 'shellcheck failed.'
    fi
  else
    warn 'shellcheck is unavailable; syntax checks passed.'
  fi
}

check_markdown() {
  if has markdownlint-cli2; then
    if markdownlint-cli2 '**/*.md' '#node_modules'; then
      pass 'markdownlint passed.'
    else
      fail 'markdownlint failed.'
    fi
  else
    warn 'markdownlint-cli2 is unavailable.'
  fi
}

check_yaml() {
  if has yamllint; then
    if yamllint .; then
      pass 'yamllint passed.'
    else
      fail 'yamllint failed.'
    fi
  else
    warn 'yamllint is unavailable.'
  fi
  if has actionlint; then
    if actionlint; then
      pass 'actionlint passed.'
    else
      fail 'actionlint failed.'
    fi
  else
    warn 'actionlint is unavailable.'
  fi
}

case "$MODE" in
  all) check_format; check_links; check_secrets; check_make; check_shell; check_markdown; check_yaml ;;
  lint) check_make; check_shell; check_markdown; check_yaml ;;
  docs) check_markdown; check_links ;;
  *) printf 'usage: %s {all|lint|docs}\n' "$0" >&2; exit 2 ;;
esac

printf '\nSummary: %s failure(s), %s warning(s)\n' "$FAILURES" "$WARNINGS"
[ "$FAILURES" -eq 0 ]
