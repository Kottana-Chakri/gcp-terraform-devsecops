
# Enable IAP API for secure VM access
resource "google_project_service" "iap" {
  project            = var.project_id
  service            = "iap.googleapis.com"
  disable_on_destroy = false
}

# Allow IAP to access SSH and the application
resource "google_compute_firewall" "iap_access" {
  name      = "devops-lab-allow-iap"
  network   = google_compute_network.devops_vpc.name
  direction = "INGRESS"

  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["devops-lab"]

  allow {
    protocol = "tcp"
    ports    = ["22", "8080"]
  }
}

# Create Compute Engine VM
resource "google_compute_instance" "devops_vm" {
  name         = "devops-app-vm"
  machine_type = var.machine_type
  zone         = var.zone

  tags = ["devops-lab"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
      size  = 10
      type  = "pd-standard"
    }
    auto_delete = true
  }

  network_interface {
    network    = google_compute_network.devops_vpc.id
    subnetwork = google_compute_subnetwork.devops_subnet.id

    # No access_config: no external public IP
  }

  metadata_startup_script = templatefile(
    "${path.module}/startup.sh.tftpl",
    {
      app_source = file("${path.module}/app/app.py")
    }
  )

  depends_on = [
    google_project_service.iap,
    google_compute_firewall.iap_access
  ]
}

output "vm_name" {
  value = google_compute_instance.devops_vm.name
}

output "vm_private_ip" {
  value = google_compute_instance.devops_vm.network_interface[0].network_ip
}

output "vm_zone" {
  value = google_compute_instance.devops_vm.zone
}
