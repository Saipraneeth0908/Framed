import pytest

from main import app, compute_cart_totals, normalize_config, parse_quantity


@pytest.fixture()
def client():
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    with app.test_client() as test_client:
        yield test_client


@pytest.mark.parametrize(
    "path", ["/", "/shop", "/product/mclaren-720s-orange", "/cart", "/checkout", "/about", "/contact"]
)
def test_pages_render(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert b"Motorsport Gallery" in response.data


def test_product_redirects_when_unknown(client):
    response = client.get("/product/not-a-product")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/shop")


def test_price_api_uses_server_product_price(client):
    response = client.post(
        "/api/price",
        json={
            "slug": "mclaren-720s-orange",
            "frame": "walnut",
            "size": "A3",
            "poster_theme": "circuit",
            "base_price": -1000,
        },
    )
    assert response.status_code == 200
    assert response.get_json() == {"price": 114.0}


def test_price_api_rejects_unknown_product(client):
    response = client.post("/api/price", json={"slug": "unknown"})
    assert response.status_code == 404


def test_invalid_configuration_falls_back():
    assert normalize_config("chrome", "huge", "unknown") == {
        "frame": "black",
        "size": "A3",
        "poster_theme": "racing_stripes",
    }


@pytest.mark.parametrize(("value", "expected"), [("3", 3), ("-10", 0), ("100", 25), ("bad", 1)])
def test_quantity_is_bounded(value, expected):
    assert parse_quantity(value) == expected


def test_bundle_discount():
    totals = compute_cart_totals([{"qty": 3, "unit_price": 100}])
    assert totals == {"subtotal": 300.0, "bundle_discount": 30.0, "total": 270.0, "total_qty": 3}


def test_negative_cart_add_is_ignored(client):
    client.post("/cart/add", data={"slug": "mclaren-720s-orange", "qty": "-2"})
    with client.session_transaction() as session:
        assert session["cart"] == []


def test_checkout_requires_cart(client):
    response = client.post(
        "/checkout", data={"name": "Driver", "email": "driver@example.com", "address": "1 Track Way"}
    )
    assert response.status_code == 200
    assert b"Your cart is empty" in response.data


def test_newsletter_validation(client):
    invalid = client.post("/newsletter", data={"email": "invalid"})
    valid = client.post("/newsletter", data={"email": "driver@example.com"})
    assert invalid.headers["Location"].endswith("/?newsletter=error#updates")
    assert valid.headers["Location"].endswith("/?newsletter=success#updates")
