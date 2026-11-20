terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.14"
    }
  }

  # État distant recommandé (verrouillage + partage). Créer d'abord le compte de stockage avec
  # bootstrap-state.ps1, puis décommenter ce bloc et lancer « terraform init -migrate-state ».
  # backend "azurerm" {
  #   resource_group_name  = "rg-ecg-tfstate"
  #   storage_account_name = "<nom unique affiché par bootstrap-state.ps1>"
  #   container_name       = "tfstate"
  #   key                  = "mlops-ecg/dev.tfstate"
  #   use_azuread_auth     = true
  # }
}

provider "azurerm" {
  features {
    resource_group {
      # Sécurité : refuser de supprimer un groupe qui contient encore des ressources
      # créées hors Terraform.
      prevent_deletion_if_contains_resources = true
    }
  }
  subscription_id = var.subscription_id
}
