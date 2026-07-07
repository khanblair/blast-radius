-- Deliberate SILENT_CORRUPTION showcase (kickoff guide §6.2): this model
-- references dim_customers directly via `select *`, so it has no pinned
-- column list of its own for that side. If dim_customers's columns are
-- renamed, reordered, or retyped, fct_revenue silently inherits the new
-- shape -- nothing crashes, but anything consuming fct_revenue by position
-- or by a name that moved can go quietly wrong.
select
    o.order_id,
    o.order_date,
    o.status,
    o.amount,
    c.*
from {{ ref('fct_orders') }} as o
inner join {{ ref('dim_customers') }} as c
    on o.customer_key = c.customer_key
where o.status != 'cancelled'
