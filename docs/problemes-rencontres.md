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
