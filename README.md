# mlops-gitops-ecg

Plateforme MLOps de bout en bout pour la détection d'anomalies cardiaques sur ECG
(base MIT-BIH, modèle CNN-BiLSTM) : entraînement suivi par MLflow, API FastAPI,
CI/CD GitHub Actions, GitOps avec ArgoCD, observabilité Prometheus/Grafana,
canary avec Argo Rollouts, suivi de dérive avec Evidently, infrastructure Terraform sur Azure.

> Projet en cours de construction, une phase à la fois.

## Feuille de route

- [x] 1. Entraînement du modèle suivi avec MLflow
- [x] 2. API de prédiction FastAPI + Prometheus, image Docker non-root
- [ ] 3. CI/CD GitHub Actions (tests, helm lint, build, Trivy, GHCR, mise à jour GitOps du tag)
- [ ] 4. Kubernetes local (kind) + Helm + ArgoCD
- [ ] 5. Observabilité : kube-prometheus-stack, SLO 99 %, budget d'erreur, alertes Discord
- [ ] 6. Autoscaling HPA + test de charge k6
- [ ] 7. Déploiement canary d'une nouvelle version du modèle (Argo Rollouts)
- [ ] 8. Surveillance de la dérive des données (Evidently)
- [ ] 9. Terraform sur Azure for Students
- [ ] 10. Documentation : architecture, problèmes rencontrés, postmortem

## Phase 1 : entraînement suivi avec MLflow

- **Données** : MIT-BIH, dérivation MLII filtrée de 0,5 à 40 Hz, fenêtre de 256 points autour du pic R + 4 features RR,
  4 classes AAMI (N, S, V, F).
- **Évaluation honnête** : découpage **inter-patient** de de Chazal (DS1 pour l'entraînement et la validation, DS2 pour le test,
  aucun patient en commun). Un découpage aléatoire par battement donne ~99 % grâce à une fuite de données.
- **Modèle** : CNN 1D → BiLSTM → concaténation des features RR → classification. Perte pondérée par classe, early stopping
  sur le macro-F1 de validation.
- **MLflow** : paramètres, courbes, matrice de confusion, commit Git, modèle avec signature ; chaque run crée une
  version dans le Model Registry, et l'alias `@champion` n'avance que si le macro-F1 de test progresse.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python -m pip install -e ".[train,dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ecg.data                      # téléchargement + préparation DS1/DS2
.venv\Scripts\python -m ecg.train                     # entraînement avec params.yaml
.venv\Scripts\python -m ecg.train --set train.lr=0.0005   # expérience sans modifier le YAML
.venv\Scripts\mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5000
```

| Run | Changement | Accuracy | Macro-F1 | Rappel S | Rappel V | Promu |
|---|---|---|---|---|---|---|
| v1 | référence (`class_weight_power=0.5`) | 0,907 | **0,427** | 0,00 | 0,87 | ✅ champion |
| v2 | `class_weight_power=1.0`, `dropout=0.5` | 0,742 | 0,390 | 0,11 | 0,87 | ❌ |

Limite connue : la classe S (supraventriculaire) n'est pas reconnue chez des patients inconnus ; une version améliorée
des features RR est prévue pour la Phase 7 (déploiement canary). Détails dans
[docs/problemes-rencontres.md](docs/problemes-rencontres.md).

## Phase 2 : API de prédiction conteneurisée

- **Export découplé** : `ecg.export` copie le modèle `@champion` hors de MLflow (poids `state_dict` + `metadata.json`
  avec version, run_id, métriques et SHA-256). Le dossier est versionné ; **une image = un modèle précis**.
- **Chargement sûr** : `torch.load(weights_only=True)` (pas d'exécution de code arbitraire) et vérification du SHA-256 ;
  l'API refuse de démarrer si les poids ont été modifiés.
- **API FastAPI** : `POST /predict` (1 à 256 battements de 260 valeurs, validés par Pydantic), `/health` (liveness),
  `/ready` (readiness), `/model`, `/metrics`.
- **Prometheus** : signaux RED (`http_requests_total`, `http_request_duration_seconds`) étiquetés par gabarit de route,
  avec une cardinalité bornée ; signaux métier (`ecg_predictions_total`, `ecg_prediction_confidence`, `ecg_model_info`).
- **Docker** : multi-stage, torch CPU, utilisateur UID 10001 sans shell, modèle en lecture seule, HEALTHCHECK.

```powershell
.venv\Scripts\python -m ecg.export                    # MLflow @champion -> models/ecg-cnn-bilstm
docker build -t ecg-api:0.1.0 .
docker run -d --name ecg-api -p 8000:8000 ecg-api:0.1.0
Invoke-RestMethod -Method Post -Uri http://localhost:8000/predict -ContentType "application/json" -InFile samples\beats.json
```

## Prérequis

Windows 11 + WSL2, Docker Desktop, kind, kubectl, Helm, Git, Python 3.11,
k6, Trivy, Terraform, Azure CLI, GitHub CLI.
