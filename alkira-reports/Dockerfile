# Simple container for Alkira aggregate budget helper
# Build: docker build -t alkira-aggregate:1.2 .
# Run (example): docker run --rm --env-file .env -v "$PWD":/app alkira-aggregate:1.2

FROM python:3.11-slim

# Metadata
LABEL maintainer="Copilot <copilot@example.com>"

WORKDIR /app

# Copy code
COPY . /app

# Install optional dependency for Excel output
RUN pip install --no-cache-dir openpyxl==3.1.2

# Ensure wrapper and script are executable
RUN chmod +x /app/run_aggregate_and_email.sh /app/run_aggregate_budget.sh /app/alkira_aggregate_budget.py

ENV PYTHONUNBUFFERED=1

# Default command runs the wrapper. Override with your own command to run a one-off task.
ENTRYPOINT ["/app/run_aggregate_and_email.sh"]
