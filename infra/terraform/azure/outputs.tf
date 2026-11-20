output "resource_group_name" {
  description = "Groupe de ressources de l'environnement."
  value       = azurerm_resource_group.main.name
}

output "aks_name" {
  description = "Nom du cluster AKS."
  value       = azurerm_kubernetes_cluster.main.name
}

output "oidc_issuer_url" {
  description = "Émetteur OIDC, utilisé pour fédérer des identités de charge de travail."
  value       = azurerm_kubernetes_cluster.main.oidc_issuer_url
}

output "get_credentials_command" {
  description = "Commande pour récupérer le kubeconfig (authentification Entra ID via kubelogin)."
  value       = "az aks get-credentials -g ${azurerm_resource_group.main.name} -n ${azurerm_kubernetes_cluster.main.name} && kubelogin convert-kubeconfig -l azurecli"
}
