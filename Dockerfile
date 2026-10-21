# Ban Docker: anh Open WebUI goc + custom.css / loader.js. Khoa dung phien ban da kiem.
FROM ghcr.io/open-webui/open-webui:v0.11.4

COPY static/custom.css static/loader.js /app/backend/open_webui/static/
COPY static/custom.css static/loader.js /app/build/static/
COPY static/hop-thu /app/backend/open_webui/static/hop-thu
# URL https cua bot Hermes cho trang Hop thu: docker build --build-arg HERMES_INBOX_URL=https://bot.shop.vn .
ARG HERMES_INBOX_URL=""
RUN printf '{"api": "%s"}\n' "$HERMES_INBOX_URL" > /app/backend/open_webui/static/hop-thu/config.json
