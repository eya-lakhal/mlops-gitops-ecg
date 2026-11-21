# Journal des problèmes rencontrés

Notes prises au fil du projet ; elles alimenteront la section « Problèmes rencontrés »
du README final. Format : symptôme → cause → solution → leçon.

## Phase 0 : environnement

### Commandes « non reconnues » juste après `winget install`
- **Symptôme** : `kind : Le terme «kind» n'est pas reconnu…` alors que l'installation avait réussi.
- **Cause** : le PATH d'un processus est lu à son démarrage ; le terminal ouvert avant l'installation garde l'ancien.
- **Solution** : rouvrir le terminal.
- **Leçon** : une variable d'environnement modifiée ne se propage pas aux processus déjà lancés (même logique qu'un Pod Kubernetes qu'il faut redémarrer après un changement de ConfigMap injectée en variable d'environnement).

### Auteur Git incomplet (`+eya-lakhal@users.noreply.github.com`)
- **Cause** : `gh api user` a échoué silencieusement (gh non authentifié), la variable `$id` était vide.
- **Solution** : e-mail noreply récupéré dans les réglages GitHub, puis `git commit --amend --reset-author`.
- **Leçon** : vérifier la sortie d'une sous-commande avant de l'utiliser ; réécrire l'historique seulement tant qu'il n'est pas poussé.

## Phase 1 : entraînement

### `pip install` : `TypeError: expected string or bytes-like object, got 'NoneType'`
- **Cause** : deux `pip install` lancés en parallèle dans le même venv (un par onglet de terminal) ; le second a lu les métadonnées d'un paquet que le premier était en train d'écrire.
- **Solution** : attendre la fin de l'installation de torch, puis relancer.
- **Leçon** : pip n'a pas de verrou ; un environnement = un seul installateur à la fois.

### Premier modèle : recall S = 0 et F = 0 malgré 90 % d'accuracy
- **Symptôme** (run 1) : accuracy test 0,907, macro-F1 0,427 ; N F1 0,95, V F1 0,76, **S et F jamais prédits**. Meilleure validation dès l'époque 1, puis la validation se dégrade alors que la perte d'entraînement baisse.
- **Cause** : déséquilibre extrême (N ≈ 90 %) + découpage inter-patient : le modèle apprend la morphologie des patients d'entraînement et généralise mal ; l'accuracy masque l'échec sur les classes rares.
- **Leçon** : en données déséquilibrées, suivre le macro-F1 et le rappel par classe, jamais l'accuracy seule.
- **Expérience 2** (`class_weight_power=1.0`, `dropout=0.5`) : rappel S 0 → 0,11 mais précision S 0,04 et rappel N 0,96 → 0,77 ; macro-F1 0,43 → 0,39. Le modèle déplace sa frontière de décision sans réellement distinguer S de N chez un patient inconnu.
- **Ce que l'expérience a validé côté MLOps** : la version 2 a été enregistrée dans le Registry mais **pas promue** ; l'alias `champion` est resté sur la v1. La règle de promotion a empêché une régression.
- **Analyse** : (1) repondérer ne crée pas d'information ; il faut des features plus discriminantes pour S (RR normalisé par le rythme moyen du patient). (2) La validation contient seulement 15 battements F et 175 S : son macro-F1 est très bruité, donc l'early stopping est peu fiable.
- **Suite prévue** : améliorer les features RR → modèle v2, déployé en canary en Phase 7.

### Accents illisibles dans la console (`�poque`)
- **Cause** : la console Windows PowerShell 5.1 utilise la page de code OEM (850) alors que Python écrit de l'UTF-8.
- **Solution** : `chcp 65001` avant de lancer les scripts.

### Avertissement MLflow : `torch==2.15.0` au lieu de `2.15.0+cpu`
- **Cause** : MLflow retire le suffixe local `+cpu` pour que le `requirements.txt` du modèle soit installable depuis PyPI ; or PyPI sert la version CUDA de torch sur Linux, soit plusieurs Go.
- **À retenir pour la Phase 2** : dans l'image Docker, installer torch depuis l'index CPU de PyTorch au lieu des requirements générés par MLflow.

## Phase 2 : API et Docker

