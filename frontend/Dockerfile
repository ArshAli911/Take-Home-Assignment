# --- build stage ---------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json ./
# Use `npm install` (not `npm ci`) so the build works whether or not a
# lockfile is committed — convenient for a take-home repo.
RUN npm install

COPY . .
RUN npm run build

# --- serve stage ---------------------------------------------------------
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
