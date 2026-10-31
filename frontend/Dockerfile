FROM node:20-alpine AS build
WORKDIR /app
# Install from lockfile inside the image — never copy host node_modules (Windows .bin breaks BuildKit)
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Same-origin /api — nginx proxies to the api service in Compose
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
