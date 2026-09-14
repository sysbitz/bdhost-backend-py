import asyncio
import sys
from decimal import Decimal
from pathlib import Path

# Ensure project root is on sys.path when executed directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from api.core.security import get_password_hash  # noqa: E402
from shared.db.base import async_session_factory  # noqa: E402
from shared.db.models import Plan, User  # noqa: E402
from shared.enums import UserRole  # noqa: E402

DEFAULT_PLANS = [
    {
        "name": "Free",
        "app_limit": 1,
        "storage_limit_mb": 100,
        "price": Decimal("0.00"),
        "features": {
            "custom_subdomain": True,
            "ssl_enabled": True,
            "spa_support": True,
        },
    },
    {
        "name": "Pro",
        "app_limit": 5,
        "storage_limit_mb": 1024,  # 1 GB
        "price": Decimal("9.99"),
        "features": {
            "custom_subdomain": True,
            "ssl_enabled": True,
            "spa_support": True,
            "priority_support": True,
        },
    },
    {
        "name": "Enterprise",
        "app_limit": 50,
        "storage_limit_mb": 10240,  # 10 GB
        "price": Decimal("49.99"),
        "features": {
            "custom_subdomain": True,
            "ssl_enabled": True,
            "spa_support": True,
            "priority_support": True,
            "high_concurrency": True,
        },
    },
]


async def seed() -> None:
    session_maker = async_session_factory()

    async with session_maker() as session:
        print("Seeding default plans...")
        for p_data in DEFAULT_PLANS:
            result = await session.execute(select(Plan).where(Plan.name == p_data["name"]))
            existing = result.scalar_one_or_none()
            if not existing:
                plan = Plan(
                    name=p_data["name"],
                    app_limit=p_data["app_limit"],
                    storage_limit_mb=p_data["storage_limit_mb"],
                    price=p_data["price"],
                    features=p_data["features"],
                )
                session.add(plan)
                print(f"  + Created plan: {p_data['name']}")
            else:
                print(f"  = Plan already exists: {p_data['name']}")

        print("\nSeeding admin user...")
        admin_email = "admin@bdappshub.com"
        user_res = await session.execute(select(User).where(User.email == admin_email))
        existing_admin = user_res.scalar_one_or_none()

        if not existing_admin:
            admin_user = User(
                email=admin_email,
                password_hash=get_password_hash("admin123456"),
                full_name="System Administrator",
                role=UserRole.ADMIN,
            )
            session.add(admin_user)
            print(f"  + Created admin: {admin_email} (Password: admin123456)")
        else:
            print(f"  = Admin user already exists: {admin_email}")

        await session.commit()
        print("\nDatabase seeding completed successfully!")


if __name__ == "__main__":
    asyncio.run(seed())
