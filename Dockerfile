# Dockerfile to run the PDO daemon in the foreground.
# 
# Build the image:
#   docker build -t pdo-daemon .
#
# Run the container (add -v $(pwd):/app/workspace if you want to mount local CSV files):
#   docker run -d --name pdo-daemon -v $(pwd):/app/workspace pdo-daemon
#
# Jump into the container to interact with the daemon (e.g., using the CLI):
#   docker exec -it pdo-daemon bash
#   
#   # Once inside the container, you can interact with the CLI:
#   # root@container:/app# pdo status
#   # root@container:/app# pdo import /app/workspace/products.csv -m product_id:ID -m description:Text
#

FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Define central paths for PDO data, logs, and socket so CLI and daemon stay in sync
ENV PDO_DATA_DIR=/var/lib/pdo/data
ENV PDO_LOG_DIR=/var/log/pdo
ENV PDO_SOCKET_PATH=/var/lib/pdo/pdo.sock

# Create necessary directories for PDO
RUN mkdir -p /var/lib/pdo/data /var/log/pdo

# Set the working directory
WORKDIR /app

# Copy the build configuration and source
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the application and its optional dependencies (gemini, openai)
RUN pip install --no-cache-dir '.[gemini,openai]'

# Start the daemon in the foreground so the container stays alive
# and can process requests from `pdo` CLI commands executed via `docker exec`.
CMD ["pdo", "daemon", "start", "--foreground"]
