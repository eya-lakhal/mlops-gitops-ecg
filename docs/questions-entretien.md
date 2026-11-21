# Questions d'entretien : 3 par phase

Chaque question s'appuie sur ce qui a réellement été fait dans ce projet. Les pistes de réponse sont
volontairement courtes : à reformuler avec ses propres mots et ses propres chiffres.

## Phase 1 : entraînement et MLflow

**1. Ton modèle atteint 91 % d'accuracy. Pourquoi ne le considères-tu pas comme bon ?**
> Les données sont très déséquilibrées (~90 % de N). Un modèle qui ne prédit jamais S ni F obtient 91 %. J'ai suivi le
> **macro-F1** (chaque classe pèse autant) et le rappel par classe : v1 avait un rappel S de 0.

**2. Pourquoi un découpage par patient (DS1/DS2) plutôt qu'aléatoire par battement ?**
> Sinon, des battements du même patient sont à la fois en entraînement et en test : le modèle reconnaît le patient
> (fuite de données) et affiche ~99 %, un score qui s'effondre en production sur de nouveaux patients.

**3. À quoi sert l'alias `@champion` du Model Registry ?**
> L'API et l'export ciblent `models:/ecg-cnn-bilstm@champion` et non un numéro de version. La promotion est automatique
> et conditionnelle (meilleur macro-F1 de test) : v2 et v5 ont été enregistrées mais **pas promues**. Changer de modèle
> = déplacer l'alias, sans modifier de code.

## Phase 2 : API et Docker

**1. Pourquoi l'API tourne-t-elle avec l'UID 10001, et pourquoi un UID numérique ?**
> Moindre privilège : en cas de faille (RCE dans une dépendance), l'attaquant n'est pas root dans le conteneur, ce qui
> limite les évasions vers l'hôte. Avec un UID numérique, Kubernetes peut vérifier `runAsNonRoot` sans lire `/etc/passwd`.

**2. Différence entre `/health` et `/ready` ?**
> Liveness : le processus répond ; en échec, Kubernetes **redémarre** le conteneur. Readiness : l'instance peut recevoir
> du trafic (modèle chargé) ; en échec, le Pod est **retiré du Service** sans redémarrage.

**3. Pourquoi étiqueter les métriques avec `route="/predict"` et pas l'URL ou un identifiant patient ?**
> Chaque combinaison de labels crée une série temporelle. Des valeurs non bornées (URL, ID) provoquent une **explosion
> de cardinalité** qui sature la mémoire de Prometheus. Les 404 sont regroupées sous `unmatched` pour la même raison.

## Phase 3 : CI/CD

**1. Pourquoi la CI ne fait-elle pas `helm upgrade` dans le cluster ?**
> Modèle GitOps « pull » : la CI n'a aucun identifiant du cluster (surface d'attaque réduite), l'état voulu est dans Git
> (audit, revue, `git revert` = rollback), et ArgoCD corrige aussi les dérives manuelles, ce qu'un `push` ne fait pas.

**2. Pourquoi épingler les actions par SHA et taguer les images `sha-xxxxxxx` ?**
> Un tag (`@v7`, `latest`) peut être déplacé : action compromise ou image différente sous le même nom. Un SHA est
> immuable : reproductibilité, traçabilité jusqu'au commit et protection de la chaîne d'approvisionnement.

**3. Pourquoi `--ignore-unfixed` dans la barrière Trivy ?**
> Pour garder une barrière actionnable : bloquer sur une CVE sans correctif empêcherait tout déploiement, y compris les
> correctifs. Le rapport complet reste publié ; une CVE critique sans correctif se traite par analyse d'exploitabilité,
> mitigation et exception datée dans `.trivyignore`.

## Phase 4 : kind, Helm, ArgoCD

**1. Tu as fait `kubectl scale --replicas=3` et ArgoCD est revenu à 1 en 3 secondes. Comment agir en urgence ?**
> `selfHeal` compare en continu l'état réel à Git et annule l'écart. En urgence : modifier Git (le plus propre), ou
> suspendre temporairement la synchronisation automatique de l'Application, puis réconcilier Git ensuite.

**2. Qu'est-ce qui garantit l'absence de coupure pendant un rolling update ?**
> `maxUnavailable: 0` + `maxSurge: 1` : le nouveau Pod est créé avant de retirer l'ancien, et il ne reçoit du trafic
> qu'une fois la **readinessProbe** OK. Le `startupProbe` laisse le temps à torch de se charger.

**3. À quoi sert l'AppProject `ecg` si l'Application déclare déjà source et destination ?**
> Défense en profondeur : même si quelqu'un modifie le manifeste de l'Application, il ne peut ni lire un autre dépôt, ni
> déployer hors `ecg-*`, ni créer de ressources de cluster (réservées au projet `platform`).

## Phase 5 : observabilité et SLO

**1. Qu'est-ce qu'un budget d'erreur et à quoi sert-il ?**
> Avec un SLO de 99 %, on accepte 1 % d'échecs sur 30 jours : c'est le budget. Il arbitre vitesse et fiabilité : tant qu'il
> en reste, on déploie ; s'il est épuisé, on gèle les changements non correctifs.

**2. Pourquoi alerter sur le burn rate avec deux fenêtres ?**
> Alerter sur « une erreur » réveille pour rien ; alerter sur le taux à 30 jours arrive trop tard. Le burn rate mesure la
> vitesse de consommation du budget ; la fenêtre longue garantit que c'est significatif, la courte fait retomber l'alerte
> vite après correction. Exercice réel : détection en ~7 min.

