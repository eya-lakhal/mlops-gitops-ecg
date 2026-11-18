{{/* Nom court du chart */}}
{{- define "ecg-api.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Nom complet des ressources : <release>-<chart>, ou le release seul s'il contient déjà le nom */}}
{{- define "ecg-api.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/* Labels de sélection : immuables une fois le Deployment créé */}}
{{- define "ecg-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ecg-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Labels communs recommandés par Kubernetes */}}
{{- define "ecg-api.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "ecg-api.selectorLabels" . }}
app.kubernetes.io/version: {{ include "ecg-api.imageTag" . | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: mlops-gitops-ecg
{{- end }}

{{- define "ecg-api.imageTag" -}}
{{- default .Chart.AppVersion .Values.image.tag }}
{{- end }}

{{- define "ecg-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "ecg-api.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
