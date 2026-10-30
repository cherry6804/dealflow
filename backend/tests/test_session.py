from app.auth.session import (
    generate_session_token,
    hash_session_token,
    verify_session_token,
)


def test_generate_session_token_returns_non_empty_token() -> None:
    token = generate_session_token()

    assert token
    assert isinstance(token, str)


def test_generate_session_tokens_are_unique() -> None:
    first_token = generate_session_token()
    second_token = generate_session_token()

    assert first_token != second_token


def test_hash_session_token_does_not_return_plaintext() -> None:
    token = generate_session_token()

    token_hash = hash_session_token(token)

    assert token_hash != token


def test_hash_session_token_returns_sha256_hex() -> None:
    token = generate_session_token()

    token_hash = hash_session_token(token)

    assert len(token_hash) == 64
    assert all(character in "0123456789abcdef" for character in token_hash)


def test_session_token_verifies_against_hash() -> None:
    token = generate_session_token()
    token_hash = hash_session_token(token)

    assert verify_session_token(token, token_hash) is True


def test_wrong_session_token_does_not_verify() -> None:
    token = generate_session_token()
    wrong_token = generate_session_token()
    token_hash = hash_session_token(token)

    assert verify_session_token(wrong_token, token_hash) is False


def test_empty_session_token_cannot_be_hashed() -> None:
    try:
        hash_session_token("")
    except ValueError:
        pass
    else:
        raise AssertionError("Empty session tokens must be rejected.")


def test_empty_session_token_cannot_verify() -> None:
    assert verify_session_token("", "some-token-hash") is False


def test_empty_token_hash_cannot_verify() -> None:
    token = generate_session_token()

    assert verify_session_token(token, "") is False