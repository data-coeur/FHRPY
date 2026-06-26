# FHRPY inference server — small CPU image (no GPU, no TensorFlow).
FROM python:3.11-slim

WORKDIR /app
# Install runtime deps first for better layer caching.
RUN pip install --no-cache-dir numpy scipy

COPY pyproject.toml README.md ./
COPY fhrpy ./fhrpy
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000
# Workers default to min(4, cpu); override with --workers for a 2-4 core box.
ENTRYPOINT ["python", "-m", "fhrpy.server", "--host", "0.0.0.0", "--port", "8000"]
