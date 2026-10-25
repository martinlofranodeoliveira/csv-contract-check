# csv-contract-check

Valide um arquivo CSV antes de importá-lo em outro sistema. Um contrato JSON
descreve os cabeçalhos, os campos obrigatórios e os tipos esperados; o relatório
aponta cada problema com a linha física correspondente.

Python 3.10 ou superior. A execução e os testes usam somente a biblioteca padrão,
sem conexão de rede. Licença MIT. A [referência completa em inglês](README.md)
inclui a API, a gramática numérica e todos os códigos de erro.

## Uso

Dentro da pasta do projeto, sem instalar pacotes:

```sh
python3 -m csv_contract_check --schema examples/people.schema.json examples/valid.csv
# OK: 3 record(s) checked.

python3 -m csv_contract_check --schema examples/people.schema.json --format json examples/invalid.csv

cat examples/valid.csv | python3 -m csv_contract_check --schema examples/people.schema.json -
python3 -m csv_contract_check --help
```

O argumento `-` lê o CSV pela entrada padrão. O esquema deve ser um caminho de
arquivo. A opção `--format json` escreve um único objeto JSON em stdout, terminado
por uma quebra de linha; o padrão é um relatório textual em inglês.

## Contrato

Este formato é específico do projeto; não é JSON Schema.

```json
{
  "version": 1,
  "allow_extra_columns": false,
  "columns": [
    {"name": "id", "type": "integer", "required": true},
    {"name": "name", "type": "string", "required": true},
    {"name": "active", "type": "boolean", "required": true},
    {"name": "score", "type": "number"}
  ]
}
```

`version` deve ser o inteiro `1`. `columns` deve ser uma lista não vazia, com nomes
únicos e não vazios. `required` e `allow_extra_columns` são booleanos e assumem
`false` quando omitidos. Propriedades desconhecidas, nomes duplicados, propriedades
JSON repetidas, versões/tipos incompatíveis e JSON inválido são rejeitados.

Todos os nomes do esquema precisam estar no cabeçalho, mesmo quando o valor da
célula é opcional. A ordem das colunas pode variar. Colunas extras são rejeitadas
por padrão; com `allow_extra_columns: true`, seus valores são ignorados, mas elas
continuam contando no número de campos da linha. Cabeçalhos vazios ou repetidos
sempre são inválidos.

| Tipo | Valor não vazio aceito |
| --- | --- |
| `string` | Qualquer texto, inclusive espaços e quebras de linha entre aspas |
| `integer` | Algarismos ASCII com sinal opcional; zeros à esquerda são aceitos |
| `number` | Decimal finito com sinal e expoente opcionais, como `-2.5`, `.5` ou `1e3` |
| `boolean` | Somente `true` ou `false`, em minúsculas |

Uma célula vazia é aceita se for opcional. Espaços são preservados: um espaço
atende a uma string obrigatória, mas não é um número válido. Não há conversão de
maiúsculas, remoção de espaços nem interpretação de vírgula decimal. NaN e Infinity
são rejeitados, assim como números hexadecimais ou com separadores `_`.

## Resultado

O JSON contém `valid`, `records_checked` e `errors`. Cada erro possui `code`,
`line`, `column` e `message`. Erros de entrada/esquema usam `null` nos campos de
localização. Os relatórios não incluem valores das células; nomes de cabeçalhos
aparecem na identificação das colunas.

| Código de saída | Significado |
| --- | --- |
| `0` | CSV válido |
| `1` | Cabeçalho, sintaxe CSV, quantidade de campos ou valores inválidos |
| `2` | Esquema inválido, erro de leitura/UTF-8 ou uso incorreto do comando |

Os relatórios vão para stdout. Erros de argumentos usam texto em stderr.
`--help` e `--version` funcionam sem ler arquivos.

Erros de cabeçalho impedem a validação dos registros. Nos demais casos, os erros
seguem a ordem dos registros e das colunas no esquema. Um registro com quantidade
incorreta de campos gera um erro e não tem suas células verificadas. Registros
completos são contados, inclusive registros vazios ou com quantidade incorreta de
campos; um registro com sintaxe CSV malformada interrompe a leitura e não é contado.

## Formato e limites

Os arquivos e a entrada padrão devem usar UTF-8, com BOM opcional. O separador é
vírgula, as aspas são duplas e uma aspa dentro do campo é representada por duas
aspas. Campos com vírgulas e várias linhas são aceitos. O relatório indica a
primeira linha física de cada registro, incluindo os registros malformados.

Um arquivo só com cabeçalho pode ser válido. Um arquivo vazio é inválido. Uma linha
em branco tem zero campos, diferente de uma célula vazia escrita entre aspas.
O limite de tamanho de campo de `csv.field_size_limit()` é respeitado sem ser
alterado. Todos os erros ficam na memória até o relatório. Não há validação de
datas, inferência de tipos, outros delimitadores nem sanitização de fórmulas de
planilha. Use dados sintéticos ao relatar problemas.

## Testes e contribuições

```sh
python3 -B -m unittest discover -s tests -v
```

Para contribuir, inclua um caso pequeno com dados sintéticos e preserve a ordem
determinística dos erros. Não envie arquivos de clientes nem credenciais.

Copyright 2026 Martin Lofrano de Oliveira. Consulte [LICENSE](LICENSE).
