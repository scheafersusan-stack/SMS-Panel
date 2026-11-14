"""ORM models; importing this package registers every table on ``Base.metadata``."""

from payamakyar.db.models.rbac import Permission, Role, RolePermission, UserRole
from payamakyar.db.models.system import AuditEvent, Job, Setting, SystemMessage
from payamakyar.db.models.user import LoginEvent, OtpChallenge, Session, User

__all__ = [
    "AuditEvent",
    "Job",
    "LoginEvent",
    "OtpChallenge",
    "Permission",
    "Role",
    "RolePermission",
    "Session",
    "Setting",
    "SystemMessage",
    "User",
    "UserRole",
]