### `/docs` comptabilisé comme route `unmatched` dans Prometheus
- **Symptôme** : `http_requests_total{route="unmatched",status="200"}` alors qu'aucune requête n'avait échoué.
- **Cause** : seules les routes déclarées avec `@app.get/post` portent un gabarit (`scope["route"]`) ; `/docs` et `/openapi.json` sont des routes internes de FastAPI sans gabarit.
- **Solution** : utiliser le chemin réel pour ces routes, mais regrouper toutes les 404 sous `unmatched`. Sinon, un scan d'URL créerait une série temporelle par chemin inventé et ferait exploser la mémoire de Prometheus (explosion de cardinalité).

### Image de 1,58 Go
- **Cause** : PyTorch, même en version CPU, pèse environ 1 Go une fois installé ; le reste vient de Python et de FastAPI.
- **Déjà évité** : la version CUDA de torch, qui aurait donné plusieurs Go.
- **Piste** : exporter le modèle en ONNX et servir avec `onnxruntime` (~50 Mo) ramènerait l'image vers 300 Mo, avec un démarrage plus rapide et une surface d'attaque réduite (moins de CVE pour Trivy).

## Phase 3 : CI/CD

### Trivy bloque l'image : 5 vulnérabilités HIGH corrigeables
- **Détection** : scan local avant le premier push (`trivy image --severity CRITICAL,HIGH --ignore-unfixed`), soit le même seuil que la barrière de la CI.
- **Résultats** :
  - `zlib1g` (CVE-2026-85091, paquet Debian) : l'image `python:3.11-slim` est antérieure au correctif publié par Debian.
  - `wheel` (CVE-2026-24049) et `jaraco.context` (CVE-2026-23949) : **copies embarquées** dans `setuptools/_vendor`, présentes deux fois (Python système et venv). Invisibles dans `pip list`, mais détectées par Trivy.
- **Corrections** (Dockerfile) : `apt-get upgrade` dans l'image finale ; mise à jour de `setuptools` dans le venv (requis par torch) ; suppression de `pip`, `setuptools` et `wheel` du Python système et de `pip` du venv, puisqu'ils ne servent pas à l'exécution.
- **Résultat** : 0 HIGH/CRITICAL corrigeable ; l'image fonctionne aussi avec `--read-only --tmpfs /tmp`, comme dans Kubernetes.
- **Leçons** : (1) une image de base « à jour » ne l'est jamais longtemps : il faut scanner à chaque build et reconstruire régulièrement ; (2) `--ignore-unfixed` évite de bloquer sur des CVE sans correctif disponible, ce qui garde la barrière actionnable ; (3) moins de paquets = moins de surface d'attaque.

## Phase 4 : kind et ArgoCD

### `helm install argocd` échoue : `failed pre-install: Job argocd-redis-secret-init not ready`
- **Symptôme** : la release Helm est en état `failed`, il n'y a aucun Pod dans `argocd`, et `kubectl apply` de l'Application échoue (`the server doesn't have a resource type "applications"`), donc `ecg-dev` reste vide.
- **Cause** : le chart lance un *hook* `pre-install` (un Job qui génère le secret Redis) avant de créer le reste. Ce Job utilise l'image `quay.io/argoproj/argocd` (229 Mo) ; avec une connexion lente, son téléchargement a dépassé le délai par défaut de `--wait` (5 min). Helm a abandonné avant d'installer les CRD.
- **Diagnostic** : `helm list -A` (STATUS `failed`) et `helm history argocd -n argocd` (message du hook) ; `crictl images` sur le nœud kind a montré que l'image avait fini par arriver.
- **Solution** : `helm uninstall`, puis réinstallation avec `--timeout 15m`.
- **Leçons** : (1) une erreur en aval (`resource type "applications"` inconnu) cache souvent la vraie cause en amont : il faut remonter la chaîne ; (2) les hooks Helm s'exécutent avant les ressources : s'ils échouent, rien n'est créé ; (3) sur un réseau lent, on peut pré-charger les images dans kind (`kind load docker-image`).

## Phase 5 : observabilité

### `git push` refusé (non fast-forward) juste après un commit d'infrastructure
- **Cause** : le commit `feat(monitoring)` modifiait uniquement `infra/` et `deploy/`, mais le filtre `paths-ignore` excluant ces dossiers n'arrivait que dans le commit suivant. La CI a donc tourné, reconstruit l'image et le bot a poussé son commit GitOps pendant que je préparais le suivant.
- **Solution** : `git pull --rebase`, sans conflit, car le bot modifie seulement la ligne `image.tag`.
- **Leçons** : (1) en GitOps, un bot écrit dans la branche principale : toujours faire un `pull --rebase` avant de pousser ; (2) un changement de configuration ne doit pas reconstruire l'image : `paths-ignore` sur `deploy/**` et `infra/**`.

