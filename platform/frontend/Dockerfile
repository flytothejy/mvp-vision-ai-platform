# Frontend Dockerfile for Development
# Uses npm run dev with hot reload

ARG REGISTRY_MIRROR=
FROM ${REGISTRY_MIRROR}node:20-alpine

WORKDIR /app

# Create a non-root user (same UID as K8s securityContext)
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source code
COPY . .

# Set ownership and permissions for all files
RUN chown -R 1001:1001 /app && chmod -R 755 /app

# Switch to non-root user
USER nextjs

# Expose dev server port
EXPOSE 3000

ENV NODE_ENV=development
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME="0.0.0.0"

# Start dev server with hot reload
CMD ["npm", "run", "dev"]
