FROM node:22-alpine AS frontend-build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y nginx supervisor tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus && rm -rf /var/lib/apt/lists/*

ARG UV_VERSION=0.11.15
RUN pip install --no-cache-dir "uv==${UV_VERSION}"

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file /tmp/requirements.lock \
    && uv pip install --system --require-hashes --no-deps --requirement /tmp/requirements.lock \
    && rm /tmp/requirements.lock

COPY backend/ ./
RUN mkdir -p /app/data /app/data/sandbox

COPY --from=frontend-build /app/build /usr/share/nginx/html

COPY nginx.conf /etc/nginx/sites-available/default
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80
CMD ["/entrypoint.sh"]
