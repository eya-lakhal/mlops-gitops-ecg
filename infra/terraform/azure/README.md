# Terraform : environnement Azure (AKS)

Reproduit le cluster kind local sur **Azure for Students**. Terraform crée l'infrastructure ; ArgoCD
installe ensuite tout le reste depuis le même dépôt Git, exactement comme en local.

| Ressource | Choix | Raison |
|---|---|---|
| AKS `sku_tier = "Free"` | plan de contrôle gratuit | crédit étudiant limité, pas besoin de SLA |
| Pool `Standard_B2s_v2`, 1 à 2 nœuds | autoscaling du cluster | coût faible, respecte le quota de vCPU des comptes étudiants |
| Identité managée + Workload Identity (OIDC) | aucun secret de principal de service | pas de clé à stocker, faire tourner ou laisser fuiter |
| RBAC Azure + `local_account_disabled` | accès via Entra ID uniquement | pas de kubeconfig administrateur partagé |
| `api_server_authorized_ip_ranges` **obligatoire** | API joignable depuis ses IP seulement | correctif d'un CRITICAL Trivy (AZU-0041) |
| Azure CNI overlay + Cilium | NetworkPolicies appliquées | isolation réseau entre namespaces |
| Budget de 20 € avec alertes à 50/80/100 % | garde-fou financier | éviter d'épuiser le crédit sans s'en rendre compte |
| Mises à jour automatiques (patch + image des nœuds) le dimanche | correctifs de sécurité appliqués | fenêtre de maintenance hors usage |

Écarts assumés (signalés MEDIUM par Trivy) : pas de cluster privé (il faudrait un VPN ou un bastion) et pas
d'agent Log Analytics (coût) ; la supervision reste assurée par kube-prometheus-stack dans le cluster.

## Utilisation

```powershell
az login
az account show --query id -o tsv                     # identifiant d'abonnement
cd infra/terraform/azure
Copy-Item example.tfvars terraform.tfvars              # puis l'adapter (ignoré par Git)
./bootstrap-state.ps1                                  # facultatif : état distant, puis activer le backend
terraform init
terraform plan -out tfplan                             # relire le plan avant tout apply
terraform apply tfplan
```

Puis, sur le nouveau cluster, le même bootstrap qu'en local :

```powershell
az aks get-credentials -g rg-mlops-ecg-dev -n aks-mlops-ecg-dev
kubelogin convert-kubeconfig -l azurecli
helm upgrade --install argocd oci://ghcr.io/argoproj/argo-helm/argo-cd --version 10.18.1 `
  -n argocd --create-namespace -f ../../argocd/values.yaml --wait --timeout 15m
kubectl apply -f ../../../deploy/argocd/ -f ../../../deploy/platform/
```

**Penser à `terraform destroy`** après une démonstration : un cluster qui tourne consomme le crédit.

La CI (`.github/workflows/infra.yml`) vérifie `terraform fmt`, `terraform validate` et analyse la configuration
avec Trivy à chaque modification, sans aucun accès à Azure.
