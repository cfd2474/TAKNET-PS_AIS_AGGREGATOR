FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 4000 4001
ENV PYTHONUNBUFFERED=1
CMD ["python3", "-u", "server.py"]
