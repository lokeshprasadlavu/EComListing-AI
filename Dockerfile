FROM python:3.10-slim

WORKDIR /app

# Copy everything from root (including shared/, backend/, etc.)
COPY . /app

# Install backend dependencies and shared
RUN pip install --no-cache-dir -r backend/requirements.txt

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
