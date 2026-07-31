Feature: Salvar faturamento
  Como analista de faturamento
  Quero salvar o valor de faturamento de um subgrupo
  Para que a tela reflita o valor mais atual do conglomerado

  Background:
    Given o catálogo de parâmetros do salvar tem as faixas padrão
    And o catálogo de parâmetros do salvar aceita as moedas "BRL,USD"

  Scenario: Salvar um valor dentro de uma faixa conhecida
    Given um marcador para o subgrupo "12345678000100" com valor "5000000" e moeda "BRL"
    When eu salvar o faturamento do conglomerado "12345678000100"
    Then o faturamento deve ser persistido com sucesso
    And o marcador do subgrupo "12345678000100" deve ter a faixa "FAIXA_2"

  Scenario: Salvar sem nenhum marcador falha
    Given um faturamento sem nenhum marcador para o conglomerado "12345678000100"
    When eu tentar salvar o faturamento do conglomerado "12345678000100"
    Then deve ser rejeitado com erro de validação

  Scenario: Valor fora de qualquer faixa conhecida falha
    Given um marcador para o subgrupo "12345678000100" com valor "1" e moeda "BRL"
    When eu tentar salvar o faturamento do conglomerado "12345678000100"
    Then deve ser rejeitado com erro de validação

  Scenario: Divergência de valor não confirmada é barrada
    Given que já existe um valor salvo de "1000000" para o subgrupo "12345678000100"
    And o gate de divergência está ativo com limite de "30" por cento
    And um marcador para o subgrupo "12345678000100" com valor "5000000" e moeda "BRL"
    When eu tentar salvar o faturamento do conglomerado "12345678000100"
    Then deve ser exigida confirmação de divergência

  Scenario: Divergência confirmada é aceita
    Given que já existe um valor salvo de "1000000" para o subgrupo "12345678000100"
    And o gate de divergência está ativo com limite de "30" por cento
    And um marcador para o subgrupo "12345678000100" com valor "5000000" e moeda "BRL" confirmando a divergência
    When eu salvar o faturamento do conglomerado "12345678000100"
    Then o faturamento deve ser persistido com sucesso
