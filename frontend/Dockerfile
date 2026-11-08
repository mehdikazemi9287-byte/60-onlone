FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# NEXT_PUBLIC_* are baked into the client bundle at build time
ARG NEXT_PUBLIC_API_URL=""
ARG NEXT_PUBLIC_MAIN_SITE=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_MAIN_SITE=$NEXT_PUBLIC_MAIN_SITE
RUN npm run build

ENV NODE_ENV=production
ENV PORT=3000
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0"]
