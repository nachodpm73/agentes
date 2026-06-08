# html2mp4 — HTML standalone → MP4 con timing exacto

Convierte un archivo HTML autónomo (con sus animaciones/transiciones CSS y JS)
en un vídeo MP4 **respetando los tiempos exactos** de las transiciones.

## Cómo funciona

No graba la pantalla en tiempo real (lo que produciría jitter y dependería de
la potencia de la máquina). En su lugar usa [`timecut`](https://github.com/tungs/timecut)
(Puppeteer + ffmpeg) con un **reloj virtual** ([`timeweb`](https://github.com/tungs/timeweb))
que intercepta `Date`, `performance.now`, `requestAnimationFrame`,
`setTimeout`/`setInterval` y la línea de tiempo de las animaciones/transiciones
CSS. Avanza el tiempo en pasos fijos de `1/fps`, toma un screenshot por paso y
ensambla los fotogramas con ffmpeg.

Resultado: **timing perfecto, suave y reproducible**, sea cual sea la máquina.
Funciona con animaciones CSS, `@keyframes`, transiciones y animaciones JS.

## Requisitos

- Node.js (probado con v22)
- ffmpeg en el `PATH`
- Chromium (Puppeteer descarga uno propio al instalar; o exporta `CHROME_PATH`)

## Instalación

```bash
npm install
```

## Uso

```bash
node html2mp4.js entrada.html [opciones]
```

Ejemplo:

```bash
node html2mp4.js ejemplo.html -o salida.mp4 --duration 4 --fps 30 \
  --width 1920 --height 1080
```

### Opciones

| Opción | Descripción | Por defecto |
|---|---|---|
| `-o, --output <f>` | Archivo MP4 de salida | `<entrada>.mp4` |
| `-d, --duration <s>` | Segundos a capturar | auto-detecta (ver abajo) |
| `-f, --fps <n>` | Fotogramas por segundo | `30` |
| `-w, --width <px>` | Ancho del viewport | `1920` |
| `-h, --height <px>` | Alto del viewport | `1080` |
| `-s, --scale <n>` | Supersampling / `deviceScaleFactor` | `1` |
| `--start <s>` | Tiempo virtual inicial | `0` |
| `--selector <css>` | Capturar sólo ese elemento | (toda la página) |
| `--crf <n>` | Calidad x264 (menor = mejor) | `18` |
| `--keep-frames` | Conservar frames intermedios | (no) |

## Auto-detección de duración

Si no pasas `--duration`, el script intenta leerla del propio HTML, en este orden:

1. `<meta name="capture-duration" content="6">`
2. `window.CAPTURE_DURATION` (número en segundos)
3. atributo `data-capture-duration` en `<body>` o `<html>`

Si no encuentra ninguno, usa 5 s por defecto y avisa.

## Lote (varios HTML)

```bash
for f in *.html; do node html2mp4.js "$f"; done
```

## Notas / límites

- El Chromium que descarga la versión incluida de Puppeteer es antiguo
  (~Chrome 80). Soporta la inmensa mayoría de CSS (flexbox, grid, transforms,
  `@keyframes`, transiciones). Si tu HTML usa CSS muy reciente
  (`:has()`, container queries, etc.) exporta `CHROME_PATH` apuntando a un
  Chrome moderno.
- Para animaciones en bucle infinito, define una `--duration` (cuánto vídeo
  quieres) ya que no tienen final natural.
- El audio no se captura (los HTML standalone rara vez lo necesitan; se puede
  añadir después con ffmpeg si hace falta).
