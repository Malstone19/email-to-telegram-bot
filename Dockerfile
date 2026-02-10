FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install --quiet --no-cache-dir -r requirements.txt

COPY email_to_telegram.py .

RUN useradd -m -u 1000 appuser && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser

CMD ["python", "email_to_telegram.py"]
