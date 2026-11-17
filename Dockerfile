# FastAPI web frontend (api/) — Hugging Face Spaces (Docker SDK, free CPU)
# and any other container host. Port 7860 is the Spaces convention.
FROM python:3.12-slim

WORKDIR /app

# deps first for layer caching; the API set is deliberate (no streamlit/bot)
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY . .

EXPOSE 7860
# APP_PASSWORD / DEEPSEEK_API_KEY / DISPATCH_DATABASE_URL /
# DISPATCH_DATABASE_PASSWORD come from the host's secret store
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "7860"]
