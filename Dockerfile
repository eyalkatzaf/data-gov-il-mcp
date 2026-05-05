FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Hosting platforms (Render, Railway, Fly.io) inject PORT
ENV MCP_HOST=0.0.0.0
ENV MCP_TRANSPORT=streamable-http

EXPOSE 8000

CMD ["python", "server.py"]
