# Memória revisável de projeto — contrato experimental v1

Autoria original: Carlos Felipe, com assistência de IA. MIT. Decisão B — STUDY:
o exxperts (`EXXETA/exxperts`, `df52b073e5328221645bc0b0aeb63419b9bd4fa5`)
é referência conceitual de revisão/undo; nenhum código ou runtime foi incorporado.

`radar_evidence.memory.MemoryStore` persiste **notas derivadas de documentos**,
não fatos verificados, instruções de sistema ou autoridade de execução. O
backend fornece Scope, Evidence atual, relógio e identidade. Não aceitar esses
campos da saída de um modelo ou do corpo HTTP como autorização.

## Fluxo e proveniência

`propose` cria versão pendente com hash de todo o texto, escopo, finalidade,
classe de confiança, validade, proponente e IDs completos de Evidence.
Cada ID vincula revisão, documento, página, hashes da fonte e do texto e revisão
humana. `decide` exige o hash exato da última proposta e revisor distinto;
aprovação e rejeição são terminais. Uma correção cria nova versão pendente;
a versão aprovada anterior permanece disponível até nova aprovação.

`recall` devolve somente versões ativas aprovadas, dentro de 30 dias no máximo,
com todas as fontes ainda elegíveis. Revogar, alterar ou remover fonte bloqueia
imediatamente a próxima leitura. Isso não apaga automaticamente notas antigas:
`forget` apaga o conteúdo de todas as versões e `purge_expired` apaga expiradas.
`undo` restaura a aprovação anterior somente se suas fontes e validade ainda
permitirem; na primeira versão, retira a nota. Não restaura conteúdo esquecido.

## Política e limites

- Padrão exige `identity_verified=True` em fontes e revisor. A biblioteca **não
  autentica** ninguém: o emissor confiável é responsabilidade do consumidor.
- `local_review=True` é exceção explícita para laboratório offline de um
  operador. Rótulos continuam não autenticados. Reabrir no modo estrito oculta
  notas com revisão não verificada; trocar nomes não prova segregação humana.
- 4 KiB UTF-8 por nota, 1–8 fontes distintas, 1.000 versões por banco,
  10.000 eventos. Ao atingir quota, falha fechada; arquivamento é operação
  explícita do operador. Não há classificação de privacidade automática.
- Transações SQLite impedem dupla aprovação/versões concorrentes. Não existe
  transação distribuída com o banco de fontes: o consumidor deve serializar
  mudanças de fonte e operações de memória ou usar snapshot externo consistente.
- Banco 0600, path controlado pelo operador, sem serviço público/multitenant.
  Eventos contêm hashes de propostas e atores, sem texto das notas. O banco
  contém texto privado em claro e metadados; hashes de atores não anonimizam.
- Verificação de digest detecta edição acidental do payload, não um operador
  malicioso que reescreva banco/hash. Auditoria não assinada, sem checkpoint
  externo. Nenhuma promessa de inviolabilidade ou conformidade regulatória.

## Backup, descarte e rollback

Parar escritores e usar `sqlite3.Connection.backup` para arquivo privado; testar
reabertura e `recall` com fontes **atuais**, nunca promover dados do backup.
Backups contêm texto privado. `forget`/`purge_expired` fazem exclusão lógica e
VACUUM do banco ativo; apagar cópias e backups é obrigação do operador. Isso não
garante apagamento físico em SSD, snapshots ou journaling do sistema.

Rollback do piloto: parar consumidor, preservar recibos mínimos conforme sua
política, descartar banco/backup privado e remover import opcional. Nenhuma
migração da API Evidence, serviços pagos, shell, browser ou permissões de tools.

## Validação e sequência

`PYTHONPATH=src python -m unittest discover -s tests -v` inclui persistência,
negativas de fonte/escopo, expiração, undo, descarte e concorrência. Fixtures
verificadas são sintéticas e não demonstram identidade de produção.

Próximos gates: avaliação PT-BR independente no Runtime Lab; consumidor local no
assistente documental; revisão humana das PRs. Control Plane e Hub ficam para
integração posterior, com identidade real, retenção e orçamento preventivo
antes de qualquer provider. O módulo não faz chamadas de rede nem cobra tokens.
