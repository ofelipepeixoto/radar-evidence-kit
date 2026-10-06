# Citações de trechos — contrato aditivo 0.2

O texto integral de uma página revisada continua em `Evidence`. `Citation`
contém apenas `parent_evidence_id`, `start`, `end` e `quote_sha256`. Os offsets
são pontos de código Unicode, iguais aos índices de strings Python. Não são
bytes, tokens, posições de PDF nem índices UTF-16 de JavaScript.

`make_citation` vincula um trecho ao registro completo; não decide elegibilidade.
`resolve_citation(citation, parent, scope)` exige a identidade exata do pai,
hash do trecho, contenção no span original, revisão atual, escopo e aprovação.
Retorna outro `Evidence` com o texto integral preservado e o span selecionado.
Mudanças fora do trecho, no original ou na revisão também invalidam a referência.
O novo registro pode usar os recibos existentes; nenhum schema do journal mudou.

`split_evidence(parent, max_chars=512, overlap=64)` cria janelas fixas sem LLM,
sem retirar caracteres e sem afirmar limites semânticos. Limites: 64–4096
caracteres por janela, sobreposição até metade da janela, no máximo 512 janelas
por evidência. Um consumidor deve limitar também o total de documentos/páginas.

O consumidor obtém o pai e o `Scope` de seu estado confiável e revalida ambos
antes do uso. Um hash autoconsistente recebido por HTTP não prova procedência.
A biblioteca não autentica usuários nem confirma acesso ao documento original.
O padrão exige `identity_verified=True`; laboratório local pode declarar
`require_verified_review=False`, preservando `False` no resultado e mantendo
todos os outros controles. Isso não é uma exceção de autenticação para SaaS.

Esta implementação é original. A análise do Jevbox motivou a granularidade de
citações e a avaliação hierárquica nos consumidores; nenhum código ou asset
do Jevbox foi incorporado ao núcleo. MIT e histórico do projeto preservados.
