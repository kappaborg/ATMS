{{/*
Common labels
*/}}
{{- define "atms.labels" -}}
app.kubernetes.io/name: atms-traffic-system
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{/*
Service catalogue: values.yaml key -> k8s name + container port.
Ports are the single source of truth shared with docker-compose.services.yml.
*/}}
{{- define "atms.services" -}}
apiGateway: {name: api-gateway, port: 8000}
aiPerception: {name: ai-perception, port: 8004}
analytics: {name: analytics, port: 8005}
dashboard: {name: dashboard, port: 8006}
decisionEngine: {name: decision-engine, port: 8007}
sensorFusion: {name: sensor-fusion, port: 8008}
dataAggregator: {name: data-aggregator, port: 8009}
trafficController: {name: traffic-controller, port: 8010}
videoProcessor: {name: video-processor, port: 8018}
{{- end }}

{{/*
Image reference for a service config dict.
*/}}
{{- define "atms.image" -}}
{{- $registry := .root.Values.global.imageRegistry -}}
{{- if $registry -}}
{{ printf "%s/%s:%s" $registry .cfg.image.repository .cfg.image.tag }}
{{- else -}}
{{ printf "%s:%s" .cfg.image.repository .cfg.image.tag }}
{{- end -}}
{{- end }}
