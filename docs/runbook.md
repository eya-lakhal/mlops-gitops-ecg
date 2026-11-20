# Runbook : ecg-api

Procédures liées aux alertes envoyées sur Discord. Chaque alerte contient un lien vers sa section.

**SLO** : 99 % des `POST /predict` sans erreur 5xx sur 30 jours glissants. Le **budget d'erreur** vaut donc 1 %
des requêtes. Le **burn rate** mesure la vitesse de consommation du budget : un burn rate de 1 l'épuise en
exactement 30 jours ; un burn rate de 14,4 consomme 2 % du budget mensuel en 1 heure.

Accès rapides :

```powershell
kubectl -n ecg-dev get pods,deploy                                   # état de l'API
kubectl -n ecg-dev logs deploy/ecg-api --tail=100                   # logs applicatifs
kubectl -n argocd get application ecg-api-dev                        # version déployée par GitOps
kubectl -n monitoring port-forward svc/kps-grafana 3000:80          # dashboard « ECG API — SLO et budget d'erreur »
```

## EcgApiErrorBudgetBurnFast

**Sévérité** : critical. **Signification** : plus de 14,4 % des requêtes échouent (fenêtres 1 h et 5 min), ou plus de 6 %
(fenêtres 6 h et 30 min). Au rythme actuel, le budget mensuel est épuisé en moins de 2 jours.

1. **Un déploiement récent ?** `kubectl -n argocd get application ecg-api-dev -o jsonpath="{.status.history}"` et
   `git log -5 -- deploy/envs/dev/values.yaml`. Si l'alerte suit un nouveau tag → **rollback** par `git revert` du commit
   `chore(gitops)` fautif, puis `git push` : ArgoCD redéploie la version précédente.
2. **Injection de pannes active ?** Vérifier `faultRate` dans `deploy/envs/dev/values.yaml` (doit valoir `"0"` hors exercice).
3. **Erreurs applicatives ?** `kubectl -n ecg-dev logs deploy/ecg-api | Select-String " 500 "` : chercher la trace d'exception.
4. **Ressources ?** `kubectl -n ecg-dev describe pod -l app.kubernetes.io/name=ecg-api` : OOMKilled, redémarrages, throttling CPU.

## EcgApiErrorBudgetBurnSlow

**Sévérité** : warning. **Signification** : le taux d'erreur dépasse durablement le rythme soutenable (3 fois sur 1 jour, ou
1 fois sur 3 jours). Pas d'urgence immédiate, mais le SLO sera manqué si rien ne change.

> **Attention** : cette alerte peut se déclencher **après** la résolution d'un incident rapide (sa fenêtre courte est
> de 2 h et contient encore les erreurs passées). Si le panneau « Taux d'erreur 5xx » est revenu à 0 et que l'alerte
> rapide est résolue, elle retombera d'elle-même : pas d'action requise.

1. Sur le dashboard, identifier le début de la hausse dans le panneau « Taux d'erreur 5xx vs seuil du SLO ».
2. La corréler avec les déploiements (même démarche que ci-dessus) et la charge (panneau « Trafic »).
3. Ouvrir un ticket ; si le budget restant passe sous 25 %, **geler les déploiements non correctifs** (politique de budget d'erreur).

## EcgApiDown

**Sévérité** : critical. **Signification** : Prometheus ne joint plus aucun Pod depuis 2 minutes. Le taux d'erreur ne peut pas
le voir (plus aucune requête n'est mesurée) : c'est pour cela que cette alerte existe.

1. `kubectl -n ecg-dev get pods` : `CrashLoopBackOff` → `kubectl -n ecg-dev logs <pod> --previous`
   (empreinte SHA-256 du modèle invalide, import de torch impossible, etc.).
2. `ImagePullBackOff` → le tag dans `deploy/envs/dev/values.yaml` existe-t-il dans GHCR ? L'image est-elle publique ?
3. `Pending` → `kubectl describe pod` : ressources insuffisantes sur le nœud.

## EcgApiHighLatency

**Sévérité** : warning. **Signification** : p95 de `/predict` supérieur à 0,5 s pendant 10 minutes.

1. Panneau « Trafic » : pic de charge ? → vérifier l'autoscaling (Phase 6) : `kubectl -n ecg-dev get hpa`.
2. Throttling CPU : comparer la consommation avec `resources.limits.cpu` dans les valeurs Helm.
3. Taille des lots : une hausse de `ecg_batch_size` augmente la latence par requête.
