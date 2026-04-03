FROM python:3.11-slim

WORKDIR /app
COPY proxy.py udp_forward.py .

EXPOSE 10110
CMD ["python3", "-u", "proxy.py"]
