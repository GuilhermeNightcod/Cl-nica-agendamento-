# Instalação no VPS da Hostinger

Servidor: **VPS KVM 1** (Ubuntu + Docker), IP `187.41.123.141`, domínio **centralodonto.tech**.
Tempo estimado: 20–30 minutos.

> ⚠️ **Teste com dados fictícios.** Pacientes reais só depois do acordo com a faculdade (LGPD)
> e com o backup diário funcionando e copiado para fora do servidor.

---

## 1. Apontar o domínio para o servidor (painel da Hostinger)

1. hPanel → **Domínios** → `centralodonto.tech` → **DNS / Nameservers**.
2. Apague registros **A** antigos de `@` e `www` (a Hostinger às vezes cria um apontando para uma página de "estacionamento").
3. Crie:

   | Tipo | Nome | Aponta para | TTL |
   |---|---|---|---|
   | A | `@` | `187.41.123.141` | 300 |
   | A | `www` | `187.41.123.141` | 300 |

4. Confira (pode levar de 5 minutos a algumas horas):
   ```bash
   nslookup centralodonto.tech
   ```
   Tem que responder `187.41.123.141`.

> Também no hPanel: **verifique o e-mail** do registro do domínio (o aviso amarelo). Sem isso o domínio pode ser suspenso.

## 2. Entrar no servidor

hPanel → **VPS** → **Gerenciar** → botão **Terminal do navegador**, ou pelo seu computador:
```bash
ssh root@187.41.123.141
```

Firewall: no hPanel (VPS → **Firewall**) deixe abertas só as portas **22** (SSH), **80** e **443**.

## 3. Baixar o projeto (repositório privado)

Crie uma chave de leitura só para este servidor:
```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/github_deploy -C "vps-central-odonto"
```
```bash
cat ~/.ssh/github_deploy.pub
```
Copie a linha que aparecer e, no GitHub, vá no repositório **Cl-nica-agendamento-** → **Settings** →
**Deploy keys** → **Add deploy key** → cole, título `VPS Hostinger`, **sem** marcar "Allow write access".

```bash
printf 'Host github.com\n  IdentityFile ~/.ssh/github_deploy\n' >> ~/.ssh/config
```
```bash
git clone git@github.com:GuilhermeNightcod/Cl-nica-agendamento-.git /root/central-odonto
```
Na primeira vez o terminal pergunta *"Are you sure you want to continue connecting?"*: digite `yes` e Enter.

## 4. Instalar

```bash
cd /root/central-odonto && sudo bash scripts/instalar.sh centralodonto.tech
```

O script:
- instala o Docker se não houver;
- cria o `.env` com **senhas aleatórias** (banco, sessão, tokens) e permissão só para o root;
- mostra **uma vez** o usuário `coordenacao` e a senha provisória: **anote**;
- sobe banco + sistema + HTTPS automático (Caddy/Let's Encrypt).

Abra **https://centralodonto.tech** e entre com o usuário `coordenacao`. O sistema pede para trocar a senha.

Revise no `.env` (com `nano /root/central-odonto/.env`):
- `NOME_CLINICA`, `SEMESTRE_INICIO`, `SEMESTRE_FIM`;
- depois de mudar: `docker compose --profile producao up -d`.

## 5. Primeiros usuários

Em **Usuários → Cartões de primeiro acesso**, gere e imprima os cartões de quem já vem cadastrado
(professores, Jhenifer na coordenação da clínica, Keylla, Larissa e Herika). Alunos: **Usuários →
Cadastrar turma de alunos**, colando a lista de nomes.

## 6. Backup diário (obrigatório antes de dados reais)

```bash
(crontab -l 2>/dev/null; echo "0 3 * * * /root/central-odonto/scripts/backup.sh >> /var/log/backup-odonto.log 2>&1") | crontab -
```
Testar agora:
```bash
/root/central-odonto/scripts/backup.sh && ls -lh /root/backups-central-odonto
```
Copie essa pasta para fora do servidor (Google Drive com `rclone`, por exemplo). Restaurar o banco:
```bash
gunzip -c /root/backups-central-odonto/banco_DATA.sql.gz | docker compose exec -T postgres psql -U postgres odonto
```

## 7. Atualizar quando houver versão nova

```bash
cd /root/central-odonto && git pull && docker compose --profile producao up -d --build
```

## 8. Comandos úteis

Rode sempre dentro da pasta do projeto: `cd /root/central-odonto`.

| Para | Comando |
|---|---|
| Ver se está rodando | `docker compose --profile producao ps` |
| Ver o que o sistema está fazendo | `docker compose logs -f bot` |
| Ver o HTTPS (Caddy) | `docker compose logs -f caddy` |
| Reiniciar | `docker compose --profile producao restart` |

## Problemas comuns

- **HTTPS não abre / erro de certificado:** o DNS ainda não aponta para o IP (passo 1) ou as portas 80/443
  estão fechadas no firewall. Veja `docker compose logs caddy`.
- **"Bad Gateway":** o sistema ainda está subindo ou caiu: `docker compose logs bot`.
- **Esqueci a senha da coordenação:** outro usuário da coordenação gera uma senha provisória em **Usuários**.
  Se ninguém consegue entrar, no servidor:
  ```bash
  cd /root/central-odonto && docker compose exec bot python redefinir_senha.py coordenacao
  ```

## Depois: WhatsApp

Com o sistema no ar em HTTPS, o webhook da Meta fica `https://centralodonto.tech/webhook`
(passo 5 do README). Isso depende da conta Meta/CNPJ da faculdade.
