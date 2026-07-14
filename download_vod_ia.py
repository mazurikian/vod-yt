# download_vod.py
# Kick VOD -> Internet Archive
# Sin YouTube
# VOD completo sin dividir

import copy
import json
import os
import subprocess
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
    "community"
)


HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/120 Safari/537.36"
    ),

    "Accept": (
        "application/json,"
        "application/vnd.apple.mpegurl,"
        "*/*"
    )
}



def get_kick_videos():

    request = urllib.request.Request(
        KICK_API_URL,
        headers=HTTP_HEADERS
    )


    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:

        videos = json.load(
            response
        )


    if not isinstance(
        videos,
        list
    ):

        raise RuntimeError(
            "Kick no devolvió una lista."
        )


    return sorted(
        [
            video
            for video in videos

            if video.get(
                "is_live"
            ) is not True

            and video.get(
                "source"
            )

            and video.get(
                "id"
            )
        ],

        key=lambda video: (
            video.get(
                "created_at",
                ""
            ),

            str(
                video.get(
                    "id"
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

    info = variant.stream_info


    bandwidth = (
        getattr(
            info,
            "average_bandwidth",
            None
        )

        or

        getattr(
            info,
            "bandwidth",
            None
        )

        or 0
    )


    resolution = (
        getattr(
            info,
            "resolution",
            None
        )

        or

        (0, 0)
    )


    fps = (
        getattr(
            info,
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
                    "Playlist sin segmentos."
                )


            return (
                playlist,
                final_url
            )


        if not playlist.playlists:

            raise RuntimeError(
                "Playlist maestro inválido."
            )


        selected = max(
            playlist.playlists,
            key=variant_score
        )


        current_url = urljoin(
            final_url,
            selected.uri
        )


        print(
            "Calidad seleccionada:",
            selected.stream_info.resolution,
            selected.stream_info.frame_rate,
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

            "-y",

            str(output_path)
        ],

        check=True
    )



def build_metadata(video):

    vod_id = str(
        video["id"]
    )


    created_at = str(
        video.get(
            "created_at",
            ""
        )
    )


    date = (
        created_at
        .split("T")[0]
        .split(" ")[0]
    )


    try:

        year, month, day = (
            date.split("-")
        )

        formatted_date = (
            f"{day}/{month}/{year}"
        )

    except Exception:

        formatted_date = date



    channel_name = (
        CHANNEL[0].upper()
        +
        CHANNEL[1:]
    )


    title = (
        f"{channel_name} | "
        f"{formatted_date}"
    )



    session_title = str(
        video.get(
            "session_title"
        )
        or
        "Sin título"
    )


    start_time = str(
        video.get(
            "start_time"
        )
        or
        ""
    )


    source = str(
        video.get(
            "source"
        )
        or
        ""
    )


    description = "\n\n".join(
        [
            session_title,

            start_time,

            source
        ]
    )


    tags = [

        CHANNEL,

        "Kick",

        "VOD",

        f"kick-vod-id:{vod_id}"

    ]


    return {

        "title":
            title,

        "description":
            description,

        "tags":
            tags,

        "vod_id":
            vod_id
    }

def get_archive_identifier(vod_id):

    return (
        f"{CHANNEL}-kick-vod-{vod_id}"
    )



def archive_vod_exists(vod_id):

    identifier = get_archive_identifier(
        vod_id
    )


    item = internetarchive.get_item(
        identifier
    )


    exists = item.exists


    if exists:

        print(
            f"Encontrado en Archive.org: {identifier}"
        )


    return exists



def upload_archive(
    video,
    video_path
):

    if not IA_ACCESS_KEY or not IA_SECRET_KEY:

        raise RuntimeError(
            "Faltan IA_ACCESS_KEY o IA_SECRET_KEY."
        )



    metadata = build_metadata(
        video
    )


    identifier = get_archive_identifier(
        metadata["vod_id"]
    )



    archive_metadata = {

        "title":
            metadata["title"],


        "description":
            metadata["description"],


        "creator":
            CHANNEL,


        "mediatype":
            "movies",


        "collection":
            IA_COLLECTION,


        "subject":
            metadata["tags"],


        "keywords":
            metadata["tags"],


        "identifier":
            identifier
    }



    print(
        "Preparando subida:"
    )

    print(
        identifier
    )



    item = internetarchive.get_item(
        identifier
    )



    files = [

        {

            "name":
                video_path.name,


            "path":
                str(video_path)

        }

    ]



    print(
        "Subiendo archivo:"
    )

    print(
        video_path
    )



    response = item.upload(

        files,

        metadata=archive_metadata,

        access_key=IA_ACCESS_KEY,

        secret_key=IA_SECRET_KEY,

        retries=10,

        verbose=True

    )



    print(
        "Respuesta Archive.org:"
    )

    print(
        response
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

        vod_id = str(
            video["id"]
        )


        if archive_vod_exists(
            vod_id
        ):

            print(
                f"VOD {vod_id} ya está subido. Se omite."
            )

            continue



        print(
            f"Procesando VOD más antiguo pendiente: {vod_id}"
        )



        media_playlist, playlist_url = (
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
            .split(" ")[0]
        )



        vod_directory = (

            WORKSPACE

            /

            f"{video_date}_{vod_id}"

        )


        vod_directory.mkdir(
            parents=True,
            exist_ok=True
        )



        playlist_file = (

            vod_directory

            /

            "full_vod.m3u8"

        )



        output_file = (

            vod_directory

            /

            f"{CHANNEL}_vod_{vod_id}.ts"

        )



        print(
            "Creando playlist completa..."
        )



        write_full_playlist(

            media_playlist,

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
            "Archivo descargado:"
        )


        print(
            output_file
        )



        upload_archive(

            video,

            output_file

        )



        print(
            f"VOD {vod_id} finalizado correctamente."
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



    processed = process_oldest_pending_video(
        videos
    )



    if not processed:

        print(
            "No hay VODs pendientes."
        )





if __name__ == "__main__":

    main()
