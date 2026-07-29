"""Cria a tabela do DynamoDB local, se ainda não existir. Roda uma vez via docker-compose."""
from __future__ import annotations

import os
import time

import boto3
from botocore.exceptions import ClientError

ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT", "http://dynamodb-local:8000")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "tbcv4163_fatm_cogl_subg")


def _client():
    return boto3.client(
        "dynamodb",
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )


def _wait_for_dynamo(client, tries: int = 30, delay_s: float = 1.0) -> None:
    for i in range(tries):
        try:
            client.list_tables()
            return
        except Exception:
            time.sleep(delay_s)
    raise RuntimeError(f"DynamoDB local não respondeu em {ENDPOINT} após {tries * delay_s}s")


def main() -> None:
    client = _client()
    _wait_for_dynamo(client)

    try:
        client.describe_table(TableName=TABLE_NAME)
        print(f"tabela '{TABLE_NAME}' já existe")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    client.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "cod_cogl", "KeyType": "HASH"},
            {"AttributeName": "cod_subg", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "cod_cogl", "AttributeType": "S"},
            {"AttributeName": "cod_subg", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    print(f"tabela '{TABLE_NAME}' criada")


if __name__ == "__main__":
    main()