### Choix d'installation de kube-prometheus-stack dans kind
- Composants du plan de contrôle (`kube-scheduler`, `kube-controller-manager`, `etcd`, `kube-proxy`) **désactivés** : non joignables dans kind, ils déclencheraient des alertes `TargetDown` permanentes (fatigue d'alerte).
- **Webhook d'admission** de Prometheus Operator désactivé (ses Jobs de certificats se synchronisent mal avec ArgoCD) ; compensé par `promtool check rules` dans la CI.
- **Mot de passe Grafana** dans un Secret créé hors Git : un mot de passe aléatoire généré par le chart changerait à chaque rendu ArgoCD (désynchronisation permanente).
- **CRD trop volumineuses** pour `kubectl apply` côté client (limite de 256 Ko sur l'annotation `last-applied-configuration`) : `ServerSideApply=true` dans l'Application ArgoCD.

## Exploitation : redémarrage du PC

### Docker Desktop ne démarre plus après un redémarrage de Windows
- **Symptôme** : `kubectl` → `connection refused` ; Docker Desktop affiche une erreur avec seulement « Quit » ou « Reset to factory defaults » ; la distribution WSL `docker-desktop` reste `Stopped`.
- **Diagnostic** : `%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log` → `initializing Ingest server: listening on unix://…/Docker/run/sailor-ingest.sock: rename … .stale: The file cannot be accessed by the system`, puis la même erreur sur `docker-secrets-engine/engine.sock`.
- **Cause** : après un arrêt brutal, Docker laisse des **sockets Unix** orphelins (des *reparse points* NTFS) que Windows ne sait ni renommer ni supprimer (`Remove-Item` et `del` échouent tous les deux). Au démarrage, Docker essaie de les renommer et abandonne.
- **Solution** : quitter Docker Desktop, **renommer les dossiers** `%LOCALAPPDATA%\Docker\run` et `%LOCALAPPDATA%\docker-secrets-engine` (Docker les recrée), relancer Docker, puis `docker start mlops-control-plane mlops-worker`. Le cluster kind et toutes ses données sont intacts.
- **Piège évité** : « Reset to factory defaults » aurait **supprimé toutes les images et le cluster kind**. Lire le journal avant de cliquer sur le bouton proposé.
- **Leçon** : forcer l'arrêt des processus (`Stop-Process -Force`) recrée le problème ; il faut écarter les deux dossiers **en une seule fois**, juste avant le démarrage.

## Phase 7 : canary

### Premier canary du modèle v4 annulé à tort (faux négatif de l'analyse)
- **Symptôme** : 1 min 20 après le début du canary : `RolloutAborted … Metric "confiance-modele" assessed Failed due to failed (2) > failureLimit (1)`, avec des mesures `NaN` ; les deux autres métriques renvoyaient « no data ». Le Rollout est revenu seul à 100 % sur la version stable.
- **Ce qui a bien marché** : la sécurité. Dans le doute, la nouvelle version a été retirée, sans intervention.
- **Cause** : l'analyse commençait 1 min après la création du Pod canary. Or le Pod met ~60 s à démarrer (import de torch), puis il faut au moins 2 collectes Prometheus (toutes les 15 s) dans la fenêtre de `rate()`. Les premières mesures valaient donc « pas de données » ou `0/0 = NaN`, et `NaN >= 0.6` est faux.
- **Vérifications** : le label `rollouts_pod_template_hash` était bien présent sur les métriques (`podTargetLabels` fonctionnel) et le trafic k6 bien réparti (~2,5 req/s par Pod).
- **Solution** : `initialDelay: 2m30s` (démarrage + collectes + fenêtre) et `failureLimit` paramétrable ; correction poussée par Git, ce qui a relancé un nouveau canary.
- **Leçon** : une analyse automatique doit attendre que la mesure soit *possible* avant de la juger. Distinguer « mauvaise valeur » et « pas encore de valeur » est le même problème que l'alerte `EcgApiDown` et que le générateur de trafic silencieux du postmortem.
