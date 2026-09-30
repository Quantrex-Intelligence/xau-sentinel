# Production build of the Next.js frontend. The browser only talks to this
# server's own origin: next.config.ts rewrites /api/* and /ws/* to
# API_PROXY_TARGET, so one image works on any hostname. Rewrites are compiled
# at build time, so the target (a container-network address) is a build arg.
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --legacy-peer-deps

FROM node:22-slim AS build
WORKDIR /app
ARG API_PROXY_TARGET=http://api:8000
ARG NEXT_PUBLIC_API_AUTH_TOKEN=""
ENV API_PROXY_TARGET=$API_PROXY_TARGET \
    NEXT_PUBLIC_API_AUTH_TOKEN=$NEXT_PUBLIC_API_AUTH_TOKEN \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-slim AS run
WORKDIR /app
ARG API_PROXY_TARGET=http://api:8000
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    API_PROXY_TARGET=$API_PROXY_TARGET \
    PORT=3000
COPY --from=build --chown=node:node /app/package.json ./package.json
COPY --from=build --chown=node:node /app/next.config.ts ./next.config.ts
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
