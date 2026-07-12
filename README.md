# Subir VODs de Kick a YouTube

Este workflow procesa un VOD por ejecución:

1. Consulta los VODs del canal `vector` en Kick.
2. Consulta los videos ya subidos al canal de YouTube.
3. Ordena los VODs por fecha, del más antiguo al más reciente.
4. Descarga el primer VOD pendiente como MP4.
5. Lo sube mediante la YouTube Data API con carga resumible.
6. Añade `kick-vod-id:<ID>` como etiqueta del video para evitar duplicados.

## Preparar la API de YouTube

1. Crea un proyecto en Google Cloud.
2. Habilita **YouTube Data API v3**.
3. Configura la pantalla de consentimiento OAuth.
4. Crea un cliente OAuth de tipo **Aplicación de escritorio**.
5. Descarga el archivo de credenciales, por ejemplo `client_secret.json`.

## Obtener el refresh token

Ejecuta estos comandos en tu computadora:

```bash
python -m pip install -r requirements.txt
python get_youtube_token.py client_secret.json
```

Se abrirá el navegador para autorizar el canal. El script mostrará tres valores.
Agrégalos en GitHub, dentro de **Settings > Secrets and variables > Actions**:

- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

No subas `client_secret.json` al repositorio.

## Ejecutar

Abre la pestaña **Actions**, selecciona **Upload oldest VOD to YouTube** y pulsa
**Run workflow**. Cada ejecución sube un solo VOD pendiente.

## Configuración

En `.github/workflows/upload-youtube.yml` puedes cambiar:

- `KICK_CHANNEL`: canal de Kick.
- `YOUTUBE_PRIVACY_STATUS`: `private`, `unlisted` o `public`.
- `YOUTUBE_CATEGORY_ID`: categoría de YouTube; `20` corresponde a Gaming.

Los proyectos de API no verificados pueden quedar limitados a videos privados hasta
que Google apruebe una auditoría del proyecto.


## Formato publicado

El título se genera así:

```text
Vector | DD/MM/AAAA
```

La descripción contiene, en este orden y en líneas separadas:

```text
<session_title>
<start_time>
<source>
```
