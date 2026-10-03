# Controle de segredos no GitHub

O CLI Gitleaks MIT, versão 8.30.1, é obtido do release oficial e verificado por SHA-256 antes de executar. Copyright e licença de Zachary Rice estão preservados em `licenses/GITLEAKS-LICENSE.txt`. Controles e testes Radar originais estão sob `licenses/RADAR-CONTROLS-MIT.txt`; isso não muda a licença do restante do repo.

## Dois checks distintos

`Testar controle de segredos / fixtures` usa o código da PR com token somente de leitura, checkout sem credenciais persistidas e nenhuma chave externa. Valida fixtures sintéticas do scanner em job separado dos testes da aplicação. **Não certifica o histórico real da PR como livre de segredos.** É o check de bootstrap, necessário porque o novo controle ainda não existe na base.

`Verificar segredos / segredos` usa `pull_request_target`, push em main e dispatch manual. Em PR, workflow, script e política vêm exclusivamente da base confiável. O conteúdo da PR é lido como histórico Git; nenhum script, action, hook ou pacote do alvo é executado. Não adicionar execução de código do checkout `alvo` neste job. Em push/dispatch, os controles vêm do commit executado.

Depois de incorporar o bootstrap, verificar uma execução real do check de segredos no novo main. Ausência do check durante o bootstrap não significa sucesso. Configurar como obrigatório apenas quando o recurso estiver disponível e o check estiver homologado. A preparação destes arquivos não modifica regras de branch nem comprova que o check é obrigatório.

## Cobertura e falha fechada

O wrapper exige histórico não shallow. Faz clone bare mirror temporário das refs disponíveis e aplica a política `.security/gitleaks.toml` da base. `.gitleaks.toml`, `.gitleaksignore` e `gitleaks:allow` do alvo não desabilitam o controle. Nunca usar `continue-on-error` neste job. Saídas: 0 varredura completa limpa, 1 candidato de segredo, 2 erro/timeout/varredura incompleta. Resultados incompletos bloqueiam.

O CLI usa código interno 10 para candidatos, pois 1 pode ser erro. Sem `--verbose`: a auditoria confirmou exposição de valor auxiliar em regra multipart na saída verbose. Findings recebem redaction 100%; o wrapper não imprime saída capturada e persiste apenas quantidade, regra, commit e linha. Mensagem de commit, autor/e-mail, caminho e match são omitidos. Nenhum relatório bruto é enviado como artifact.

O job dura no máximo 15 minutos; scanner 540 segundos e subprocesso 600 segundos. Não promete scan de objetos sem referência, reflogs, todos os forks/PRs removidos, arquivos não obtidos, anexos ou conteúdo de arquivos compactados. A configuração padrão não percorre arquivos compactados. Não prova validade de um segredo nem substitui rotação de uma credencial real. Histórico obtido do GitHub pode conter candidatos antigos; revisar com acesso controlado.

## Teste local

```bash
bash scripts/install_gitleaks.sh /tmp/radar-gitleaks
RADAR_GITLEAKS_BINARY=/tmp/radar-gitleaks/gitleaks python3 -m unittest discover -s tests/security -p 'test_secrets.py' -v
python3 scripts/scan_secrets.py --binary /tmp/radar-gitleaks/gitleaks --repository . --config .security/gitleaks.toml --report /tmp/radar-secret-summary.json
```

O teste usa somente credenciais sintéticas geradas em diretórios temporários. A instalação do binário requer rede; a suíte de fixtures não chama provedores. O checksum fixo está em `scripts/install_gitleaks.sh` e no workflow confiável. Atualizações de versão/checksum são mudanças no controle e exigem revisão e retestes.

## Reversão

Reverter o commit restaura o workflow anterior; preservar evidência de falha e não esconder candidatos por allowlist ampla. Se um check obrigatório existir futuramente, coordenar seu nome/regra antes de renomear/remover o job. Falha de scan não autoriza apagar histórico, alterar acesso ou rotacionar credenciais sem diagnóstico.

As fixtures de scanner ficam em `tests/security/` sem pacote `__init__.py`, fora da descoberta recursiva habitual da suíte da aplicação. O CI standalone as executa explicitamente, usando o binário real fixado; não instala novas dependências Python.
