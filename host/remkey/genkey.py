"""Print a random shared secret for station.toml and client.toml."""

import secrets

if __name__ == "__main__":
    print(secrets.token_urlsafe(32))
