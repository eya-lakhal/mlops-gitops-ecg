# Copier en terraform.tfvars (ignoré par Git) puis adapter.
subscription_id     = "00000000-0000-0000-0000-000000000000"
location            = "francecentral"
budget_alert_emails = ["prenom.nom@example.com"]

# Obligatoire : IP publique autorisée à joindre l'API Kubernetes (Invoke-RestMethod ifconfig.me).
api_server_authorized_ip_ranges = ["203.0.113.10/32"]
