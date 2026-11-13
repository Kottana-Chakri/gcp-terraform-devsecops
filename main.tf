#qwerty
# 1. Create a custom VPC

resource "google_compute_network" "devops_vpc" {
  name                    = "devops-lab-vpc"
  auto_create_subnetworks = false

  description = "VPC created using Terraform"
}
#hi

# 2. Create a subnet inside the VPC

resource "google_compute_subnetwork" "devops_subnet" {
  name          = "devops-lab-subnet"
  ip_cidr_range = "10.10.0.0/24"
  region        = var.region
  network       = google_compute_network.devops_vpc.id
}

# 3. Create an internal firewall rule

resource "google_compute_firewall" "internal" {
  name      = "devops-lab-allow-internal"
  network   = google_compute_network.devops_vpc.name
  direction = "INGRESS"

  target_tags = ["devops-lab"]

  allow {
    protocol = "tcp"
    ports    = ["22", "80", "443"]
  }

  source_ranges = ["10.10.0.0/24"]
}
