# Crée le stockage de l'état Terraform distant (à lancer une seule fois, avant le backend azurerm).
# Pourquoi hors Terraform : l'état ne peut pas être stocké dans une ressource que ce même
# Terraform crée (problème de l'œuf et de la poule).
param(
  [string]$Location = "francecentral",
  [string]$ResourceGroup = "rg-ecg-tfstate"
)
$ErrorActionPreference = "Stop"
$suffix = -join ((48..57) + (97..122) | Get-Random -Count 6 | ForEach-Object { [char]$_ })
$account = "stecgtfstate$suffix"

az group create --name $ResourceGroup --location $Location --output none
az storage account create --name $account --resource-group $ResourceGroup --location $Location `
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 `
  --allow-blob-public-access false --allow-shared-key-access false --output none
az storage container create --name tfstate --account-name $account --auth-mode login --output none

# Versionnage des blobs : chaque écriture de l'état est conservée (retour arrière possible).
az storage account blob-service-properties update --account-name $account `
  --resource-group $ResourceGroup --enable-versioning true --output none

Write-Output "Compte de stockage créé : $account (à reporter dans versions.tf, bloc backend)"
