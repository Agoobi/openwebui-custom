# Ban Docker: anh Open WebUI goc + custom.css / loader.js. Khoa dung phien ban da kiem.
FROM ghcr.io/open-webui/open-webui:v0.11.4

COPY static/custom.css static/loader.js /app/backend/open_webui/static/
COPY static/custom.css static/loader.js /app/build/static/
COPY static/hop-thu /app/backend/open_webui/static/hop-thu
