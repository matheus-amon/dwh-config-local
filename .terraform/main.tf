terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Data Lake - Google Cloud Storage Bucket
resource "google_storage_bucket" "data_lake" {
  name          = "${var.project_id}-data-lake"
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true
  
  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type          = "SetStorageClass"
      storage_class = "ARCHIVE"
    }
  }
}

# Data Warehouse - BigQuery Dataset
resource "google_bigquery_dataset" "data_warehouse" {
  dataset_id  = "data_warehouse"
  description = "Data Warehouse for processed data"
  location    = var.region

  delete_contents_on_destroy = false

  access {
    role          = "OWNER"
    user_by_email = var.data_engineer_email
  }
}

# BigQuery Dataset for raw data
resource "google_bigquery_dataset" "raw_data" {
  dataset_id  = "raw_data"
  description = "Raw data ingested from data lake"
  location    = var.region

  delete_contents_on_destroy = false

  access {
    role          = "OWNER"
    user_by_email = var.data_engineer_email
  }
}

# Service Account for data pipeline
resource "google_service_account" "data_pipeline" {
  account_id   = "data-pipeline"
  display_name = "Data Pipeline Service Account"
  description  = "Service account for data pipeline operations"
}

# IAM bindings for service account
resource "google_storage_bucket_iam_member" "data_lake_admin" {
  bucket = google_storage_bucket.data_lake.name
  role   = "roles/storage.admin"
  member = "serviceAccount:${google_service_account.data_pipeline.email}"
}

resource "google_bigquery_dataset_iam_member" "data_warehouse_admin" {
  dataset_id = google_bigquery_dataset.data_warehouse.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.data_pipeline.email}"
}

resource "google_bigquery_dataset_iam_member" "raw_data_admin" {
  dataset_id = google_bigquery_dataset.raw_data.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.data_pipeline.email}"
}

resource "google_project_iam_member" "bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.data_pipeline.email}"
}