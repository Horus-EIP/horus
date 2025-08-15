FROM python:3.9-slim

WORKDIR /

COPY requirements.txt .
COPY ./app/ app/
COPY ./documents/ documents/
COPY ./chroma_data/ chroma_data/

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--reload"]


