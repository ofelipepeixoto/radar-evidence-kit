# ADR 0001 — Conteúdo e ocorrências de fonte

Data: 2026-10-04. Estado: implementação offline proposta para revisão.

## Problema e decisão

A auditoria de `odysseus-dev/odysseus` no commit
`2992bf6d368a11472323e47d3bfed91e79cefc6b` reproduziu a perda da segunda fonte
quando o mesmo proprietário indexa texto igual de dois documentos. Isso motiva
um contrato autoral separado no evidence-kit; nenhum código AGPL foi copiado.

Manter a identidade existente de `Evidence`, que inclui o recibo de revisão.
Adicionar uma identidade de conteúdo escopada por cliente/projeto/text hash e
uma identidade de ocorrência por cliente/projeto/documento/revisão/página/span/
source hash/text hash. Todas são SHA-256 completas de arrays JSON versionados,
com UTF-8 e separadores compactos. O contrato JSON é verificável também em Node.

Registrar as identidades de ocorrência e recibo de todos os registros válidos
antes de excluir registros inelegíveis. Agrupar somente os aprovados por
`check_evidence` no Scope confiável. Se uma ocorrência que seria incluída tiver
recibos divergentes, rejeitar a prévia inteira, independentemente da ordem:
rejected/pending, identidade não verificada ou revisor ausente não podem ocultar
uma divergência. Repetição exata não duplica. Conflitos apenas entre ocorrências
que não seriam incluídas continuam excluídos, sem afetar outras fontes; tenant,
projeto e revisão integram a identidade de ocorrência. O snapshot não possui
ordem temporal autenticada para escolher uma decisão como mais recente.
A prévia é composta de trechos existentes, sem geração de novas afirmações.

## Limites e integração

Processamento em memória limitado, sem migração/indexador persistente. Mudanças
de revisão exigem novo Scope e novo snapshot; não mesclar revisões antigas.
Não é mecanismo de autenticação, custódia de original, certificado de verdade,
tenant RLS ou autorização de efeito externo. O consumidor declara emissor não
autenticado e ações/gastos desabilitados.

O Hub pode usar a CLI como trabalhador local fixo. Scope e localização do
snapshot vêm do operador, fora do pedido/modelo. Deve homologar o commit do kit,
verificar os arquivos originais e autenticar o emissor antes de servir clientes.

## Verificação

Regressões: duas fontes para texto igual, replay exato, ordem determinística,
separação entre tenants/projetos, revisão desatualizada, pending/rejected,
recibo conflitante, hashes/spans e JSON/volume inválidos, CLI Python real.
