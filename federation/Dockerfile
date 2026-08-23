FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/ ./packages/
COPY federation/ ./federation/
ENV PYTHONPATH=/app/packages/agronomy:/app/packages/geo:/app/federation \
    PYTHONUNBUFFERED=1
EXPOSE 9000
CMD ["python", "federation/node_server.py"]
