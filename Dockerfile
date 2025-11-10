# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Install necessary system dependencies for OpenCV and libgthread
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils libgl1 libglib2.0-0 git \
  build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app
COPY ./app /app

# The image runs the web process by default; workers should be run separately

# Install any needed packages specified in requirements.txt

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120

RUN python -m pip install --no-cache-dir -U pip setuptools wheel

RUN mkdir -p /wheels && \
    python -m pip download --no-cache-dir --progress-bar off --prefer-binary \
      --retries 5 --timeout 120 \
      -r requirements.txt -d /wheels && \
    python -m pip install --no-cache-dir --no-index --find-links=/wheels \
      -r requirements.txt

# Make port 80 available to the world outside this container
EXPOSE 80

# Define environment variable
ENV NAME World

# Run uvicorn when the container launches (web process only)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80", "--proxy-headers", "--forwarded-allow-ips", "*"]
