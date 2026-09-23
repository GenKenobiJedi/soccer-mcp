FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir apify beautifulsoup4 lxml

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY actor/src/main.py /app/main.py

ENTRYPOINT ["python3", "/app/main.py"]
