FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies declared in pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "fastapi>=0.129.0" \
    "unicorn>=2.1.4" \
    "uvicorn>=0.41.0" \
    "ydb>=3.26.5"

# Copy application source
COPY app ./app

EXPOSE 8080

# Run FastAPI app with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]