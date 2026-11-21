# SEO blog writer: plans, researches, writes and uploads articles on a daily schedule.
# Runs the built-in scheduler (`cli.py daemon`); no cron needed inside the container.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY agent/ agent/
COPY clients/ clients/
COPY cli.py .

# Run as an unprivileged user; data/ (plans, drafts, history) is a volume it owns.
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data && chown -R app:app /app/data
USER app
VOLUME ["/app/data"]

# Healthy while the scheduler loop is alive (it refreshes the heartbeat every minute).
HEALTHCHECK --interval=5m --timeout=10s --start-period=1m --retries=2 \
  CMD python -c "import os,sys,time; sys.exit(0 if time.time()-os.path.getmtime('/app/data/.heartbeat')<600 else 1)"

CMD ["python", "cli.py", "daemon"]
