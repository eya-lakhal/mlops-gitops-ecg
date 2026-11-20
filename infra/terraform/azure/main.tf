# Environnement Azure de la plateforme : un cluster AKS qui reproduit le cluster kind local.
# Le reste (ArgoCD, supervision, Argo Rollouts, ecg-api) s'installe ensuite exactement comme
# en local : même dépôt Git, mêmes Applications ArgoCD. Terraform gère l'infrastructure,
# ArgoCD gère ce qui tourne dessus.

locals {
  name = "${var.project}-${var.environment}"
  tags = merge({
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
    repository  = "github.com/eya-lakhal/mlops-gitops-ecg"
  }, var.tags)
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-${local.name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  dns_prefix          = local.name
  kubernetes_version  = var.kubernetes_version

  # Plan de contrôle gratuit (sans SLA) : suffisant pour un environnement de démonstration.
  sku_tier = "Free"

  default_node_pool {
    name                 = "system"
    vm_size              = var.node_vm_size
    auto_scaling_enabled = true
    min_count            = var.node_min_count
    max_count            = var.node_max_count
    os_disk_size_gb      = 64
    os_disk_type         = "Managed"
    max_pods             = 60
    tags                 = local.tags

    upgrade_settings {
      max_surge = "33%"
    }
  }

  # Provisionnement des nœuds « Manual » : pools déclarés ici + cluster autoscaler classique
  # (et non Node Auto Provisioning/Karpenter, qui choisit lui-même les tailles de VM).
  node_provisioning_profile {
    mode = "Manual"
  }

  # Identité managée : aucun secret de principal de service à stocker ni à renouveler.
  identity {
    type = "SystemAssigned"
  }

  # Workload Identity : les Pods pourront accéder à Azure (ex. stockage des artefacts MLflow)
  # avec une identité fédérée, sans clé dans un Secret Kubernetes.
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  # RBAC Kubernetes adossé à Entra ID, comptes locaux désactivés.
  local_account_disabled = true
  azure_active_directory_role_based_access_control {
    tenant_id          = data.azurerm_client_config.current.tenant_id
    azure_rbac_enabled = true
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_policy      = "cilium"
    network_data_plane  = "cilium"
    load_balancer_sku   = "standard"
  }

  # API Kubernetes joignable uniquement depuis les IP déclarées (refus de 0.0.0.0/0 dans variables.tf).
  api_server_access_profile {
    authorized_ip_ranges = var.api_server_authorized_ip_ranges
  }

  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "NodeImage"

  maintenance_window_auto_upgrade {
    frequency   = "Weekly"
    interval    = 1
    duration    = 4
    day_of_week = "Sunday"
    start_time  = "02:00"
    utc_offset  = "+01:00"
  }

  tags = local.tags

  lifecycle {
    # Le nombre de nœuds est piloté par l'autoscaler du cluster, pas par Terraform.
    ignore_changes = [default_node_pool[0].node_count]
  }
}

# L'identité qui lance Terraform devient administratrice du cluster (RBAC Azure).
data "azurerm_client_config" "current" {}

resource "azurerm_role_assignment" "aks_admin" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Garde-fou financier : alertes e-mail avant d'épuiser le crédit étudiant.
resource "azurerm_consumption_budget_resource_group" "main" {
  name              = "budget-${local.name}"
  resource_group_id = azurerm_resource_group.main.id
  amount            = var.monthly_budget_eur
  time_grain        = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", plantimestamp())
  }

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThanOrEqualTo"
      threshold_type = notification.value == 100 ? "Forecasted" : "Actual"
      contact_emails = var.budget_alert_emails
    }
  }

  lifecycle {
    # La date de début n'a de sens qu'à la création.
    ignore_changes = [time_period]
  }
}
