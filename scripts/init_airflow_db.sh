#!/bin/bash
set -e

AIRFLOW_CONN="postgresql+psycopg2://cargaexpress_admin:IYUMOYnnHnk%7B%24j%284S%5DQx%7BzLx@cargaexpress-staging-postgres.cnmosmsqi0oq.us-east-2.rds.amazonaws.com:5432/airflow"

echo "Pulling apache/airflow:2.9.3..."
docker pull apache/airflow:2.9.3

echo "Running airflow db migrate..."
docker run --rm \
  -e AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="$AIRFLOW_CONN" \
  -e AIRFLOW__CORE__EXECUTOR="CeleryExecutor" \
  -e AIRFLOW__CORE__LOAD_EXAMPLES="false" \
  apache/airflow:2.9.3 airflow db migrate

echo "Creating Airflow admin user..."
docker run --rm \
  -e AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="$AIRFLOW_CONN" \
  -e AIRFLOW__CORE__EXECUTOR="CeleryExecutor" \
  apache/airflow:2.9.3 airflow users create \
    --username admin \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email admin@cargaexpress.com \
    --password admin || true

echo "Airflow DB initialized successfully!"
