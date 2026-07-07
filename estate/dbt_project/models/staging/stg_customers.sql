-- Explicit cust_id reference: the deliberate HARD_BREAK dependency for the
-- canonical Blast Radius change (raw_customers.cust_id -> customer_id).
select
    cust_id,
    first_name,
    last_name,
    email,
    created_at
from {{ source('raw', 'raw_customers') }}
