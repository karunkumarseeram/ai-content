from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from app.settings import Settings
from app.publishers import YOUTUBE_UPLOAD_SCOPE


def main() -> None:
    settings = Settings.from_env()
    client_secrets = settings.google_oauth_client_secrets
    if not client_secrets.is_file():
        raise FileNotFoundError(
            f"YouTube OAuth client file not found: {client_secrets}. "
            "Create an OAuth Desktop client in Google Cloud and save it there."
        )
    credentials = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets), YOUTUBE_UPLOAD_SCOPE
    ).run_local_server(port=0, access_type="offline", prompt="consent")
    token_file = settings.google_oauth_token_file
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    print(f"YouTube OAuth token saved to {token_file}. Keep it private.")


if __name__ == "__main__":
    main()
