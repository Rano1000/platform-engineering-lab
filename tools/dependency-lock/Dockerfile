ARG PYTHON_IMAGE=python:3.13.15-slim-bookworm@sha256:c45a22ea000adfd9cda29364bbe7edd23001ce5cc2ad15857cfbf7766943b9ca

FROM ${PYTHON_IMAGE}
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --require-hashes -r /tmp/requirements.txt
WORKDIR /requirements
ENTRYPOINT ["pip-compile"]
