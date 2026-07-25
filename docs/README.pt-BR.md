# Turbo Recorder — documentação em português do Brasil

O **Turbo Recorder** grava a tela, o microfone e o áudio do sistema com o
FFmpeg. Ele detecta o sistema operacional, a tela, os dispositivos de áudio, a
GPU e os codificadores disponíveis e oferece duas interfaces:

Este guia corresponde ao **Turbo Recorder 3.7.0**.

- `turborec`: interface gráfica e linha de comando para Windows, macOS, Linux e
  FreeBSD;
- `turborecorder`: linha de comando alternativa, voltada para Linux com X11 ou
  Wayland/wlroots.

Para começar, use `turborec`. Esta página usa nomes de arquivos sem fixar uma
versão; substitua `*` ou `VERSÃO` pelo número mostrado na
[página de lançamentos (Releases)](https://github.com/cristiancmoises/turborec/releases/latest).

Documentos relacionados:

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
| Windows 10/11 x64 | GDI (`gdigrab`) | DirectShow | O `.exe` x64 inclui Python, Tk e FFmpeg |
| macOS | AVFoundation | AVFoundation | É necessário autorizar tela, microfone e câmera |
| Linux X11 | `x11grab` | PulseAudio/PipeWire e V4L2 | `wmctrl` é opcional para listar janelas |
| Linux Wayland/wlroots | `wf-recorder` | PipeWire/PulseAudio e V4L2 | Compatível com sway, Hyprland, river e outros compositores wlroots |
| FreeBSD | caminho Unix/X11 | PulseAudio e dispositivos expostos ao FFmpeg | Python, FFmpeg e, para a GUI, Tk devem ser instalados separadamente |

Requisitos quando não se usa o executável autossuficiente do Windows:

- Python 3.8 ou mais recente;
- FFmpeg disponível no `PATH`;
- Tk para a interface gráfica; a CLI funciona sem Tk;
- no Linux/FreeBSD, `pactl` é necessário para a detecção automática de
  microfones e fontes de áudio PulseAudio/PipeWire; ainda é possível informar
  um dispositivo manualmente pela CLI;
- no Wayland/wlroots, `wf-recorder` e `swaymsg` ou `wlr-randr`.

> O suporte a Wayland é direcionado a compositores **wlroots**. Em sessões
> Wayland do GNOME ou KDE, o método de captura pode não estar disponível. Nesse
> caso, entre em uma sessão X11/Xorg ou use um compositor compatível.

## Instalação

Baixe os artefatos somente na
[página oficial de lançamentos](https://github.com/cristiancmoises/turborec/releases/latest).

### Windows

Baixe `Turbo_Recorder-VERSÃO-windows-x64.exe`. O arquivo já contém Python, Tk e
FFmpeg, não exige instalação administrativa e pode ser aberto com dois cliques.
Sem argumentos, ele abre a interface gráfica.

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

### FreeBSD

Execute como `root` (diretamente, com `doas` ou com `sudo`, conforme a
configuração local):

```sh
pkg add ./turborec-*.pkg
pkg install python3 ffmpeg
turborec --version
```

O pacote nativo do Turbo Recorder não força dependências de execução; por isso,
Python e FFmpeg devem ser instalados separadamente. Para a interface gráfica,
procure e instale o pacote Tk que corresponda à versão padrão do Python:

```sh
pkg search tkinter
```

A detecção automática de áudio usa `pactl`. Instale e configure PulseAudio na
sessão do usuário quando precisar de microfone ou áudio do sistema:

```sh
pkg install pulseaudio
pactl info
```

Em X11, `xrandr`/`xdpyinfo` ajudam a detectar a tela e `wmctrl` permite listar
janelas. Em uma sessão Wayland/wlroots, instale `wf-recorder` e `wlr-randr` ou
use `swaymsg`.

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
3. mantenha **Encoder: Auto** no primeiro teste;
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

Os alvos dependem do backend. Linux/FreeBSD com X11 e Linux com
Wayland/wlroots oferecem monitores, regiões e, conforme o compositor,
janelas. No Windows, a listagem inclui a área de trabalho virtual, monitores e
janelas nativas, inclusive quando um monitor fica à esquerda ou acima do
principal. O AVFoundation no macOS seleciona telas completas. Use somente
monitores e janelas realmente mostrados por `turborec targets`.

Opções importantes:

| Opção | Valores ou exemplo | Padrão |
|---|---|---|
| `-q, --quality` | `best`, `high`, `balanced`, `compact` | `best` |
| `-R, --resolution` | `native`, `720p`, `1080p`, `1440p`, `4k` | `native` |
| `-c, --codec` | `h264`, `hevc`, `av1` | `h264` |
| `-f, --fps` | `23`, `30`, `60` ou outro inteiro | `60` |
| `-o, --out` | pasta de saída | `~/Videos` ou `~/Audio` |
| `--backend` | `auto`, `gpu`, `cpu` | `auto` |
| `--audio-codec` | `flac`, `aac`, `opus` | `flac` |
| `--audio-channels` | `stereo`, `mono`, `left`, `right` | `stereo` |
| `-t, --duration` | `90s`, `5m`, `1h30m`, `HH:MM:SS` | sem limite |

Execute `turborec record --help` para ver todas as opções.

### Transmissão ao vivo

Para YouTube ou outro destino RTMP/RTMPS:

```bash
turborec record -m video_both --stream "SUA_CHAVE"
turborec record --stream "SUA_CHAVE" --stream-url rtmps://servidor/aplicacao
```

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
- **FreeBSD:** use uma fonte monitor/loopback disponibilizada pelo PulseAudio;
  `pactl` permite conferir e selecionar essa fonte explicitamente.

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

### Linux/FreeBSD: nenhum dispositivo de áudio

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

### Webcam no Linux/FreeBSD não aparece

Confira se existe um dispositivo de vídeo e se o usuário tem permissão para
abri-lo:

```bash
ls -l /dev/video*
turborec cameras
```

No Linux, o usuário pode precisar pertencer ao grupo que possui `/dev/videoN`
e iniciar uma nova sessão depois da alteração. No FreeBSD, a webcam precisa ser
exposta em um formato que o FFmpeg reconheça; isso pode exigir a configuração
de `webcamd`/`cuse`, conforme o dispositivo.

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

Use `turborec encoders` para confirmar o codificador escolhido. `--gpu` força
hardware e pode falhar quando o driver ou o FFmpeg não oferecem o codificador;
`--cpu` é o caminho de compatibilidade.

## Qualidade, desempenho e compatibilidade

- **H.264** é a opção mais compatível para reprodução e edição.
- **HEVC/H.265** e **AV1** podem produzir arquivos menores, mas exigem suporte no
  hardware, no FFmpeg e no reprodutor.
- **30 fps** é uma boa escolha para aulas, apresentações e demonstrações;
  **60 fps** é mais indicado para movimento rápido e exige mais processamento.
- `-R native` preserva a resolução da captura. `-R 4k` pode ser útil para a
  camada de alta qualidade do YouTube, mas aumenta bastante a carga.
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
  "mode": "video_mic",
  "quality": "high",
  "codec": "h264",
  "fps": 30,
  "resolution": "native",
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
