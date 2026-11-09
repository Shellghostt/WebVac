# WebVac — asyncio dynamic web scraper (scrape/crawl mode).
#
# Build:  docker build -t webvac .
# Doctor: docker run --rm webvac --doctor
# Scrape: docker run --rm -v webvac-data:/data webvac --url https://example.com --mode single
#
# Scan output is written under /data/scraped_data (the working directory),
# so mount a volume at /data to keep it. The optional De-Caffeinator VAPT
# task is not included: it needs the decaffeinator submodule and Node.js,
# which are deliberately left out to keep this image lean.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the package first (README is referenced by pyproject metadata).
COPY pyproject.toml README.md ./
COPY webvac ./webvac
COPY run.py ./

RUN pip install --upgrade pip \
    && pip install . \
    && python -m patchright install --with-deps chromium

# Runtime working directory: scraped_data/ lands here.
RUN mkdir -p /data
WORKDIR /data

ENTRYPOINT ["webvac"]
CMD ["--help"]
