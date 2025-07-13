from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from google.cloud import storage
from loguru import logger

from get_quotes import get_quotes


def upload_quotes_to_gcs(
    bucket_name: str,
    quotes_data: List[Dict],
    timestamp: Optional[datetime] = None,
    credentials_path: Optional[str] = None,
) -> str:
    """Upload quotes data to Google Cloud Storage in parquet format.
    
    Creates a data lake structure: bucket/year/month/day/hour.parquet
    
    Args:
        bucket_name: GCS bucket name
        quotes_data: List of quote dictionaries from get_quotes()
        timestamp: Timestamp for the file path (defaults to current time)
        credentials_path: Path to GCS service account credentials JSON file
        
    Returns:
        The GCS path where the file was uploaded
        
    Raises:
        ValueError: If quotes_data is empty
        Exception: If upload fails
    """
    if not quotes_data:
        raise ValueError("No quotes data provided")
    
    if timestamp is None:
        timestamp = datetime.now()
    
    df = pd.DataFrame(quotes_data)
    
    year = timestamp.strftime("%Y")
    month = timestamp.strftime("%m")
    day = timestamp.strftime("%d")
    hour = timestamp.strftime("%H")
    
    blob_path = f"{year}/{month}/{day}/{hour}.parquet"
    
    try:
        if credentials_path:
            client = storage.Client.from_service_account_json(credentials_path)
        else:
            client = storage.Client()
        
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        
        parquet_buffer = df.to_parquet(index=False)
        
        blob.upload_from_string(parquet_buffer, content_type='application/octet-stream')
        
        gcs_path = f"gs://{bucket_name}/{blob_path}"
        logger.info(f"Successfully uploaded {len(quotes_data)} quotes to {gcs_path}")
        
        return gcs_path
        
    except Exception as e:
        logger.error(f"Failed to upload quotes to GCS: {e}")
        raise


def fetch_and_upload_quotes(
    bucket_name: str,
    start_date: datetime,
    end_date: Optional[datetime] = None,
    currencies: List[str] = ["USD", "EUR"],
    credentials_path: Optional[str] = None,
) -> str:
    """Fetch quotes and upload to GCS in one operation.
    
    Args:
        bucket_name: GCS bucket name
        start_date: Start date for quotes
        end_date: End date for quotes (defaults to today)
        currencies: List of currency codes
        credentials_path: Path to GCS credentials
        
    Returns:
        The GCS path where the file was uploaded
    """
    logger.info(f"Fetching quotes from {start_date} to {end_date or datetime.today()}")
    
    quotes_data = get_quotes(
        start_date=start_date,
        end_date=end_date,
        currencies=currencies
    )
    
    if not quotes_data:
        logger.warning("No quotes data retrieved")
        return ""
    
    return upload_quotes_to_gcs(
        bucket_name=bucket_name,
        quotes_data=quotes_data,
        credentials_path=credentials_path
    )


if __name__ == "__main__":
    bucket_name = "your-data-lake-bucket"
    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 1, 10)
    
    gcs_path = fetch_and_upload_quotes(
        bucket_name=bucket_name,
        start_date=start_date,
        end_date=end_date,
        currencies=["USD", "EUR", "GBP"]
    )
