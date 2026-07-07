select
    cust_id as customer_key,
    first_name,
    last_name,
    email,
    created_at
from {{ ref('stg_customers') }}
