from estate.seeds.generate_seed_data import generate_customers, generate_orders, generate_payments


def test_generate_customers_deterministic():
    a = generate_customers(10, seed=42)
    b = generate_customers(10, seed=42)
    assert a == b


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
    assert len(payments) == len(set(p["payment_id"] for p in payments))
