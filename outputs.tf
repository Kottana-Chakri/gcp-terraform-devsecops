
output "vpc_name" {
  value = google_compute_network.devops_vpc.name
}

output "subnet_name" {
  value = google_compute_subnetwork.devops_subnet.name
}

output "subnet_cidr" {
  value = google_compute_subnetwork.devops_subnet.ip_cidr_range
}
