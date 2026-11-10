# Roteiro do vídeo – até 5 minutos

Regras do enunciado: **nome do grupo e a frase "QUERO CONCORRER" nos primeiros segundos**, explicar a
integração entre as disciplinas e demonstrar a solução funcionando. Publicar no YouTube como
**"Não listado"** e colar o link no final do PDF e no README.

Dica: grave a tela com o OBS Studio ou a Barra de Jogo do Windows (Win + G), com a voz por cima. Ensaie
com cronômetro: o texto abaixo, lido com calma, dá cerca de 4min30.

| Tempo | Tela | Fala (sugestão) |
|---|---|---|
| 0:00–0:10 | Câmera ou slide com o nome do grupo | "Somos o grupo **[NOME DO GRUPO]**, da turma [TURMA], e **QUERO CONCORRER**. Este é o Refúgio." |
| 0:10–0:45 | `docs/img/mapa_lst_santa_maria.png` e depois `dias_35C_por_ano.png` | "O Rio Grande do Sul é o estado mais envelhecido do Brasil, e Santa Maria passou de 40 graus em 2020, 2022 e 2025. Medimos com satélite: a superfície da cidade varia 9 graus de um bairro para outro, e os dias acima de 35 graus triplicaram desde os anos 90." |
| 0:45–1:10 | `calor_saude_idosos.png` | "Cruzando o clima com os dados do SUS, descobrimos que nesses dias morrem 14% mais idosos do que o esperado em Santa Maria, mas as internações não sobem: o risco aparece antes do hospital. Por isso o Refúgio é preventivo." |
| 1:10–1:50 | Painel Streamlit, aba **Mapa de risco** (trocar as camadas) | "Juntamos o Censo, o Landsat e uma rede neural. A ResNet-18, com transfer learning, acertou 98% no teste e mede a área construída de cada setor. Com o índice de risco do IPCC e o K-Means, achamos 15 mil idosos em setores de prioridade alta." |
| 1:50–2:30 | Aba **Onde se refrescar**: escolher Tancredo Neves, quarta 14h e depois domingo | "Para o cidadão, um sistema de recomendação indica o refúgio climatizado aberto mais adequado. Vejam: na quarta há opções a 300 metros, mas no domingo os postos fecham. Só 45% dos idosos têm um refúgio aberto por perto no domingo, e essa é uma recomendação direta para a Prefeitura." |
| 2:30–3:20 | **Wokwi** rodando: arrastar o DHT22 de 30 °C para 38 °C (LEDs mudam, buzzer bipa), apertar **PEDIR AJUDA**; ao lado, o terminal da ponte MQTT | "Na rua, nossa estação ESP32 calcula a sensação térmica no próprio dispositivo. Quando o idoso aperta o botão, o pedido sai por MQTT criptografado e assinado com HMAC. A ponte rejeita mensagens falsas ou repetidas, e os dados vão para o DynamoDB na AWS." |
| 3:20–4:05 | Aba **Alertas**: pessoa simulada, máxima de 38 °C, gerar; mostrar a mensagem e o roteiro de voz; aba **Assistente**: "Minha mãe desmaiou" | "O nível do alerta é uma regra transparente, e a IA generativa redige a mensagem: texto para quem lê e ligação de voz para quem não lê. O alerta é publicado no Amazon SNS. No chat, o agente usa só as orientações oficiais do Ministério da Saúde e sempre manda ligar 192 em emergência. Ele também detecta tentativas de manipulação." |
| 4:05–4:35 | Terminal: `python -m pytest` (43 passed) + slide das disciplinas | "Tudo foi testado: 43 testes automatizados. Integramos análise de dados, banco SQL e NoSQL, visão computacional, machine learning, recomendação, IA generativa, IoT, nuvem e cibersegurança, com dados públicos reais e respeitando a LGPD." |
| 4:35–4:55 | Slide final: ODS 3, 11 e 13 e indicadores | "Contribuímos para os ODS 3, 11 e 13 e vamos medir o impacto pelo excesso de mortes de idosos e pela cobertura de refúgios aos domingos. Refúgio: ninguém deveria enfrentar o calor sozinho. Obrigado!" |

## Antes de gravar

- [ ] Rodar `streamlit run src/app/painel.py` e deixar o painel aberto.
- [ ] Abrir o projeto no Wokwi (ver `src/iot/README.md`) e rodar `python -m src.iot.ponte_mqtt` num terminal.
- [ ] Testar o fluxo inteiro uma vez (regra 8: tudo que aparece como funcional precisa ter sido testado pelo grupo).
- [ ] Conferir que o vídeo tem no máximo 5:00.
