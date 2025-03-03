# Use the official Python image
FROM arm64v8/python:3.11

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libmariadb-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*
# Add Cargo to PATH
ENV PATH="/root/.cargo/bin:${PATH}"

# Copy the requirements and install dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the entire application
COPY . .

# Expose the application port
EXPOSE 8000

# Command to run FastAPI app
CMD ["fastapi", "run", "app/main.py", "--reload"]