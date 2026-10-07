FROM node:20.20.2-alpine AS deps
WORKDIR /app
ENV NPM_CONFIG_UPDATE_NOTIFIER=false
COPY package*.json ./
COPY .npmrc ./
RUN npm ci

FROM node:20.20.2-alpine AS builder
WORKDIR /app
ENV NPM_CONFIG_UPDATE_NOTIFIER=false
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG ORCHESTRATOR_URL=http://mas:8000
ENV ORCHESTRATOR_URL=${ORCHESTRATOR_URL}
ARG NEXT_PUBLIC_KNOWLEDGE_STORE_URL=http://localhost:8080
ENV NEXT_PUBLIC_KNOWLEDGE_STORE_URL=${NEXT_PUBLIC_KNOWLEDGE_STORE_URL}
ARG NEXT_PUBLIC_KNOWLEDGE_STORE_API_PREFIX=
ENV NEXT_PUBLIC_KNOWLEDGE_STORE_API_PREFIX=${NEXT_PUBLIC_KNOWLEDGE_STORE_API_PREFIX}

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20.20.2-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Runtime: Route Handler proxy reads ORCHESTRATOR_URL per request.
ARG ORCHESTRATOR_URL=http://mas:8000
ENV ORCHESTRATOR_URL=${ORCHESTRATOR_URL}

RUN addgroup -g 1001 -S nodejs && adduser -S -u 1001 -G nodejs nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
