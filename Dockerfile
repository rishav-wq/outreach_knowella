# Single container: build the React frontend, then run FastAPI which serves BOTH
# the API and the built frontend. Targets Hugging Face Spaces (Docker SDK, port 7860).

# 1) Build the frontend (Vite). web/.env.production supplies the public Clerk key.
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# 2) Backend that also serves web/dist
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY config/ ./config/
COPY --from=web /web/dist ./web/dist
EXPOSE 7860
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "7860"]
