"""Sprint 6: CSV round-trip and bulk edit.

A price change applied to 3 of 4 rows without saying so is worse than one that
fails outright, so the reporting is the part under test.
"""

from __future__ import annotations

import io

from db.conn import Role, tx


def _a_sku():
    with tx(Role.SUPER) as cur:
        cur.execute("select sku, price_cents from store.variants where archived_at is null order by id limit 1")
        return cur.fetchone()


def test_variants_export_round_trips(as_role):
    response = as_role("owner").get("/catalog/variants.csv")
    assert response.status_code == 200
    header = response.get_data(as_text=True).splitlines()[0]
    for column in ("sku", "price_cents", "sale_price_cents", "status"):
        assert column in header


def _upload(client, body: str):
    return client.post(
        "/catalog/import",
        data={"file": (io.BytesIO(body.encode()), "prices.csv")},
        content_type="multipart/form-data",
    )


def test_import_applies_price_changes(as_role):
    variant = _a_sku()
    new_price = variant["price_cents"] + 500
    response = _upload(as_role("owner"), f"sku,price_cents\n{variant['sku']},{new_price}\n")
    assert response.status_code == 200
    assert b"1 of 1 rows applied" in response.data

    with tx(Role.SUPER) as cur:
        cur.execute("select price_cents from store.variants where sku = %s", (variant["sku"],))
        assert cur.fetchone()["price_cents"] == new_price
        # Restore, so the parity test keeps meaning something.
        cur.execute("update store.variants set price_cents = %s where sku = %s",
                    (variant["price_cents"], variant["sku"]))


def test_unknown_skus_are_reported_not_skipped(as_role):
    variant = _a_sku()
    response = _upload(
        as_role("owner"),
        f"sku,price_cents\n{variant['sku']},{variant['price_cents']}\nNOT-A-SKU,9900\n",
    )
    assert b"1 of 2 rows applied" in response.data
    assert b"NOT-A-SKU" in response.data


def test_a_spreadsheet_decimal_is_accepted(as_role):
    variant = _a_sku()
    response = _upload(as_role("owner"), f"sku,price_cents\n{variant['sku']},11600.00\n")
    assert b"1 of 1 rows applied" in response.data
    with tx(Role.SUPER) as cur:
        cur.execute("select price_cents from store.variants where sku = %s", (variant["sku"],))
        assert cur.fetchone()["price_cents"] == 11600
        cur.execute("update store.variants set price_cents = %s where sku = %s",
                    (variant["price_cents"], variant["sku"]))


def test_a_negative_price_is_rejected_without_touching_the_row(as_role):
    variant = _a_sku()
    response = _upload(as_role("owner"), f"sku,price_cents\n{variant['sku']},-100\n")
    assert b"0 of 1 rows applied" in response.data
    with tx(Role.SUPER) as cur:
        cur.execute("select price_cents from store.variants where sku = %s", (variant["sku"],))
        assert cur.fetchone()["price_cents"] == variant["price_cents"]


def test_import_requires_the_price_permission(as_role):
    assert as_role("fulfilment").get("/catalog/import").status_code == 403


def test_bulk_import_is_audited(as_role, staff):
    variant = _a_sku()
    with tx(Role.SUPER) as cur:
        cur.execute("select count(*) as n from ops.audit_log where entity = 'store.variants'")
        before = cur.fetchone()["n"]

    _upload(as_role("owner"), f"sku,price_cents\n{variant['sku']},{variant['price_cents'] + 1}\n")

    with tx(Role.SUPER) as cur:
        cur.execute(
            """select actor_id from ops.audit_log where entity = 'store.variants'
                order by id desc limit 1"""
        )
        assert cur.fetchone()["actor_id"] == staff["owner"]["id"]
        cur.execute("select count(*) as n from ops.audit_log where entity = 'store.variants'")
        assert cur.fetchone()["n"] > before
        cur.execute("update store.variants set price_cents = %s where sku = %s",
                    (variant["price_cents"], variant["sku"]))


def test_bulk_product_edit(as_role, scratch_product):
    response = as_role("owner").post(
        "/catalog/bulk", data={"product_id": str(scratch_product), "status": "active"}
    )
    assert response.status_code == 302
    with tx(Role.SUPER) as cur:
        cur.execute("select status::text as s from store.products where id = %s", (scratch_product,))
        assert cur.fetchone()["s"] == "active"
        cur.execute("update store.products set status = 'draft' where id = %s", (scratch_product,))
