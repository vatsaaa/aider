# Production Dockerfile for the Digital Equity Analyst.

FROM python:3.12-slim

# Install system packages required by the WBS (pandoc, xetex, fonts, git, curl)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       pandoc \
       texlive-xetex \
       texlive-fonts-recommended \
       texlive-fonts-extra \
       git \
       curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r analyst && useradd -r -g analyst -m -d /home/analyst -s /bin/bash analyst

WORKDIR /app

# Layer caching: install Python deps first
COPY requirements.txt pyproject.toml /app/
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy source and set permissions
COPY . /app
RUN chown -R analyst:analyst /app

USER analyst

ENV PYTHONUNBUFFERED=1

CMD ["python"]
