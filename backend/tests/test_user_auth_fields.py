from app.db.models.user import User

def test_user_has_password_hash_field() -> None:
    assert User.password_hash.property.columns[0].nullable is False