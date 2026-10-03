FROM python:3.11-slim

WORKDIR /app

COPY app.py .

RUN chmod +x app.py

EXPOSE 8080

CMD ["python3", "app.py"]
