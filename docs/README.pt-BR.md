# Turbo Recorder — documentação em português do Brasil

O **Turbo Recorder** grava a tela, o microfone e o áudio do sistema com o
FFmpeg. Ele detecta o sistema operacional, a tela, os dispositivos de áudio, a
GPU e os codificadores disponíveis e oferece duas interfaces:

Este guia corresponde ao **Turbo Recorder 3.9.1**.

- `turborec`: interface gráfica e linha de comando para Windows, macOS, Linux,
  FreeBSD, OpenBSD, NetBSD e DragonFly;
- `turborecorder`: linha de comando alternativa, voltada para Linux com X11 ou
  Wayland/wlroots.

Para começar, use `turborec`. Nos exemplos genéricos, substitua `*` ou `VERSÃO`
pelo número mostrado na
[página de lançamentos (Releases)](https://github.com/cristiancmoises/turborec/releases/latest).
Os exemplos específicos deste lançamento usam 3.9.1.

Ao abrir o aplicativo, o perfil inicial já prioriza qualidade: **Qualidade
Best**, **Codec Auto**, **23 fps** e saída **4K (3840×2160)**. No modo Auto, o
Turbo Recorder escolhe o primeiro codificador por hardware realmente utilizável
nesta ordem: **AV1 → HEVC/H.265 → H.264**. Se nenhum deles funcionar, usa H.264
por software, que é a alternativa mais segura e compatível. Todos esses valores
podem ser alterados pela GUI, CLI ou configuração JSON.

A versão 3.9.1 mantém esse perfil e todas as correções recentes do Windows —
nomes Unicode, identificadores estáveis do DirectShow, janelas nativas e
coordenadas de vários monitores — e acrescenta detecção portátil dos quatro
sistemas BSD sem anunciar dispositivos inexistentes.

Documentos relacionados:

- [site oficial do Turbo Recorder](https://turborec.securityops.co)
- [README principal em inglês](../README.md)
- [tutorial completo em inglês](TUTORIAL.md)
- [histórico de alterações](../CHANGELOG.md)
- [licença GPL-3.0](../LICENSE)

## Sumário

- [Compatibilidade e requisitos](#compatibilidade-e-requisitos)
- [Instalação](#instalação)
- [Primeiro teste](#primeiro-teste)
- [Interface gráfica](#interface-gráfica)
- [Uso pela linha de comando](#uso-pela-linha-de-comando)
- [Microfone, áudio do sistema e câmera](#microfone-áudio-do-sistema-e-câmera)
- [Solução de problemas por sistema](#solução-de-problemas-por-sistema)
- [Qualidade, desempenho e compatibilidade](#qualidade-desempenho-e-compatibilidade)
- [Configuração persistente](#configuração-persistente)
- [Como coletar um diagnóstico](#como-coletar-um-diagnóstico)

## Compatibilidade e requisitos

| Sistema | Captura de tela | Áudio e câmera | Observações |
|---|---|---|---|
| Windows 10/11 x64 | GDI (`gdigrab`) | DirectShow | O `.exe` e o instalador (`setup.exe`) x64 incluem Python, Tk e FFmpeg |
| macOS | AVFoundation | AVFoundation | É necessário autorizar tela, microfone e câmera |
| Linux X11 | `x11grab` | PulseAudio/PipeWire e V4L2 | `wmctrl` é opcional para listar janelas |
| Linux Wayland/wlroots | `wf-recorder` | PipeWire/PulseAudio e V4L2 | Compatível com sway, Hyprland, river e outros compositores wlroots |
| FreeBSD | X11/XWayland (`x11grab`) | OSS; Pulse opcional; V4L2 quando disponível | Há pacote `.pkg`; Python, FFmpeg e Tk são instalados separadamente |
| OpenBSD | X11/XWayland (`x11grab`) | sndio; Pulse opcional; V4L2 quando disponível | O tarball portátil usa as ferramentas nativas disponíveis |
| NetBSD | X11/XWayland (`x11grab`) | OSS; Pulse opcional; V4L2 quando disponível | Use o tarball portátil e os pacotes do sistema |
| DragonFly | X11/XWayland (`x11grab`) | OSS; Pulse opcional; V4L2 quando disponível | Use o tarball portátil e os pacotes do sistema |

Requisitos quando não se usa o executável/instalador autossuficiente do Windows:

- Python 3.8 ou mais recente;
- FFmpeg disponível no `PATH`;
- Tk para a interface gráfica; a CLI funciona sem Tk;
- no Linux, `pactl` é usado para detectar fontes PulseAudio/PipeWire;
- nos BSDs, o microfone usa sndio ou OSS nativo quando o FFmpeg oferece o
  backend e existe um nó de dispositivo real; `pactl` é opcional e necessário
  apenas para descobrir uma fonte monitor do PulseAudio para o áudio do sistema;
- no Linux com Wayland/wlroots, `wf-recorder` e `swaymsg` ou `wlr-randr`.

> O suporte nativo do Linux a Wayland é direcionado a compositores **wlroots**.
> Em sessões Wayland do GNOME ou KDE, o método de captura pode não estar
> disponível. Nesse caso, entre em uma sessão X11/Xorg ou use um compositor
> compatível.

## Instalação

Baixe os artefatos somente na
[página oficial de lançamentos](https://github.com/cristiancmoises/turborec/releases/latest).

### Windows

Baixe `Turbo_Recorder-VERSÃO-windows-x64.exe`. O arquivo já contém Python, Tk e
FFmpeg, não exige instalação administrativa e pode ser aberto com dois cliques.
Sem argumentos, ele abre a interface gráfica.

Alternativa: o instalador clássico `Turbo_Recorder-VERSÃO-windows-x64-setup.exe`
também é autossuficiente — ele inclui o Python 3.12 (com Tk), o FFmpeg e o
aplicativo; instala o Python silenciosamente apenas se não houver um Python 3.8+
com Tk no sistema, cria atalhos no Menu Iniciar e aparece em **Configurações →
Aplicativos** para desinstalação.

Para usar a CLI no PowerShell, você pode renomear o arquivo baixado:

```powershell
Rename-Item .\Turbo_Recorder-*-windows-x64.exe Turbo_Recorder.exe
.\Turbo_Recorder.exe --version
.\Turbo_Recorder.exe detect
.\Turbo_Recorder.exe gui
```

Se o Windows exibir o SmartScreen, confirme primeiro que o arquivo veio do
lançamento oficial do projeto. O pacote publicado atualmente é para Windows x64;
em outra arquitetura, execute o projeto a partir do código-fonte com uma versão
compatível do Python.

### Debian, Ubuntu e derivados

Com somente um pacote `.deb` da versão desejada na pasta atual:

```bash
sudo apt install ./turborec_*_all.deb
turborec --version
```

O pacote instala FFmpeg, Python e Tk como dependências. Em Wayland/wlroots,
instale também:

```bash
sudo apt install wf-recorder pulseaudio-utils
```

### Fedora, RHEL, openSUSE e derivados

No Fedora/RHEL:

```bash
sudo dnf install ./turborec-*.noarch.rpm
turborec --version
```

No openSUSE:

```bash
sudo zypper install ./turborec-*.noarch.rpm
turborec --version
```

Em Wayland/wlroots, instale também `wf-recorder`. O pacote que fornece `pactl`
normalmente se chama `pulseaudio-utils`; o nome pode variar conforme a
distribuição.

O Fedora pode fornecer `ffmpeg-free` sem `libx264`. No Turbo Recorder 3.9.1, os
caminhos Auto, H.264 explícito, CPU e transmissão podem usar `libopenh264` como
última alternativa H.264, mas somente depois de um teste real de codificação de
um quadro. O pacote de compatibilidade `noopenh264`, que anuncia o codificador
sem conseguir inicializá-lo, é rejeitado. Com o repositório
`fedora-cisco-openh264` habilitado, a instalação normal pode obter a
implementação real:

```bash
sudo dnf install ffmpeg-free
```

Se o `noopenh264` já estiver instalado, troque-o pela implementação funcional:

```bash
sudo dnf swap noopenh264 openh264
```

Se preferir, use outro pacote que forneça `/usr/bin/ffmpeg` com um codificador
H.264 funcional.

### AppImage

O AppImage é portátil, mas usa o Python, o Tk e o FFmpeg do sistema:

```bash
mv ./Turbo_Recorder-*-x86_64.AppImage ./Turbo_Recorder.AppImage
chmod +x ./Turbo_Recorder.AppImage
./Turbo_Recorder.AppImage
```

Se o AppImage não iniciar, execute-o no terminal para ver a mensagem de erro e
confirme `python3 --version`, `ffmpeg -version` e
`python3 -c "import tkinter"`.

### Arch Linux e outras distribuições

Instale `python`, `tk`, `ffmpeg` e os utilitários de áudio da distribuição. No
Arch Linux, por exemplo:

```bash
sudo pacman -S python tk ffmpeg libpulse
```

Depois use o tarball portátil ou o código-fonte:

```bash
tar xzf turborec-*.tar.gz
cd turborec-*/
PREFIX="$HOME/.local" ./install.sh
"$HOME/.local/bin/turborec" --version
```

Adicione `$HOME/.local/bin` ao `PATH` para chamar apenas `turborec`.

O lançamento também inclui `turborec-3.9.1-source.tar.gz`, um arquivo imutável
com toda a árvore rastreada do código-fonte e os testes, destinado a quem mantém
ports e pacotes de distribuições. Para instalar e usar o programa, prefira o
tarball portátil `turborec-3.9.1.tar.gz` mostrado acima. Ao todo, o lançamento
contém nove artefatos de plataforma, o arquivo completo do código-fonte e
`SHA256SUMS`: 11 artefatos.

### GNU Guix

O arquivo `guix.scm` e o pack relocável incluem a saída `tk` do Python e validam
que o módulo `_tkinter` pode ser importado. Portanto, a CLI e a GUI são os
caminhos previstos nas duas formas de instalação:

```bash
guix package -f guix.scm
turborec gui

# ou o pack do lançamento
sudo tar xf turborec-3.9.1-guix-x86_64.tar.gz -C /
/bin/turborec gui
```

A CI valida a construção e a importação do Tk sem ambiente gráfico. Isso não
equivale a um teste visual da GUI nem a um teste com dispositivos físicos de
captura.

### macOS

Instale Python 3.8+ com suporte a Tk — o instalador do
[python.org](https://www.python.org/downloads/) inclui Tk — e
[FFmpeg](https://ffmpeg.org/download.html). Se você já usa Homebrew, pode
instalar o FFmpeg com:

```bash
brew install ffmpeg
```

Use o tarball portátil:

```bash
tar xzf turborec-*.tar.gz
cd turborec-*/
PREFIX="$HOME/.local" ./install.sh
"$HOME/.local/bin/turborec" gui
```

Ou execute diretamente a partir do repositório:

```bash
git clone https://github.com/cristiancmoises/turborec.git
cd turborec
python3 turborec.py gui
```

Na primeira captura, o macOS pedirá permissões. Autorize o aplicativo que está
executando o Turbo Recorder — Terminal, iTerm, Python ou o lançador usado — em
**Ajustes do Sistema → Privacidade e Segurança**:

- **Gravação de Tela e Áudio do Sistema** ou **Gravação da Tela**;
- **Microfone**;
- **Câmera**, se for usar a webcam.

Feche e abra novamente o Terminal ou o aplicativo depois de alterar uma
permissão.

### FreeBSD, OpenBSD, NetBSD e DragonFly

No FreeBSD, instale primeiro o pacote nativo como `root` (diretamente, com
`doas` ou com `sudo`, conforme a configuração local):

```sh
pkg add ./turborec-*.pkg
pkg install python3 ffmpeg
turborec --version
```

O pacote nativo do Turbo Recorder não força dependências de execução; por isso,
Python e FFmpeg devem ser instalados separadamente. Para a interface gráfica,
procure e instale o pacote Tk correspondente ao Python:

```sh
pkg search tkinter
```

No OpenBSD, instale os requisitos e use o tarball portátil:

```sh
pkg_add python3 ffmpeg
tar xzf turborec-3.9.1.tar.gz
cd turborec-3.9.1
doas ./install.sh
```

No NetBSD e no DragonFly, instale Python 3, FFmpeg e Tk pelos repositórios do
sistema e use o mesmo tarball. Os nomes exatos dos pacotes Python/Tk podem
acompanhar a versão padrão oferecida pelo sistema.

O Turbo Recorder registra cada sistema como `freebsd`, `openbsd`, `netbsd` ou
`dragonfly`, sem tratá-los como Linux. Em X11, `xrandr`/`xdpyinfo` ajudam a
detectar a tela e `wmctrl` permite listar janelas. Em uma sessão Wayland, use
XWayland; o backend nativo `wf-recorder` documentado neste guia é específico do
Linux/wlroots.

Para microfone, o programa prefere sndio no OpenBSD e OSS no FreeBSD, NetBSD e
DragonFly, sempre conferindo antes se o FFmpeg contém esse backend e se o
arquivo em `/dev` é realmente um dispositivo de caractere. Portanto, não é
necessário instalar PulseAudio apenas para gravar o microfone. Para gravar o
som do sistema, configure PulseAudio opcionalmente e confirme que existe uma
fonte monitor real:

```sh
pactl info
pactl list short sources
```

Uma webcam só aparece quando o FFmpeg oferece uma entrada V4L2 e um nó
`/dev/video*` real e capturável está presente.

### A partir do código-fonte

Este método funciona em qualquer plataforma suportada quando Python, Tk e
FFmpeg já estão instalados:

```bash
git clone https://github.com/cristiancmoises/turborec.git
cd turborec
python3 turborec.py --version
python3 turborec.py gui
```

No Windows, use `py turborec.py` ou `python turborec.py`.

## Primeiro teste

Antes de tentar misturar todas as fontes, valide cada parte separadamente.

Para uma instalação com o comando `turborec`:

```bash
turborec --version
turborec detect
turborec devices
turborec cameras
turborec targets
```

Faça primeiro uma gravação curta **sem áudio**. Ela evita que a ausência de um
dispositivo de loopback bloqueie o teste:

```bash
turborec record -m video_only -t 10s --open
```

Depois teste o microfone:

```bash
turborec record -m audio_mic -t 10s --open
turborec record -m video_mic -f 30 -t 10s --open
```

O modo padrão, `auto`, escolhe a combinação disponível nesta ordem: microfone +
áudio do sistema, somente microfone, somente áudio do sistema ou somente vídeo.
Assim, a ausência de loopback não bloqueia a primeira gravação:

```bash
turborec record
```

Use `-m video_both` quando quiser exigir explicitamente as duas fontes.

Na CLI, pressione `q` ou `Ctrl+C` para encerrar e finalizar o arquivo
corretamente. Por padrão, vídeos são salvos em `~/Videos` e gravações somente de
áudio em `~/Audio`. No Windows, essas pastas ficam dentro do perfil do usuário.

Ao executar a partir do código-fonte, troque `turborec` por
`python3 turborec.py` (`py turborec.py` no Windows). Ao usar o `.exe`, troque por
`.\Turbo_Recorder.exe`.

## Interface gráfica

Abra com:

```bash
turborec gui
```

Na GUI:

1. escolha o modo de captura;
2. escolha uma fonte em **Source** e atualize a lista após conectar dispositivos
   ou abrir novas janelas;
3. para o perfil recomendado, mantenha **Best · Auto · 23 fps · 4K** e
   **Encoder: Auto**;
4. confirme o microfone e o áudio do sistema;
5. escolha a pasta de saída;
6. clique em **Start** e, ao terminar, em **Stop**.

Os indicadores ao lado dos dispositivos mostram se eles foram detectados. A
prévia do comando ajuda a diagnosticar a seleção sem iniciar a gravação.

## Uso pela linha de comando

Formato geral:

```text
turborec <subcomando> [opções]
```

Subcomandos:

| Comando | Função |
|---|---|
| `detect` | Mostra sistema, tela, GPU, codificadores e dispositivos detectados |
| `devices` | Lista microfones e fontes de áudio do sistema |
| `cameras` | Lista webcams e placas de captura |
| `targets` | Lista telas, monitores e janelas disponíveis no backend atual |
| `encoders` | Mostra os codificadores de vídeo disponíveis |
| `gui` | Abre a interface gráfica |
| `record` | Inicia uma gravação ou transmissão |

Os comandos de inspeção aceitam `--json`, o que facilita diagnósticos e scripts:

```bash
turborec detect --json
turborec devices --json
turborec cameras --json
turborec targets --json
```

### Modos de captura

| Modo | Conteúdo |
|---|---|
| `auto` | Melhor modo de vídeo compatível com os dispositivos detectados; é o padrão |
| `video_both` | Tela + microfone + áudio do sistema |
| `video_mic` | Tela + microfone |
| `video_system` | Tela + áudio do sistema |
| `video_only` | Somente tela |
| `audio_both` | Microfone + áudio do sistema, sem vídeo |
| `audio_mic` | Somente microfone |
| `audio_system` | Somente áudio do sistema |

### Exemplos práticos

```bash
# Aula ou demonstração: tela + voz, H.264, 30 fps
turborec record -m video_mic -c h264 -f 30

# Um monitor ou uma região; use apenas alvos retornados por "turborec targets"
turborec record --monitor HDMI-1
turborec record --region 1280x720+100+50

# Gravação com tempo definido e contagem regressiva
turborec record -m video_mic -t 5m --countdown 3 --open

# Escolha explícita de dispositivo; copie exatamente o nome ou id listado
turborec record -m audio_mic --mic-device "Microfone USB"
turborec record -m video_system --system-device "fonte de loopback"

# Corrige microfone que toca somente à esquerda ou à direita
turborec record -m video_mic --audio-channels left
turborec record -m video_mic --audio-channels right

# Webcam sobreposta no canto inferior direito
turborec cameras
turborec record -m video_mic --camera "ID DA CÂMERA" \
  --camera-size medium --camera-position bottom-right

# Redução de ruído aplicada somente ao microfone
turborec record -m video_mic --denoise medium

# Mostra o pipeline do FFmpeg sem iniciar a captura
turborec record -m video_mic --dry-run
```

Os alvos dependem do backend. Linux e os quatro BSDs em uma sessão X11 oferecem
tela, monitores, regiões e janelas visíveis. No XWayland dos BSDs, é possível
capturar a tela/região exposta pelo servidor de compatibilidade, conforme a
política do compositor. O Linux com Wayland/wlroots também oferece saídas,
regiões e, conforme o compositor, janelas. No Windows, a listagem inclui a área
de trabalho virtual, monitores e
janelas nativas, inclusive quando um monitor fica à esquerda ou acima do
principal. O AVFoundation no macOS seleciona telas completas. Use somente
monitores e janelas realmente mostrados por `turborec targets`.

Opções importantes:

| Opção | Valores ou exemplo | Padrão |
|---|---|---|
| `-q, --quality` | `best`, `high`, `balanced`, `compact` | `best` |
| `-R, --resolution` | `native`, `720p`, `1080p`, `1440p`, `4k` | `4k` |
| `-c, --codec` | `auto`, `h264`, `hevc`, `av1` | `auto` |
| `-f, --fps` | `23`, `30`, `60` ou outro inteiro | `23` |
| `-o, --out` | pasta de saída | `~/Videos` ou `~/Audio` |
| `--backend` | `auto`, `gpu`, `cpu` | `auto` |
| `--audio-codec` | `flac`, `aac`, `opus` | `flac` |
| `--audio-channels` | `stereo`, `mono`, `left`, `right` | `stereo` |
| `-t, --duration` | `90s`, `5m`, `1h30m`, `1h30`, `HH:MM:SS` | sem limite |

Execute `turborec record --help` para ver todas as opções.

### Transmissão ao vivo

Para YouTube ou outro destino RTMP/RTMPS:

```bash
turborec record -m video_both --stream "SUA_CHAVE"
turborec record --stream "SUA_CHAVE" --stream-url rtmps://servidor/aplicacao
```

Em transmissões, o Turbo Recorder sempre usa H.264, AAC, taxa constante e
intervalo de quadro-chave adequado ao RTMP, mesmo que `Codec Auto`, HEVC ou AV1
esteja selecionado para gravações locais.

A aplicação oculta a chave das prévias e mensagens, mas qualquer segredo
informado na linha de comando pode permanecer no histórico do shell e ficar
visível na lista de processos enquanto estiver em uso. Prefira o campo mascarado
da GUI, não compartilhe logs sem revisar e revogue imediatamente uma chave
exposta.

## Microfone, áudio do sistema e câmera

Essas são fontes diferentes:

- **microfone**: entrada física ou virtual usada para a sua voz;
- **áudio do sistema**: retorno/loopback do som enviado aos alto-falantes;
- **câmera**: webcam ou placa de captura usada na sobreposição.

Liste cada categoria antes de gravar:

```bash
turborec devices
turborec cameras
```

O asterisco indica o dispositivo padrão. Para selecionar outro, copie o `id` ou
o nome exatamente como aparece:

```bash
turborec record -m video_mic --mic-device "NOME OU ID"
turborec record -m video_system --system-device "NOME OU ID"
turborec record -m video_mic --camera "NOME OU ID"
```

### Áudio do sistema não é o microfone

Nem Windows nem macOS expõem necessariamente o som dos alto-falantes como uma
entrada gravável. O Turbo Recorder só pode selecionar uma fonte que o sistema e
o FFmpeg consigam enxergar.

- **Windows:** habilite **Mixagem estéreo/Stereo Mix/What U Hear** nas
  propriedades de Som, se o driver oferecer essa entrada. Em
  **Mais configurações de som → Gravação**, habilite a exibição de dispositivos
  desabilitados e ative a entrada. Se o hardware não oferecer loopback, use um
  dispositivo virtual confiável, como
  [VB-CABLE](https://vb-audio.com/Cable/).
- **macOS:** instale e configure um loopback, como
  [BlackHole](https://github.com/ExistentialAudio/BlackHole) ou Loopback. No app
  **Configuração de Áudio e MIDI**, crie a saída múltipla necessária para ouvir
  o som e enviá-lo ao dispositivo virtual.
- **Linux:** o PulseAudio ou a camada de compatibilidade Pulse do PipeWire
  normalmente cria uma fonte com final `.monitor` para cada saída.
- **FreeBSD, OpenBSD, NetBSD e DragonFly:** sndio/OSS oferece entrada de
  microfone, não retorno dos alto-falantes. Para o áudio do sistema, configure
  uma fonte monitor real no PulseAudio; `pactl` permite conferi-la e selecioná-la.

Depois de habilitar ou criar o loopback, feche e abra a aplicação ou atualize os
dispositivos na GUI.

## Solução de problemas por sistema

### Windows: microfone ou câmera não aparece

1. Atualize para o lançamento mais recente e confirme a versão:

   ```powershell
   .\Turbo_Recorder.exe --version
   ```

2. Abra **Configurações → Privacidade e segurança → Microfone** e habilite:
   **Acesso ao microfone** e **Permitir que aplicativos da área de trabalho
   acessem o microfone**.
3. Para a webcam, faça o mesmo em **Privacidade e segurança → Câmera**.
4. Confirme em **Sistema → Som → Entrada** que o dispositivo está habilitado e
   produz sinal.
5. Feche aplicativos que possam ter aberto o dispositivo em modo exclusivo,
   reconecte o USB e atualize a lista:

   ```powershell
   .\Turbo_Recorder.exe devices
   .\Turbo_Recorder.exe cameras
   ```

6. Copie o nome exato retornado:

   ```powershell
   .\Turbo_Recorder.exe record -m audio_mic --mic-device "NOME EXATO" -t 10s
   .\Turbo_Recorder.exe record -m video_mic --camera "NOME EXATO" -t 10s
   ```

Nomes de dispositivos são fornecidos pelo driver e podem estar traduzidos ou
conter acentos e símbolos. Não simplifique nem traduza o nome listado. A
listagem pode mostrar um nome amigável e um `id` único iniciado por
`@device_...`; prefira esse `id` quando dois dispositivos tiverem o mesmo nome.

Se você instalou um FFmpeg de sistema e precisa conferir a enumeração bruta do
DirectShow, execute:

```powershell
ffmpeg -hide_banner -sources dshow
ffmpeg -hide_banner -f dshow -list_devices true -i dummy
```

O segundo comando é o método legado e pode terminar com código de erro depois
de listar os dispositivos; isso é esperado porque `dummy` não é uma entrada
real. O FFmpeg interno do `.exe` oficial não precisa ser extraído para esse
diagnóstico: prefira `devices --json` e `cameras --json`.

### Windows: não aparece áudio do sistema

Uma saída de alto-falante comum não é uma entrada DirectShow. Ative
**Mixagem estéreo/Stereo Mix/What U Hear** ou um cabo virtual e execute
novamente:

```powershell
.\Turbo_Recorder.exe devices
.\Turbo_Recorder.exe record -m audio_system --system-device "NOME DO LOOPBACK" -t 10s
```

Se o loopback aparece como microfone em vez de “áudio do sistema”, informe o
nome explicitamente em `--system-device`. Na GUI do Windows, o seletor de áudio
do sistema também oferece todas as entradas DirectShow detectadas, para que uma
fonte com nome localizado ou fornecido pelo fabricante possa ser escolhida
manualmente.

### Windows: tela preta ou escala incorreta

- Atualize o driver de vídeo e teste primeiro `video_only`.
- Em notebooks com mais de uma GPU, teste `--cpu` para separar a captura do
  problema de codificação.
- Execute `targets` novamente depois de conectar um monitor ou abrir uma janela.
- Use `--monitor`, `--window` ou `--region` para limitar a captura. Coordenadas
  negativas são válidas para monitores à esquerda/acima do principal.
- Em uma sessão de Área de Trabalho Remota, o desktop capturável pode mudar ou
  desaparecer ao desconectar.

```powershell
.\Turbo_Recorder.exe targets
.\Turbo_Recorder.exe record -m video_only --monitor "DISPLAY2" -t 10s
.\Turbo_Recorder.exe record -m video_only --window "Bloco de Notas" -t 10s
.\Turbo_Recorder.exe record -m video_only --region 1920x1080-1920+0 -t 10s
.\Turbo_Recorder.exe record -m video_only --cpu -f 30 -t 10s
```

### macOS: tela preta ou sem permissão

Autorize **Gravação de Tela e Áudio do Sistema/Gravação da Tela** para o
Terminal, Python ou aplicativo que inicia o Turbo Recorder. Encerre totalmente
esse aplicativo e abra-o novamente. Teste:

```bash
turborec record -m video_only --cpu -f 30 -t 10s
```

Se microfone ou câmera não aparecer, revise também as permissões específicas e
execute:

```bash
turborec devices
turborec cameras
```

Para escolher outra tela, copie o rótulo mostrado por:

```bash
turborec targets
turborec record -m video_only --monitor "RÓTULO MOSTRADO" -t 10s
```

Os índices do AVFoundation podem mudar quando um dispositivo é conectado ou
removido; sempre use a listagem mais recente.

### Linux X11: tela ou janela não aparece

Confirme que a variável `DISPLAY` pertence à sessão atual:

```bash
printf '%s\n' "$DISPLAY"
xrandr --query
turborec targets
```

Para listar janelas, instale `wmctrl`. A captura de uma janela em X11 é um
recorte da região visível; outra janela sobreposta também será gravada.

### Linux Wayland: tela preta ou erro de `wf-recorder`

Confira a sessão e as ferramentas:

```bash
printf '%s\n' "$XDG_SESSION_TYPE"
command -v wf-recorder
command -v swaymsg
command -v wlr-randr
turborec detect
```

Em sway, Hyprland, river e outros compositores wlroots, instale `wf-recorder`.
No GNOME/KDE Wayland, entre em uma sessão X11/Xorg se o backend wlroots não
estiver disponível.

### Linux: nenhum dispositivo de áudio

O Turbo Recorder consulta `pactl`. Primeiro confirme que ele alcança o servidor
de áudio da sessão:

```bash
pactl info
pactl list short sources
turborec devices
```

No PipeWire, confirme também:

```bash
wpctl status
```

Procure uma fonte física para o microfone e uma fonte terminada em `.monitor`
para o áudio do sistema. Execute o Turbo Recorder como o usuário da sessão
gráfica, não como `root`, para que ele acesse o servidor de áudio correto.

### BSD: nenhum dispositivo de áudio

Confira quais entradas o FFmpeg realmente contém e quais nós existem:

```sh
ffmpeg -hide_banner -devices
ls -l /dev/audio* /dev/dsp* 2>/dev/null
turborec devices
```

No OpenBSD, procure `sndio`; no FreeBSD, NetBSD e DragonFly, procure `oss`.
Mesmo que o nome do backend apareça, o Turbo Recorder só lista o microfone se o
caminho correspondente resolver para um dispositivo de caractere real. Isso
evita que diretórios como `/dev/sound` ou nomes presumidos sejam anunciados como
fontes. Verifique também permissões e se outro programa mantém o dispositivo
aberto.

PulseAudio e `pactl` não são obrigatórios para o microfone nativo. Eles são
necessários no BSD apenas quando você deseja usar fontes Pulse ou gravar áudio
do sistema por uma fonte terminada em `.monitor`. Nós sndio/OSS não devem ser
informados em `--system-device`.

### Webcam no Linux ou BSD não aparece

Confira se existe um dispositivo de vídeo e se o usuário tem permissão para
abri-lo:

```bash
ls -l /dev/video*
turborec cameras
```

No Linux, o usuário pode precisar pertencer ao grupo que possui `/dev/videoN`
e iniciar uma nova sessão depois da alteração. Nos BSDs, a webcam só é listada
se o FFmpeg oferecer `video4linux2`/`v4l2` e `/dev/videoN` for um dispositivo de
caractere capturável. No FreeBSD, isso pode exigir a configuração de
`webcamd`/`cuse`, conforme o dispositivo.

### `FFmpeg not found`

Confirme:

```bash
ffmpeg -version
command -v ffmpeg
```

Também é possível apontar uma instalação específica. A opção global deve vir
antes do subcomando:

```bash
turborec --ffmpeg /caminho/para/ffmpeg devices
```

No PowerShell:

```powershell
py turborec.py --ffmpeg "C:\ffmpeg\bin\ffmpeg.exe" devices
```

O `.exe` oficial do Windows já contém o FFmpeg.

### A GUI não abre

Teste o Tk:

```bash
python3 -c "import tkinter; print(tkinter.TkVersion)"
```

Instale `python3-tk` no Debian/Ubuntu, `python3-tkinter` no Fedora ou `tk` no
Arch Linux. No FreeBSD, instale o pacote `py*-tkinter` correspondente ao Python.
A CLI continua disponível mesmo sem Tk.

### A gravação está lenta, travando ou fora de sincronia

Reduza primeiro a carga:

```bash
turborec record -m video_mic --backend auto -q high -f 30
turborec record -m video_mic --cpu -q balanced -f 30
```

Use `turborec encoders` para confirmar o codificador escolhido. `--gpu` solicita
hardware explicitamente e avisa antes de usar a alternativa segura por software
quando nenhum candidato funciona; `--cpu` força o caminho por software.

## Qualidade, desempenho e compatibilidade

- O perfil inicial é **Best + Auto + 23 fps + 4K**. Ele privilegia a qualidade
  sem exigir que a pessoa conheça o hardware da máquina.
- Em `-c auto`, a preferência é **AV1 por hardware → HEVC por hardware → H.264
  por hardware → H.264 por software**. A seleção considera testes reais do
  codificador, não apenas o nome mostrado pelo FFmpeg.
- **H.264** é a opção mais compatível para reprodução e edição.
- **HEVC/H.265** e **AV1** podem produzir arquivos menores, mas exigem suporte no
  hardware, no FFmpeg e no reprodutor.
- **23 fps** é o padrão de alta qualidade e reduz o trabalho do codificador;
  **30 fps** é uma boa escolha para aulas, apresentações e demonstrações;
  **60 fps** é mais indicado para movimento rápido e exige mais processamento.
- `-R 4k` é o padrão e produz um quadro exato de 3840×2160, ampliando a origem
  quando necessário. `-R native` preserva a resolução capturada e reduz a carga.
- FLAC é o padrão e não perde qualidade; AAC e Opus geram arquivos menores.
- MKV tolera melhor interrupções durante a gravação do que contêineres menos
  resilientes.

Para confirmar que o arquivo final contém os fluxos esperados:

```bash
ffprobe -v error -show_entries \
  stream=codec_type,codec_name,width,height,sample_rate,channels \
  -of default=noprint_wrappers=1 /caminho/para/gravacao.mkv
```

## Configuração persistente

Os padrões podem ser salvos em:

- `~/.config/turborec/config.json`;
- `~/.turborec.json`;
- um arquivo indicado por `TURBOREC_CONFIG`;
- um arquivo indicado por `--config`.

Exemplo:

```json
{
  "mode": "auto",
  "quality": "best",
  "codec": "auto",
  "fps": 23,
  "resolution": "4k",
  "backend": "auto",
  "audio_codec": "flac",
  "denoise": "medium"
}
```

Uma opção informada na CLI tem precedência sobre o arquivo. Não armazene chaves
de transmissão em arquivos de configuração compartilhados ou em repositórios.

## Como coletar um diagnóstico

Ao relatar um problema, informe:

- versão do Turbo Recorder;
- edição e versão do sistema operacional;
- tipo de sessão gráfica: X11, Wayland/wlroots, Quartz ou GDI;
- modelo do microfone/câmera e como ele está conectado;
- modo e comando usados;
- mensagem completa de erro.

Gere os relatórios sem iniciar uma gravação:

```bash
turborec --version
turborec detect --json
turborec devices --json
turborec cameras --json
turborec targets --json
turborec encoders --json
turborec record -m video_only --dry-run
```

No PowerShell com o executável oficial:

```powershell
.\Turbo_Recorder.exe --version
.\Turbo_Recorder.exe detect --json
.\Turbo_Recorder.exe devices --json
.\Turbo_Recorder.exe cameras --json
```

Revise os arquivos antes de publicá-los: nomes de dispositivos, janelas e
caminhos podem revelar informações pessoais. Nunca envie uma chave de
transmissão.

Para pedir ajuda ou relatar um defeito, abra uma
[issue no repositório](https://github.com/cristiancmoises/turborec/issues) com o
menor teste que reproduza o problema.
