select
    payment_id,
    order_id,
    payment_method,
    amount,
    payment_date
from {{ source('raw', 'raw_payments') }}
