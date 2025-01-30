# Use the official Python image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1  # Prevents Python from writing .pyc files
ENV PYTHONUNBUFFERED 1        # Ensures logs are output directly

# Create working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libmariadb-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application
COPY . .

# Expose the application port
EXPOSE 4000

# Command to run FastAPI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4000"]