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
     grep -Eq '^      - containerPort: 30080$' "$cluster_config" &&
     grep -Eq '^        hostPort: 80$' "$cluster_config" &&
     grep -Eq '^      - containerPort: 30443$' "$cluster_config" &&
     grep -Eq '^        hostPort: 443$' "$cluster_config"; then
    pass 'API and HTTP(S) NodePort mappings are pinned to loopback.'
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

check_application() {
  chart=charts/golden-path-api
  application=applications/golden-path-api
  gateway=platform/addons/traefik-gateway
  static_revision=0123456789abcdef0123456789abcdef01234567
  static_tag=0.1.0-0123456789ab

  if python3 - "$application/src" "$application/tests" <<'PY'
import ast
import pathlib
import sys
for root in sys.argv[1:]:
    for source in pathlib.Path(root).rglob("*.py"):
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
PY
  then
    pass 'Python application and tests compile.'
  else
    fail 'Python application syntax validation failed.'
  fi

  if grep -Eq '^ARG PYTHON_IMAGE=python:3\.13\.15-slim-trixie@sha256:[0-9a-f]{64}$' "$application/Dockerfile" &&
     grep -Eq '^USER 10001:10001$' "$application/Dockerfile" &&
     grep -Fq "revision=\$(full_revision)" scripts/app.sh &&
     grep -Fq -- "--set-string \"image.revision=\$(full_revision)\"" scripts/app.sh &&
     ! grep -Eiq '(^|[^[:alnum:]])latest([^[:alnum:]]|$)' "$application/Dockerfile" "$chart/values.yaml" &&
     python3 - "$application/requirements/runtime.txt" "$application/requirements/test.txt" <<'PY'
import pathlib
import re
import sys

invalid = []
for name in sys.argv[1:]:
    for number, raw in enumerate(pathlib.Path(name).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-r "):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", line):
            invalid.append(f"{name}:{number}: {line}")
if invalid:
    print("\n".join(invalid))
    raise SystemExit(1)
PY
  then
    pass 'application image and dependencies are pinned, non-root, revision-labelled, and never use latest.'
  else
    fail 'application image pin or non-root runtime contract is incomplete.'
  fi

  if has helm; then
    if helm lint "$chart" --kube-version 1.35.0 --set-string "image.tag=$static_tag" --set-string "image.revision=$static_revision" >/dev/null &&
       helm template golden-path "$chart" --kube-version 1.35.0 --namespace platform-apps --set-string "image.tag=$static_tag" --set-string "image.revision=$static_revision" >"${TMPDIR:-/tmp}/golden-path-rendered.yaml" &&
       helm template golden-path "$chart" --kube-version 1.35.0 --namespace platform-apps --set autoscaling.enabled=true --set-string "image.tag=$static_tag" --set-string "image.revision=$static_revision" >"${TMPDIR:-/tmp}/golden-path-hpa-rendered.yaml"; then
      pass 'Helm chart lints and renders normal and HPA variants.'
    else
      fail 'Helm chart linting or rendering failed.'
      return
    fi
  else
    warn 'helm is unavailable; application chart rendering was not validated.'
    return
  fi

  rendered=${TMPDIR:-/tmp}/golden-path-rendered.yaml
  hpa_rendered=${TMPDIR:-/tmp}/golden-path-hpa-rendered.yaml

  if python3 - "$rendered" "$hpa_rendered" <<'PY'
import sys
import yaml

errors = []
for path in sys.argv[1:]:
    for document in yaml.safe_load_all(open(path, encoding="utf-8")):
        if not isinstance(document, dict):
            continue
        kind = document.get("kind")
        if kind not in {"Deployment", "DaemonSet", "StatefulSet", "Job", "Pod"}:
            continue
        spec = document.get("spec", {})
        if kind != "Pod":
            spec = spec.get("template", {}).get("spec", {})
        if spec.get("hostNetwork") is True:
            errors.append(f"{path}: {kind} declares hostNetwork: true")
        for container_type in ("containers", "initContainers", "ephemeralContainers"):
            for container in spec.get(container_type, []) or []:
                for port in container.get("ports", []) or []:
                    if int(port.get("hostPort", 0) or 0) != 0:
                        errors.append(f"{path}: {kind} declares non-zero hostPort")
if errors:
    print("\n".join(errors))
    raise SystemExit(1)
PY
  then
    pass 'rendered application Pod specifications avoid host networking and host ports.'
  else
    fail 'rendered application Pod specifications use forbidden host networking or host ports.'
  fi

  if python3 - "$rendered" <<'PY'
import sys
import yaml

routes = [doc for doc in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8"))
          if isinstance(doc, dict) and doc.get("kind") == "HTTPRoute"]
if len(routes) != 1:
    raise SystemExit(f"expected one HTTPRoute, found {len(routes)}")
rules = routes[0].get("spec", {}).get("rules", [])
matches = [match for rule in rules for match in rule.get("matches", [])]
expected = [{"path": {"type": "Exact", "value": "/"}}]
if matches != expected:
    raise SystemExit(f"public route matches differ from exact root: {matches!r}")
PY
  then
    pass 'HTTPRoute exposes only the exact root path.'
  else
    fail 'HTTPRoute must expose exactly / and no internal endpoint prefix.'
  fi

  if python3 - "$rendered" <<'PY'
import sys
import yaml

policies = [doc for doc in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8"))
            if isinstance(doc, dict) and doc.get("kind") == "NetworkPolicy"]
ingress = next((doc for doc in policies if doc["metadata"]["name"].endswith("-allow-approved-ingress")), None)
egress = next((doc for doc in policies if doc["metadata"]["name"].endswith("-metrics-test-egress")), None)
if ingress is None or egress is None:
    raise SystemExit("expected application ingress and metrics-test egress policies")
ingress_rules = ingress.get("spec", {}).get("ingress", [])
egress_rules = egress.get("spec", {}).get("egress", [])
if len(ingress_rules) != 2 or any("from" not in rule or "to" in rule for rule in ingress_rules):
    raise SystemExit(f"unexpected application ingress rules: {ingress_rules!r}")
if len(egress_rules) != 1 or "to" not in egress_rules[0] or "from" in egress_rules[0]:
    raise SystemExit(f"unexpected metrics-test egress rules: {egress_rules!r}")
for rule in ingress_rules + egress_rules:
    if rule.get("ports") != [{"protocol": "TCP", "port": 8080}]:
        raise SystemExit(f"unexpected application policy port: {rule.get('ports')!r}")
PY
  then
    pass 'application and metrics-test NetworkPolicy directions are structurally correct.'
  else
    fail 'application or metrics-test NetworkPolicy direction is incorrect.'
  fi
  if grep -q '^kind: HorizontalPodAutoscaler$' "$hpa_rendered" && ! grep -q '^kind: HorizontalPodAutoscaler$' "$rendered"; then
    pass 'HPA renders only when autoscaling is explicitly enabled.'
  else
    fail 'HPA enablement does not match the disabled-by-default contract.'
  fi

  if grep -q 'runAsUser: 10001' "$rendered" &&
     grep -q 'readOnlyRootFilesystem: true' "$rendered" &&
     grep -q 'type: RuntimeDefault' "$rendered" &&
     grep -q 'whenUnsatisfiable: ScheduleAnyway' "$rendered" &&
     grep -q 'automountServiceAccountToken: false' "$rendered"; then
    pass 'rendered workload matches the restricted Pod security contract.'
  else
    fail 'rendered workload security or scheduling contract is incomplete.'
  fi

  if grep -q '^TRAEFIK_VERSION=v3.7.10$' scripts/lib/app-common.sh &&
     grep -q '^TRAEFIK_CHART_VERSION=41.2.0$' scripts/lib/app-common.sh &&
     grep -q '^TRAEFIK_CHART_DIGEST=sha256:5d1a255b73e5dd67d70fc21b1536a405d88bf6b63896bc78dbefa15e9bfb371b$' scripts/lib/app-common.sh &&
     grep -q '^TRAEFIK_CHART_ARCHIVE_SHA256=f7f8b70f021f34164709bc6440165c0ccb79073dccb6369310d95a1c3cf8a2f0$' scripts/lib/app-common.sh &&
     grep -q '^GATEWAY_API_VERSION=v1.6.1$' scripts/lib/app-common.sh &&
     grep -q '^GATEWAY_API_SHA256=24d931f22abd8e40c973264319ead7cfa09d0fb7716b7ab1ee2ff174cb063a73$' scripts/lib/app-common.sh &&
     grep -q '^  digest: sha256:9c3b91d5fb7770853ca5c1124a23c34bf2d9b47ffaebeab2614cbaf410dcb2ac$' "$gateway/values.yaml" &&
     grep -q 'kubernetesGateway:' "$gateway/values.yaml" &&
     grep -q 'kubernetesIngress:' "$gateway/values.yaml" &&
     grep -q '^    type: NodePort$' "$gateway/values.yaml" &&
     grep -q '^    externalTrafficPolicy: Local$' "$gateway/values.yaml" &&
     grep -q '^    nodePort: 30080$' "$gateway/values.yaml" &&
     grep -q '^    nodePort: 30443$' "$gateway/values.yaml" &&
     grep -q '^  name: platform-traefik$' "$gateway/gateway.yaml" &&
     grep -q '^  gatewayClassName: platform-traefik$' "$gateway/gateway.yaml" &&
     grep -q '^  controllerName: traefik.io/gateway-controller$' "$gateway/gateway.yaml" &&
     ! grep -Eq '^[[:space:]]*hostPort:|^[[:space:]]*hostNetwork:[[:space:]]*true' "$gateway/values.yaml"; then
    pass 'Traefik versions, providers, fixed NodePorts, and Pod networking controls are pinned.'
  else
    fail 'Traefik version, provider, NodePort, or Pod networking controls are incomplete.'
  fi

  if has kubeconform; then
    if kubeconform -kubernetes-version 1.35.0 -strict -ignore-missing-schemas -summary "$rendered" "$hpa_rendered" "$gateway/gateway.yaml" "$gateway/network-policies.yaml"; then
      pass 'application and Gateway manifests pass available Kubernetes schema validation.'
    else
      fail 'application or Gateway schema validation failed.'
    fi
  else
    warn 'kubeconform is unavailable; Helm rendering passed without schema validation.'
  fi
}

case "$MODE" in
  all) check_format; check_links; check_secrets; check_make; check_shell; check_markdown; check_yaml; check_platform; check_application ;;
  lint) check_make; check_shell; check_markdown; check_yaml; check_platform; check_application ;;
  docs) check_markdown; check_links ;;
  *) printf 'usage: %s {all|lint|docs}\n' "$0" >&2; exit 2 ;;
esac

printf '\nSummary: %s failure(s), %s warning(s)\n' "$FAILURES" "$WARNINGS"
[ "$FAILURES" -eq 0 ]
