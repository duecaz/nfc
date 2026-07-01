FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates ./templates

EXPOSE 5000

# I/O-bound (cada /auth espera a Nextcloud): pocos workers + muchos threads.
# 2 workers x 8 threads = ~16 logins concurrentes (antes: 2).
CMD ["gunicorn", "--workers=2", "--threads=8", "--worker-class=gthread", \
     "--bind=0.0.0.0:5000", "--timeout=30", "app:app"]
