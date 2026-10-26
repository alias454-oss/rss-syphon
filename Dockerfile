# Python 3.13 matches Fedora 42; keep Debian's base release stable.
FROM python:3.13-slim-bookworm

# Prevent Python from writing .pyc files to disk
# Prevent Python from buffering stdout and stderr, so logs appear in real time
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory
WORKDIR /app

# Install runtime utilities without browser dependencies.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file first
# This is the most important optimization. This layer will only be
# rebuilt when your requirements.txt file actually changes.
COPY requirements.txt .

# Fail closed if a resolved package or its artifact hash differs.
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.txt

# Now, copy the rest of the application code
# This is the layer that will be rebuilt most often, but since it's at the end,
# it won't invalidate the slow dependency installation steps.
COPY src/ /app/

# Install the sanitized configuration template as the container default.
# Never bake the private syphon.toml into the image.
COPY syphon.conf /app/syphon.toml

# Copy profile configuration and entrypoint
COPY profiles/ /app/profiles/
COPY entrypoint.sh .

# Make the entrypoint script executable
RUN chmod +x entrypoint.sh

# Build-time import smoke test. No feeds, network requests, or credentials.
RUN python -c "from rss_syphon import config, data; from rss_syphon.modules import files, splunk"

# Set the entrypoint for the container
ENTRYPOINT ["./entrypoint.sh"]
