# CS2HQ 前端多阶段构建：node 构建 → nginx 托管
# /api 由 nginx 反代到后端服务名（compose 网络），无需 host.docker.internal
FROM node:22-alpine AS builder
WORKDIR /app
# 路径前缀部署（will-site /cs2hq/）：构建时注入 base，资源与 API 调用都带前缀
ARG VITE_BASE=/
# 先拷贝清单利用层缓存
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build -- --base=${VITE_BASE}

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# SPA 路由回退 + /api 反代到 compose 服务名 backend:8101
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx-spa.conf /etc/nginx/conf.d/app.conf
EXPOSE 80
