# Ban Docker: anh Open WebUI goc + openwebui-custom. CHUA KIEM: anh Docker chay start.sh va de giao dien o /app/build,
# con cqf_openwebui dat FROM_INIT_PY nhu ban pip; can thu va chinh truoc khi dung. Ban da kiem: deploy/install.sh (pip).
FROM ghcr.io/open-webui/open-webui:v0.11.4

COPY static/custom.css static/loader.js /app/backend/open_webui/static/
COPY static/custom.css static/loader.js /app/build/static/
COPY static/hop-thu /app/backend/open_webui/static/hop-thu
COPY static/chatbot /app/backend/open_webui/static/chatbot
COPY static/kien-thuc /app/backend/open_webui/static/kien-thuc
COPY static/cqf /app/backend/open_webui/static/cqf
COPY backend /opt/openwebui-custom/backend
RUN echo /opt/openwebui-custom/backend > "$(python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")/cqf_openwebui.pth"
CMD ["bash", "-c", "cd /app/backend && exec python -m cqf_openwebui serve --host 0.0.0.0 --port 8080"]
