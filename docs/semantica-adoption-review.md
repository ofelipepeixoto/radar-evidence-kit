# Revisão das recomendações Semantica

Data: 2026-10-06. Auditoria upstream de referência:
`semantica-agi/semantica@9a71df67bb50800bd74ebef25f4472726c571458`.
Snapshot de execução opcional preservado:
`a1a8404e20bc146b481dad65cbe5dcccddae84ab`.

| Recomendação | Aplicação nesta entrega |
|---|---|
| Preservar adapter opcional | API anterior e manifesto de dez arquivos intactos |
| Distinguir citação e verdade | Contrato explícito nas saídas, documentação e gates |
| Medir retirada/expiração | Módulo limitado e comparação com motor real no consumidor |
| Preservar quatro contraexemplos | Gate do consumidor exige os quatro casos conhecidos |
| Revisar patch MCP | Revisão abaixo; servidores upstream continuam fora da adoção |
| Evitar Compose compartilhado | Nenhum Compose ou serviço adicionado; uso local apenas |
| Identidade e escopo no backend | Checks emitidos pelo backend; não introduzir autoridade via LLM |
| Limitar antes de executar | 20 fontes, 32 observações, dois rules fixos, validação prévia |
| Lint/exclusões relevantes | Não importar Explorer/SDK completo ou suas exclusões para este recorte |
| Ampliar por ganho comprovado | Sem promoção a produção por equivalência de regras |

## Patch MCP candidato: decisão de revisão

O patch produzido na auditoria troca detalhes de erro por `TOOL_EXECUTION_FAILED`,
remove traceback no dispatcher e marca erro de ferramenta no caminho legado.
Ele trata falhas levantadas e dicts com chave `error` em dois dispatchers.
É uma redução localizada de exposição; **não autoriza adotar esses servidores**.

Limitações verificáveis na revisão do diff:

1. Os handlers ainda podem registrar ou devolver conteúdo privado internamente.
2. Ferramenta desconhecida e outros métodos JSON-RPC não são integralmente cobertos.
3. Um dict de negócio com chave `error` pode ser classificado como falha; é
   necessário definir o envelope de retorno antes de aplicar a política geral.
4. Não limita tamanho de transporte, tempo rígido, isolamento, recursos ou quotas.
5. Testes delimitados não substituem compatibilidade de todos os clientes MCP.

Por isso, o patch não foi vendorizado, aplicado ao runtime ou enviado ao upstream
nesta implementação. O estudo usa apenas classes de raciocínio fixadas, sem
iniciar MCP. O tratamento de erro do módulo Radar não inclui traceback nem
texto de exceção; não se alega sanitização de todos os logs internos upstream.

## Backlog condicionado a ampliar a adoção

- Antes de MCP: contratos de erro, validação de entrada, limites de transporte,
  testes de não exposição em todos os métodos e autenticação por escopo.
- Antes de serviço multiusuário: worker isolado, limites reais de CPU/memória,
  deadline de processo, filas persistentes, recuperação e teste de carga.
- Antes de LLM pago: autorização e reserva persistente de orçamento no Hub.
- Antes de Explorer/SDK completo: corrigir lint relevante e revisar exclusões
  da versão escolhida. Nada disso é homologado pelos testes deste estudo.

Este recorte não cria repositório, servidor, dependência obrigatória, banco,
workflow n8n, implantação ou mensalidade. Fontes Radar permanecem MIT de Carlos
Felipe; Semantica mantém autoria e licença MIT próprias.
