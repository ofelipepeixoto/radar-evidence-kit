# Estudo de retirada e expiração de suporte

Data: 2026-10-06. Decisão: **B — STUDY**. Implementação experimental,
sem homologação de produção. Não instala o Semantica completo.

## Resultado e uso

Uma análise que depende de todas as fontes perde elegibilidade quando uma
delas expira, é retirada ou falha no contrato de revisão/escopo. O módulo
`radar_evidence.support_lifecycle` torna isso verificável ao longo do tempo.
Ele devolve os IDs das fontes ainda ativas e motivos fixos das exclusões.
Não avalia se o texto sustenta semanticamente a afirmação da resposta.

```python
from radar_evidence.support_lifecycle import SupportWindow, evaluate_timeline

# check foi emitido por check_evidence(evidence, scope) no backend confiável.
# Valores abaixo são tempos fictícios em milissegundos desde o epoch UTC.
window = SupportWindow(check.evidence_id, valid_from_ms=100, valid_until_ms=200)
result = evaluate_timeline([check], [window], [100, 199, 200])
assert result.evaluation_completed
# Se check.supported: True, True, False, respectivamente.
```

O modo padrão usa apenas Python stdlib. `use_semantica=True` usa o loader
existente, verifica os mesmos dez fontes e a versão 0.7.0 e cria **uma sessão**
com duas regras fixas. Insere e retira suportes com `session.apply`, comparando
todos os fatos derivados com o cálculo determinístico Radar a cada observação.
Ausência do motor, erro, divergência ou atraso descarta todos os frames;
`evaluation_completed=False` nunca equivale a uma conclusão negativa válida.
Não há fallback silencioso para aprovar quando o motor falha.

## Contrato e limites

- De 1 a 20 `EvidenceCheck` únicos, já emitidos por backend confiável.
- Exatamente uma `SupportWindow` por ID; campos extras não existem no contrato.
- De 1 a 32 observações estritamente crescentes. Inteiros exatos, sem bool,
  de zero a `2**53-1`, em milissegundos desde o epoch UTC.
- Início inclusivo, expiração exclusiva: `at >= valid_until_ms` retira suporte.
  Retirada é efetiva em `at >= withdrawn_at_ms`, inclusive no início.
- `None` significa ausência de prazo/retirada declarados, não consulta de
  revogação externa. Uma retirada é definitiva neste snapshot; restauração
  exige avaliação nova emitida pelo backend.
- Todas as fontes são obrigatórias (AND). Não implementa suportes alternativos,
  grafos arbitrários, inferência de texto, regras ou callbacks do usuário.
- Orçamento de 10–5.000 ms verificado entre etapas; default 2.000 ms.
  Não interrompe import/processo travado: prazo rígido exige worker supervisionado.
- Resultado só contém hashes, códigos, tempos e estados. Sem texto, prompts,
  nomes de revisores, credenciais ou detalhes de exceção.

O `study_id` vincula checks, motivos, janelas, observações e versão das regras.
Hashes permitem correlação e não anonimizam dados. Uma sessão nova por chamada
evita compartilhar o grafo entre avaliações, mas **não é isolamento de processo**.

## Identidade e integração

O backend deve autenticar o solicitante, obter tenant/projeto e revisões atuais
do seu armazenamento, verificar bytes/origem e revisão humana, e só então
emitir Scope, checks, janelas e horário de observação. Não aceitar esses campos
de uma resposta de LLM como autoridade. Os contratos Python não autenticam.
Cada chamada é um snapshot: mudança posterior de revisão/identidade exige
checks novos. Resultados antigos não substituem consulta ao estado atual.

O componente é uma função offline. Não observa fontes continuamente, não
persiste eventos nem altera recibos históricos. O consumidor pode recalcular
ao receber um evento autenticado de revisão, mas essa operação persistente
ainda não foi implementada ou homologada. n8n, Hub e Control Plane permanecem
nos seus papéis existentes; nenhum novo endpoint ou ferramenta MCP é exposto.

## Critérios e evidências

`tests/test_support_lifecycle.py` adiciona 19 testes: 17 sem motor e dois com
o motor real. Cobrem retirada/expiração exatas, replay, permutação, vínculo de
identidade do estudo, revisão/escopo, limites máximos, entrada malformada,
erro privado, dependência ausente, atraso e divergência do motor.

Na execução local Linux/Python 3.12, a suíte completa passou com **111 testes**
e motor real no snapshot `a1a8404e20bc146b481dad65cbe5dcccddae84ab`.
Sem motor: **106 passaram e cinco foram ignorados**, explicitamente opcionais.
A matriz 3.11/3.12 e receita mínima permanecem na CI. O consumidor
`avaliacao-rag-juridico` guarda fixtures, resultados e métricas de comparação.

Manter B — STUDY se o motor apenas reproduzir as regras. Ampliar somente se
uma avaliação nova demonstrar utilidade superior para dependências reais,
com custo, privacidade e limites medidos. Equivalência não é ganho de qualidade.

## Reversão

O adapter anterior, contratos Evidence/Scope e recibos SQLite não mudaram.
Remover o uso deste módulo ou retornar o consumidor ao commit anterior elimina
o estudo; não há migração de banco, ativação ou recurso remoto a desfazer.
