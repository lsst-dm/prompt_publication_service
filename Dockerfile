# syntax=docker/dockerfile:1
#
# Based on the fastapi_safir_app template from
# https://github.com/lsst/templates

FROM python:3.13.12-slim-trixie AS base-image

RUN <<ENDRUN
set -e
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get -y upgrade
apt-get clean
ENDRUN

FROM base-image AS install-image

RUN <<ENDRUN
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get -y install git
ENDRUN

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /bin/uv

# Disable hard links during uv package installation since we're using a
# cache on a separate file system.
ENV UV_LINK_MODE=copy

# Force use of system Python so that the Python version is controlled by
# the Docker base image version, not by whatever uv decides to install.
ENV UV_PYTHON_PREFERENCE=only-system

# Install the dependencies.
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --compile-bytecode --no-install-project

FROM base-image AS runtime-image

# Create a non-root user.
RUN useradd --create-home appuser

# Copy the virtualenv.
COPY --from=install-image /app/.venv /app/.venv

WORKDIR /app

# Copy the application code.
COPY python/lsst ./lsst

# Switch to the non-root user.
USER appuser

# Make sure we use the virtualenv.
ENV PATH="/app/.venv/bin:$PATH"

# Run the application.
ENTRYPOINT ["python3", "-m"]
CMD ["lsst.prompt_publication_service.service"]
