# Modo Guerrero

Panel autoalojado de carrera a pie con tus datos de Garmin Connect, pensado para Umbrel:
carreras con mapa, gráficas y parciales, récords personales, forma y carga (CTL/ATL/TSB),
VO2max, sueño, VFC, pulso en reposo, Body Battery y estrés, con una página de inicio
personalizable mediante widgets.

Este repositorio es a la vez **el código de la app** y **una tienda comunitaria de Umbrel**.

## Instalar en Umbrel

1. En Umbrel abre **App Store → ⋯ (arriba a la derecha) → Community App Stores**.
2. Pega la URL de este repositorio y pulsa **Add**.
3. Abre la tienda **Modo Guerrero** e instala la app.
4. Abre Modo Guerrero → **Ajustes → Cuenta de Garmin** y conecta tu cuenta (admite verificación en dos pasos).

La app queda protegida por el inicio de sesión de Umbrel. Tus datos se guardan en la carpeta de
datos de la app en Umbrel y se conservan entre actualizaciones.

## Actualizar

Cuando se publica una versión nueva, Umbrel la muestra como actualización disponible de Modo Guerrero.
Pulsa **Actualizar**. (Umbrel revisa las tiendas comunitarias cada cierto tiempo; para forzarlo,
vuelve a abrir la tienda.)

## Publicar una versión nueva

1. Sube los cambios a `main` (la acción **Comprobaciones** verifica que la app arranca).
2. En GitHub: **Releases → Draft a new release**, crea una etiqueta `vX.Y.Z` (por ejemplo `v0.1.1`),
   escribe las novedades y pulsa **Publish release**.
   Alternativa desde la terminal: `git tag -a v0.1.1 -m "Novedades…" && git push origin v0.1.1`.
3. La acción **Publicar versión**:
   - construye la imagen para amd64 y arm64 y la publica en `ghcr.io/rawd0/modo-guerrero`,
   - mete la versión en la app (se ve en el banner),
   - actualiza `modo-guerrero-app/` con la nueva versión, la imagen fijada por su digest y las notas.

### Primera vez: hacer pública la imagen

GitHub puede crear el paquete de la imagen como privado. Tras la primera publicación, ve a tu perfil
→ **Packages → modo-guerrero → Package settings → Change visibility → Public**. Sin esto, Umbrel no podrá
descargarla. Sólo hay que hacerlo una vez.

## Estructura

```
umbrel-app-store.yml        definición de la tienda comunitaria
modo-guerrero-app/          ficha de la app para Umbrel (manifiesto + docker-compose)
src/                        código de la app (FastAPI + SQLite + web)
  app/                      backend y web
  scripts/demo_data.py      datos de ejemplo
  Dockerfile
scripts/update_umbrel_app.py  usado por la acción de publicación
.github/workflows/          comprobaciones y publicación
docs/icon.svg               icono de la app
```

## Desarrollo local

```bash
cd src
pip install -r requirements.txt
DATA_DIR=./data python -m scripts.demo_data   # datos de ejemplo (borra la base de datos)
DATA_DIR=./data uvicorn app.main:app --reload --port 8080
```

## Sin la tienda de Umbrel (Docker a mano)

```yaml
services:
  modo-guerrero:
    image: ghcr.io/rawd0/modo-guerrero:latest
    restart: unless-stopped
    ports: ["8095:8080"]
    environment:
      APP_PASSWORD: "una-contraseña"          # sin el login de Umbrel, ponla siempre
      APP_SECRET_KEY: "frase-larga-aleatoria"  # cifra el token de Garmin
    volumes: ["./data:/data"]
```

## Seguridad

- La contraseña de Garmin no se guarda: sólo un token de sesión cifrado (la clave se genera en tu
  servidor, en la carpeta de datos, y nunca está en este repositorio).
- No expongas la app a internet; usa Tailscale para entrar desde fuera.
- El acceso a Garmin usa la librería no oficial `garminconnect`; si Garmin cambia su sistema puede
  fallar temporalmente. Siempre puedes importar archivos .FIT a mano desde Ajustes.
