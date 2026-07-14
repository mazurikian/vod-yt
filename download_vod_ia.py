import copy
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

import internetarchive
import m3u8
from m3u8.model import SegmentList


CHANNEL = os.environ.get(
    "KICK_CHANNEL",
    "vector"
)

KICK_API_URL = (
    f"https://kick.com/api/v2/channels/{CHANNEL}/videos"
)

WORKSPACE = Path(
    os.environ.get(
        "WORKSPACE_DIR",
        "/mnt/workspace"
    )
)

IA_ACCESS_KEY = os.environ.get(
    "IA_ACCESS_KEY"
)

IA_SECRET_KEY = os.environ.get(
    "IA_SECRET_KEY"
)

IA_COLLECTION = os.environ.get(
    "IA_COLLECTION",
    "opensource_media"
)


HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/120 Safari/537.36"
    ),
    "Accept": (
        "application/json,"
        "application/vnd.apple.mpegurl,"
        "*/*"
    ),
}


RETRIABLE_EXCEPTIONS = (
    IOError,
    socket.timeout,
)


MAX_RETRIES = 10



def get_kick_videos():

    request = urllib.request.Request(
        KICK_API_URL,
        headers=HTTP_HEADERS
    )


    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:

        videos = json.load(response)


    if not isinstance(
        videos,
        list
    ):
        raise RuntimeError(
            "La API de Kick no devolvió una lista."
        )


    return sorted(
        (
            video
            for video in videos
            if (
                video.get("is_live")
                is not True
            )
            and video.get("source")
            and video.get("id") is not None
        ),
        key=lambda video: (
            video.get(
                "created_at",
                ""
            ),
            str(
                video.get(
                    "id",
                    ""
                )
            )
        )
    )



def fetch_playlist(url):

    request = urllib.request.Request(
        url,
        headers=HTTP_HEADERS
    )


    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:

        final_url = response.geturl()

        content = (
            response
            .read()
            .decode(
                "utf-8-sig"
            )
        )


    return (
        m3u8.loads(
            content,
            uri=final_url
        ),
        final_url
    )



def variant_score(variant):

    stream_info = variant.stream_info


    bandwidth = (
        getattr(
            stream_info,
            "average_bandwidth",
            None
        )
        or
        getattr(
            stream_info,
            "bandwidth",
            None
        )
        or 0
    )


    resolution = (
        getattr(
            stream_info,
            "resolution",
            None
        )
        or (0,0)
    )


    fps = (
        getattr(
            stream_info,
            "frame_rate",
            None
        )
        or 0
    )


    return (
        int(bandwidth),
        int(resolution[0])
        *
        int(resolution[1]),
        float(fps)
    )



def resolve_media_playlist(source_url):

    current_url = source_url


    for _ in range(5):

        playlist, final_url = fetch_playlist(
            current_url
        )


        if not playlist.is_variant:

            if not playlist.segments:

                raise RuntimeError(
                    "Playlist vacío."
                )

            return (
                playlist,
                final_url
            )


        if not playlist.playlists:

            raise RuntimeError(
                "Playlist maestro sin variantes."
            )


        selected = max(
            playlist.playlists,
            key=variant_score
        )


        current_url = urljoin(
            final_url,
            selected.uri
        )


        info = selected.stream_info


        print(
            "Calidad seleccionada:",
            getattr(
                info,
                "resolution",
                None
            ),
            getattr(
                info,
                "frame_rate",
                None
            ),
            "FPS"
        )


    raise RuntimeError(
        "Demasiados niveles HLS."
    )



def absolutize_segment_references(
    segment,
    playlist_url
):

    segment.uri = urljoin(
        playlist_url,
        segment.uri
    )


    if (
        segment.key
        and segment.key.uri
    ):

        segment.key.uri = urljoin(
            playlist_url,
            segment.key.uri
        )


    if (
        segment.init_section
        and segment.init_section.uri
    ):

        segment.init_section.uri = urljoin(
            playlist_url,
            segment.init_section.uri
        )



