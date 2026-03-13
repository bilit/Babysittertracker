FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY app.py .
COPY templates/ templates/
COPY static/ static/

# Create data directory for SQLite
RUN mkdir -p /data

ENV PORT=5050
EXPOSE 5050

CMD ["python", "app.py"]
