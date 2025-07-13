output "data_lake_bucket_name" {
  description = "Name of the data lake bucket"
  value       = google_storage_bucket.data_lake.name
}

output "data_lake_bucket_url" {
  description = "URL of the data lake bucket"
  value       = google_storage_bucket.data_lake.url
}

output "data_warehouse_dataset_id" {
  description = "BigQuery data warehouse dataset ID"
  value       = google_bigquery_dataset.data_warehouse.dataset_id
}

output "raw_data_dataset_id" {
  description = "BigQuery raw data dataset ID"
  value       = google_bigquery_dataset.raw_data.dataset_id
}

output "service_account_email" {
  description = "Email of the data pipeline service account"
  value       = google_service_account.data_pipeline.email
}