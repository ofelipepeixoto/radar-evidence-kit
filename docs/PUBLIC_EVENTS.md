# Eventos públicos — extração original e offline

Núcleo autoral MIT de Carlos Felipe, inspirado conceitualmente nos contratos de
observação e composição de ferramentas estudados no God’s Eye View. Esta entrega
não copia código, assets, tiles ou datasets upstream. Não distribui o globo e não
instala suas dependências vulneráveis. Referência/limite de autoria:
[ADR](adr/0001-public-event-extraction.md).

## Executar

Python 3.11+, sem dependências de runtime novas:

```bash
python -m pip install --no-deps .
python -m unittest discover -s tests -v
python examples/public_events_demo.py
```

A demonstração consulta dois registros sintéticos, registra uma avaliação
**pendente** no Journal real SQLite, verifica a cadeia e elimina somente seu
banco temporário. O hostname example.invalid é metadata, nunca acessado. Não há
coleta ativa, MCP remoto, LLM, n8n, publicação ou chamada paga.

## Contratos

Importação explícita: `from radar_evidence.public_events import PublicEvent,
EventSnapshot, SourcePolicy, PublicEventCatalog`.

- `PublicEvent`: event_id, kind, observed_at_ms, latitude_e6, longitude_e6, summary.
  Coordenadas WGS84 em micrograus inteiros; converter externamente usando uma
  política explícita de arredondamento. Horários em Unix milissegundos; `None`
  significa observação desconhecida, nunca horário de recebimento.
- `EventSnapshot`: tenant_id, project_id, snapshot_id, revision, source_id,
  source_url, license_ref, source_sha256, retrieved_at_ms, coverage, records.
  Coverage: complete/partial/unknown. Registros imutáveis, IDs únicos dentro de
  cada snapshot; até 100 registros, total de 12 KiB. Shape exato na desserialização.
- `SourcePolicy`: configuração confiável de source_id, URL, licença e permissão
  comercial. URL/identificador de licença devem coincidir com o snapshot. A flag
  comercial registra a decisão do operador; **não comprova permissão jurídica**.
- `PublicEventCatalog`: até 16 snapshots e 16 políticas, vinculados ao Scope e
  suas revisões atuais. Recriar o catálogo após revisão/revogação; não existe
  atualização automática. Só os dados previamente configurados são consultados.

`source_sha256` é o hash declarado dos bytes originais; o coletor futuro deverá
compará-lo aos bytes reais. `snapshot_sha256` cobre a representação canônica Radar
inteira, inclusive fonte, licença, escopo e tempos. Nenhum hash prova verdade,
origem autêntica ou licença. A normalização admite somente strings/inteiros/
booleanos/null/containers limitados, compatível com o ledger existente.

`to_evidence()` preserva snapshot completo no texto e o source_sha256 declarado.
Usa document_id=snapshot_id, page=1 como envelope sintético (não página de PDF),
review_status=pending e identity_verified=false. Reutiliza Journal/check_evidence;
não altera o formato v1 de recibos e não concede aprovação. Receipts guardam texto
integral; avaliar retenção e acesso antes de usar dados reais.

## Consultas somente leitura

`call(name, arguments, now_ms=...)`: now_ms e max_age_ms são fornecidos pela
aplicação, fora dos argumentos do modelo. Não aceitar configuração do cliente.

| Ferramenta | Shape exato de arguments | Saída |
|---|---|---|
| events.query | bbox_e6=[west,south,east,north], start_ms, end_ms, limit | Registros dentro de área/tempo, matched_records local, truncated, contagem de horários desconhecidos na área e metadata dos snapshots |
| events.get | snapshot_id, event_id | Registro específico ou null; nunca busca URL/file path |

BBox e intervalo são inclusivos; não atravessa antimeridiano (dividir em duas
consultas). Limit inteiro 1–20. Ordenação crescente por horário/snapshot/ID.
Horários desconhecidos ficam fora da consulta temporal, mas aparecem no contador
e permanecem recuperáveis por events.get. Cada registro devolve frescor da
coleta separado do frescor da observação: fresh/stale/unknown/future. Uma coleta
recente não transforma evento antigo em observação recente. Eventos stale/future
não são apagados; cabe ao consumidor decidir sua elegibilidade.

`matched_records` só conta correspondências no acervo local; não é total global
do provedor. A consulta conserva registros de snapshots diferentes, inclusive
o mesmo event_id em revisões/coletas distintas. O consumidor deve reconciliar
identidade/versão se contar eventos únicos. `absence_supported=false` em todas
as respostas: nenhum conjunto vazio prova ausência de eventos no mundo.

Não há texto executável nem interpretação de instruções de summary. Todos os
nomes de tools fora das duas permitidas e campos extras são rejeitados. Dados
retornados são cópias sem referência mutável aos snapshots.

## Integração e limites

O código é um catálogo offline; **não é um servidor MCP conectado ao ChatGPT**.
Control Plane poderá envolver essas duas consultas com sua identidade, transporte
e recibos. Antes disso, fixar revisão do Evidence Kit e validar contratos entre
os repositórios. Hub poderá receber a Evidence pendente dentro do seu fluxo de
rascunho/revisão existente. n8n poderá disparar um coletor testado; nenhum workflow
foi ativado aqui. Não criar novo serviço ou repo para esta fatia.

Fontes reais, busca em API externa, licença vigente, armazenamento durável,
conexão Control Plane/Hub, custódia externa do checkpoint, UI e E2E permanecem
pendentes. Este núcleo limita seu próprio acervo; não protege stdin/HTTP contra
flood. O patch stdio do estudo upstream é separado e não foi incorporado.

Critérios verificados: escopo/revisão, allowlist, UTF-8 bytes, tempos desconhecidos,
bounds, truncamento, mensagens inesperadas, frescor independente, outputs
desacoplados e integração real com o Journal incluindo rejeição de replay com
checkpoint antigo. Suites/modelos opcionais mantêm seus gates próprios.
