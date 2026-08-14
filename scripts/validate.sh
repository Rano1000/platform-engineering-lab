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
    if has shellcheck && ! shellcheck -x "$file"; then
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

check_platform() {
  cluster_config=platform/bootstrap/kind/cluster.yaml
  baseline_dir=platform/baseline
  expected_image='kindest/node:v1.35.0@sha256:452d707d4862f52530247495d180205e029056831160e22870e37e3f6c1ac31f'

  control_planes=$(grep -Ec '^  - role: control-plane$' "$cluster_config")
  workers=$(grep -Ec '^  - role: worker$' "$cluster_config")
  pinned_images=$(grep -Ec "^    image: $expected_image$" "$cluster_config")
  cluster_names=$(grep -Ec '^name: platform-engineering-lab$' "$cluster_config")
  kubeadm_versions=$(grep -Ec '^        apiVersion: kubeadm\.k8s\.io/v1beta3$' "$cluster_config")
  ingress_patches=$(grep -Fc 'node-labels: "ingress-ready=true"' "$cluster_config")
  if [ "$control_planes" -eq 1 ] && [ "$workers" -eq 2 ] && [ "$pinned_images" -eq 3 ] && [ "$cluster_names" -eq 1 ] && [ "$kubeadm_versions" -eq 1 ] && [ "$ingress_patches" -eq 1 ]; then
    pass 'kind configuration pins one control plane and two workers to the approved image digest.'
  else
    fail 'kind topology, image pin, or kubeadm patch does not match the Phase 1 design.'
  fi

  if grep -Eq '^  apiServerAddress: 127\.0\.0\.1$' "$cluster_config" &&
     [ "$(grep -Ec '^        listenAddress: 127\.0\.0\.1$' "$cluster_config")" -eq 2 ] &&
     grep -Eq '^        hostPort: 80$' "$cluster_config" &&
     grep -Eq '^        hostPort: 443$' "$cluster_config"; then
    pass 'Kubernetes API, HTTP, and HTTPS bindings are restricted to loopback.'
  else
    fail 'expected loopback-only API, HTTP, and HTTPS bindings are missing.'
  fi

  if kubectl kustomize "$baseline_dir" >/dev/null; then
    pass 'Kubernetes baseline renders with kubectl kustomize.'
  else
    fail 'Kubernetes baseline rendering failed.'
  fi

  namespace_count=$(grep -Ec '^  name: (platform-system|platform-apps|observability|security|gitops)$' "$baseline_dir/namespaces.yaml")
  deny_count=$(grep -Ec '^  name: default-deny$' "$baseline_dir/network-policies.yaml")
  dns_count=$(grep -Ec '^  name: allow-dns-egress$' "$baseline_dir/network-policies.yaml")
  if [ "$namespace_count" -eq 5 ] && [ "$deny_count" -eq 5 ] && [ "$dns_count" -eq 5 ]; then
    pass 'all five owned namespaces have default-deny and DNS egress policies.'
  else
    fail 'namespace or NetworkPolicy baseline is incomplete.'
  fi

  if grep -Eq '^    requests\.storage: 20Gi$' "$baseline_dir/resource-controls.yaml" &&
     grep -Eq '^        storage: 10Gi$' "$baseline_dir/resource-controls.yaml"; then
    pass 'application storage requests and individual claims are bounded.'
  else
    fail 'application storage constraints differ from the approved local budget.'
  fi

  if has kubeconform; then
    if kubectl kustomize "$baseline_dir" | kubeconform -kubernetes-version 1.35.0 -strict -summary; then
      pass 'Kubernetes schemas pass kubeconform.'
    else
      fail 'Kubernetes schema validation failed.'
    fi
  else
    warn 'kubeconform is unavailable; Kustomize rendering passed without schema validation.'
  fi
}

case "$MODE" in
  all) check_format; check_links; check_secrets; check_make; check_shell; check_markdown; check_yaml; check_platform ;;
  lint) check_make; check_shell; check_markdown; check_yaml; check_platform ;;
  docs) check_markdown; check_links ;;
  *) printf 'usage: %s {all|lint|docs}\n' "$0" >&2; exit 2 ;;
esac

printf '\nSummary: %s failure(s), %s warning(s)\n' "$FAILURES" "$WARNINGS"
[ "$FAILURES" -eq 0 ]
