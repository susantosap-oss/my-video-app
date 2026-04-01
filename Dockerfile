FROM python:3.11-slim

# Install ffmpeg (required by moviepy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download NLTK data
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

# Copy app source
COPY api.py auth.py database.py render_engine.py ai_spec.py ./
COPY static/ ./static/
COPY assets/ ./assets/
COPY fonts/ ./fonts/

# Writable dirs for uploads & output
RUN mkdir -p /app/output /app/uploads

ENV PORT=8080
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
