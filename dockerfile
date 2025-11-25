
FROM node:20-alpine AS frontend_builder

WORKDIR /app/frontend

# Copy frontend source
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build
FROM python:3.11-slim AS backend

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy backend source
COPY backend/ ./backend/
COPY data/ ./data/

# Install backend dependencies
RUN pip install --upgrade pip
RUN pip install -r backend/requirements.txt

# Copy FRONTEND BUILD → backend static folder
COPY --from=frontend_builder /app/frontend/dist/ ./backend/static/

EXPOSE 5000
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1
CMD ["python", "backend/app.py"]
