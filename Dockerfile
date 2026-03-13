FROM python:3.12-alpine

RUN apk add --no-cache ffmpeg tzdata

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x run.sh && sh -n run.sh

CMD ["sh", "/app/run.sh"]
