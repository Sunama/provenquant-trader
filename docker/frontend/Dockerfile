FROM node:22-alpine

WORKDIR /app

# Copy only manifest first — layer is cached until deps change
COPY frontend/package.json frontend/package-lock.json* ./

RUN npm install

# Source files are mounted at runtime via volume (hot reload)
CMD ["npm", "run", "dev"]
