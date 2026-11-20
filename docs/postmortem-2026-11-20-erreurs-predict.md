# Postmortem : 30 % d'erreurs 5xx sur POST /predict (exercice de chaos)

| | |
|---|---|
| **Date** | 20-21 novembre 2026 (heure locale, UTC+1) |
| **Environnement** | `ecg-dev` (cluster kind local) |
| **Type** | Exercice planifié (*game day*) : panne injectée volontairement |
| **Gravité** | SEV-2 simulée : dégradation partielle, service toujours joignable |
| **Statut** | Résolu |
| **Format** | *Blameless* : on analyse le système et les processus, pas les personnes |

## Résumé

Pour valider la chaîne d'observabilité de bout en bout (métriques → SLO → alerte → Discord → runbook →
correction GitOps), 30 % d'erreurs 500 ont été injectées sur `POST /predict` via le paramètre `faultRate`.
L'alerte critique **EcgApiErrorBudgetBurnFast** s'est déclenchée et a été livrée sur Discord ; la correction a
consisté en un simple `git revert`, appliqué par ArgoCD en 28 secondes.

L'exercice a aussi révélé un **défaut de l'outillage de test** : pendant 21 minutes, le générateur de trafic
n'envoyait aucune requête, sans qu'aucun signal ne le montre. C'est l'enseignement principal.

## Impact

- **Requêtes en erreur** : environ 29 % des `POST /predict` pendant environ 9 minutes de trafic réel avec la panne
  (00:10 → 00:19).
- **Budget d'erreur** : le SLO de 99 % sur 30 jours a été **consommé au-delà de 100 %**, car il y avait très peu
  de trafic historique. Sur un vrai mois de trafic, le même incident aurait coûté une fraction du budget.
- **Utilisateurs réels** : aucun (environnement de démonstration).

## Chronologie

| Heure | Événement |
|---|---|
| 23:47:38 | Commit `d5c912b` : `faultRate: "0.3"` dans `deploy/envs/dev/values.yaml` (début de l'exercice) |
| 23:49:08 | ArgoCD a synchronisé : nouveau Pod avec `FAULT_RATE=0.3` (**90 s** après le push) |
| 23:49 → 00:10 | ⚠️ **Aucune requête n'atteint l'API** : le générateur de trafic est connecté à un `port-forward` mort (voir causes) |
| 00:10:10 | Détecté **manuellement** (Prometheus : 0 requête sur 10 min) ; générateur relancé sur un autre port |
| 00:12:31 | `EcgApiErrorBudgetBurnSlow` en *pending* (taux d'erreur à 5 min : 25,7 %) |
| 00:15:06 | `EcgApiErrorBudgetBurnFast` en *pending* (27,4 %) |
| 00:16:35 | `EcgApiErrorBudgetBurnFast` actif (`activeAt`) ; **firing** après le `for: 2m` |
| 00:17:10 | Firing confirmé dans Prometheus (29,0 %) |
| ≈00:17:40 | **Notification Discord n°1** (après `group_wait: 30s`) ; 0 échec d'envoi |
| 00:18:43 | Mitigation : `git revert` → commit `f77f187` (`faultRate: "0"`) poussé |
| 00:19:11 | ArgoCD a redéployé la version saine (**28 s**) ; trafic de contrôle : 2 716 requêtes, 0 erreur |
| 00:27:17 | `EcgApiErrorBudgetBurnSlow` passe en firing : **notification Discord n°2** (attendu, voir analyse) |
| RESOLUTION_FAST | Résolution de `EcgApiErrorBudgetBurnFast` : notification ✅ RESOLVED |

**Indicateurs** : délai de détection (début des erreurs → alerte firing) ≈ **7 min** ; délai de mitigation (alerte →
correction déployée) ≈ **2 min** ; la correction elle-même est un commit Git, donc tracée et réversible.

## Ce qui a bien fonctionné

1. **Méthode multi-fenêtres** : l'alerte rapide a attendu que le taux d'erreur dépasse 14,4 fois le budget sur 5 min
   **et** sur la fenêtre longue, ce qui évite les fausses alertes sur un pic isolé.
2. **Routage** : seules les alertes `team="ecg"` sont arrivées sur Discord ; aucun bruit des règles Kubernetes par défaut.
3. **GitOps comme mécanisme de rollback** : `git revert` + ArgoCD = retour à l'état sain en moins de 30 s, sans
   `kubectl` ni accès privilégié au cluster.
4. **Runbook** lié depuis chaque notification : sa première étape (« un déploiement récent ? ») pointait directement vers la cause.

## Ce qui n'a pas fonctionné

1. **Générateur de trafic silencieux (21 min perdues)**. Le premier générateur (exercice précédent) gardait le port
   local 8000 avec un `port-forward` vers un Pod **supprimé** par le rolling update. Le second n'a jamais pu se lier au
   port, et ses requêtes échouaient sans rien afficher (progression affichée toutes les 300 requêtes seulement).
2. **L'alerte lente s'est déclenchée après la correction** (00:27). Ce n'est pas un bug : sa fenêtre courte (2 h)
   contenait encore les erreurs. Mais une personne d'astreinte non avertie pourrait croire à une rechute.
3. **Budget d'erreur peu représentatif** : avec quelques milliers de requêtes seulement, 9 minutes d'incident suffisent
   à dépasser 100 % du budget « mensuel ».

## Causes racines

- **Outillage** : un `kubectl port-forward` vise **un Pod précis** (même via `svc/...`) et meurt avec lui ; il ne suit
  pas le rolling update. Le script de trafic ne distinguait pas « erreur 500 attendue » et « erreur réseau ».
- **Observabilité du test lui-même** : l'absence de trafic n'était surveillée par rien. C'est exactement le cas que
  couvre `EcgApiDown` pour l'API (un taux d'erreur est muet quand il n'y a plus de requêtes), mais pas pour l'outil de test.

## Actions correctives

| Action | Statut |
|---|---|
| Générateur de trafic : progression **toutes les 2 min**, comptage séparé des 500 et des erreurs réseau | ✅ fait pendant l'exercice |
| Tests de charge exécutés **dans le cluster** (Job k6 → Service), insensibles aux redémarrages de Pods | ✅ Phase 6 (`load/k6/job.yaml`) |
| Seuils k6 alignés sur le SLO (`http_req_failed < 1 %`, p95 < 500 ms) : un test sans trafic valide échoue | ✅ Phase 6 |
| Runbook : préciser que l'alerte lente peut se déclencher **après** une correction et retomber d'elle-même | ✅ ajouté au runbook |
| Annoncer les *game days* dans le canal d'alerte avant de commencer | À faire |
| Analyse canary (Phase 7) : le même SLO (99 % de succès) comme critère de promotion d'une nouvelle version | ✅ Phase 7 |
