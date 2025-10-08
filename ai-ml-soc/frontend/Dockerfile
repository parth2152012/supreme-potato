# Use a lightweight Python image to serve the static file.
FROM python:3.9-slim

WORKDIR /app

COPY ./index.html .

CMD ["python", "-m", "http.server", "3000"]