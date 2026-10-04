# IP-SAKTI Sahayak frontend (React SPA, static build served by nginx).
#
#   docker build -t ipsakti-frontend ./FRONTEND
#   docker run -p 5173:80 ipsakti-frontend
#
# The Vite dev proxy (vite.config.js) is a development convenience only;
# this image bakes the production bundle and proxies /api/* to the
# backend service. Point API_PROXY_PASS at the backend origin.
FROM node:24-alpine AS build
WORKDIR /srv/web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /srv/web/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
