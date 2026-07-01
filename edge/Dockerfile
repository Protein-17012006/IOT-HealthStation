# =============================================================================
#  Cloud image for the Flask dashboard (ECS Fargate).
#  Build context = the edge/ folder:   docker build -f edge/Dockerfile edge
#
#  Only the web tier lives here (SPA + REST/SSE/MJPEG + DB access). The ESP32
#  serial reader (main.py) and the GPU YOLO detector stay on the local machine
#  and talk to this container over the network (RDS for data, /api/fall for
#  alerts) -- see README "Cloud deployment (AWS)".
# =============================================================================

# ---- Stage 1: build the React/Vite dashboard into dist/ ---------------------
FROM node:20-slim AS frontend
WORKDIR /fe
# install deps first (better layer caching)
COPY webapp/frontend/package.json webapp/frontend/package-lock.json ./
RUN npm ci
COPY webapp/frontend/ ./
RUN npm run build          # -> /fe/dist

# ---- Stage 2: python runtime ------------------------------------------------
FROM python:3.12-slim
WORKDIR /app

# curl is only for the container health/debug; drop apt lists to stay small
RUN pip install --no-cache-dir --upgrade pip

COPY webapp/requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# app.py inserts its parent (=/app) on sys.path to import these modules
# (rules.py is used by the /api/ingest endpoint)
COPY config.py db.py rules.py ./
COPY webapp/ ./webapp/
# built SPA must land where app.py looks for it: <webapp>/frontend/dist
COPY --from=frontend /fe/dist ./webapp/frontend/dist

ENV WEB_HOST=0.0.0.0 \
    WEB_PORT=8080 \
    PYTHONUNBUFFERED=1
EXPOSE 8080

# 1) create the schema + seed on RDS (db.init_db is idempotent), then
# 2) serve with gunicorn.
#    -w 1 is REQUIRED: the annotated-frame relay (_ai_frame in app.py) is
#    in-process state shared between POST /api/ai_frame and the /api/ai_camera
#    MJPEG stream; multiple workers would land the poster and the viewer in
#    different processes. --threads keeps SSE + MJPEG (long-lived) concurrent.
CMD ["sh", "-c", "python -c 'import db; db.init_db()' && exec gunicorn --chdir /app/webapp -w 1 --threads 16 --timeout 120 -b 0.0.0.0:8080 app:app"]
