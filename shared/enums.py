from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class AppStatus(StrEnum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
