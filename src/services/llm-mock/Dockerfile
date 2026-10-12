FROM python:3.11.17-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin horus

WORKDIR /app

COPY llm_mock ./llm_mock

COPY --from=notices THIRD_PARTY_NOTICES /usr/share/doc/horus/THIRD_PARTY_NOTICES
COPY --from=notices LICENSES /usr/share/doc/horus/LICENSES
COPY --from=notices NOTICES /usr/share/doc/horus/NOTICES

USER 10001

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"]

CMD ["python", "-m", "llm_mock"]
