FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY schema.sql .
COPY server ./server
COPY mkdocs.yml /app/repo/mkdocs.yml
COPY docs /app/repo/docs
ENV PYTHONPATH=/app
ENV WIKIMEDIA_REPO_ROOT=/app/repo
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
