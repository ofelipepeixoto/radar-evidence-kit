# ADR 0001 — Contratos de observação e catálogo de leitura

Status: implementado localmente para revisão; integração operacional pendente.
Data UTC: 2026-10-11. Código original: Carlos Felipe, MIT.

## Contexto

A auditoria de God’s Eye View concluiu C — EXTRACT. Referência:
https://github.com/bilawalsidhu/gods-eye-view/tree/591f299d11f38a612629a274463196d57ae3862e
(Bilawal Sidhu, código MIT). Seu contrato distingue cobertura, observação e
recebimento; seu catálogo separa tools de serviços/superfícies. O aplicativo
inteiro tem datasets/ativos com condições próprias e dependências que não são
necessárias para o primeiro uso Radar.

## Decisão

Implementar contratos Python originais no Evidence Kit, sem copiar código ou
ativos upstream. Reutilizar Scope, Evidence, canonical_bytes e Journal já
existentes. Coordenadas em micrograus inteiros mantêm o encoding v1 sem floats.
Separar dois comandos de consulta somente leitura da futura camada MCP/HTTP.
Não introduzir banco, framework agentic, LLM ou coleta real.

## Alternativas

Importar/distribuir o globo: superfície técnica/jurídica grande para esta fatia.
Criar repo próprio: duplica governança e recibos. Implementar em workflow n8n:
esconde validação/testabilidade dentro da orquestração. Reescrever todos os
consumidores: não resolve o contrato antes de definir fonte/caso de uso.

## Consequências

A implementação é autoral, com referência técnica explícita; não reivindica
autoria sobre God’s Eye View nem diz ser implementação clean-room certificada.
Não há código derivado upstream nesta entrega. Na eventual extração literal de
MIT no futuro, preservar copyright/aviso/licença e registrar o arquivo/revisão.

É necessário configurar fonte, escopo e direitos no backend. Coletor futuro deve
verificar bytes originais, retenção e termos atuais. Aprovação e autenticação são
externas ao contrato; hash/synthetic fixture não libera publicação. A ponte
gera Evidence pendente e preserva o ledger existente. Revogação exige reconstruir
catálogo. Conexão Control Plane/Hub/n8n e fonte real serão mudanças posteriores,
com sua validação própria. Reverter consiste em retirar este módulo/docs/demo;
nenhuma migration ou mudança em formatos existentes é necessária.
