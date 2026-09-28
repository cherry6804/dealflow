from app.auth.password import hash_password, verify_password


def test_hash_password_does_not_return_plaintext() -> None:
    password = "StrongTestPassword!123"

    password_hash = hash_password(password)

    assert password_hash != password


def test_hash_password_produces_a_verifiable_hash() -> None:
    password = "StrongTestPassword!123"

    password_hash = hash_password(password)

    assert verify_password(password, password_hash) is True


def test_different_password_does_not_verify() -> None:
    password = "StrongTestPassword!123"
    wrong_password = "WrongPassword!456"

    password_hash = hash_password(password)

    assert verify_password(wrong_password, password_hash) is False


def test_same_password_produces_different_hashes() -> None:
    password = "StrongTestPassword!123"

    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash


def test_empty_password_cannot_be_hashed() -> None:
    try:
        hash_password("")
    except ValueError:
        pass
    else:
        raise AssertionError("Empty passwords must be rejected.")


def test_empty_password_cannot_verify() -> None:
    assert verify_password("", "some-password-hash") is False


def test_empty_hash_cannot_verify() -> None:
    assert verify_password("StrongTestPassword!123", "") is False