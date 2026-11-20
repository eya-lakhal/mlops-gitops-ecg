{{/*
Gabarit de Pod partagé par le Deployment (Phase 4) et le Rollout (Phase 7) : une seule
définition de la sécurité, des sondes et des ressources, quel que soit le contrôleur.
*/}}
{{- define "ecg-api.podTemplate" -}}
metadata:
  {{- with .Values.podAnnotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  labels:
    {{- include "ecg-api.labels" . | nindent 4 }}
    {{- with .Values.podLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  {{- with .Values.imagePullSecrets }}
  imagePullSecrets:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  serviceAccountName: {{ include "ecg-api.serviceAccountName" . }}
  automountServiceAccountToken: {{ .Values.serviceAccount.automount }}
  securityContext:
    {{- toYaml .Values.podSecurityContext | nindent 4 }}
  containers:
    - name: api
      image: "{{ .Values.image.repository }}:{{ include "ecg-api.imageTag" . }}"
      imagePullPolicy: {{ .Values.image.pullPolicy }}
      securityContext:
        {{- toYaml .Values.securityContext | nindent 8 }}
      ports:
        - name: http
          containerPort: {{ .Values.containerPort }}
          protocol: TCP
      env:
        {{- range $key, $value := .Values.env }}
        - name: {{ $key }}
          value: {{ $value | quote }}
        {{- end }}
        - name: FAULT_RATE
          value: {{ .Values.faultRate | quote }}
      startupProbe:
        {{- toYaml .Values.startupProbe | nindent 8 }}
      livenessProbe:
        {{- toYaml .Values.livenessProbe | nindent 8 }}
      readinessProbe:
        {{- toYaml .Values.readinessProbe | nindent 8 }}
      resources:
        {{- toYaml .Values.resources | nindent 8 }}
      volumeMounts:
        # Racine en lecture seule : /tmp reste inscriptible pour Python et torch.
        - name: tmp
          mountPath: /tmp
  volumes:
    - name: tmp
      emptyDir:
        sizeLimit: 64Mi
  {{- with .Values.nodeSelector }}
  nodeSelector:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with .Values.affinity }}
  affinity:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with .Values.tolerations }}
  tolerations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