def write_full_playlist(
    media_playlist,
    media_playlist_url,
    destination
):

    playlist = copy.deepcopy(
        media_playlist
    )


    segments = list(
        playlist.segments
    )


    for segment in segments:

        absolutize_segment_references(
            segment,
            media_playlist_url
        )


    playlist.segments = SegmentList(
        segments
    )


    playlist.is_endlist = True

    playlist.playlist_type = "vod"


    destination.write_text(
        playlist.dumps(),
        encoding="utf-8"
    )



def download_full_vod(
    playlist_path,
    output_path
):

    subprocess.run(
        [
            "ffmpeg",

            "-protocol_whitelist",
            "file,http,https,tcp,tls,crypto,data",

            "-i",
            str(playlist_path),

            "-c",
            "copy",

            "-bsf:a",
            "aac_adtstoasc",

            str(output_path)
        ],
        check=True
    )

  def upload_archive(video, video_path):

    if not IA_ACCESS_KEY or not IA_SECRET_KEY:
        raise RuntimeError(
            "Faltan IA_ACCESS_KEY o IA_SECRET_KEY."
        )


    vod_id = str(
        video["id"]
    )


    identifier = (
        f"{CHANNEL}-kick-vod-{vod_id}"
    )


    metadata = {
        "title": (
            f"{CHANNEL} Kick VOD "
            f"{video.get('created_at','')}"
        ),

        "creator": CHANNEL,

        "mediatype": "movies",

        "collection": IA_COLLECTION,

        "subject": [
            "Kick",
            "VOD",
            CHANNEL
        ],

        "description": (
            video.get(
                "session_title",
                ""
            )
        ),
    }


    item = internetarchive.get_item(
        identifier
    )


    print(
        f"Subiendo a Archive.org: {identifier}"
    )


    result = item.upload(
        video_path.name,
        str(video_path),
        metadata=metadata,
        access_key=IA_ACCESS_KEY,
        secret_key=IA_SECRET_KEY,
        retries=10,
    )


    if not result:

        raise RuntimeError(
            "Archive.org no devolvió resultado."
        )


    print(
        "Subida completada:"
    )

    print(
        f"https://archive.org/details/{identifier}"
    )


    return identifier



def process_oldest_pending_video(videos):

    for video in videos:

        video_id = str(
            video["id"]
        )


        print(
            f"Procesando VOD completo {video_id}"
        )


        playlist, playlist_url = (
            resolve_media_playlist(
                video["source"]
            )
        )


        created_at = str(
            video.get(
                "created_at",
                "unknown"
            )
        )


        video_date = (
            created_at
            .split("T")[0]
        )


        folder = (
            WORKSPACE /
            f"{video_date}_{video_id}"
        )


        folder.mkdir(
            parents=True,
            exist_ok=True
        )


        playlist_file = (
            folder /
            "full_vod.m3u8"
        )


        output_file = (
            folder /
            f"{CHANNEL}_kick_vod_{video_id}.ts"
        )


        print(
            "Creando playlist completa..."
        )


        write_full_playlist(
            playlist,
            playlist_url,
            playlist_file
        )


        print(
            "Descargando VOD completo..."
        )


        download_full_vod(
            playlist_file,
            output_file
        )


        print(
            "Archivo generado:",
            output_file
        )


        upload_archive(
            video,
            output_file
        )


        print(
            f"VOD {video_id} finalizado."
        )


        return True


    return False



def main():

    WORKSPACE.mkdir(
        parents=True,
        exist_ok=True
    )


    videos = get_kick_videos()


    if not videos:

        print(
            "No hay VODs disponibles."
        )

        return


    processed = (
        process_oldest_pending_video(
            videos
        )
    )


    if not processed:

        print(
            "No se procesó ningún VOD."
        )



if __name__ == "__main__":

    main()
