# ---- deps: install packages with pnpm, pinned to the committed lockfile ----
FROM node:22-alpine AS deps
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ---- builder: build the Next.js app ----
FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* vars are inlined into the client bundle at build time by
# Next.js, so they have to arrive as build args here — setting them only as
# container env vars at runtime would be too late.
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_DEFAULT_TENANT_ID
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
    NEXT_PUBLIC_DEFAULT_TENANT_ID=$NEXT_PUBLIC_DEFAULT_TENANT_ID \
    NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

RUN pnpm build

# ---- runner: serve the production build ----
FROM node:22-alpine AS runner
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9 --activate
ENV NODE_ENV=production

COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.mjs ./next.config.mjs

EXPOSE 3000
CMD ["pnpm", "start"]
