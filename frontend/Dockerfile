FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_API_BASE_URL=/api
ARG VITE_APP_VERSION=V1.009
ARG NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_APP_VERSION=$VITE_APP_VERSION
ENV NPM_CONFIG_REGISTRY=$NPM_CONFIG_REGISTRY

COPY package*.json ./
RUN npm ci

COPY index.html vite.config.js ./
COPY src ./src

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
