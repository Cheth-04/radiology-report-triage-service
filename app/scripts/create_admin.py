"""Usage: docker compose exec -it api python -m app.scripts.create_admin admin@example.com"""
import getpass
import sys
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User

def main() -> int:
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print("Usage: python -m app.scripts.create_admin admin@example.com")
        return 2
    email = sys.argv[1].strip().lower()
    pw = getpass.getpass("Admin password (12-128 chars): ")
    if not 12 <= len(pw) <= 128:
        print("Password must have 12 to 128 characters")
        return 2
    confirm = getpass.getpass("Confirm password: ")
    if pw != confirm:
        print("Passwords do not match")
        return 2
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            print("An account with this email already exists; not modifying it")
            return 1
        db.add(User(email=email, password_hash=hash_password(pw), role="admin"))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            print("Unable to create account (possible duplicate email)")
            return 1
    print("Admin account created")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
