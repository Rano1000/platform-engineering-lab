{{- define "golden-path-api.name" -}}
golden-path-api
{{- end }}

{{- define "golden-path-api.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "golden-path-api.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "golden-path-api.labels" -}}
app.kubernetes.io/name: {{ include "golden-path-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end }}

{{- define "golden-path-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "golden-path-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
