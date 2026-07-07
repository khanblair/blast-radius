from estate.golden.capture_golden import compute_checksum


def test_checksum_order_independent():
    rows_a = [(1, "a"), (2, "b"), (3, "c")]
    rows_b = [(3, "c"), (1, "a"), (2, "b")]
    assert compute_checksum(rows_a) == compute_checksum(rows_b)


def test_checksum_changes_with_data():
    rows_a = [(1, "a"), (2, "b")]
    rows_b = [(1, "a"), (2, "c")]
    assert compute_checksum(rows_a) != compute_checksum(rows_b)


def test_checksum_deterministic():
    rows = [(1, "a"), (2, "b")]
    assert compute_checksum(rows) == compute_checksum(rows)
