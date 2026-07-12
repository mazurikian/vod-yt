import json
import os
import random
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import httplib2
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

CHANNEL = os.environ.get("KICK_CHANNEL", "vector")
KICK_API_URL = f"https://kick.com/api/v2/channels/{CHANNEL}/videos"
WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/mnt/workspace"))
PRIVACY_STATUS = os.environ.get("YOUTUBE_PRIVACY_STATUS", "private")
CATEGORY_ID = os.environ.get("YOUTUBE_CATEGORY_ID", "20")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
RETRIABLE_EXCEPTIONS = (
    httplib2.HttpLib2Error,
    IOError,
    socket.timeout,
)
MAX_RETRIES = 10
VOD_ID_PATTERN = re.compile(r"kick-vod-id:([^\s]+)")


def get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable o secreto requerido: {name}")
    return value


def build_youtube_client():
    credentials = Credentials(
        token=None,
        refresh_token=get_required_env("YOUTUBE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=get_required_env("YOUTUBE_CLIENT_ID"),
        client_secret=get_required_env("YOUTUBE_CLIENT_SECRET"),
        scopes=SCOPES,
    )

    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def get_uploaded_vod_ids(youtube):
    """Obtiene los IDs de Kick guardados en descripciones del canal de YouTube."""
    channel_response = youtube.channels().list(
        part="contentDetails",
        mine=True,
    ).execute()

    if not channel_response.get("items"):
        raise RuntimeError("No se encontró un canal de YouTube para estas credenciales.")

    uploads_playlist = channel_response["items"][0]["contentDetails"][
        "relatedPlaylists"
    ]["uploads"]

    uploaded_vod_ids = set()
    page_token = None

    while True:
        playlist_response = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        video_ids = [
            item["contentDetails"]["videoId"]
            for item in playlist_response.get("items", [])
        ]

        if video_ids:
            videos_response = youtube.videos().list(
                part="snippet",
                id=",".join(video_ids),
                maxResults=50,
            ).execute()

            for item in videos_response.get("items", []):
                snippet = item.get("snippet", {})
                description = snippet.get("description", "")
                tags = snippet.get("tags", [])

                # Compatibilidad con videos antiguos que guardaban el ID
                # en la descripción.
                match = VOD_ID_PATTERN.search(description)
                if match:
                    uploaded_vod_ids.add(match.group(1))

                # Los videos nuevos guardan el ID en una etiqueta para dejar
                # la descripción exactamente con los datos solicitados.
                for tag in tags:
                    match = VOD_ID_PATTERN.fullmatch(tag)
                    if match:
                        uploaded_vod_ids.add(match.group(1))

        page_token = playlist_response.get("nextPageToken")
        if not page_token:
            break

    return uploaded_vod_ids


def get_kick_videos():
    request = urllib.request.Request(
        KICK_API_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
                "Gecko/20100101 Firefox/152.0"
            ),
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        videos = json.load(response)

    if not isinstance(videos, list):
        raise RuntimeError("La API de Kick no devolvió una lista de videos.")

    return sorted(
        (
            video
            for video in videos
            if video.get("is_live") is not True
            and video.get("source")
            and video.get("id") is not None
        ),
        key=lambda video: (
            video.get("created_at", ""),
            str(video.get("id", "")),
        ),
    )


def select_oldest_pending_video(videos, uploaded_vod_ids):
    for video in videos:
        if str(video["id"]) not in uploaded_vod_ids:
            return video
    return None


def download_video(video, output_path):
    subprocess.run(
        [
            "ffmpeg",
            "-i",
            video["source"],
            "-c",
            "copy",
            str(output_path),
        ],
        check=True,
    )


def upload_video(youtube, video, video_path):
    video_id = str(video["id"])
    created_at = str(video.get("created_at", ""))
    video_date = created_at.split("T")[0].split(" ")[0]

    try:
        year, month, day = video_date.split("-")
        formatted_date = f"{day}/{month}/{year}"
    except ValueError as error:
        raise RuntimeError(
            f"Fecha created_at no válida para el VOD {video_id}: {created_at}"
        ) from error

    channel_name = CHANNEL[:1].upper() + CHANNEL[1:]
    session_title = str(video.get("session_title") or "Sin título")
    start_time = str(video.get("start_time") or "")
    source = str(video.get("source") or "")

    title = f"{channel_name} | {formatted_date}"[:100]
    description = "\n\n".join(
        [
            session_title,
            start_time,
            source,
        ]
    )

    insert_request = youtube.videos().insert(
        part="snippet,status",
        notifySubscribers=False,
        body={
            "snippet": {
                "title": title,
                "description": description,
                "tags": [CHANNEL, "Kick", "VOD", f"kick-vod-id:{video_id}"],
                "categoryId": CATEGORY_ID,
            },
            "status": {
                "privacyStatus": PRIVACY_STATUS,
            },
        },
        media_body=MediaFileUpload(
            str(video_path),
            mimetype="video/mp2t",
            chunksize=8 * 1024 * 1024,
            resumable=True,
        ),
    )

    response = None
    retry = 0

    while response is None:
        try:
            status, response = insert_request.next_chunk()
            if status:
                print(f"Progreso de subida: {int(status.progress() * 100)}%")
        except HttpError as error:
            if error.resp.status not in RETRIABLE_STATUS_CODES:
                raise

            retry += 1
            if retry > MAX_RETRIES:
                raise RuntimeError("Se agotaron los reintentos de subida.") from error

            delay = random.random() * (2**retry)
            print(
                f"Error temporal HTTP {error.resp.status}; "
                f"nuevo intento en {delay:.1f} segundos."
            )
            time.sleep(delay)
        except RETRIABLE_EXCEPTIONS as error:
            retry += 1
            if retry > MAX_RETRIES:
                raise RuntimeError("Se agotaron los reintentos de subida.") from error

            delay = random.random() * (2**retry)
            print(
                f"Error temporal de conexión; "
                f"nuevo intento en {delay:.1f} segundos: {error}"
            )
            time.sleep(delay)

    uploaded_id = response["id"]
    print(f"Video subido correctamente: https://youtu.be/{uploaded_id}")
    return uploaded_id


def main():
    if PRIVACY_STATUS not in {"private", "unlisted", "public"}:
        raise RuntimeError(
            "YOUTUBE_PRIVACY_STATUS debe ser private, unlisted o public."
        )

    WORKSPACE.mkdir(parents=True, exist_ok=True)

    youtube = build_youtube_client()
    uploaded_vod_ids = get_uploaded_vod_ids(youtube)
    videos = get_kick_videos()

    (WORKSPACE / "videos.json").write_text(
        json.dumps(videos, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    video = select_oldest_pending_video(videos, uploaded_vod_ids)
    if video is None:
        print("No hay VODs pendientes para subir a YouTube.")
        return

    video_id = str(video["id"])
    created_at = str(video.get("created_at", "unknown"))
    video_date = created_at.split("T")[0].split(" ")[0]
    video_directory = WORKSPACE / f"{video_date}_{video_id}"
    video_directory.mkdir(parents=True, exist_ok=True)

    (video_directory / "video.json").write_text(
        json.dumps(video, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    output_path = video_directory / "output.ts"

    print(f"Descargando el VOD pendiente más antiguo: {video_id} ({created_at})")
    download_video(video, output_path)
    upload_video(youtube, video, output_path)


if __name__ == "__main__":
    main()
