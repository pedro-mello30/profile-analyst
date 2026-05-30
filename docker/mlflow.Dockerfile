# MLflow tracking server image (spec 0006 §14 / spec 0007 §4.1).
# Adds psycopg2-binary (PostgreSQL backend store) and boto3 (MinIO / S3 artifact store)
# to a pinned MLflow base so deps are explicit and reproducible.
FROM python:3.11-slim

RUN pip install --no-cache-dir \
        mlflow==2.14.3 \
        psycopg2-binary==2.9.9 \
        boto3==1.34.131

# MLflow server reads backend/artifact config from env vars injected by compose.
EXPOSE 5000

CMD ["mlflow", "server", \
     "--host", "0.0.0.0", \
     "--port", "5000", \
     "--backend-store-uri", "${MLFLOW_BACKEND_STORE_URI}", \
     "--artifacts-destination", "${MLFLOW_ARTIFACTS_DESTINATION}", \
     "--serve-artifacts"]
