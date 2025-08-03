FROM python:3.12-slim

# Create non-root user and workspace
RUN adduser --disabled-password --gecos '' watchdog
WORKDIR /home/watchdog

# Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App
COPY fritz_ipv4_watchdog.py .

# Prepare log dir; the bind mount will overlay it but this ensures perms if absent
RUN mkdir -p /logs && chown -R watchdog:watchdog /logs

USER watchdog
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "fritz_ipv4_watchdog.py"]