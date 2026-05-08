# ─── Dev (default, hot-reload via volume mount) ────────────────
FROM node:22-alpine AS dev
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
CMD ["npm", "run", "dev"]

# ─── Builder ───────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
ARG NEXT_PUBLIC_API_URL=http://localhost:8001
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8001/ws
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
RUN npm run build && mkdir -p public

# ─── Production (standalone, minimal image) ───────────────────
FROM node:22-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
