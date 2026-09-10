# ARIADNE MCP server — official MCP SDK over streamable HTTP
FROM node:20-alpine AS build
WORKDIR /srv/mcp
COPY apps/mcp-server/package.json apps/mcp-server/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY apps/mcp-server .
RUN npm run build

FROM node:20-alpine
WORKDIR /srv/mcp
COPY --from=build /srv/mcp /srv/mcp
EXPOSE 8765
CMD ["node", "dist/index.js"]
