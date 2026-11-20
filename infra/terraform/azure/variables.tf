variable "subscription_id" {
  description = "Identifiant de l'abonnement Azure for Students (az account show --query id -o tsv)."
  type        = string
}

variable "project" {
  description = "Préfixe des noms de ressources."
  type        = string
  default     = "mlops-ecg"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.project))
    error_message = "Le préfixe doit contenir 3 à 20 caractères : minuscules, chiffres ou tirets."
  }
}

variable "environment" {
  description = "Nom de l'environnement (dev, staging, prod)."
  type        = string
  default     = "dev"
}

variable "location" {
  description = "Région Azure. Les abonnements Azure for Students n'autorisent qu'une liste de régions (voir la stratégie « Allowed locations »)."
  type        = string
  default     = "francecentral"
}

variable "kubernetes_version" {
  description = "Version de Kubernetes (null = version par défaut proposée par AKS)."
  type        = string
  default     = null
}

variable "node_vm_size" {
  description = "Taille des VM du pool de nœuds. B-series : faible coût, adaptée au quota de vCPU des comptes étudiants."
  type        = string
  default     = "Standard_B2s_v2"
}

variable "node_min_count" {
  description = "Nombre minimal de nœuds (autoscaling du cluster)."
  type        = number
  default     = 1
}

variable "node_max_count" {
  description = "Nombre maximal de nœuds. Avec 2 vCPU par nœud, rester sous le quota régional de l'abonnement."
  type        = number
  default     = 2
}

variable "monthly_budget_eur" {
  description = "Budget mensuel du groupe de ressources : alertes à 50 %, 80 % et 100 % (crédit étudiant limité)."
  type        = number
  default     = 20
}

variable "budget_alert_emails" {
  description = "Adresses qui reçoivent les alertes de budget."
  type        = list(string)
}

variable "api_server_authorized_ip_ranges" {
  description = "Plages d'IP autorisées à joindre l'API Kubernetes (ex. votre IP publique en /32). Obligatoire : une API ouverte à tout Internet est la première cible des scans automatisés."
  type        = list(string)

  validation {
    condition = length(var.api_server_authorized_ip_ranges) > 0 && alltrue([
      for cidr in var.api_server_authorized_ip_ranges : can(cidrhost(cidr, 0)) && cidr != "0.0.0.0/0"
    ])
    error_message = "Indiquer au moins une plage CIDR valide, différente de 0.0.0.0/0."
  }
}

variable "tags" {
  description = "Étiquettes ajoutées à toutes les ressources."
  type        = map(string)
  default     = {}
}
