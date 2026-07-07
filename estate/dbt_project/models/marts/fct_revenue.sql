-- Deliberate SILENT_CORRUPTION showcase: this model exposes whatever shape
-- revenue_by_customer happens to have via `select *`, rather than pinning
-- column names explicitly. If an upstream mart's columns are renamed,
-- reordered, or retyped, this model keeps compiling and running -- nothing
-- crashes, but consumers relying on column order/names can go quietly wrong.
with revenue_by_customer as (
    select
        c.customer_key,
        c.first_name,
        c.last_name,
        count(o.order_id) as order_count,
        sum(o.amount) as total_amount
    from {{ ref('dim_customers') }} as c
    inner join {{ ref('fct_orders') }} as o
        on c.customer_key = o.customer_key
    where o.status != 'cancelled'
    group by c.customer_key, c.first_name, c.last_name
)

select *
from revenue_by_customer
