variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "data_engineer_email" {
  description = "Email of the data engineer for BigQuery access"
  type        = string
}