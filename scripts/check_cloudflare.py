"""Cloudflare Connectivity & Wildcard DNS Verification CLI Tool.

Usage:
    uv run python scripts/check_cloudflare.py [--provision] [--zone-id ZONE_ID] [--ip IP]

Checks:
    1. Validates presence of CLOUDFLARE_API_TOKEN.
    2. Tests Cloudflare API authentication & connectivity.
    3. Verifies access to the configured zone.
    4. Checks if the platform wildcard record (*.bdappshub.com) exists.
    5. Optionally provisions the wildcard record if --provision is passed.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from shared.config import get_settings  # noqa: E402
from src.api.services.cloudflare.client import get_async_cloudflare_client  # noqa: E402
from src.api.services.cloudflare.dns import CloudflareDNSService  # noqa: E402
from src.api.services.cloudflare.exceptions import (  # noqa: E402
    CloudflareAuthenticationError,
    CloudflareError,
)


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Cloudflare credentials, zone access, and platform wildcard DNS record."
    )
    parser.add_argument(
        "--provision",
        action="store_true",
        help="Automatically provision the wildcard DNS record (*.<BASE_DOMAIN>) if missing.",
    )
    parser.add_argument(
        "--zone-id",
        type=str,
        default=None,
        help="Override CLOUDFLARE_ZONE_ID from settings.",
    )
    parser.add_argument(
        "--ip",
        type=str,
        default=None,
        help="Override APP_RUNTIME_IP from settings for wildcard provisioning.",
    )

    args = parser.parse_args()
    settings = get_settings()

    zone_id = args.zone_id or settings.cloudflare_zone_id
    target_ip = args.ip or settings.app_runtime_ip
    base_domain = settings.base_domain

    print("=" * 60)
    print("BDHost Cloudflare DNS Connectivity & Wildcard Verifier")
    print("=" * 60)
    print(f"Base Domain:    {base_domain}")
    print(f"Zone ID:        {zone_id or '[NOT CONFIGURED]'}")
    print(f"Runtime IP:     {target_ip}")
    print(f"Auto-provision: {args.provision}")
    print("-" * 60)

    # 1. Check API token configuration
    if not settings.cloudflare_api_token:
        print("[FAIL] CLOUDFLARE_API_TOKEN is not set in environment or .env file.")
        print("       Please set CLOUDFLARE_API_TOKEN to run live Cloudflare checks.")
        return 1
    print("[PASS] Cloudflare API token is configured.")

    if not zone_id:
        print("[FAIL] CLOUDFLARE_ZONE_ID is not set in environment or .env file.")
        print("       Provide --zone-id or set CLOUDFLARE_ZONE_ID in .env.")
        return 1
    print("[PASS] Zone ID is configured.")

    try:
        client = get_async_cloudflare_client()
        dns_service = CloudflareDNSService(client=client)

        # 2. Test connectivity / user verification
        print("[INFO] Testing Cloudflare API token validity...")
        user_tokens = await client.user.tokens.verify()
        print(f"[PASS] Token verified successfully: status={user_tokens.status}")

        # 3. Test zone access
        print(f"[INFO] Verifying access to zone {zone_id}...")
        zone_info = await client.zones.get(zone_id=zone_id)
        zone_name = getattr(zone_info, "name", "unknown")
        print(
            f"[PASS] Zone accessed successfully: '{zone_name}' (status: {getattr(zone_info, 'status', 'unknown')})"
        )

        # 4. Check for wildcard DNS record
        print(f"[INFO] Checking wildcard DNS record (*.{base_domain} -> {target_ip})...")
        records = await dns_service.list_records(zone_id=zone_id, type="A")
        wildcard_rec = None
        for rec in records:
            norm_name = rec.name.lower().rstrip(".")
            if norm_name in ("*", f"*.{base_domain.lower()}"):
                wildcard_rec = rec
                break

        if wildcard_rec:
            print(
                f"[PASS] Wildcard DNS record exists: ID={wildcard_rec.id}, "
                f"Name={wildcard_rec.name}, IP={wildcard_rec.content}, Proxied={wildcard_rec.proxied}"
            )
            if wildcard_rec.content != target_ip:
                print(
                    f"[WARN] Existing wildcard content ({wildcard_rec.content}) differs from APP_RUNTIME_IP ({target_ip})."
                )
        else:
            print(f"[INFO] No wildcard DNS record found for '*.{base_domain}'.")
            if args.provision:
                print(f"[INFO] Provisioning wildcard record (*.{base_domain} -> {target_ip})...")
                created = await dns_service.ensure_wildcard_record(
                    zone_id=zone_id,
                    ip=target_ip,
                )
                print(
                    f"[PASS] Successfully provisioned wildcard record: ID={created.id}, "
                    f"Name={created.name}, IP={created.content}"
                )
            else:
                print(
                    "[NOTE] Run with --provision to automatically create the wildcard DNS record."
                )

        print("=" * 60)
        print("Cloudflare verification completed successfully.")
        return 0

    except CloudflareAuthenticationError as e:
        print(f"[FAIL] Cloudflare authentication error: {e}")
        return 1
    except CloudflareError as e:
        print(f"[FAIL] Cloudflare error: {e}")
        return 1
    except Exception as e:
        print(f"[FAIL] Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
