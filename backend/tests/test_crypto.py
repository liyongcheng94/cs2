from app.services.crypto import decrypt, encrypt


def test_encrypt_decrypt_roundtrip(tmp_path, monkeypatch):
    """
    Given 任意明文凭证
    When  encrypt 后 decrypt
    Then  还原出原文，且密文不含明文子串
    """
    monkeypatch.setenv("CS2HQ_DATA_DIR", str(tmp_path))
    token = encrypt("my-access-token-123")
    assert "my-access-token-123" not in token
    assert decrypt(token) == "my-access-token-123"


def test_secret_key_env_derivation_consistent(monkeypatch, tmp_path):
    """
    Given 相同的 CS2HQ_SECRET_KEY 环境变量
    When  分别在两次初始化中加解密
    Then  可以互相解密（密钥派生确定性）
    """
    monkeypatch.setenv("CS2HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CS2HQ_SECRET_KEY", "passphrase-A")
    token = encrypt("value-1")

    monkeypatch.setenv("CS2HQ_SECRET_KEY", "passphrase-B")
    token_b = encrypt("value-1")
    assert token != token_b  # 不同口令派生不同密钥

    monkeypatch.setenv("CS2HQ_SECRET_KEY", "passphrase-A")
    assert decrypt(token) == "value-1"
