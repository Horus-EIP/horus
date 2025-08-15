FROM node:18-alpine

# Work in nested Next.js app folder
WORKDIR /app/app

# Install dependencies
COPY app/package*.json ./
RUN npm install

# Copy source
COPY app/ ./

EXPOSE 3000

CMD ["npm", "run", "dev"]


