# Use an official Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies (e.g. ffmpeg for video)
RUN apt-get update && apt-get install -y \
    ffmpeg \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy backend and shared code
COPY ../shared /app/shared
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port for FastAPI
EXPOSE 8000

# Run the FastAPI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
