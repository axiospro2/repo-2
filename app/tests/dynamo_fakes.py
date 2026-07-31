"""Dublê mínimo do recurso boto3 do DynamoDB, injetável em `DynamoRepository`
(que aceita `dynamodb=...` no construtor) — sem precisar de DynamoDB local."""

from __future__ import annotations


class _FakeBatchWriter:
    def __init__(self, table: "FakeTable") -> None:
        self._table = table

    def __enter__(self) -> "_FakeBatchWriter":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def put_item(self, Item: dict) -> None:
        self._table.itens[(Item["cod_cogl"], Item["cod_subg"])] = Item


class FakeTable:
    def __init__(self) -> None:
        self.itens: dict[tuple[str, str], dict] = {}

    def get_item(self, Key: dict) -> dict:
        item = self.itens.get((Key["cod_cogl"], Key["cod_subg"]))
        return {"Item": item} if item is not None else {}

    def query(self, KeyConditionExpression) -> dict:
        valor = KeyConditionExpression._values[1]  # boto3.dynamodb.conditions.Equals
        return {"Items": [it for (cogl, _), it in self.itens.items() if cogl == valor]}

    def batch_writer(self) -> _FakeBatchWriter:
        return _FakeBatchWriter(self)


class FakeDynamoResource:
    def __init__(self, table: FakeTable) -> None:
        self._table = table

    def Table(self, name: str) -> FakeTable:
        return self._table
