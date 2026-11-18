# mlops-gitops-ecg

Plateforme MLOps de bout en bout pour la détection d'anomalies cardiaques sur ECG
(base MIT-BIH, modèle CNN-BiLSTM) : entraînement suivi par MLflow, API FastAPI,
CI/CD GitHub Actions, GitOps avec ArgoCD, observabilité Prometheus/Grafana,
canary avec Argo Rollouts, suivi de dérive avec Evidently, infrastructure Terraform sur Azure.

> Projet en cours de construction, une phase à la fois.

## Feuille de route

- [ ] 1. Entraînement du modèle suivi avec MLflow
- [ ] 2. API de prédiction FastAPI + Prometheus, image Docker non-root
- [ ] 3. CI/CD GitHub Actions (tests, helm lint, build, Trivy, GHCR, mise à jour GitOps du tag)
- [ ] 4. Kubernetes local (kind) + Helm + ArgoCD
- [ ] 5. Observabilité : kube-prometheus-stack, SLO 99 %, budget d'erreur, alertes Discord
- [ ] 6. Autoscaling HPA + test de charge k6
- [ ] 7. Déploiement canary d'une nouvelle version du modèle (Argo Rollouts)
- [ ] 8. Surveillance de la dérive des données (Evidently)
- [ ] 9. Terraform sur Azure for Students
- [ ] 10. Documentation : architecture, problèmes rencontrés, postmortem

## Prérequis

Windows 11 + WSL2, Docker Desktop, kind, kubectl, Helm, Git, Python 3.11,
k6, Trivy, Terraform, Azure CLI, GitHub CLI.
