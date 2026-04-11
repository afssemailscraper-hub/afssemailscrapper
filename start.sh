#!/bin/bash
set -e

DB_PATH="$(dirname "$0")/database.sqlite"

if [ ! -f "$DB_PATH" ]; then
    echo "Database not found. Downloading from R2..."
    python -c "
import boto3, os, sys
s3 = boto3.client(
    's3',
    endpoint_url=os.environ['R2_ENDPOINT'],
    aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
    aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
    region_name='auto'
)
db_path = os.path.join(os.path.dirname(os.path.abspath('$0')), 'database.sqlite')
print(f'Downloading database to {db_path} ...')
s3.download_file(os.environ['R2_BUCKET'], 'database.sqlite', db_path)
print('Database downloaded successfully.')
"
else
    echo "Database already present. Skipping download."
fi

echo "Starting API server..."
uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
