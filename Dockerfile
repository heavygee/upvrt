FROM python:3.11-slim
WORKDIR /app

# Install system dependencies including FFmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn
COPY . .

# Run with unbuffered Python output and proper gunicorn logging
CMD ["python", "-u", "-m", "gunicorn", "--bind", "0.0.0.0:7001", "--access-logfile=-", "--error-logfile=-", "--log-level=info", "--capture-output", "wsgi:app"] 