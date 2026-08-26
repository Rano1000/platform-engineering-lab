ARG PYTHON_IMAGE=python:3.13.15-slim-trixie@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

FROM ${PYTHON_IMAGE} AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH
WORKDIR /build
COPY requirements/runtime.txt requirements/runtime.txt
RUN python -m venv /opt/venv && python -m pip install --no-compile -r requirements/runtime.txt

FROM dependencies AS test
COPY requirements/test.txt requirements/test.txt
RUN python -m pip install --no-compile -r requirements/test.txt
COPY pyproject.toml ./
COPY src/ src/
COPY tests/ tests/
ENV PYTHONPATH=/build/src
RUN python -m pytest

FROM ${PYTHON_IMAGE} AS runtime
ARG APP_VERSION
ARG VCS_REF
LABEL org.opencontainers.image.title="Golden Path API" \
      org.opencontainers.image.description="Reference workload for the Platform Engineering Lab" \
      org.opencontainers.image.source="https://github.com/Rano1000/platform-engineering-lab" \
      org.opencontainers.image.version="$APP_VERSION" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV HOME=/tmp \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=dependencies /opt/venv/ /opt/venv/
COPY --chown=10001:10001 src/ /app/
WORKDIR /app
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=2)"]
ENTRYPOINT ["python", "-m", "uvicorn"]
CMD ["golden_path_api.main:app", "--host=0.0.0.0", "--port=8080", "--no-access-log", "--timeout-graceful-shutdown=20"]
