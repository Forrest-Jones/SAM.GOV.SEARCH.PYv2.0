FROM python:3.12-slim

WORKDIR /app

# Copied separately (and before the app code) so dependency layers cache.
# Both files are named requirements.txt, so they need distinct destinations.
COPY requirements.txt ./requirements.txt
COPY webapp/requirements.txt ./webapp/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r webapp/requirements.txt

COPY . .

ENV PORT=8080 \
    PUBLIC_DEPLOY=1 \
    DATA_DIR=/data

EXPOSE 8080

CMD ["sh", "-c", "gunicorn --chdir webapp app:app --bind 0.0.0.0:$PORT --timeout 300"]
