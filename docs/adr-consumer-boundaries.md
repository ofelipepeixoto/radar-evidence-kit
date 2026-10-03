# ADR — integridade histórica e responsabilidades dos consumidores

Data: 2026-10-03. Estado: adotada para o laboratório; sem homologação operacional.

## Contexto

O núcleo já liga tenant, projeto, documento, revisão, hashes, texto integral,
span, rótulo de revisor e flag de identidade ao `evidence_id`. O recibo inclui
Evidence, Scope e a avaliação padrão recalculada. SQLite usa `BEGIN IMMEDIATE`
e compara o checkpoint retido dentro da transação. Não foi identificado um
motivo para mudar esses schemas ou acrescentar flags de identidade.

Os dois consumidores são `assistente-documental-ia` (exportação opcional) e
`avaliacao-rag-juridico` (experimento de elegibilidade de citação). A presença
de uma implementação em uma branch não homologa seu runtime, identidade,
permissões ou qualidade jurídica. Fixar o commit do pacote e testar a
composição escolhida continuam sendo responsabilidade de cada consumidor.

## Decisão

Manter Python stdlib, schemas e API existentes. Não adicionar servidor MCP,
banco remoto, autenticador, policy engine ou integração SPARQL ao pacote.
Usar o kit como contrato de dados e registro de avaliação histórica.

| Momento | Verificação do consumidor | Limite do kit |
|---|---|---|
| Ingestão | Calcular SHA-256 dos bytes completos e guardar origem e revisão | Só valida o formato de `source_sha256` |
| Extração | Ligar texto/página ao original e à revisão atual; preservar o texto inteiro | Recalcula `text_sha256`, sem executar ou certificar extratores |
| Revisão | Obter decisão e identidade em um canal autenticado; ligar ao hash/revisão/span revistos | `reviewer` e `identity_verified` são afirmações do emissor |
| Avaliação | Emitir Scope de estado confiável, nunca do documento ou de um LLM | Compara tenant/projeto/documento/revisão e política declarada |
| Recibo | Fornecer a avaliação padrão e o checkpoint mais recente retido fora do banco | Detecta divergência, sem fornecer custódia externa |
| Reuso | Revalidar origem, revisão, decisão e identidade atuais; recalcular `check_evidence` | Verificar a cadeia histórica não renova elegibilidade |
| Ação externa | Autorizar, limitar orçamento e executar no serviço responsável | Recibo, `supported=True` e PROV-O não autorizam ações |

Um PDF substituído precisa de revisão nova, mesmo se o texto da página parecer
igual. Um hash correto identifica bytes, mas não garante quem produziu o
artefato nem a verdade de seu conteúdo. Uma evidência pode ser elegível para
citação e não sustentar semanticamente a afirmação da resposta.

O consumidor documental local conserva `identity_verified=False`: rótulo
digitado não é identidade autenticada. Os fixtures de avaliação podem usar
flags sintéticas para testar o contrato; isso não representa revisão humana
real. Não promover exportações, fixtures ou respostas de LLM a aprovações.

## Escrita concorrente, retry e custódia

Dois escritores com o mesmo checkpoint antigo não podem criar sucessores
independentes: só um confirma; o outro recebe `IntegrityError`. Replays
simultâneos com o mesmo `event_id` e evento têm esse comportamento quando enviam
o checkpoint anterior. O replay idempotente exige o checkpoint atual retido
pelo domínio confiável. IDs iguais com outro conteúdo continuam recusados.

Após timeout ou perda de resposta entre commit SQLite e custódia, não substituir
o checkpoint por um hash calculado do próprio banco. Registrar a operação como
pendente e reconciliar com o registro independente do operador e backup. O kit
recusa o retry com checkpoint antigo; não fornece transação distribuída ou
uma estratégia automática de recuperação. O consumidor precisa definir
custódia, retenção, proteção de dados, backup e reconciliação antes da produção.

Guardar banco e checkpoint juntos não protege contra reescrita dos dois. Uma
mudança de Scope atual não reescreve recibos antigos: `verify` confirma a
integridade do que foi avaliado naquele momento; `check_evidence` confirma
elegibilidade perante o Scope recebido agora. Revogações de identidade e
revisão exigem consulta e emissão atualizadas pela aplicação.

## Evidência desta decisão

Novos testes usam conexões SQLite independentes e uma barreira de threads,
sem mocks do mecanismo transacional. Verificam concorrência entre eventos
distintos, replay simultâneo com checkpoint antigo e retry explícito com o
checkpoint vencedor. Outro teste abre o histórico com uma revisão atual nova:
a cadeia permanece íntegra, mas a evidência antiga é recusada com
`stale_revision`; um check positivo antigo não pode entrar como avaliação nova.

Os testes existentes cobrem hashes/review fields, serialização canônica,
alteração/truncamento da cadeia, replay divergente, rollback e permissões.
Esses testes não implementam custódia, autenticação, throughput ou implantação.
O adapter Semantica permanece opcional e experimental; políticas, SPARQL,
MCP e ações upstream continuam fora da adoção operacional.
