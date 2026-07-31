Feature: Buscar faturamento
  Como tela do CRA
  Quero consultar o faturamento consolidado de um conglomerado
  Para exibir o melhor valor disponível para cada subgrupo

  Background:
    Given um conglomerado "12345678000100" com os subgrupos "AAA,BBB" no NJ6
    And o catálogo de parâmetros do buscar tem as faixas padrão

  Scenario: Subgrupo sem dado salvo usa o resultado do Endpoint
    Given que o subgrupo "AAA" não tem nenhum valor salvo no banco
    And o Endpoint devolve um resultado de "5000000" para o subgrupo "AAA"
    When eu buscar o faturamento do conglomerado "12345678000100"
    Then o marcador do subgrupo "AAA" deve ter origem "ENDPOINT"

  Scenario: Subgrupo sem banco e sem Endpoint fica manual
    Given que o subgrupo "BBB" não tem nenhum valor salvo no banco
    And o Endpoint não devolve nenhum resultado para o subgrupo "BBB"
    When eu buscar o faturamento do conglomerado "12345678000100"
    Then o marcador do subgrupo "BBB" deve ter origem "MANUAL"

  Scenario: Subgrupo em quarentena usa o valor anterior, sem consultar o Endpoint
    Given que o subgrupo "AAA" está em quarentena com um valor anterior de "4000000" salvo
    When eu buscar o faturamento do conglomerado "12345678000100"
    Then o marcador do subgrupo "AAA" deve estar em quarentena
    And o marcador do subgrupo "AAA" deve ter o valor "4000000"

  Scenario: Banco sempre vence, mesmo com resultado disponível no Endpoint
    Given que o subgrupo "AAA" já tem um valor de "6000000" salvo no banco
    And o Endpoint devolve um resultado de "9000000" para o subgrupo "AAA"
    When eu buscar o faturamento do conglomerado "12345678000100"
    Then o marcador do subgrupo "AAA" deve ter origem "BASE"
    And o marcador do subgrupo "AAA" deve ter o valor "6000000"

  Scenario: Falha isolada no Endpoint não derruba os outros subgrupos
    Given que o subgrupo "AAA" não tem nenhum valor salvo no banco
    And o Endpoint falha ao consultar o subgrupo "AAA"
    And que o subgrupo "BBB" não tem nenhum valor salvo no banco
    And o Endpoint devolve um resultado de "1000000" para o subgrupo "BBB"
    When eu buscar o faturamento do conglomerado "12345678000100"
    Then o marcador do subgrupo "AAA" deve ter origem "MANUAL"
    And o marcador do subgrupo "BBB" deve ter origem "ENDPOINT"
