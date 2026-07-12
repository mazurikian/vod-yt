import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python get_youtube_token.py client_secret.json")

    client_secret_path = Path(sys.argv[1])
    if not client_secret_path.is_file():
        raise SystemExit(f"No existe el archivo: {client_secret_path}")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secret_path),
        scopes=SCOPES,
    )

    credentials = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
    )

    client_data = json.loads(client_secret_path.read_text(encoding="utf-8"))
    client = client_data.get("installed") or client_data.get("web") or {}

    print("\nGuarda estos valores como secretos de GitHub:\n")
    print(f"YOUTUBE_CLIENT_ID={client.get('client_id', '')}")
    print(f"YOUTUBE_CLIENT_SECRET={client.get('client_secret', '')}")
    print(f"YOUTUBE_REFRESH_TOKEN={credentials.refresh_token or ''}")

    if not credentials.refresh_token:
        print(
            "\nNo se recibió refresh token. Revoca el acceso anterior de la "
            "aplicación y vuelve a ejecutar este script."
        )


if __name__ == "__main__":
    main()
