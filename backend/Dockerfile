FROM python:3.12-slim

WORKDIR /app

# Dependencias del sistema mínimas (docker-cli para run_python si se monta el socket)
RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY . .

# Por defecto arranca la API; el worker/scheduler sobreescriben el comando.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
