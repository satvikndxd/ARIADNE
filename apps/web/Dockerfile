# ARIADNE web — build with vite, serve with vite preview (prototype-grade)
FROM node:20-alpine AS build
WORKDIR /srv/web
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY apps/web .
RUN npm run build

FROM node:20-alpine
WORKDIR /srv/web
COPY --from=build /srv/web /srv/web
EXPOSE 4173
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "4173"]
