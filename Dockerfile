FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY bridge.py app.py .

RUN chmod +x app.py

EXPOSE 8080

CMD ["python3", "-u", "app.py"]
