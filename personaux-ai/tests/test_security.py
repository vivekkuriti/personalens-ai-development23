import pytest

from security import (
    URLValidationError,
    allowed_domains_for,
    is_domain_allowed,
    is_ip_blocked,
    is_navigation_allowed,
    normalize_url,
    validate_target_url,
)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "0.0.0.0"])
def test_private_ips_blocked(ip):
    assert is_ip_blocked(ip)


def test_public_ip_allowed():
    assert not is_ip_blocked("93.184.215.14")


@pytest.mark.parametrize("url", ["http://localhost", "http://127.0.0.1:8000", "file:///etc/passwd",
                                 "ftp://example.com", "http://169.254.169.254/latest/meta-data", "javascript:alert(1)"])
def test_unsafe_urls_rejected(url):
    with pytest.raises(URLValidationError):
        validate_target_url(url)


def test_normalize_adds_scheme():
    assert normalize_url("example.com").startswith("https://example.com")


def test_navigation_restricted_to_domain():
    allowed = allowed_domains_for("https://www.example.com/")
    assert is_domain_allowed("shop.example.com", allowed)
    assert not is_domain_allowed("evil.test", allowed)
    assert not is_domain_allowed("notexample.com", allowed)
    assert not is_navigation_allowed("https://evil.test/", allowed)
    assert not is_navigation_allowed("file:///etc/passwd", allowed)
