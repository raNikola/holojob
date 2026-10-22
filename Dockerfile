# Stage 1: Build frontend
FROM node:20-bookworm AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Runtime with Python + Node
FROM python:3.12-slim-bookworm
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates \
    libxcb-shm0 libx11-xcb1 libxcb1 libx11-6 libxext6 libxrender1 \
    libxrandr2 libxcomposite1 libxcursor1 libxdamage1 libxi6 libxfixes3 \
    libgtk-3-0 libgdk-pixbuf-2.0-0 libpangocairo-1.0-0 libpango-1.0-0 \
    libcairo-gobject2 libcairo2 libatk1.0-0 libatk-bridge2.0-0 \
    libglib2.0-0 libdbus-1-3 libdbus-glib-1-2 libxt6 \
    libasound2 libfreetype6 libfontconfig1 \
    libnss3 libnspr4 libcups2 libdrm2 libgbm1 libxkbcommon0 \
    libatspi2.0-0 libxshmfence1 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

RUN npm install -g @anthropic-ai/claude-code && claude --version

COPY python ./python
COPY scripts ./scripts
COPY companies ./companies
COPY data/examples ./data/examples
COPY requirements.txt ./

RUN bash scripts/setup-job-discovery.sh

# Put the venv first so bare `python` (e.g. `podman exec career-os python ...`)
# sees the same dependencies as the app, which runs .venv/bin/python.
ENV PATH="/app/.venv/bin:${PATH}"

COPY --from=frontend /app/dist ./dist
COPY src ./src

RUN mkdir -p data/profile data/intelligence data/jobs data/resumes data/outreach data/cache data/analytics data/audits data/interviews

ENV PORT=5173
ENV CLAUDE_AUTO_LOGIN=0
EXPOSE 5173
VOLUME ["/app/data"]

CMD ["npm", "run", "start:server"]
