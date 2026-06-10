FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY goldguard ./goldguard

RUN pip install --no-cache-dir ".[live]"

USER nobody

CMD ["uvicorn", "goldguard.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
