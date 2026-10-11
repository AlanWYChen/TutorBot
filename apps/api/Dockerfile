FROM python:3.12.10-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace/apps/api
COPY apps/api/requirements*.txt apps/api/requirements*.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY apps/api .
RUN useradd --create-home tutorbot && chown -R tutorbot:tutorbot /workspace/apps/api
USER tutorbot
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
FROM base AS checks
COPY infra/litellm/render_config.py /workspace/infra/litellm/render_config.py
USER root
RUN pip install --no-cache-dir -r requirements-dev.lock
USER tutorbot
