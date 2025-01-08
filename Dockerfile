FROM python:3.11-slim
WORKDIR /app

# Install system dependencies including FFmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn
COPY . .

# Default command (can be overridden in docker-compose.yml)
CMD ["gunicorn", "--bind", "0.0.0.0:7001", "wsgi:app"] 