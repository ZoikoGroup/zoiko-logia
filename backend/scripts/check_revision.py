"""Read back a production deployment's health and immutable revision."""
import os
import httpx

if __name__ == "__main__":
    base = os.environ["PRODUCTION_API_URL"].rstrip("/")
    expected = os.environ["CANDIDATE_REVISION"]
    expected_config = os.environ["EXPECTED_CONFIG_HASH"]
    with httpx.Client(timeout=20) as client:
        client.get(base + "/health/ready").raise_for_status()
        response = client.get(base + "/health/version")
        response.raise_for_status()
        if response.json().get("revision") != expected:
            raise SystemExit("Production revision does not match the verified candidate")
        if response.json().get("config_hash") != expected_config:
            raise SystemExit("Production configuration differs from the evaluated staging configuration")
    print("Production health and revision verified.")
