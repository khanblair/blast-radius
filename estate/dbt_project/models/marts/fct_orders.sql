select
    order_id,
    cust_id as customer_key,
    order_date,
    status,
    amount
from {{ ref('stg_orders') }}
