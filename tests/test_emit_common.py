from estate.metadata.emit_common import dataset_urn


def test_dataset_urn_format():
    urn = dataset_urn("fct_revenue")
    assert urn == "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.fct_revenue,PROD)"


def test_dataset_urn_varies_by_table():
    assert dataset_urn("raw_customers") != dataset_urn("fct_revenue")
