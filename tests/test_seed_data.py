from datetime import datetime

from estate.seeds.generate_seed_data import (
    CUSTOMER_CREATED_END,
    CUSTOMER_CREATED_START,
    ORDER_DATE_END,
    ORDER_DATE_START,
    generate_customers,
    generate_orders,
    generate_payments,
)


def test_generate_customers_deterministic():
    a = generate_customers(10, seed=42)
    b = generate_customers(10, seed=42)
    assert a == b


def test_customer_created_at_dates_use_fixed_bounds_not_relative_to_now():
    # Regression coverage for a confirmed non-determinism bug: dates used to
    # be drawn from a window computed relative to datetime.now() at call
    # time ("-2y" to "-30d"), so the exact window -- and so the exact date
    # drawn -- silently shifted depending on what day the script ran,
    # despite the fixed seed. A same-process round-trip comparison (like the
    # test above) can't catch this since "now" barely moves between two
    # calls milliseconds apart -- this instead asserts every generated date
    # falls within the module's fixed absolute bounds, which are not
    # computed from datetime.now() at all.
    customers = generate_customers(20, seed=42)
    for customer in customers:
        created_at = datetime.fromisoformat(customer["created_at"])
        assert CUSTOMER_CREATED_START <= created_at <= CUSTOMER_CREATED_END


def test_order_dates_use_fixed_bounds_not_relative_to_now():
    customers = generate_customers(20, seed=42)
    orders = generate_orders(customers, 50, seed=42)
    for order in orders:
        order_date = datetime.fromisoformat(order["order_date"])
        assert ORDER_DATE_START <= order_date <= ORDER_DATE_END


def test_generate_customers_unique_ids_and_emails():
    customers = generate_customers(50, seed=1)
    ids = [c["cust_id"] for c in customers]
    emails = [c["email"] for c in customers]
    assert len(ids) == len(set(ids)) == 50
    assert len(emails) == len(set(emails)) == 50


def test_generate_orders_reference_valid_customers():
    customers = generate_customers(20, seed=7)
    orders = generate_orders(customers, 100, seed=7)
    valid_ids = {c["cust_id"] for c in customers}
    assert len(orders) == 100
    assert all(o["cust_id"] in valid_ids for o in orders)


def test_generate_payments_skip_cancelled_and_reference_valid_orders():
    customers = generate_customers(20, seed=3)
    orders = generate_orders(customers, 100, seed=3)
    payments = generate_payments(orders, seed=3)

    valid_order_ids = {o["order_id"] for o in orders if o["status"] != "cancelled"}
    payment_order_ids = {p["order_id"] for p in payments}

    assert payment_order_ids <= valid_order_ids
    assert len(payments) == len({p["payment_id"] for p in payments})
