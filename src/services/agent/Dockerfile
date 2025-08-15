FROM python:3.11-slim

WORKDIR /app

# Install only the runtime deps we need
RUN pip install --no-cache-dir fastapi uvicorn requests pika

# Copy the agent application as the working dir
COPY ./app/ /app/

ENV ORCHESTRATOR_URL=http://mas:8000
ENV RABBITMQ_HOST=rabbitmq

EXPOSE 8001

CMD ["python", "main.py"]


