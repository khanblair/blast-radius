select
    order_id,
    cust_id,
    order_date,
    status,
    amount
from {{ source('raw', 'raw_orders') }}
