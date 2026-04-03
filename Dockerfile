FROM python:3.12-slim AS builder
RUN pip install --no-cache-dir mkdocs-material==9.*
WORKDIR /app
COPY . .
RUN mkdocs build

FROM nginx:alpine
COPY --from=builder /app/site /usr/share/nginx/html
EXPOSE 80
