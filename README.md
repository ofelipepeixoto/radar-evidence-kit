# radar-evidence-kit — experimental 0.2.0

O contrato aditivo 0.2 inclui referências a trechos com contexto integral,
revisão e hashes preservados. Veja [citações](docs/citacoes.md). Os contratos
`Evidence`, `Scope` e journal existentes continuam compatíveis.

Biblioteca **autoral de Carlos Felipe**, MIT, para contratos de evidência,
recibos SQLite e exportação PROV-O selecionada. O núcleo Python 3.11+ usa
somente a biblioteca padrão. Semantica é um motor opcional de terceiro;
a biblioteca não é um fork ou renomeação dele.

O núcleo inicial e seus testes foram extraídos sem alteração de
[`avaliacao-rag-juridico` em `2fb8059d55974795c9db7bd4fa2540d4f5af5d2a`](https://github.com/ofelipepeixoto/avaliacao-rag-juridico/tree/2fb8059d55974795c9db7bd4fa2540d4f5af5d2a/packages/radar-evidence-kit).
Este repositório separa o núcleo reutilizável dos consumidores. O
[experimento com baseline e fixtures sintéticas](https://github.com/ofelipepeixoto/avaliacao-rag-juridico/tree/2fb8059d55974795c9db7bd4fa2540d4f5af5d2a/experiments/semantica)
continua naquela revisão; seu corpus, runner e métricas não foram incorporados
ao pacote.

## Instalação e testes

Na raiz deste repositório, em um ambiente virtual:

```sh
python -m pip install --no-deps .
python -c "import radar_evidence, sys; assert 'semantica' not in sys.modules"
python -m unittest discover -s tests -v
```

O build usa `setuptools>=68`; o pacote instalado não tem dependências de
runtime. Sem o motor opcional, a suíte tem 92 testes: 89 executados e os três
testes reais do adapter explicitamente skipped. A CI verifica o núcleo em
Python 3.11 e 3.12. A verificação local desta extração foi feita em Linux/Python
3.12; a execução 3.11 depende do job de CI.

## Contratos e escopo

`Evidence` exige exatamente os campos definidos em `src/radar_evidence/modelos.py`:
tenant, projeto, documento, revisão, página, texto integral, span Unicode
`[start:end]`, SHA-256 do original e do texto, estado de revisão, rótulo de
revisor e flag de identidade. Recalcula o hash do **texto inteiro**; o ID da
evidência inclui todos esses campos. O contrato valida o formato do hash do
original, mas verificar esse hash contra os bytes do artefato é responsabilidade
do consumidor. Nenhum campo é truncado ou normalizado.

`Scope` deve vir de configuração confiável da aplicação, com revisões atuais.
`check_evidence(evidence, scope)` recusa escopo/revisão divergente, revisão
pendente/rejeitada, revisor ausente e identidade não verificada. Uma flag é uma
afirmação do emissor: o kit não fornece login, assinatura ou autenticação.
Um dict de LLM não deve emitir aprovações, `Scope` ou `EvidenceCheck`. O modo
`require_verified_review=False` é uma política explícita de laboratório e não
verifica a identidade. O diário aceita somente avaliações da política padrão.

Texto: até 16 KiB UTF-8; IDs: até 256 code points; revisor: até 100; revisões e
páginas: inteiros positivos exatos (bool não é inteiro válido); Scope: até
10.000 documentos. `Evidence.from_dict` rejeita campos desconhecidos. Os
registros representam **elegibilidade de citação**, sem provar verdade jurídica
ou correspondência semântica entre uma resposta e a fonte.

Exemplo sintético com identidade ainda não verificada:

```python
from hashlib import sha256
from radar_evidence import Evidence, Scope, check_evidence

text = "Prazo fictício: 30 dias."
digest = sha256(text.encode("utf-8")).hexdigest()
evidence = Evidence(
    tenant_id="laboratorio", project_id="demo", document_id="documento-1",
    revision=1, page=1, start=0, end=len(text), text=text,
    source_sha256=digest, text_sha256=digest,
    review_status="approved", reviewer="revisor-sintetico",
    identity_verified=False,
)
scope = Scope("laboratorio", "demo", {"documento-1": 1})
check = check_evidence(evidence, scope)
assert check.supported is False
assert check.reasons == ("reviewer_identity_unverified",)
```

## Recibos e checkpoint independente

```python
from radar_evidence import Checkpoint, Journal, export_prov

# evidence, scope e check vêm da aplicação confiável, como no exemplo acima.
journal = Journal("recibos.sqlite3", scope)
previous = Checkpoint.empty(scope)  # somente ao iniciar um diário vazio
checkpoint = journal.append(
    evidence, check, event_id="avaliacao-001",
    occurred_at="2026-10-03T12:00:00Z", expected_checkpoint=previous,
)
# Retenha checkpoint em um domínio independente antes da próxima operação.
journal.verify(checkpoint)
prov = export_prov(journal, checkpoint)
```

SQLite usa transação `BEGIN IMMEDIATE`; sequência, hash anterior e envelope
JSON completo entram no checksum. A serialização local é versionada, com
nomes/tipos de campos, sem floats ou objetos arbitrários; não alega RFC 8785.
Um ID repetido com o mesmo evento é idempotente; conteúdo divergente é recusado.
O checkpoint anterior é comparado dentro da transação, evitando sobrescrever
histórico concorrente ou truncado silenciosamente. Texto de outro tenant/projeto
não entra no diário, mesmo quando a avaliação seria negativa.

**Um checkpoint independente é obrigatório.** Apagar o fim ou reescrever toda
a cadeia pode produzir uma cadeia interna válida; compará-la com count/head
guardados fora detecta isso. Guardar banco e checkpoint sob as mesmas permissões
não oferece essa garantia. O kit não implementa custódia, assinatura, retenção,
backup, criptografia, append-only remoto nem autoridade sobre ações.

Banco e custódia externa não têm commit distribuído. Se o banco confirmar um
append e a aplicação perder a confirmação/checkpoint, retry com o checkpoint
antigo é recusado. A reconciliação exige procedimento do operador com seu
registro independente e backup; não substitua o checkpoint apenas recalculando
a cadeia local. Retenha sempre o checkpoint mais recente.

`verify` e `export_records` verificam a integridade do **histórico**, usando o
Scope registrado em cada evento. Uma avaliação positiva antiga continua no
histórico após mudança de revisão; ela não vale como citação atual. Antes de
reutilizar uma evidência, o consumidor deve verificar os bytes do original,
seu vínculo à revisão e ao texto, e chamar `check_evidence` com o Scope atual
emitido pela aplicação. O kit não consulta revogação de identidade ou aprovações.
Veja a [decisão de integração dos consumidores](docs/adr-consumer-boundaries.md).

Limites: 1.000 recibos por diário, 64 KiB por registro e profundidade JSON 8.
O append verifica a cadeia inteira: adequado a este laboratório pequeno, sem
garantia de throughput ou prazo máximo. O diário contém o texto integral;
use somente dados sintéticos no Git/CI. Arquivos novos usam modo 0600; em POSIX
o kit recusa arquivos existentes acessíveis a grupo/outros, de outro proprietário
ou symlinks. Use também uma pasta privada. No Windows, configure ACLs do usuário:
o kit não gerencia ACLs nem isola o runtime.

## PROV-O selecionado

O exportador original produz JSON-LD com contexto inline, `Entity` para a
evidência e `Activity` para a avaliação. `qualifiedAssociation` pertence à
Activity e aponta ao `Agent` do rótulo de revisor; a flag de identidade é
preservada. Não exporta texto nem nome literal do revisor. IDs/hashes permitem
correlação e ataques de dicionário a rótulos previsíveis: o resultado não é
anonimização. A exportação não consulta URLs, RDF/SPARQL ou contextos remotos,
e não alega conformidade integral de um histórico PROV.

## Adapter Semantica opcional

`radar_evidence.semantica_adapter.evaluate_support(checks)` chama somente
`TruthMaintenanceSession`, `Rule` e `FactSupport`, com duas regras fixas e
átomos derivados de hashes. Entrada: 1–20 EvidenceChecks únicos, emitidos pela
aplicação confiável. Retorno determinístico com escopo `citation_contract_only`;
nenhum texto de documento vira regra. `evaluation_completed` distingue uma
avaliação concluída de recusa técnica, inclusive para contratos negativos.

Snapshot esperado: [`semantica-agi/semantica`](https://github.com/semantica-agi/semantica/tree/a1a8404e20bc146b481dad65cbe5dcccddae84ab),
versão declarada **0.7.0**, commit
`a1a8404e20bc146b481dad65cbe5dcccddae84ab`. Os dez arquivos listados em
`optional/source-manifest.json` são verificados por SHA-256 antes do import;
isso **não verifica o pacote inteiro, dependências transitivas ou a segurança
do ambiente Python**. Módulos previamente carregados, import hooks e código
local precisam pertencer ao runtime confiável. Ausência, versão/hash divergente,
erro e resultado inconsistente recusam suporte.

O orçamento default é 2.000 ms (admite inteiros de 10 a 5.000); ele rejeita
resultados atrasados nos checkpoints, sem interromper thread ou import bloqueado.
Para um prazo rígido, use processo supervisionado. O adapter não autentica
checks, analisa a afirmação da resposta nem melhora recuperação. Políticas,
decision recorder, SPARQL, MCP, ingestão, provedores, ações e explorer upstream
não estão integrados ou homologados por estes testes.

A receita mínima real é para **Linux/Python 3.12**. NetworkX 3.7 exige Python
3.12+, por isso esses pins não servem ao job básico 3.11. Com um checkout
separado e confiável do upstream fixado:

```sh
git clone https://github.com/semantica-agi/semantica.git ../semantica-upstream
git -C ../semantica-upstream checkout --detach a1a8404e20bc146b481dad65cbe5dcccddae84ab
python -m pip install --only-binary=:all: --no-deps -r optional/requirements.txt
python -m pip check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../semantica-upstream \
  python optional/verify_minimal_imports.py
PYTHONDONTWRITEBYTECODE=1 RADAR_SEMANTICA_INTEGRATION=1 \
  SEMANTICA_DISABLE_JUPYTER_PROGRESS=1 PYTHONPATH=../semantica-upstream \
  python -m unittest discover -s tests -v
```

Esta receita não instala o pacote SDK completo nem seus extras. Seus dez pins
são versões efetivamente usadas; o probe bloqueia outros imports externos em
um processo novo. Ele não é sandbox de rede nem substitui um ambiente confiável.
A execução opcional ativa os três testes reais e executa os 92 testes da suíte.
O baseline e os gates específicos do experimento permanecem no consumidor
referenciado acima.

## Autoria, licença e revisão

Código deste pacote: MIT, Copyright (c) 2026 Carlos Felipe. Nenhum fonte
Semantica foi copiado ou vendorizado. O motor opcional é dependência de terceiro,
MIT, Copyright (c) 2026 Semantica; autoria, licença e versão permanecem
independentes. Hashes e referência ao commit registram a dependência sem
transferir autoria. Este repositório não publica artefatos PyPI ou releases.

Antes de integrar um consumidor, revise sua emissão de Scope/revisão/identidade,
a verificação dos bytes do original, a custódia independente do checkpoint e as
permissões/retenção de dados do diário. Revise também o snapshot e as dependências
opcionais se ativar o motor. Testes de contratos e recibos não validam esses
controles de implantação ou a qualidade jurídica de uma aplicação.
