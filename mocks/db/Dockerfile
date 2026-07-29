FROM python:3.11-slim

WORKDIR /srv

RUN pip install --no-cache-dir boto3

COPY init_table.py .

CMD ["python", "init_table.py"]
