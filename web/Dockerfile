FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_MAIN_SITE=https://60online.ir
ARG NEXT_PUBLIC_SITE_URL=https://vambi.ir
ARG VAMBI_API_ORIGIN=https://60online.ir
ENV NEXT_PUBLIC_MAIN_SITE=$NEXT_PUBLIC_MAIN_SITE NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL VAMBI_API_ORIGIN=$VAMBI_API_ORIGIN
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
