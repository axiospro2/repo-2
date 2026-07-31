"""Constantes de validação de path/query params compartilhadas entre as rotas.

`documento` aceita qualquer sequência de dígitos (CPF, CNPJ, CGI ou outro
identificador numérico), sem exigir uma faixa de tamanho fixa (9 a 14) nem
validar o dígito verificador. O objetivo aqui é só falhar rápido (422) em
entradas obviamente malformadas (vazio, letras), não validar o formato exato
do documento.
"""

from __future__ import annotations

DOCUMENTO_PATTERN = r"^\d+$"
DOCUMENTO_DESCRICAO = "Documento numérico do conglomerado (CPF, CNPJ, CGI ou outro identificador)"