**3. Pourquoi une alerte `EcgApiDown` en plus des alertes de taux d'erreur ?**
> Si l'API est totalement tombée, il n'y a plus de requêtes donc plus de taux d'erreur : les alertes de burn rate se
> taisent. Il faut un signal d'**absence** (`absent(up == 1)`). Le postmortem montre le même piège avec le générateur de trafic.

## Phase 6 : autoscaling et charge

**1. Sur quelle valeur le HPA calcule-t-il les 60 % de CPU ?**
> Sur les **requests** du conteneur (200m en dev), pas les limits. Des requests mal calibrées faussent l'autoscaling ; elles
> servent aussi au placement par le scheduler.

**2. Pourquoi retirer `replicas` du Deployment quand le HPA est actif ?**
> Sinon, ArgoCD (selfHeal) remet la valeur de Git pendant que le HPA la change : les deux contrôleurs se battent et le
> nombre de Pods oscille.

**3. Pourquoi lancer k6 dans le cluster avec un débit imposé ?**
> Un `port-forward` vise un seul Pod : la charge ne serait pas répartie et le HPA serait inutile. Un débit imposé
> (`arrival-rate`) maintient la charge même si l'API ralentit, ce qui révèle la saturation. Résultat : 14 159 requêtes,
> 0 erreur, p95 = 10,9 ms, montée de 2 à 3 Pods.

## Phase 7 : canary

**1. Pourquoi un canary plutôt qu'un rolling update pour un nouveau modèle ?**
> Un modèle peut répondre 200 OK tout en étant moins bon. Le canary expose d'abord une fraction du trafic et compare des
> métriques **sur les seuls Pods canary** ; en cas d'échec, l'abandon est automatique et la version stable reprend 100 %.

**2. Comment l'analyse distingue-t-elle les Pods canary des Pods stables ?**
> Argo Rollouts pose un label `rollouts-pod-template-hash` sur chaque Pod ; le ServiceMonitor le copie sur les métriques
> (`podTargetLabels`) et l'AnalysisTemplate filtre sur le hash de la nouvelle révision.

**3. Quelles limites a ton canary et comment l'améliorer ?**
> Sans Ingress ni maillage de services, le poids est approché par la proportion de Pods. Et l'analyse mesure la santé
> technique et la confiance, pas l'exactitude médicale (les vraies étiquettes arrivent tard). Améliorations : routage
> précis (Gateway API), *shadow traffic*, évaluation hors ligne sur un jeu étiqueté comme critère de promotion.

## Phase 8 : dérive

**1. Différence entre dérive des données et dérive du concept ?**
> Données : la distribution des entrées change (capteur bruité, autre population). Concept : la relation entrée → étiquette
> change. La première se détecte **sans étiquettes** ; la seconde demande des étiquettes récentes.

**2. Pourquoi des descripteurs plutôt que les 260 valeurs brutes ?**
> Les tests colonne par colonne sur 260 points corrélés sont bruités et ininterprétables. Des descripteurs (RR, énergie HF,
> asymétrie, confiance) disent **quoi** a changé : énergie HF ×50 → problème de capteur ; RR absolus ×7 → population plus rapide.

**3. DS2 « dérive » déjà sur 8 colonnes sur 10. Est-ce un problème ?**
> C'est un résultat : la différence entre patients existe déjà, ce qui explique les difficultés du modèle sur S. Un
> compte de colonnes ne suffit pas ; il faut regarder l'ampleur et l'effet sur le modèle (confiance 0,86 → 0,61 pour le
> capteur bruité, quasi inchangée pour DS2).

## Phase 9 : Terraform

**1. Pourquoi un état Terraform distant avec verrouillage ?**
> Un état local se perd, ne se partage pas et deux `apply` simultanés le corrompent. Le backend Azure Storage apporte
> verrouillage, versionnage et authentification Entra ID (`use_azuread_auth`, clés partagées désactivées).

**2. Qu'est-ce que Workload Identity apporte ?**
> Les Pods obtiennent un jeton Azure par fédération OIDC avec leur ServiceAccount : aucun secret de principal de service
> à stocker, faire tourner ou laisser fuiter.

**3. Comment as-tu sécurisé l'IaC avant tout déploiement ?**
> `fmt`, `validate` et Trivy config en CI. Trivy a signalé une API Kubernetes ouverte à Internet (CRITICAL) : la liste
> d'IP autorisées est devenue obligatoire, avec une validation qui refuse `0.0.0.0/0`. S'y ajoutent un budget avec alertes
> et des comptes locaux désactivés.

## Phase 10 : documentation et postmortem

**1. Qu'est-ce qu'un postmortem *blameless* ?**
> On cherche les causes dans le système et les processus, pas chez une personne : sans peur de la sanction, les gens
> racontent ce qui s'est vraiment passé, et les actions corrigent la cause racine.

**2. Quel a été l'enseignement principal de ton exercice de panne ?**
> L'outillage de test doit lui-même être observable : le générateur de trafic a échoué en silence pendant 21 minutes.
> Correctifs : comptage séparé des erreurs attendues et réseau, tests de charge dans le cluster, seuils k6.

**3. Si tu reprenais le projet, que changerais-tu en premier ?**
> Le modèle (RR normalisés par patient) pour améliorer la classe S, l'export ONNX pour diviser la taille de l'image par 5,
> et la gestion des secrets (External Secrets + Key Vault) au lieu de Secrets créés à la main.
