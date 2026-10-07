# Ordem de revisão e integração dos contratos — 2026-10-07

Estado: proposta para revisão humana, sem autorização de merge.
Base documental: main `22d3cae88f1a43f55f75d880bbe6b46d5582d0ba`.
Inspeção atual de metadados das 14 PRs abaixo, dos pins dos consumidores
Python e dos contratos novos do Kit. Não repete auditorias de motores, UI,
patches upstream ou produção. Nenhuma branch funcional foi reescrita.

## Sequência proposta

Cada linha é um grupo independente. Revisar o fornecedor, aprovar o contrato
humano, integrar somente após autorização e então revalidar o consumidor.
A seta descreve precedência, não aprovação nem automação de merge.

| Ordem dentro do grupo | Contrato fixado / evidência |
| --- | --- |
| [Kit5](https://github.com/ofelipepeixoto/radar-evidence-kit/pull/5) → [Jurídico5](https://github.com/ofelipepeixoto/avaliacao-rag-juridico/pull/5) | requirements-evidence.txt fixa `6701507eb328c034edfc491e1289a53e61197218`. Expiração exclusiva e retirada efetiva na fronteira; erro/atraso do motor descarta frames. |
| [Kit6](https://github.com/ofelipepeixoto/radar-evidence-kit/pull/6) → [Documental6](https://github.com/ofelipepeixoto/assistente-documental-ia/pull/6) → [Lab4](https://github.com/ofelipepeixoto/laboratorio-busca-rag/pull/4) | Kit `a81f29b43f780d7f83be257be3de99213d2437ea`; Lab fixa também Documental `df532b43801f51fc132debf92fa7e1a140bc1342` no workflow/manifesto. Lab4 depende de ambos, não só Kit6. |
| [Kit7](https://github.com/ofelipepeixoto/radar-evidence-kit/pull/7) → [Documental7](https://github.com/ofelipepeixoto/assistente-documental-ia/pull/7) / [Runtime3](https://github.com/ofelipepeixoto/radar-runtime-lab/pull/3) | Ambos fixam `1619c0a24896e876abe817eb83a4d6f7bde82f6c`. Revisão pelo hash, fonte atual e predecessor ativo do undo. |
| [Lab5](https://github.com/ofelipepeixoto/laboratorio-busca-rag/pull/5) → [Lab6](https://github.com/ofelipepeixoto/laboratorio-busca-rag/pull/6) | Base de Lab6: study/code-graph-corpus, SHA `72088a14fcc1ca4647731e2b0c380e6971502293`. Correções de root/hashes já presentes; não reimplementar. |
| [Memory1](https://github.com/ofelipepeixoto/radar-memory-lab/pull/1) → [Memory2](https://github.com/ofelipepeixoto/radar-memory-lab/pull/2) | Base de Memory2: feat/governed-memory, SHA `7913eed48b4e12aa8c7e51673f869b466aa1a374`. |
| [Media1](https://github.com/ofelipepeixoto/radar-media-platform/pull/1) → [Media2](https://github.com/ofelipepeixoto/radar-media-platform/pull/2) | Base de Media2: feature/original-pilot, SHA `5b64bfc14edb8737dad419672c1e845f5700f5d2`. Documento de convergência não substitui checks da base. |

## Bloqueio de composição: um pacote, vários commits

As três PRs do Kit partem da mesma main; nenhuma contém as outras duas.
O snapshot Kit6 tem citations.py e não tem memory.py; Kit7 tem memory.py e
não tem citations.py. Ambos distribuem o pacote radar-evidence-kit.
Instalar requirements-evidence.txt e requirements-memory.txt no mesmo venv não
produz a união das APIs: o resolvedor pode recusar referências incompatíveis
ou uma instalação sequencial substituir a anterior.

Correção deste procedimento: manter venvs/checkouts separados por experimento.
Para integração conjunta futura, primeiro revisar uma composição do Kit,
preservando contratos existentes e versão aditiva, executar os três conjuntos
de regressões e só então atualizar TODOS os pins do grupo para um mesmo SHA
composto revisado. Não trocar pins por main, não escolher automaticamente um
dos SHAs atuais e não copiar módulos soltos para simular um pacote integrado.

Em Lab4, uma atualização futura exige coerência entre requirements do Kit,
checkout Documental no workflow, source-manifest.json e reprodução de
composição. Em stacks do mesmo repositório, depois de integrar a base
autorizada, retargetar a camada e conferir o diff restante e CI do novo head.
A reversão procede pelos consumidores antes do fornecedor.

## Gates concretos mantidos

- Kit5: sem motor local, os dois testes opcionais continuam explicitamente
  ignorados. Equivalência de regras não atesta qualidade jurídica.
- Kit6/Documental6: offsets Unicode, identidade local não verificada; revalidar
  pai/Store e original no momento de uso. Citação não prova verdade.
- Kit7/Runtime3: resultado registrado de 17/20 positivos permanece abaixo do
  gate de 90%. Não alterar holdout ou baixar gate para promover o estudo.
- Lab6: isolamento não homologado para código arbitrário; patches de root e
  hashes já revisados permanecem no head d67163d9a47422d51b489e9e004942297eece15b.
- Memory2: workflow Rust pesado remoto e sessão Supabase real continuam
  pendentes segundo a PR; não repetir nem promover execução local como remota.
- Media1: [run do head](https://github.com/ofelipepeixoto/radar-media-platform/actions/runs/37362149859)
  consultado novamente: conclusão failure, jobs browser e contracts (3.12)
  cancelados; contracts (3.11) e secrets aprovados. Isso é cobertura incompleta,
  não falha de asserção demonstrada. CI da Media2 não encerra esse gate.
  Portar código do Studio exige resolver licença do material específico.
- Nenhum destes gates autoriza credenciais, alteração de grants, SQL de escrita,
  chamada paga, ativação n8n, publicação ou deploy. Caixa Editorial excluída.

## Verificação realizada nesta revisão

Python local 3.12.14, checkouts extraídos dos SHAs fixados acima, sem instalação
de motor ou acesso de rede durante os testes:

| Contrato | Comando na raiz do snapshot com PYTHONPATH=src | Resultado |
| --- | --- | --- |
| Kit5 | python3 -m unittest discover -s tests -p test_support_lifecycle.py -v | 19 coletados, 17 passaram, 2 opcionais ignorados |
| Kit6 | python3 -m unittest discover -s tests -p test_citations.py -v | 14 passaram |
| Kit7 | python3 -m unittest discover -s tests -p test_memory.py -v | 27 passaram |

Inspeção de requirements e manifesto confirmou os pins; comparação das árvores
confirmou que os módulos de citações e memória ainda estão em snapshots
separados. Nenhum teste novo foi necessário para este documento. Não executei
novamente as suítes completas dos consumidores nem os motores já auditados.
Esta revisão prepara a integração; não é aceite humano independente.

## Heads dos consumidores no corte

Jurídico5: `81a7d6b14e2e0a81e1d70bc2326569b747be361f`;
Documental6: `df532b43801f51fc132debf92fa7e1a140bc1342`;
Documental7: `d51d201fd4c8610c51d5626dc1c0afc24a546a2b`;
Lab4: `fb0b45b5426aa363c3d795ef6c54ab546ca03da5`;
Runtime3: `1c0940e7cda88e852e09c0493e7e262c2326b47f`;
Memory2: `60ca588bfafc6be8c9ff97e9eecdbbe6e208d79c`;
Media2: `e6ee632ad1a0953d8d6ca04204ed9ae26d477ceb`.

Autoria: Carlos Felipe/Radar, assistência de IA. Documento original.
Reversão: fechar esta PR documental; nenhum estado operacional foi alterado.
