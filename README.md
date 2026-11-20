# Personal Trainer no Telegram 🏋️

Um bot de Telegram que funciona como personal trainer e coach de nutrição. Ele usa o Claude (API da Anthropic) e se baseia em estudos científicos.

## O que ele faz

| Recurso | Como funciona |
|---|---|
| **Monta treinos** a partir dos seus objetivos | Para cada exercício define séries, faixa de repetições, RIR alvo, descanso, **carga** e **método de carga**. O programa fica salvo. |
| **Analisa foto do prato** | Você manda a foto e ele estima os alimentos, as gramas, kcal, proteína, carboidrato e gordura, com uma margem de erro. A refeição fica registrada. |
| **Avisa quando falta proteína** | Em horários configuráveis (padrão 15:00 e 20:30) ele confere quanto você comeu. Se estiver abaixo do esperado, diz quanto falta e sugere alimentos. |
| **Diz quando aumentar o peso** | Você conta o treino ("supino 60kg 10,9,8 sobrou 1") e ele aplica **dupla progressão + RIR**: diz se é para aumentar, manter ou reduzir a carga, e para quanto. A carga é atualizada no plano. |
| **Feedback de rotina** | Aos domingos (ou com `/feedback`) ele cruza nutrição, treinos, sono, passos e peso, e aponta os 1 a 3 fatores que mais estão te atrapalhando, com uma ação prática para cada. |

Os números (metas de calorias e proteína, decisões de progressão) são calculados **em código** (`coach/science.py`), com fórmulas validadas. O modelo não os inventa, e o resultado é consistente e auditável.

## Base científica usada

**Energia e proteína**
- Mifflin MD et al. (1990). *Am J Clin Nutr* 51:241-7. Equação de taxa metabólica basal.
- Morton RW et al. (2018). *Br J Sports Med* 52:376-84. Meta-análise: o ganho de massa magra estabiliza em ~1,6 g/kg/dia (IC até 2,2). O bot usa 2,0 g/kg.
- Helms ER et al. (2014). *JISSN* 11:20. Em déficit: 2,3-3,1 g/kg de massa magra e perda de 0,5-1% do peso por semana.
- Schoenfeld BJ & Aragon AA (2018). *JISSN* 15:10. ~0,4 g/kg por refeição, em 4 ou mais refeições.
- Iraki J et al. (2019). *Sports* 7:154. Superávit moderado para ganho de massa.
- Jäger R et al. (2017). *JISSN* 14:20. Posicionamento da ISSN sobre proteína.

**Treino**
- Schoenfeld BJ, Ogborn D, Krieger JW (2017). *J Sports Sci* 35:1073-82. Dose-resposta de volume (≥10 séries/semana).
- Schoenfeld BJ et al. (2016). *Sports Med* 46:1689-97. Frequência de 2x por semana.
- Schoenfeld BJ et al. (2017). *JSCR* 31:3508-23. Cargas baixas e altas geram hipertrofia se o esforço for alto.
- Lopez P et al. (2021). *MSSE* 53:1206-16. Carga alta é melhor para força.
- Zourdos MC et al. (2016). *JSCR* 30:267-75. Escala RPE baseada em RIR.
- Schoenfeld BJ et al. (2016). *JSCR* 30:1805-12. Intervalo de 3 min é melhor que 1 min.
- ACSM (2009). *MSSE* 41:687-708. Progressão de 2-10%.
- NSCA, *Essentials of Strength Training and Conditioning*. Regra "2 por 2".
- Pedrosa GF et al. (2022); Wolf M et al. (2023). Treino em amplitude alongada.
- Bell L et al. (2023). *Sports Med Open*. Deload.

**Rotina e recuperação**
- Nedeltcheva AV et al. (2010). *Ann Intern Med* 153:435-41. Pouco sono em déficit aumenta a perda de massa magra.
- Dattilo M et al. (2011). *Med Hypotheses* 77:220-2. Sono e recuperação muscular.
- Paluch AE et al. (2022). *Lancet Public Health* 7:e219-28. Passos diários e mortalidade.
- Parr EB et al. (2014). *PLoS One* 9:e88384. Álcool reduz a síntese proteica.
- Kreider RB et al. (2017). *JISSN* 14:18. Creatina.

## Como colocar para rodar

### 1. Crie o bot no Telegram
1. Abra o Telegram e fale com **@BotFather**.
2. Mande `/newbot`, escolha um nome e copie o **token**.

### 2. Pegue uma chave da API da Anthropic
Em https://console.anthropic.com crie uma API key. O uso é cobrado por token; veja a seção de custos abaixo.

### 3. Configure
```bash
cp .env.example .env
# edite o .env com TELEGRAM_BOT_TOKEN e ANTHROPIC_API_KEY
```

### 4. Rode
**No seu computador:**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m coach.main
```

**Com Docker (servidor/VPS):**
```bash
docker build -t personal-trainer .
docker run -d --restart unless-stopped --env-file .env -v pt-data:/data personal-trainer
```

O bot precisa ficar **ligado 24 horas** para mandar os lembretes. Algumas opções: uma VPS barata, Railway, Render, Fly.io ou um Raspberry Pi. Em todas elas, use um **volume persistente** para a pasta `/data`, que guarda o banco SQLite com seu histórico.

### 5. Proteja o bot
Mande `/start` para o seu bot. Ele vai responder com o seu **ID do Telegram**. Coloque esse número em `ALLOWED_USER_IDS` no `.env` e reinicie o bot. Sem isso, qualquer pessoa que encontrar o bot consegue usá-lo e gastar a sua API.

## Uso

- Converse normalmente: *"Quero ganhar massa, treino 4x por semana, 1h, academia completa, tenho 28 anos, 75 kg, 1,78 m"*
- Mande **foto** do prato (pode pôr uma legenda como "metade do arroz sobrou").
- Depois do treino: *"agachamento 80kg 8,8,7 sobrou 2; leg press 160kg 12,11,10"*
- Rotina: *"dormi 5h, 4 mil passos, dia estressante"*

Comandos: `/hoje`, `/treino`, `/feedback`, `/perfil`, `/novaconversa`, `/ajuda`

## Custos

O modelo padrão é o `claude-opus-5-5` (US$ 4 por milhão de tokens de entrada e US$ 20 por milhão de saída). O prompt de sistema e as ferramentas ficam em cache, o que barateia as mensagens seguidas. Para gastar menos, defina `CLAUDE_MODEL=claude-sonnet-5-5` (US$ 2 / US$ 10) ou `CLAUDE_EFFORT=low` no `.env`. Os lembretes de proteína não chamam a API e não custam nada.

## Limitações (importante)

- A estimativa por foto tem erro típico de **±20-30%**. Óleo, molhos e o tamanho da porção são as maiores fontes de erro. Para precisão, pese os alimentos e descreva por texto.
- O bot não substitui médico, nutricionista ou fisioterapeuta. Em caso de dor, lesão, doença, gestação ou histórico de transtorno alimentar, procure um profissional.

## Desenvolvimento

```bash
pip install -r requirements-dev.txt
pytest
```

Estrutura:
- `coach/science.py`: fórmulas (TMB, metas, progressão de carga)
- `coach/tools.py`: ferramentas que o Claude chama (registrar refeição, treino, check-in…)
- `coach/agent.py`: loop de conversa com a API do Claude
- `coach/prompts.py`: prompt de sistema com a base científica
- `coach/reminders.py`: lembretes de proteína
- `coach/main.py`: bot do Telegram e agendamentos
